#!/usr/bin/env python3
"""hermes-bridge — Claude Code stdio MCP adapter (plan-3 v1.4 compliant).

Claude → Hermes 단방향 위임 어댑터. 5개 정제 도구를 노출하고 각각 서로 다른
Hermes 표면으로 라우팅한다. SoT: docs/plan-2-plugin.md §1 + docs/plan-3-implementation.md.

표면 매핑
- hermes_inquiry  → POST /v1/responses (sync) | POST /v1/runs + GET /v1/runs/{id} poll (async)
- hermes_schedule → POST /api/jobs (create) | GET /api/jobs/{id} (job_id status poll)
- hermes_memo     → 어댑터 SQLite 노트 스토어 (WAL upsert)
- hermes_notes    → 어댑터 SQLite 노트 스토어 (조회/검색, limit clamp)
- hermes_send     → `hermes send` CLI subprocess (argv-only; API server 아님)

설계 결정 (plan-3)
- D1=CLI: send 는 `hermes send` CLI 위임 — Hermes import 없음(direct import 제거).
- D6=B: 본 .py 는 Hermes venv python 으로 wrapper(bin/hermes-mcp-gateway[.cmd]) 가 실행.
- A5: 모든 tool boundary try/except → canonical error schema {error,kind,status?,details?}.
- B7: 200+빈 출력은 빈 성공이 아니라 구조화 anomaly.
- C1/§14: MEDIA:<path> 가드(경로 denylist/크기/secret/TOCTOU) 후 message 임베드로 전달.
- W3: stdout/stderr + 자식 출력 UTF-8(errors=replace) — cp949 mojibake/crash 방지.
- O5: best-effort JSONL telemetry, never-throw.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

def _ensure_runtime() -> None:
    """C2: deps(mcp/httpx) 없는 python 으로 launch 돼도 Hermes venv python 으로 self re-exec.

    Claude Code 런처는 Windows 에서 extensionless/.cmd 절대경로를 exec 못 함(검증). interpreter+args 만 가능.
    bundled .mcp.json 은 venv 절대경로를 박을 수 없으므로 bare `python3` 로 시작 → 본 함수가 venv 로 승격.
    HERMES_VENV_PY(install 기록) 우선, 없으면 `hermes` 바이너리 옆 python 파생."""
    try:
        import mcp  # noqa: F401
        import httpx  # noqa: F401
        return  # deps 충족 — 정상 진행
    except ImportError:
        pass
    venv_py = os.environ.get("HERMES_VENV_PY", "")
    if not venv_py:
        hb = shutil.which("hermes")
        if hb:
            cand = Path(hb).resolve().parent / ("python.exe" if os.name == "nt" else "python")
            if cand.exists():
                venv_py = str(cand)
    if venv_py and os.path.realpath(venv_py) != os.path.realpath(sys.executable):
        os.execv(venv_py, [venv_py, os.path.realpath(__file__), *sys.argv[1:]])
    # 부트스트랩 불가 → 아래 import 가 명확한 ImportError 로 실패(silent 아님)


_ensure_runtime()

import httpx  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

# ---------------------------------------------------------------------------
# 인코딩 (W3) — stdout/stderr 를 UTF-8 로 강제 (KR Windows cp949 mojibake 방지)
# ---------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

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
SESSION_KEY: str = os.getenv("HERMES_SESSION_KEY", "")          # 선택 X-Hermes-Session-Key (B3)
NOTES_DB: str = _args.notes_db
HTTP_TIMEOUT = float(os.getenv("HERMES_BRIDGE_HTTP_TIMEOUT", "110"))  # < .mcp.json timeout(120s)
SEND_TIMEOUT = float(os.getenv("HERMES_BRIDGE_SEND_TIMEOUT", "60"))   # hermes send 자식 timeout (FP2)
HERMES_BIN: str = os.getenv("HERMES_BIN", "hermes")            # install(W4)이 절대경로 기록 (C8)
ASYNC_POLL_INTERVAL = float(os.getenv("HERMES_BRIDGE_ASYNC_POLL", "1.5"))
OUTPUT_MAX_CHARS = int(os.getenv("HERMES_BRIDGE_OUTPUT_MAX", str(200_000)))  # bounded output (B8)
NOTES_LIMIT_MAX = int(os.getenv("HERMES_BRIDGE_NOTES_LIMIT_MAX", "200"))     # bounded output (B8)
MEDIA_MAX_BYTES = int(os.getenv("HERMES_BRIDGE_MEDIA_MAX", str(25 * 1024 * 1024)))  # §14
TELEMETRY_DISABLED = os.getenv("HERMES_BRIDGE_TELEMETRY_DISABLED", "") == "1"  # O5
TELEMETRY_PATH = os.getenv("HERMES_BRIDGE_TELEMETRY",
                           str(Path.home() / ".hermes-bridge" / "telemetry.jsonl"))

mcp = FastMCP("hermes-bridge")


# ---------------------------------------------------------------------------
# canonical error schema (A5) + telemetry (O5)
# ---------------------------------------------------------------------------
def tool_error(error: Any, kind: str, status: Optional[str] = None,
               details: Optional[dict] = None) -> dict[str, Any]:
    """plan-3 §A5 canonical schema. kind ∈ {http_4xx,http_5xx,timeout,bad_json,
    empty_output,sqlite,subprocess,import,venv_drift,auth_missing,gateway_down,usage,media,unknown}."""
    out: dict[str, Any] = {"error": str(error), "kind": kind}
    if status is not None:
        out["status"] = status
    if details:
        out["details"] = details
    return out


def _telemetry(tool: str, outcome: str, *, error_kind: Optional[str] = None,
               duration_ms: Optional[int] = None, **corr: Any) -> None:
    """O5: best-effort 단일 라인 JSONL. payload·secret 미기록. never-throw."""
    if TELEMETRY_DISABLED:
        return
    try:
        rec: dict[str, Any] = {"ts": int(time.time() * 1000), "tool": tool, "outcome": outcome}
        if error_kind:
            rec["error_kind"] = error_kind
        if duration_ms is not None:
            rec["duration_ms"] = duration_ms
        for k, v in corr.items():
            if v is not None:
                rec[k] = v
        p = Path(TELEMETRY_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # non-load-bearing


def _finish(tool: str, t0: float, payload: dict[str, Any], *,
            outcome: str = "ok", error_kind: Optional[str] = None, **corr: Any) -> str:
    _telemetry(tool, outcome, error_kind=error_kind,
               duration_ms=int((time.time() - t0) * 1000), **corr)
    return json.dumps(payload, ensure_ascii=False)


def _http_kind(exc: httpx.HTTPStatusError) -> str:
    code = exc.response.status_code
    return "http_5xx" if code >= 500 else "http_4xx"


_PLACEHOLDER_RE = re.compile(r"changeme|placeholder|your[-_]?key|x{16,}", re.I)  # F03: bare 'xxxx' FP 제거


def _auth_headers() -> dict[str, str]:
    # m8/FP7: 매 호출 env read → key rotation 친화 + 런타임 strong-key 검증(§14).
    key = os.getenv("HERMES_API_KEY", "")
    if not key:
        raise PermissionError("HERMES_API_KEY 미설정 — API server는 모든 배포에서 키 필수.")
    if len(key) < 32 or _PLACEHOLDER_RE.search(key):
        raise PermissionError("HERMES_API_KEY 가 약함 (≥32자 + placeholder 거부) — strong key 필요(§14).")
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    sk = os.getenv("HERMES_SESSION_KEY", "")
    if sk:
        h["X-Hermes-Session-Key"] = sk  # B3 (Honcho per-chat scope)
    return h


# ---------------------------------------------------------------------------
# 노트 스토어 (memo / notes) — B9 (DDL/dedupe/upsert/search) + WAL(C3) + perms(C5)
# ---------------------------------------------------------------------------
def harden_perms(path: str, *, is_dir: bool = False) -> bool:
    """**best-effort** owner-only 권한 (C5/M8). POSIX chmod / Windows icacls.

    성공 True. 실패 시 raise 안 하고 telemetry 경고 후 False(F01) — ~/.hermes-bridge 는 OS 기본
    user-profile 하위라 이미 owner-scoped이므로 본 함수는 *추가 방어층*(fail-open 이 신규 노출 아님).

    Windows: **non-destructive** additive grant 만 한다 (`icacls /grant user:F`). 과거 `/inheritance:r`
    (상속 제거)는 sandbox/제한 컨텍스트에서 USERNAME 이 다르거나 grant 가 실패하면 파일에서 owner ACE
    까지 날려 'unable to open database file' 락아웃을 유발했다 → 절대 상속 제거 안 함. boundary 는
    user-profile ACL 이며 본 함수는 부가 layer 이므로 restrict 실패보다 락아웃 회피를 우선한다."""
    try:
        if sys.platform == "win32":
            user = os.environ.get("USERNAME") or os.environ.get("USER")
            if not (user and os.path.exists(path)):
                return False
            # additive only: 기존 ACE/상속 보존 → owner 가 절대 락아웃되지 않음
            proc = subprocess.run(["icacls", path, "/grant", f"{user}:F"],
                                  shell=False, capture_output=True, timeout=10)
            if proc.returncode != 0:
                _telemetry("harden_perms", "warn", error_kind="acl_failed")  # F01: 실패 가시화
                return False
            return True
        os.chmod(path, 0o700 if is_dir else 0o600)
        return True
    except Exception:
        _telemetry("harden_perms", "warn", error_kind="acl_failed")
        return False


# 해석된 쓰기 가능 DB 경로 캐시 — NOTES_DB 값이 바뀌면(테스트 등) 무효화하여 재해석.
_RESOLVED_NOTES_DB: Optional[str] = None
_RESOLVED_FOR: Optional[str] = None


def _notes_db_candidates() -> list[str]:
    """primary = 설정된 NOTES_DB(기본 ~/.hermes-bridge, 또는 HERMES_BRIDGE_NOTES_DB).
    fallback = OS temp/hermes-bridge — Claude Code MCP sandbox 가 user-profile(~)에 RX-only 만 주거나
    보호 경로(AV/네트워크/OneDrive)로 sqlite open 이 실패해도 memo/notes 가 절대 죽지 않게 한다.
    영속 저장을 원하면 HERMES_BRIDGE_NOTES_DB 를 쓰기 가능한 경로로 지정."""
    cands = [NOTES_DB]
    fb = str(Path(tempfile.gettempdir()) / "hermes-bridge" / "notes.sqlite")
    if fb not in cands:
        cands.append(fb)
    return cands


def _open_notes_db(db: str) -> sqlite3.Connection:
    """단일 경로로 연결 + DDL + 권한. 열기 실패 시 sqlite3.Error 를 그대로 raise(상위에서 fallback)."""
    db_path = Path(db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    harden_perms(str(db_path.parent), is_dir=True)  # ~/.hermes-bridge owner-only(additive)
    con = sqlite3.connect(db)
    try:
        # C3-b: 동시 MCP 세션의 single-writer 경합 시 'database is locked' 대신 5s 대기.
        con.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        pass
    try:
        # C3: WAL for concurrent-session safety. 보호 경로(OneDrive/네트워크/AV 잠금)에서
        # WAL 실패 시 기본 DELETE 모드로 graceful fallback.
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    con.execute(
        "CREATE TABLE IF NOT EXISTS notes("
        "id TEXT PRIMARY KEY, category TEXT, title TEXT, body TEXT, "
        "tags TEXT, dedupe_key TEXT NOT NULL UNIQUE, created_at INTEGER)"
    )
    # C5/M8: owner-only — POSIX chmod 600 + Windows icacls. DB + WAL/SHM 사이드카.
    for suffix in ("", "-wal", "-shm"):
        sidecar = db + suffix
        if os.path.exists(sidecar):
            harden_perms(sidecar)
    return con


def _notes_conn() -> sqlite3.Connection:
    """primary NOTES_DB 로 연결 시도, 쓰기 불가(sandbox RX-only home 등)면 temp 로 fallback.
    해석된 경로는 (현재 NOTES_DB 값에 한해) 캐시 — 매 호출 실패 connect 반복 방지 + 테스트 격리."""
    global _RESOLVED_NOTES_DB, _RESOLVED_FOR
    if _RESOLVED_NOTES_DB and _RESOLVED_FOR == NOTES_DB:
        try:
            return _open_notes_db(_RESOLVED_NOTES_DB)
        except (sqlite3.Error, OSError):
            _RESOLVED_NOTES_DB = None  # 캐시 stale → 재해석
    # sqlite open 실패뿐 아니라 mkdir 의 OSError/PermissionError(경로 생성 불가)도 fallback 대상.
    last_err: Optional[Exception] = None
    for db in _notes_db_candidates():
        try:
            con = _open_notes_db(db)
            if db != NOTES_DB:  # fallback 발동 — 가시화(best-effort, never-throw)
                _telemetry("notes_db", "warn", error_kind="notes_db_fallback", path=db)
            _RESOLVED_NOTES_DB, _RESOLVED_FOR = db, NOTES_DB
            return con
        except (sqlite3.Error, OSError) as e:
            last_err = e
            continue
    raise last_err if last_err else sqlite3.OperationalError("no writable notes db path")


def _derive_dedupe_key(category: str, title: str, body: str) -> str:
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
    t0 = time.time()
    try:
        tags = tags or []
        key = dedupeKey or _derive_dedupe_key(category, title, body)
        now = int(time.time())
        with contextlib.closing(_notes_conn()) as con, con:  # m23: commit + close
            con.execute(
                "INSERT INTO notes(id, category, title, body, tags, dedupe_key, created_at) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(dedupe_key) DO UPDATE SET "
                "category=excluded.category, title=excluded.title, body=excluded.body, tags=excluded.tags",
                (key, category, title, body, json.dumps(tags, ensure_ascii=False), key, now),
            )
        return _finish("hermes_memo", t0, {"note_id": key, "dedupe_key": key, "status": "ok"})
    except sqlite3.Error as e:
        return _finish("hermes_memo", t0, tool_error(e, "sqlite"),
                       outcome="error", error_kind="sqlite")
    except Exception as e:
        return _finish("hermes_memo", t0, tool_error(e, "unknown"),
                       outcome="error", error_kind="unknown")


@mcp.tool()
def hermes_notes(query: Optional[str] = None, category: Optional[str] = None,
                 tags: Optional[str] = None, limit: int = 20) -> str:
    """저장된 메모를 조회/검색한다 (write-only 아님)."""
    t0 = time.time()
    try:
        limit = max(1, min(int(limit), NOTES_LIMIT_MAX))  # B8 bounded
        sql = "SELECT id, category, title, body, tags, created_at FROM notes WHERE 1=1"
        params: list[Any] = []
        if category:
            sql += " AND category=?"; params.append(category)
        if tags:
            sql += " AND tags LIKE ?"; params.append(f"%{tags}%")
        if query:
            sql += " AND (title LIKE ? OR body LIKE ?)"; params += [f"%{query}%", f"%{query}%"]
        sql += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
        with contextlib.closing(_notes_conn()) as con, con:  # m23: commit + close
            rows = con.execute(sql, params).fetchall()
        out = [{"note_id": r[0], "category": r[1], "title": r[2], "body": r[3],
                "tags": json.loads(r[4] or "[]"), "created_at": r[5]} for r in rows]
        return _finish("hermes_notes", t0, {"notes": out, "count": len(out)}, count=len(out))
    except sqlite3.Error as e:
        return _finish("hermes_notes", t0, tool_error(e, "sqlite"),
                       outcome="error", error_kind="sqlite")
    except Exception as e:
        return _finish("hermes_notes", t0, tool_error(e, "unknown"),
                       outcome="error", error_kind="unknown")


# ---------------------------------------------------------------------------
# inquiry → /v1/responses (sync) | /v1/runs poll (async)  — B1/B3/B6/B7
# ---------------------------------------------------------------------------
def _extract_output_text(resp: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in resp.get("output", []) or []:
        if not isinstance(item, dict):  # m7: 잘못된 형태 200 → empty_output 경로로 degrade
            continue
        for c in item.get("content", []) or []:
            if isinstance(c, dict) and c.get("type") == "output_text" and c.get("text"):
                parts.append(str(c["text"]))
    text = "\n".join(parts).strip()
    return text[:OUTPUT_MAX_CHARS]  # B8 bounded


async def _inquiry_sync(input: str, previous_response_id: Optional[str]) -> dict[str, Any]:
    body: dict[str, Any] = {"input": input}
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(f"{API_BASE}/v1/responses", headers=_auth_headers(), json=body)
        r.raise_for_status()
        data = r.json()
    text = _extract_output_text(data)
    if not text:  # B7 empty-success anomaly
        return tool_error("no output_text in /v1/responses", "empty_output", status="empty",
                          details={"response_id": data.get("id")})
    return {"response_id": data.get("id"), "text": text, "status": data.get("status") or "completed"}


async def _inquiry_async(input: str, run_id: Optional[str]) -> dict[str, Any]:
    """B1: 풀 에이전트 루프. POST /v1/runs → GET /v1/runs/{id} poll until terminal.
    (plan 의 'SSE delta/done' 은 /v1/responses 용 혼동 — /v1/runs 는 lifecycle 이벤트라
    poll 방식이 정확. 본 어댑터는 client-pull 폴링 채택.)"""
    # M4: monotonic deadline + per-request remaining budget → 총합이 host 120s 를 넘지 않게.
    deadline = time.monotonic() + HTTP_TIMEOUT

    def _remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    async with httpx.AsyncClient() as client:  # 기본 timeout 미사용 — 매 요청 remaining 으로 cap
        if not run_id:
            r = await client.post(f"{API_BASE}/v1/runs", headers=_auth_headers(),
                                  json={"input": input}, timeout=min(_remaining(), HTTP_TIMEOUT))
            r.raise_for_status()
            created = r.json()
            run_id = (created.get("run_id") or created.get("id")) if isinstance(created, dict) else None
            if not run_id:
                return tool_error("no run_id from POST /v1/runs", "empty_output", status="empty")
        # client-pull 폴링 (bounded — 각 GET 도 remaining 으로 cap)
        while _remaining() > 0:
            r = await client.get(f"{API_BASE}/v1/runs/{run_id}", headers=_auth_headers(),
                                 timeout=min(_remaining(), 30.0))
            r.raise_for_status()
            data = r.json()
            st = data if isinstance(data, dict) else {}
            status = st.get("status")
            if status == "completed":
                text = str(st.get("output") or "").strip()[:OUTPUT_MAX_CHARS]
                if not text:
                    return tool_error("run completed with empty output", "empty_output",
                                      status="empty", details={"run_id": run_id})
                return {"run_id": run_id, "text": text, "status": "completed"}
            if status in ("failed", "cancelled"):
                return tool_error(st.get("error") or f"run {status}", "gateway_down",
                                  status=status, details={"run_id": run_id})
            if status == "waiting_for_approval":  # M5: 승인 대기는 즉시 actionable 로 반환(스핀 금지)
                return {"run_id": run_id, "status": "needs_approval",
                        "note": "run 승인 대기 — Hermes 측 승인 후 hermes_inquiry(run_id=...)로 재폴링"}
            await asyncio.sleep(min(ASYNC_POLL_INTERVAL, _remaining()))
        # 어댑터 timeout 내 미종결 — run_id 반환(재폴링용, hermes_inquiry(run_id=...))
        return {"run_id": run_id, "status": "running",
                "note": "full agent loop 진행 중 — hermes_inquiry(run_id=...)로 재폴링"}


@mcp.tool()
async def hermes_inquiry(input: str = "", previous_response_id: Optional[str] = None,
                         mode: str = "sync", run_id: Optional[str] = None) -> str:
    """비개발 문의를 Hermes 에이전트에 위임한다.

    mode='sync'(기본): POST /v1/responses 동기. mode='async': 풀 루프 예상 시 POST /v1/runs
    후 폴링(in-flight 전환 불가 — 처음부터 선택). run_id 지정 시: 진행 중 async run 재폴링.
    previous_response_id: sync 컨텍스트 체이닝. send 와 달리 inquiry 는 stateful.
    """
    t0 = time.time()
    try:
        if mode not in ("sync", "async"):  # M6: silent degrade 금지 → unsupported 명시 에러
            return _finish("hermes_inquiry", t0,
                           tool_error(f"unsupported mode: {mode!r} (sync|async)", "usage"),
                           outcome="error", error_kind="usage")
        if run_id:
            result = await _inquiry_async("", run_id)
        elif mode == "async":
            if not input:
                return _finish("hermes_inquiry", t0, tool_error("input required", "usage"),
                               outcome="error", error_kind="usage")
            result = await _inquiry_async(input, None)
        else:
            if not input:
                return _finish("hermes_inquiry", t0, tool_error("input required", "usage"),
                               outcome="error", error_kind="usage")
            result = await _inquiry_sync(input, previous_response_id)
        outcome = "error" if "error" in result else "ok"
        return _finish("hermes_inquiry", t0, result, outcome=outcome,
                       error_kind=result.get("kind"), response_id=result.get("response_id"),
                       run_id=result.get("run_id"))
    except httpx.HTTPStatusError as e:
        k = _http_kind(e)
        return _finish("hermes_inquiry", t0, tool_error(e, k), outcome="error", error_kind=k)
    except httpx.TimeoutException as e:
        return _finish("hermes_inquiry", t0, tool_error(e, "timeout"),
                       outcome="error", error_kind="timeout")
    except json.JSONDecodeError as e:
        return _finish("hermes_inquiry", t0, tool_error(e, "bad_json"),
                       outcome="error", error_kind="bad_json")
    except PermissionError as e:
        return _finish("hermes_inquiry", t0, tool_error(e, "auth_missing"),
                       outcome="error", error_kind="auth_missing")
    except Exception as e:
        return _finish("hermes_inquiry", t0, tool_error(e, "unknown"),
                       outcome="error", error_kind="unknown")


# ---------------------------------------------------------------------------
# schedule → POST /api/jobs (create) | GET /api/jobs/{id} (status) — B2/B4/B5
# ---------------------------------------------------------------------------
@mcp.tool()
async def hermes_schedule(name: str = "", schedule: str = "", prompt: str = "",
                          deliver: str = "local", repeat: Optional[int] = None,
                          skills: Optional[list[str]] = None, job_id: Optional[str] = None) -> str:
    """cron job을 생성하거나(job_id 미지정) 상태를 조회한다(job_id 지정). 캘린더 아님.

    생성: name(필수,≤200), schedule(필수, 예 '30m'/'2026-06-11T14:00'/cron식), prompt(≤5000),
    deliver(기본 'local'; 팀 채널은 'slack:#biz' 등), repeat?, skills?. 발화는 gateway 상시 가동
    필요(§1.3). 상태조회: job_id 지정 시 발화/미발화/실패 3-state(B2). 길이는 백엔드 400 강제(B5).
    """
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            if job_id:  # B2 status poll mode
                r = await client.get(f"{API_BASE}/api/jobs/{job_id}", headers=_auth_headers())
                r.raise_for_status()
                data = r.json()  # m1: parse once + isinstance
                job = data.get("job", data) if isinstance(data, dict) else {}
                last_run = job.get("last_run_at")
                last_err = job.get("last_error")
                last_status = job.get("last_status")          # Hermes: "ok"/"error" (jobs.py:927)
                delivery_err = job.get("last_delivery_error")  # M7: 채널 전달 실패 (jobs.py:930)
                if delivery_err:
                    state = "delivery_failed"  # 에이전트 실행됐으나 채널 전달 실패 → false success 방지
                elif last_status == "error" or last_err:
                    state = "failed"
                elif last_status == "ok" or last_run:
                    state = "fired"
                else:
                    state = "pending"  # next_run 경과+미설정이면 gateway 미가동 의심
                warn = None
                if state == "pending":
                    warn = "미발화 — gateway 상시 가동 확인 필요(§1.3)"
                elif state == "delivery_failed":
                    warn = "에이전트는 실행됐으나 채널 전달 실패 — deliver 타깃/플랫폼 자격증명 확인"
                return _finish("hermes_schedule", t0, {
                    "job_id": job_id, "state": state, "last_status": last_status,
                    "last_run_at": last_run, "last_error": last_err,
                    "last_delivery_error": delivery_err, "next_run_at": job.get("next_run_at"),
                    "warn": warn,
                }, job_id=job_id)
            # create mode
            if not name or not schedule:
                return _finish("hermes_schedule", t0,
                               tool_error("name and schedule required for create", "usage"),
                               outcome="error", error_kind="usage")
            body: dict[str, Any] = {"name": name, "schedule": schedule,
                                    "prompt": prompt, "deliver": deliver}
            if repeat is not None:
                body["repeat"] = repeat
            if skills:
                body["skills"] = skills
            r = await client.post(f"{API_BASE}/api/jobs", headers=_auth_headers(), json=body)
            r.raise_for_status()
            data = r.json()  # m1: parse once + isinstance
            job = data.get("job", {}) if isinstance(data, dict) else {}
        jid = job.get("id")
        if not jid:  # B7 empty-success anomaly
            return _finish("hermes_schedule", t0,
                           tool_error("job created but no id returned", "empty_output", status="empty"),
                           outcome="error", error_kind="empty_output")
        warn = None if deliver != "local" else "deliver='local' — 채널 도착 ack 없음. 팀 공유는 deliver를 채널 타깃으로."
        return _finish("hermes_schedule", t0, {
            "job_id": jid, "next_run_at": job.get("next_run_at"),
            "note": "cron 발화는 gateway 상시 가동 필요. 상태는 hermes_schedule(job_id=...)로 폴링.",
            "warn": warn,
        }, job_id=jid)
    except httpx.HTTPStatusError as e:
        k = _http_kind(e)
        return _finish("hermes_schedule", t0, tool_error(e, k), outcome="error", error_kind=k)
    except httpx.TimeoutException as e:
        return _finish("hermes_schedule", t0, tool_error(e, "timeout"),
                       outcome="error", error_kind="timeout")
    except json.JSONDecodeError as e:  # m2: parity with hermes_inquiry
        return _finish("hermes_schedule", t0, tool_error(e, "bad_json"),
                       outcome="error", error_kind="bad_json")
    except PermissionError as e:
        return _finish("hermes_schedule", t0, tool_error(e, "auth_missing"),
                       outcome="error", error_kind="auth_missing")
    except Exception as e:
        return _finish("hermes_schedule", t0, tool_error(e, "unknown"),
                       outcome="error", error_kind="unknown")


# ---------------------------------------------------------------------------
# send → `hermes send` CLI subprocess (A3/C1/C8/FP2/FP6)
# ---------------------------------------------------------------------------
# Hermes MEDIA_DELIVERY_EXTS 미러 (gateway/platforms/base.py:1164) — adapter 가 Hermes 가 실제
# 전송하는 것과 동일 집합을 스캔하도록(scanned==transmitted 불변식, code-review M1/M2).
_MEDIA_EXTS = (
    "png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff", "svg", "mp4", "mov", "avi", "mkv", "webm",
    "mp3", "wav", "ogg", "opus", "m4a", "flac", "pdf", "docx", "doc", "odt", "rtf", "txt", "md", "epub",
    "xlsx", "xls", "ods", "csv", "tsv", "json", "xml", "yaml", "yml", "pptx", "ppt", "odp", "key",
    "zip", "tar", "gz", "tgz", "bz2", "xz", "7z", "rar", "apk", "ipa", "html", "htm",
)
_EXT_ALT = "|".join(sorted(_MEDIA_EXTS, key=len, reverse=True))
# Hermes MEDIA_TAG_CLEANUP_RE 미러(base.py:1200): 선택 quote + MEDIA: + \s* + 절대/홈 경로(공백 허용) + 알려진 확장자.
# group(1)=정제된 경로(따옴표 밖) → 확장자 allowlist 가 regex 로 강제됨(m6).
_MEDIA_RE = re.compile(
    r"""[`"']?MEDIA:\s*((?:~/|/|[A-Za-z]:[/\\])\S+(?:[^\S\n]+\S+)*?\.(?:""" + _EXT_ALT + r"""))['"`]?""",
    re.IGNORECASE)
_SECRET_NAME_RE = re.compile(
    r"(^\.env$|\.env\.|\.env$|credentials|\.key$|\.pem$|\.pfx$|id_rsa|id_ed25519|id_ecdsa|"
    r"\.npmrc$|\.pgpass$|\.kube|secret)", re.I)
_SECRET_DIR_PARTS = {".ssh", ".aws", ".gnupg", ".kube", ".azure", "gcloud", ".gcloud"}
_SECRET_CONTENT_RE = re.compile(
    rb"(AKIA[0-9A-Z]{16}"
    rb"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    rb"|HERMES_API_KEY\s*="
    rb"|xox[baprs]-[0-9A-Za-z-]{10,}"
    rb"|sk-[A-Za-z0-9]{20,}"
    rb"|gh[pousr]_[A-Za-z0-9]{20,}"
    rb"|github_pat_[A-Za-z0-9_]{20,}"
    rb"|AIza[0-9A-Za-z_-]{20,}"
    rb'|"private_key"\s*:'
    rb"|(?:SECRET|TOKEN|PASSWORD|API[_-]?KEY)\s*[=:]\s*\S{8,})", re.I)
_MEDIA_SCAN_BYTES = int(os.getenv("HERMES_BRIDGE_MEDIA_SCAN_BYTES", str(1024 * 1024)))  # head scan cap (m4)


def _guard_media(message: str) -> Optional[dict[str, Any]]:
    """C1/§14: message 의 MEDIA:<path>(Hermes 파서와 동일 정규식) 를 검증.

    denylist(경로/파일명) + 크기 + secret(이름·내용) + symlink/TOCTOU. 위반 시 canonical media error.
    잔여 reopen-gap(스캔 후 Hermes 재오픈)은 Hermes filter_media_delivery_paths 2차 가드에 의존(plan §14).
    """
    for m in _MEDIA_RE.finditer(message):
        raw = m.group(1)
        try:
            p = Path(raw).expanduser()
        except Exception:
            return tool_error(f"invalid MEDIA path: {raw}", "media")
        lowered_parts = {part.lower() for part in p.parts}
        if lowered_parts & _SECRET_DIR_PARTS or _SECRET_NAME_RE.search(p.name):
            return tool_error(f"MEDIA path denied (sensitive): {raw}", "media", details={"path": str(p)})
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            if os.path.islink(p):  # Windows fallback(O_NOFOLLOW 부재) + intermediate 방어 보조
                return tool_error(f"MEDIA path is a symlink (denied): {raw}", "media")
            fd = os.open(str(p), flags)
        except FileNotFoundError:
            return tool_error(f"MEDIA file not found: {raw}", "media")
        except OSError as e:
            return tool_error(f"MEDIA open failed: {raw} ({e})", "media")
        try:
            st = os.fstat(fd)
            # 열린 fd 와 path 의 lstat 비교 — open 직전 심링크 스왑 탐지(m5 보강)
            try:
                lst = os.lstat(str(p))
                if (st.st_ino, st.st_dev) != (lst.st_ino, lst.st_dev):
                    return tool_error(f"MEDIA path changed during validation (TOCTOU): {raw}", "media")
            except OSError:
                pass
            if st.st_size > MEDIA_MAX_BYTES:
                return tool_error(f"MEDIA too large: {raw} ({st.st_size} > {MEDIA_MAX_BYTES})",
                                  "media", details={"size": st.st_size})
            head = os.read(fd, _MEDIA_SCAN_BYTES)
            if _SECRET_CONTENT_RE.search(head):
                return tool_error(f"MEDIA content looks like a secret (denied): {raw}", "media")
        finally:
            os.close(fd)
    return None


@mcp.tool()
async def hermes_send(target: str = "", message: str = "") -> str:
    """메시지를 발송한다. target='platform:id'(예: 'slack:#biz'). 첨부는 message에 'MEDIA:<path>'.

    `hermes send` CLI(argv-only)로 위임 — API server toolset 제외(/v1/* 금지). 표준/yuanbao 분기는
    Hermes 내부가 target prefix로 결정(어댑터 패스스루). yuanbao/plugin-live 는 gateway 미가동 시
    CLI가 구조화 에러 반환(그대로 surface). 첨부는 MEDIA:<path> 임베드(--file 아님, Hermes extract_media).
    """
    t0 = time.time()
    try:
        if not target or not message:
            return _finish("hermes_send", t0, tool_error("target and message both required", "usage"),
                           outcome="error", error_kind="usage")
        media_err = _guard_media(message)  # C1: send 전 필수
        if media_err is not None:
            return _finish("hermes_send", t0, media_err, outcome="error", error_kind="media")
        # C8/m10: 절대경로 우선 + which 해석 + 부재 시 fail-closed(PATH-hijack degrade 차단)
        bin_path = HERMES_BIN
        if not (os.path.isabs(bin_path) and os.path.exists(bin_path)):
            resolved = shutil.which(bin_path)
            if not resolved:
                return _finish("hermes_send", t0,
                               tool_error(f"`hermes` 실행파일 미발견 ({HERMES_BIN}) — install 재실행(W4/FP8)", "import"),
                               outcome="error", error_kind="import")
            bin_path = resolved
        # shell=False + 절대경로 + argv-only(문자열 조합 금지) + message는 -- 뒤
        argv = [bin_path, "send", "--to", target, "--json", "--", message]
        try:
            proc = subprocess.run(argv, shell=False, capture_output=True,
                                  encoding="utf-8", errors="replace", timeout=SEND_TIMEOUT)  # W3/FP6/FP2
        except FileNotFoundError:
            return _finish("hermes_send", t0,
                           tool_error(f"`hermes` not found ({bin_path}) — install 재실행(W4)", "import"),
                           outcome="error", error_kind="import")
        except subprocess.TimeoutExpired:
            return _finish("hermes_send", t0, tool_error("hermes send timed out", "timeout"),
                           outcome="error", error_kind="timeout")
        if proc.returncode == 0:
            try:
                parsed = json.loads(proc.stdout) if proc.stdout.strip() else {}
            except (TypeError, ValueError):
                parsed = {"raw": proc.stdout}
            return _finish("hermes_send", t0, {"status": "ok", "result": parsed})
        # exit 1=delivery/backend(gateway down/yuanbao 미가동 포함), 2=usage
        kind = "usage" if proc.returncode == 2 else "gateway_down"
        msg = (proc.stderr or proc.stdout or f"hermes send exit {proc.returncode}").strip()
        return _finish("hermes_send", t0,
                       tool_error(msg, kind, details={"exit": proc.returncode}),
                       outcome="error", error_kind=kind)
    except Exception as e:
        return _finish("hermes_send", t0, tool_error(e, "unknown"),
                       outcome="error", error_kind="unknown")


# ---------------------------------------------------------------------------
def main() -> None:
    mcp.run()  # FastMCP stdio transport


if __name__ == "__main__":
    main()
