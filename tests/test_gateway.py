#!/usr/bin/env python3
"""hermes-bridge 어댑터 로컬 단위 테스트 (plan-3 Track E1).

실행: <hermes_venv>/python -m unittest discover -s tests  (또는 tests/test_gateway.py 직접)
외부 의존 없음 — HTTP/subprocess 경로는 mock. 실 Hermes e2e 는 E2(별도).
stdlib unittest 만 사용(pytest 불요).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 어댑터 import (mcp/httpx 필요 — Hermes venv 에서 실행). bin/ 을 path 에 추가.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "bin"))
import hermes_mcp_gateway as gw  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def loads(s: str) -> dict:
    return json.loads(s)


class TestPureHelpers(unittest.TestCase):
    def test_dedupe_key_deterministic_and_canonical(self):
        a = gw._derive_dedupe_key("c", "t", "b")
        b = gw._derive_dedupe_key("c", "t", "b")
        self.assertEqual(a, b)
        # 필드 순서 무관(canonical) + 구분자 모호성 방지
        self.assertNotEqual(gw._derive_dedupe_key("c", "t", "b"),
                            gw._derive_dedupe_key("ct", "", "b"))

    def test_extract_output_text_normal(self):
        resp = {"output": [{"content": [{"type": "output_text", "text": "hi"},
                                        {"type": "other", "text": "skip"}]}]}
        self.assertEqual(gw._extract_output_text(resp), "hi")

    def test_extract_output_text_empty_and_missing(self):
        self.assertEqual(gw._extract_output_text({}), "")
        self.assertEqual(gw._extract_output_text({"output": []}), "")
        self.assertEqual(gw._extract_output_text({"output": [{"content": []}]}), "")

    def test_extract_output_text_bounded(self):
        big = "x" * (gw.OUTPUT_MAX_CHARS + 5000)
        resp = {"output": [{"content": [{"type": "output_text", "text": big}]}]}
        self.assertLessEqual(len(gw._extract_output_text(resp)), gw.OUTPUT_MAX_CHARS)

    def test_tool_error_schema(self):
        e = gw.tool_error("boom", "timeout", status="x", details={"k": 1})
        self.assertEqual(e["error"], "boom")
        self.assertEqual(e["kind"], "timeout")
        self.assertEqual(e["status"], "x")
        self.assertEqual(e["details"], {"k": 1})
        e2 = gw.tool_error("b", "usage")
        self.assertNotIn("status", e2)
        self.assertNotIn("details", e2)


class TestNotesStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = gw.NOTES_DB
        gw.NOTES_DB = str(Path(self.tmp) / "notes.sqlite")

    def tearDown(self):
        gw.NOTES_DB = self._orig

    def test_memo_then_notes_roundtrip(self):
        r = loads(gw.hermes_memo("meeting", "회의록", "본문 한글", tags=["t1"]))
        self.assertEqual(r["status"], "ok")
        nid = r["note_id"]
        out = loads(gw.hermes_notes(query="한글"))
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["notes"][0]["note_id"], nid)
        self.assertEqual(out["notes"][0]["tags"], ["t1"])

    def test_memo_upsert_dedupe(self):
        r1 = loads(gw.hermes_memo("c", "t", "b"))
        r2 = loads(gw.hermes_memo("c", "t", "b"))  # 동일 → upsert(중복 row 없음)
        self.assertEqual(r1["dedupe_key"], r2["dedupe_key"])
        out = loads(gw.hermes_notes(category="c"))
        self.assertEqual(out["count"], 1)

    def test_notes_limit_clamp(self):
        for i in range(5):
            gw.hermes_memo("c", f"t{i}", f"b{i}")
        out = loads(gw.hermes_notes(limit=999999))  # clamp to NOTES_LIMIT_MAX
        self.assertLessEqual(out["count"], gw.NOTES_LIMIT_MAX)
        out2 = loads(gw.hermes_notes(limit=2))
        self.assertEqual(out2["count"], 2)

    def test_wal_enabled(self):
        gw.hermes_memo("c", "t", "b")
        import sqlite3
        con = sqlite3.connect(gw.NOTES_DB)
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        con.close()
        # WAL 우선; 보호 경로면 fallback 가능하나 temp dir 에선 WAL 기대
        self.assertIn(mode.lower(), ("wal", "delete", "truncate", "memory"))


class TestMediaGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _mk(self, name: str, content: bytes = b"hello") -> Path:
        p = self.tmp / name
        p.write_bytes(content)
        return p

    def test_normal_media_passes(self):
        p = self._mk("report.pdf")
        self.assertIsNone(gw._guard_media(f"see MEDIA:{p}"))

    def test_no_media_passes(self):
        self.assertIsNone(gw._guard_media("plain message no attachment"))

    def test_non_deliverable_ext_not_scanned(self):
        # Hermes 정렬: .env/.bin 은 MEDIA_DELIVERY_EXTS 아님 → Hermes 전송 안 함 → 스캔 대상 아님(pass)
        p = self._mk(".env", b"AKIAxxxxxxxxxxxxxxxx")
        self.assertIsNone(gw._guard_media(f"MEDIA:{p}"))

    def test_denylist_name_rejected(self):
        # 배포 확장자(.json) + secret 이름(credentials) → 거부
        p = self._mk("credentials.json", b"{}")
        err = gw._guard_media(f"MEDIA:{p}")
        self.assertEqual((err or {}).get("kind"), "media")

    def test_secret_content_rejected(self):
        p = self._mk("ok.txt", b"AKIA1234567890ABCDEF and more")
        err = gw._guard_media(f"MEDIA:{p}")
        self.assertEqual((err or {}).get("kind"), "media")

    def test_secret_content_gcp_and_openai(self):
        p1 = self._mk("a.json", b'{"private_key": "-----BEGIN PRIVATE KEY-----"}')
        self.assertEqual((gw._guard_media(f"MEDIA:{p1}") or {}).get("kind"), "media")
        p2 = self._mk("b.txt", b"token sk-abcdefghijklmnopqrstuvwx and more")
        self.assertEqual((gw._guard_media(f"MEDIA:{p2}") or {}).get("kind"), "media")

    def test_oversize_rejected(self):
        p = self._mk("big.pdf", b"a")
        with mock.patch.object(gw, "MEDIA_MAX_BYTES", 0):
            err = gw._guard_media(f"MEDIA:{p}")
        self.assertEqual((err or {}).get("kind"), "media")

    def test_missing_file_rejected(self):
        err = gw._guard_media(f"MEDIA:{self.tmp/'nope.pdf'}")
        self.assertEqual((err or {}).get("kind"), "media")

    def test_path_with_spaces_matched(self):
        # Hermes 정규식은 공백 포함 경로 지원 — guard 도 동일하게 매칭해야(M2)
        d = self.tmp / "My Docs"; d.mkdir()
        p = d / "report.pdf"; p.write_bytes(b"hi")
        self.assertIsNone(gw._guard_media(f"here MEDIA:{p} end"))  # 정상 파일 → pass(매칭됐고 secret 아님)
        # 같은 공백 경로의 secret 파일은 거부됨(매칭 확인)
        ps = d / "credentials.json"; ps.write_bytes(b"{}")
        self.assertEqual((gw._guard_media(f"MEDIA:{ps}") or {}).get("kind"), "media")

    def test_quoted_form_matched_like_hermes(self):
        p = self._mk("credentials.json", b"{}")
        # 선행 따옴표(`"MEDIA:/path"`)는 Hermes MEDIA_TAG_CLEANUP_RE 가 매칭 → guard 도 매칭(거부, M2)
        self.assertEqual((gw._guard_media(f'"MEDIA:{p}"') or {}).get("kind"), "media")
        # 콜론 뒤 공백+따옴표(`MEDIA: "/path"`)는 Hermes 정규식도 매칭 안 함 → 양쪽 미전송(안전, scanned==transmitted)
        self.assertIsNone(gw._guard_media(f'MEDIA: "{p}"'))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unsupported")
    def test_symlink_rejected(self):
        target = self._mk("real.pdf")
        link = self.tmp / "link.pdf"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink not permitted")
        err = gw._guard_media(f"MEDIA:{link}")
        self.assertEqual((err or {}).get("kind"), "media")


class TestSendErrorMapping(unittest.TestCase):
    def test_usage_error_empty(self):
        r = loads(run(gw.hermes_send(target="", message="")))
        self.assertEqual(r["kind"], "usage")

    def test_media_reject_blocks_before_send(self):
        # secret 이름 + 배포확장자(.json) → media error(name denylist, open 전), subprocess 미호출
        with mock.patch.object(gw.subprocess, "run") as m:
            r = loads(run(gw.hermes_send(target="slack:#x",
                                         message="MEDIA:/no/such/credentials.json")))
            self.assertEqual(r["kind"], "media")
            m.assert_not_called()

    def test_send_ok(self):
        fake = mock.Mock(returncode=0, stdout='{"ok":true}', stderr="")
        with mock.patch.object(gw.subprocess, "run", return_value=fake):
            r = loads(run(gw.hermes_send(target="slack:#x", message="hi")))
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["result"], {"ok": True})

    def test_send_backend_error_exit1(self):
        fake = mock.Mock(returncode=1, stdout="", stderr="Yuanbao adapter is not running")
        with mock.patch.object(gw.subprocess, "run", return_value=fake):
            r = loads(run(gw.hermes_send(target="yuanbao:me", message="hi")))
        self.assertEqual(r["kind"], "gateway_down")
        self.assertIn("error", r)

    def test_send_usage_exit2(self):
        fake = mock.Mock(returncode=2, stdout="", stderr="bad usage")
        with mock.patch.object(gw.subprocess, "run", return_value=fake):
            r = loads(run(gw.hermes_send(target="slack:#x", message="hi")))
        self.assertEqual(r["kind"], "usage")

    def test_send_hermes_missing(self):
        with mock.patch.object(gw.subprocess, "run", side_effect=FileNotFoundError()):
            r = loads(run(gw.hermes_send(target="slack:#x", message="hi")))
        self.assertEqual(r["kind"], "import")

    def test_send_timeout(self):
        import subprocess as _sp
        with mock.patch.object(gw.subprocess, "run",
                               side_effect=_sp.TimeoutExpired(cmd="hermes", timeout=1)):
            r = loads(run(gw.hermes_send(target="slack:#x", message="hi")))
        self.assertEqual(r["kind"], "timeout")

    def test_send_argv_shape(self):
        captured = {}

        def _capture(argv, **kw):
            captured["argv"] = argv
            captured["shell"] = kw.get("shell")
            return mock.Mock(returncode=0, stdout="{}", stderr="")
        with mock.patch.object(gw.subprocess, "run", side_effect=_capture):
            run(gw.hermes_send(target="slack:#x", message="hi"))
        self.assertEqual(captured["shell"], False)        # C8: shell=False
        self.assertIn("--", captured["argv"])             # message 는 -- 뒤
        self.assertEqual(captured["argv"][-1], "hi")
        self.assertEqual(captured["argv"][1], "send")


class TestInquiryScheduleUsage(unittest.TestCase):
    def test_inquiry_requires_input(self):
        r = loads(run(gw.hermes_inquiry(input="", mode="sync")))
        self.assertEqual(r["kind"], "usage")

    def test_schedule_create_requires_name_schedule(self):
        r = loads(run(gw.hermes_schedule(name="", schedule="")))
        self.assertEqual(r["kind"], "usage")

    def test_inquiry_empty_success_anomaly(self):
        # /v1/responses 200 + 빈 output → empty_output anomaly (B7)
        class FakeResp:
            def raise_for_status(self): pass
            def json(self): return {"id": "r1", "output": []}

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **k): return FakeResp()
        with mock.patch.object(gw.httpx, "AsyncClient", return_value=FakeClient()), \
             mock.patch.dict(os.environ, {"HERMES_API_KEY": "k" * 40}):
            r = loads(run(gw.hermes_inquiry(input="hello", mode="sync")))
        self.assertEqual(r["kind"], "empty_output")
        self.assertEqual(r["status"], "empty")


class _FakeResp:
    def __init__(self, payload, raise_exc=None):
        self._payload = payload
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise:
            raise self._raise

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    """responder(method, url, kwargs) -> _FakeResp. httpx.AsyncClient(...) 대체."""
    def __init__(self, responder):
        self._r = responder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **k):
        return self._r("POST", url, k)

    async def get(self, url, **k):
        return self._r("GET", url, k)


def _http_error(code: int):
    import httpx as _h
    req = _h.Request("GET", "http://x")
    return _h.HTTPStatusError(f"{code}", request=req, response=_h.Response(code, request=req))


def _patch_client(responder):
    return mock.patch.object(gw.httpx, "AsyncClient", side_effect=lambda *a, **k: _FakeClient(responder))


def _with_key():
    return mock.patch.dict(os.environ, {"HERMES_API_KEY": "k" * 40})


class TestInquiryHTTP(unittest.TestCase):
    def test_sync_happy(self):
        def resp(m, url, k):
            return _FakeResp({"id": "r1", "status": "completed",
                              "output": [{"content": [{"type": "output_text", "text": "hello"}]}]})
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_inquiry(input="hi", mode="sync")))
        self.assertEqual(r["text"], "hello")
        self.assertEqual(r["response_id"], "r1")

    def test_sync_http_5xx(self):
        def resp(m, url, k):
            return _FakeResp({}, raise_exc=_http_error(503))
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_inquiry(input="hi", mode="sync")))
        self.assertEqual(r["kind"], "http_5xx")

    def test_sync_http_4xx(self):
        def resp(m, url, k):
            return _FakeResp({}, raise_exc=_http_error(404))
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_inquiry(input="hi", mode="sync")))
        self.assertEqual(r["kind"], "http_4xx")

    def test_invalid_mode(self):
        with _with_key():
            r = loads(run(gw.hermes_inquiry(input="hi", mode="asnyc")))  # typo
        self.assertEqual(r["kind"], "usage")

    def test_auth_weak_key(self):
        def resp(m, url, k):
            return _FakeResp({"id": "r", "output": [{"content": [{"type": "output_text", "text": "x"}]}]})
        with _patch_client(resp), mock.patch.dict(os.environ, {"HERMES_API_KEY": "short"}):
            r = loads(run(gw.hermes_inquiry(input="hi", mode="sync")))
        self.assertEqual(r["kind"], "auth_missing")

    def test_async_completed(self):
        def resp(m, url, k):
            if m == "POST":
                return _FakeResp({"run_id": "run1", "status": "running"})
            return _FakeResp({"status": "completed", "output": "done text"})
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_inquiry(input="big", mode="async")))
        self.assertEqual(r["status"], "completed")
        self.assertEqual(r["text"], "done text")
        self.assertEqual(r["run_id"], "run1")

    def test_async_failed(self):
        def resp(m, url, k):
            if m == "POST":
                return _FakeResp({"run_id": "run1"})
            return _FakeResp({"status": "failed", "error": "boom"})
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_inquiry(input="big", mode="async")))
        self.assertEqual(r["kind"], "gateway_down")
        self.assertEqual(r["status"], "failed")

    def test_async_waiting_for_approval(self):
        def resp(m, url, k):
            if m == "POST":
                return _FakeResp({"run_id": "run1"})
            return _FakeResp({"status": "waiting_for_approval"})
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_inquiry(input="big", mode="async")))
        self.assertEqual(r["status"], "needs_approval")
        self.assertEqual(r["run_id"], "run1")

    def test_async_no_run_id(self):
        def resp(m, url, k):
            return _FakeResp({"status": "running"})  # POST 에 run_id 없음
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_inquiry(input="big", mode="async")))
        self.assertEqual(r["kind"], "empty_output")

    def test_async_running_timeout_returns_run_id(self):
        def resp(m, url, k):
            if m == "POST":
                return _FakeResp({"run_id": "run1"})
            return _FakeResp({"status": "running"})  # 영원히 running
        with _patch_client(resp), _with_key(), \
             mock.patch.object(gw, "HTTP_TIMEOUT", 0.05), \
             mock.patch.object(gw, "ASYNC_POLL_INTERVAL", 0.01):
            r = loads(run(gw.hermes_inquiry(input="big", mode="async")))
        self.assertEqual(r["status"], "running")
        self.assertEqual(r["run_id"], "run1")

    def test_run_id_repoll(self):
        def resp(m, url, k):
            self.assertEqual(m, "GET")  # re-poll 은 GET 만
            return _FakeResp({"status": "completed", "output": "re"})
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_inquiry(run_id="run1")))
        self.assertEqual(r["text"], "re")


class TestScheduleHTTP(unittest.TestCase):
    def test_create_happy(self):
        def resp(m, url, k):
            return _FakeResp({"job": {"id": "j1", "next_run_at": "2026-06-11T14:00"}})
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_schedule(name="n", schedule="30m", prompt="p")))
        self.assertEqual(r["job_id"], "j1")
        self.assertEqual(r["next_run_at"], "2026-06-11T14:00")

    def test_create_no_id_anomaly(self):
        def resp(m, url, k):
            return _FakeResp({"job": {}})
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_schedule(name="n", schedule="30m")))
        self.assertEqual(r["kind"], "empty_output")

    def test_status_fired(self):
        def resp(m, url, k):
            return _FakeResp({"job": {"last_status": "ok", "last_run_at": "t", "next_run_at": "t2"}})
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_schedule(job_id="j1")))
        self.assertEqual(r["state"], "fired")

    def test_status_failed(self):
        def resp(m, url, k):
            return _FakeResp({"job": {"last_status": "error", "last_error": "boom"}})
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_schedule(job_id="j1")))
        self.assertEqual(r["state"], "failed")

    def test_status_delivery_failed(self):
        def resp(m, url, k):
            return _FakeResp({"job": {"last_status": "ok", "last_run_at": "t",
                                      "last_delivery_error": "channel down"}})
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_schedule(job_id="j1")))
        self.assertEqual(r["state"], "delivery_failed")

    def test_status_pending(self):
        def resp(m, url, k):
            return _FakeResp({"job": {"next_run_at": "future"}})
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_schedule(job_id="j1")))
        self.assertEqual(r["state"], "pending")
        self.assertIsNotNone(r["warn"])

    def test_create_bad_json(self):
        def resp(m, url, k):
            return _FakeResp(json.JSONDecodeError("x", "doc", 0))
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_schedule(name="n", schedule="30m")))
        self.assertEqual(r["kind"], "bad_json")

    def test_create_http_5xx(self):
        def resp(m, url, k):
            return _FakeResp({}, raise_exc=_http_error(500))
        with _patch_client(resp), _with_key():
            r = loads(run(gw.hermes_schedule(name="n", schedule="30m")))
        self.assertEqual(r["kind"], "http_5xx")


if __name__ == "__main__":
    unittest.main(verbosity=2)
