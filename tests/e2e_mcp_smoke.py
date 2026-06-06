#!/usr/bin/env python3
"""E2 — 실제 MCP stdio JSON-RPC 로 어댑터 구동 (plan-3 Track E2, API-server-불요 영역).

실 FastMCP stdio transport(newline-delimited JSON-RPC) + initialize/tools.list/tools.call.
memo→notes 한글 roundtrip + send 에러경로 + MEDIA 가드 + mode 검증 — 전부 실제 프로토콜.
inquiry/schedule HTTP 는 API server 필요 → 본 스크립트 범위 밖(backend_unavailable, 별도).
SDK stdio_client 대신 raw JSON-RPC 사용(이식성/디버깅 용이).
실행: <hermes_venv>/python tests/e2e_mcp_smoke.py
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_EXPECT = ["hermes_inquiry", "hermes_memo", "hermes_notes", "hermes_schedule", "hermes_send"]


class McpStdio:
    """binary stdio JSON-RPC. 별도 reader 스레드로 라인 수집(Windows Popen 파이프 deadlock/버퍼 회피)."""
    def __init__(self, proc: subprocess.Popen, err_path: str):
        self.p = proc
        self._id = 0
        self._err_path = err_path
        self._q: "queue.Queue[bytes]" = queue.Queue()
        self._t = threading.Thread(target=self._reader, daemon=True)
        self._t.start()

    def _reader(self) -> None:
        for raw in self.p.stdout:  # binary 라인 iterator
            self._q.put(raw)
        self._q.put(b"")  # EOF sentinel

    def _send(self, obj: dict) -> None:
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        self.p.stdin.write(data)
        self.p.stdin.flush()

    def _read_id(self, want_id: int, timeout: float = 15.0) -> dict:
        while True:
            try:
                raw = self._q.get(timeout=timeout)
            except queue.Empty:
                err = ""
                try:
                    err = Path(self._err_path).read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
                raise RuntimeError(f"timeout waiting id={want_id}. stderr:\n{err}")
            if raw == b"":
                err = Path(self._err_path).read_text(encoding="utf-8", errors="replace") if Path(self._err_path).exists() else ""
                raise RuntimeError(f"server closed stdout. stderr:\n{err}")
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("id") == want_id:
                return msg

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        resp = self._read_id(self._id)
        if "error" in resp:
            raise RuntimeError(f"{method} error: {resp['error']}")
        return resp["result"]

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def call_tool(self, name: str, args: dict) -> dict:
        res = self.request("tools/call", {"name": name, "arguments": args})
        # content[].text(첫 text 블록) 가 어댑터의 JSON 문자열
        for block in res.get("content", []):
            if block.get("type") == "text":
                return json.loads(block["text"])
        raise AssertionError(f"no text content: {res}")


def main() -> int:
    py = sys.executable
    db = str(Path(tempfile.mkdtemp()) / "e2e.sqlite")
    env = {**os.environ, "HERMES_BRIDGE_NOTES_DB": db, "PYTHONIOENCODING": "utf-8",
           "HERMES_BRIDGE_TELEMETRY_DISABLED": "1"}
    err_path = str(Path(tempfile.mkdtemp()) / "stderr.log")
    err_f = open(err_path, "w", encoding="utf-8")
    # stderr 를 파일로 — PIPE 미독시 버퍼 차서 서버가 stderr write 에 블록되는 deadlock 방지.
    proc = subprocess.Popen(
        [py, str(_ROOT / "bin" / "hermes_mcp_gateway.py"), "--notes-db", db],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err_f,
        env=env, bufsize=0)  # binary unbuffered — text-mode 뉴라인 변환/버퍼 회피
    try:
        c = McpStdio(proc, err_path)
        init = c.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                        "clientInfo": {"name": "e2e", "version": "1"}})
        assert init["serverInfo"]["name"] == "hermes-bridge", init
        c.notify("notifications/initialized")
        print(f"[ OK ] initialize: serverInfo={init['serverInfo']['name']}")

        tools = c.request("tools/list")
        names = sorted(t["name"] for t in tools["tools"])
        assert names == _EXPECT, f"tools mismatch: {names}"
        print(f"[ OK ] tools/list: {names}")

        memo = c.call_tool("hermes_memo", {"category": "e2e", "title": "회의록",
                                           "body": "본문 한글 内容", "tags": ["x"]})
        assert memo.get("status") == "ok", memo
        print(f"[ OK ] hermes_memo: {memo['note_id'][:8]}…")

        notes = c.call_tool("hermes_notes", {"query": "한글"})
        assert notes.get("count") == 1, notes
        assert notes["notes"][0]["body"] == "본문 한글 内容", f"CJK 손상: {notes}"
        print(f"[ OK ] hermes_notes: count={notes['count']} (한글/CJK 무손실)")

        # send 도구 경로(MCP 프로토콜 통과) — MEDIA 가드로 subprocess 전 결정적 반환.
        # (라이브 send 는 Hermes CLI/네트워크 의존 flaky → unit test 의 exit-code mock 으로 커버)
        guarded = c.call_tool("hermes_send", {"target": "slack:#x",
                                              "message": "MEDIA:/no/such/credentials.json"})
        assert guarded.get("kind") == "media", guarded
        print(f"[ OK ] MEDIA 가드: {guarded['kind']} (secret 첨부 차단)")

        bad = c.call_tool("hermes_inquiry", {"input": "x", "mode": "asnyc"})
        assert bad.get("kind") == "usage", bad
        print(f"[ OK ] mode 검증: {bad['kind']} (오타 mode 거부)")

        print("\nE2 MCP stdio e2e: PASS — initialize/tools.list/memo/notes(한글)/send-error/media/mode")
        return 0
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        try:
            err_f.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
