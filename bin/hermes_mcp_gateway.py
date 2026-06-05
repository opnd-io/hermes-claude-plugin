#!/usr/bin/env python3
"""hermes-bridge — Claude Code stdio MCP adapter.

Claude → Hermes 단방향 위임 어댑터. 5개 정제 도구를 노출하고 각각 서로 다른
Hermes 표면으로 라우팅한다. SoT: docs/plan-2-plugin.md §1 (어댑터 계약).

표면 매핑
- hermes_inquiry  → POST {api_base}/v1/responses        (동기, output_text 파싱)
- hermes_schedule → POST {api_base}/api/jobs            (cron 생성; 발화는 gateway 필요)
- hermes_memo     → 어댑터 SQLite 노트 스토어 (upsert)
- hermes_notes    → 어댑터 SQLite 노트 스토어 (조회/검색)
- hermes_send     → Hermes send_message_tool (messages_send 위임; API server 아님)

검증된 함정 (docs/review-deep-research.md)
- schedule 발화는 gateway 60초 tick 필요(생성만 API server). gateway down이면 fire 안 됨.
- send는 API server toolset에서 제외 → /v1/* 금지. messages_send/gateway 경로.
- memo는 bounded MEMORY.md 금지 → 어댑터 SQLite. dedupe_key NOT NULL.
- inquiry는 in-flight 전환 불가 → 짧으면 /v1/responses, 풀루프는 처음부터 /v1/runs (본 어댑터는 /v1/responses 동기 경로).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
_parser = argparse.ArgumentParser(prog="hermes-mcp-gateway", add_help=True)
_parser.add_argument("--api-base", default=os.getenv("HERMES_API_BASE", "http://127.0.0.1:8642"),
                     help="Hermes API server host root (NOT including /v1 — 경로별 prefix 분기)")
_parser.add_argument("--notes-db", default=os.getenv("HERMES_BRIDGE_NOTES_DB",
                     str(Path.home() / ".hermes-bridge" / "notes.sqlite")))
_args, _ = _parser.parse_known_args()

API_BASE: str = _args.api_base.rstrip("/")
API_KEY: str = os.getenv("HERMES_API_KEY", "")
NOTES_DB: str = _args.notes_db
HTTP_TIMEOUT = float(os.getenv("HERMES_BRIDGE_HTTP_TIMEOUT", "110"))  # < .mcp.json timeout(120s)

mcp = FastMCP("hermes-bridge")


def _auth_headers() -> dict[str, str]:
    if not API_KEY:
        raise RuntimeError("HERMES_API_KEY 미설정 — API server는 모든 배포에서 키 필수.")
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# 노트 스토어 (memo / notes) — H4·FEAS-02·FRESH-03
# ---------------------------------------------------------------------------
def _notes_conn() -> sqlite3.Connection:
    Path(NOTES_DB).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(NOTES_DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS notes("
        "id TEXT PRIMARY KEY, category TEXT, title TEXT, body TEXT, "
        "tags TEXT, dedupe_key TEXT NOT NULL UNIQUE, created_at INTEGER)"
    )
    return con


def _derive_dedupe_key(category: str, title: str, body: str) -> str:
    # 구분자 없는 단순 연결의 tuple 모호성 방지 — canonical JSON
    canon = json.dumps({"category": category, "title": title, "body": body},
                       sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()


@mcp.tool()
def hermes_memo(category: str, title: str, body: str,
                tags: Optional[list[str]] = None, dedupeKey: Optional[str] = None) -> str:
    """비개발 메모/회의록/팔로업을 어댑터 노트 스토어에 저장(upsert).

    bounded MEMORY.md가 아니라 어댑터 SQLite에 구조화 저장한다. dedupeKey 미지정 시
    sha1(canonical_json(category,title,body))로 자동 파생, 충돌 시 갱신(ON CONFLICT DO UPDATE).
    """
    tags = tags or []
    key = dedupeKey or _derive_dedupe_key(category, title, body)
    note_id = key  # id == dedupe_key (idempotent)
    now = int(time.time())
    with _notes_conn() as con:
        con.execute(
            "INSERT INTO notes(id, category, title, body, tags, dedupe_key, created_at) "
            "VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(dedupe_key) DO UPDATE SET "
            "category=excluded.category, title=excluded.title, body=excluded.body, tags=excluded.tags",
            (note_id, category, title, body, json.dumps(tags, ensure_ascii=False), key, now),
        )
    return json.dumps({"note_id": note_id, "dedupe_key": key, "status": "ok"}, ensure_ascii=False)


@mcp.tool()
def hermes_notes(query: Optional[str] = None, category: Optional[str] = None,
                 tags: Optional[str] = None, limit: int = 20) -> str:
    """저장된 메모를 조회/검색한다 (write-only 아님)."""
    sql = "SELECT id, category, title, body, tags, created_at FROM notes WHERE 1=1"
    params: list[Any] = []
    if category:
        sql += " AND category=?"; params.append(category)
    if tags:
        sql += " AND tags LIKE ?"; params.append(f"%{tags}%")
    if query:
        sql += " AND (title LIKE ? OR body LIKE ?)"; params += [f"%{query}%", f"%{query}%"]
    sql += " ORDER BY created_at DESC LIMIT ?"; params.append(int(limit))
    with _notes_conn() as con:
        rows = con.execute(sql, params).fetchall()
    out = [{"note_id": r[0], "category": r[1], "title": r[2], "body": r[3],
            "tags": json.loads(r[4] or "[]"), "created_at": r[5]} for r in rows]
    return json.dumps(out, ensure_ascii=False)


# ---------------------------------------------------------------------------
# inquiry → POST /v1/responses
# ---------------------------------------------------------------------------
def _extract_output_text(resp: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in resp.get("output", []) or []:
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text" and c.get("text"):
                parts.append(c["text"])
    return "\n".join(parts).strip()


@mcp.tool()
async def hermes_inquiry(input: str, previous_response_id: Optional[str] = None) -> str:
    """비개발 문의를 Hermes 에이전트에 동기 위임한다 (POST /v1/responses).

    풀 에이전트 루프가 예상되면 호출자가 짧게 끊어 사용한다(in-flight 전환 불가, FEAS-02).
    """
    body: dict[str, Any] = {"input": input}
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(f"{API_BASE}/v1/responses", headers=_auth_headers(), json=body)
        r.raise_for_status()
        data = r.json()
    return json.dumps({
        "response_id": data.get("id"),
        "text": _extract_output_text(data),
        "status": data.get("status"),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# schedule → POST /api/jobs  (cron; 발화는 gateway 필요)
# ---------------------------------------------------------------------------
@mcp.tool()
async def hermes_schedule(name: str, schedule: str, prompt: str = "",
                          deliver: str = "local", repeat: Optional[int] = None) -> str:
    """cron job을 생성한다(캘린더 아님). 발화는 gateway 상시 가동 필요(§1.3).

    name(필수,≤200), schedule(필수, 예: '30m'/'2h'/'2026-06-11T14:00'/cron식),
    prompt(≤5000), deliver(기본 'local'; 팀 채널은 'slack:#biz' 등 타깃 명시),
    repeat(선택). 응답은 job.id + next_run_at.
    """
    body: dict[str, Any] = {"name": name, "schedule": schedule, "prompt": prompt, "deliver": deliver}
    if repeat is not None:
        body["repeat"] = repeat
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(f"{API_BASE}/api/jobs", headers=_auth_headers(), json=body)
        r.raise_for_status()
        job = (r.json() or {}).get("job", {})
    warn = None if deliver != "local" else "deliver='local' — 채널 도착 ack 없음. 팀 공유는 deliver를 채널 타깃으로."
    return json.dumps({
        "job_id": job.get("id"),
        "next_run_at": job.get("next_run_at"),
        "note": "cron 발화는 gateway 상시 가동 필요. 상태는 GET /api/jobs/{id} last_status로 폴링.",
        "warn": warn,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# send → Hermes send_message_tool (messages_send 위임; API server 아님)
# ---------------------------------------------------------------------------
def _load_send_message_tool():
    agent_path = os.getenv("HERMES_AGENT_PATH")
    if agent_path and agent_path not in sys.path:
        sys.path.insert(0, agent_path)
    from tools.send_message_tool import send_message_tool  # type: ignore
    return send_message_tool


@mcp.tool()
async def hermes_send(target: str, message: str) -> str:
    """메시지를 발송한다. target='platform:id'(예: 'slack:#biz'). 첨부는 message에 'MEDIA:<path>'.

    send_message는 API server toolset에서 제외되므로 messages_send 경로(Hermes 내부)로 위임한다.
    표준/yuanbao 분기는 Hermes 내부 _send_to_platform이 target prefix로 결정(어댑터는 패스스루).
    """
    if not target or not message:
        return json.dumps({"error": "target과 message 모두 필요"}, ensure_ascii=False)
    send_message_tool = _load_send_message_tool()
    # send_message_tool은 내부에서 자체 이벤트 루프를 돌 수 있으므로 별도 스레드에서 실행.
    result = await asyncio.to_thread(send_message_tool, {"action": "send", "target": target, "message": message})
    try:
        parsed = json.loads(result) if isinstance(result, str) else result
    except (TypeError, ValueError):
        parsed = {"raw": result}
    return json.dumps(parsed, ensure_ascii=False)


# ---------------------------------------------------------------------------
def main() -> None:
    mcp.run()  # FastMCP stdio transport


if __name__ == "__main__":
    main()
