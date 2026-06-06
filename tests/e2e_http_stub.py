#!/usr/bin/env python3
"""E2-HTTP (stub) — 어댑터의 실 httpx 네트워크 스택을 계약-충실 로컬 stub 서버로 검증.

E1(httpx.AsyncClient 전체 mock)보다 한 단계 위: 실 소켓 I/O + 요청 직렬화 + Bearer 헤더 +
응답 파싱을 진짜 HTTP 로 검증. 단, 실 Hermes 비즈니스로직은 아님(그건 user/harness-gated).
- inquiry sync(/v1/responses), schedule create(/api/jobs), schedule status(GET /api/jobs/{id})
- 인증 헤더 실제 전달 확인, output_text 파싱, job 3-state
실행: <hermes_venv>/python tests/e2e_http_stub.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

_SEEN_AUTH: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    def _auth_ok(self) -> bool:
        a = self.headers.get("Authorization", "")
        _SEEN_AUTH.append(a)
        return a.startswith("Bearer ") and len(a) > len("Bearer ") + 10

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if not self._auth_ok():
            return self._send(401, {"error": "unauthorized"})
        ln = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(ln) or b"{}")
        if self.path == "/v1/responses":
            self._send(200, {"id": "resp_1", "status": "completed",
                             "output": [{"content": [{"type": "output_text",
                                                      "text": "stub 응답: " + body.get("input", "")}]}]})
        elif self.path == "/api/jobs":
            self._send(200, {"job": {"id": "job_1", "next_run_at": "2026-06-11T14:00",
                                     "name": body.get("name")}})
        else:
            self._send(404, {"error": "not found"})

    def do_GET(self):  # noqa: N802
        if not self._auth_ok():
            return self._send(401, {"error": "unauthorized"})
        if self.path.startswith("/api/jobs/"):
            self._send(200, {"job": {"id": "job_1", "last_status": "ok",
                                     "last_run_at": "2026-06-11T14:00", "next_run_at": "2026-06-18T14:00"}})
        elif self.path == "/v1/models":
            self._send(200, {"data": [{"id": "hermes"}]})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *a):  # 조용히
        pass


def main() -> int:
    import asyncio
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    try:
        os.environ["HERMES_API_KEY"] = "e" * 40  # strong (≥32, no placeholder)
        import hermes_mcp_gateway as gw
        gw.API_BASE = base  # 실 httpx 가 stub 으로 요청

        def call(coro):
            return json.loads(asyncio.run(coro))

        r = call(gw.hermes_inquiry(input="안녕 hermes", mode="sync"))
        assert r.get("text", "").startswith("stub 응답: 안녕 hermes"), r
        assert r.get("response_id") == "resp_1", r
        print(f"[ OK ] inquiry sync (실 httpx → stub): text 파싱 + response_id={r['response_id']}")

        r = call(gw.hermes_schedule(name="회의 알림", schedule="2026-06-11T14:00", prompt="x", deliver="slack:#biz"))
        assert r.get("job_id") == "job_1", r
        assert r.get("next_run_at") == "2026-06-11T14:00", r
        print(f"[ OK ] schedule create (실 httpx → stub): job_id={r['job_id']}, next_run_at 보존")

        r = call(gw.hermes_schedule(job_id="job_1"))
        assert r.get("state") == "fired", r
        print(f"[ OK ] schedule status poll (GET): state={r['state']} (last_status=ok)")

        # 인증 헤더 실제 전달 검증
        assert any(a.startswith("Bearer eeeee") for a in _SEEN_AUTH), _SEEN_AUTH[:2]
        print(f"[ OK ] Bearer 인증 헤더 실 전달 확인 ({len(_SEEN_AUTH)} requests)")

        # 401 경로(약한 키) — strong-key 게이트
        os.environ["HERMES_API_KEY"] = "short"
        r = call(gw.hermes_inquiry(input="x", mode="sync"))
        assert r.get("kind") == "auth_missing", r
        print(f"[ OK ] strong-key 게이트: weak key → {r['kind']} (요청 전 차단)")

        print("\nE2-HTTP (stub) PASS — 어댑터 실 httpx 네트워크 스택 검증(소켓 I/O + Bearer + 파싱 + 3-state)")
        print("주의: 실 Hermes 비즈니스로직 아님 — real-Hermes live 는 API server 활성 필요(harness/user-gated)")
        return 0
    finally:
        srv.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
