#!/usr/bin/env python3
"""E2-HTTP (real Hermes) — inquiry/schedule 를 실 Hermes API server 대상 검증 (plan-3 E2).

전제(사용자/권한 영역): Hermes API server 활성 + HERMES_API_KEY env 주입.
  ~/.hermes/.env: API_SERVER_ENABLED=true / API_SERVER_HOST=127.0.0.1 / API_SERVER_PORT=8642 / API_SERVER_KEY=...
  + `hermes gateway restart` + `export HERMES_API_KEY=<위 키>`
실행: <hermes_venv>/python tests/e2e_http_live.py
§ Verification Discipline: backend unavailable 시 SKIP(backend_unavailable), terminal state 도달만 PASS.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

API_BASE = os.getenv("HERMES_API_BASE", "http://127.0.0.1:8642")


def _backend_up() -> bool:
    try:
        req = urllib.request.Request(f"{API_BASE}/v1/models")
        key = os.getenv("HERMES_API_KEY", "")
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status in (200, 401)
    except Exception:
        try:
            urllib.request.urlopen(f"{API_BASE}/v1/models", timeout=5)
            return True
        except Exception as e:  # noqa
            return "401" in str(e) or "Unauthorized" in str(e)


def main() -> int:
    if not os.getenv("HERMES_API_KEY"):
        print("SKIP (backend_unavailable): HERMES_API_KEY 미설정 — export 후 재실행")
        return 0
    if not _backend_up():
        print(f"SKIP (backend_unavailable): {API_BASE} 미연결 — API server 활성+gateway restart 필요")
        return 0

    import hermes_mcp_gateway as gw
    gw.API_BASE = API_BASE
    results = {}

    def call(coro):
        return json.loads(asyncio.run(coro))

    # 1) inquiry sync — 실 /v1/responses
    r = call(gw.hermes_inquiry(input="hermes-bridge e2e 핑: 한 단어로 답해줘", mode="sync"))
    if "error" in r:
        print(f"[FAIL] inquiry: kind={r['kind']} ({r.get('error')})")
        results["inquiry"] = "FAIL"
    else:
        print(f"[ OK ] inquiry sync: response_id={r.get('response_id')}, text[:40]={r.get('text','')[:40]!r}")
        results["inquiry"] = "PASS"

    # 2) schedule create — 실 /api/jobs
    r = call(gw.hermes_schedule(name="hbridge-e2e", schedule="2099-01-01T00:00",
                                prompt="e2e 테스트 job", deliver="local"))
    jid = r.get("job_id")
    if "error" in r or not jid:
        print(f"[FAIL] schedule create: {r}")
        results["schedule_create"] = "FAIL"
    else:
        print(f"[ OK ] schedule create: job_id={jid}, next_run_at={r.get('next_run_at')}")
        results["schedule_create"] = "PASS"
        # 3) schedule status — 실 GET /api/jobs/{id}
        s = call(gw.hermes_schedule(job_id=jid))
        if "error" in s:
            print(f"[FAIL] schedule status: {s}")
            results["schedule_status"] = "FAIL"
        else:
            print(f"[ OK ] schedule status: state={s.get('state')}, last_status={s.get('last_status')}")
            results["schedule_status"] = "PASS"

    terminal = all(v == "PASS" for v in results.values())
    label = "PASS" if terminal else "FAIL"
    print(f"\nE2-HTTP (real Hermes): {label} — {results}")
    return 0 if terminal else 1


if __name__ == "__main__":
    raise SystemExit(main())
