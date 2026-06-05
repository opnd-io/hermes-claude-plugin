#!/usr/bin/env python3
"""hermes-bridge 어댑터 스모크 테스트.

- 도구 등록 5종 확인
- 노트 스토어(memo/notes) 실제 SQLite CRUD + dedup(upsert) 검증 (Hermes 백엔드 불요)
- inquiry/schedule/send 는 live 백엔드(API server/gateway/플랫폼 creds) 필요 → 본 스모크는 미수행(별도 e2e).

실행: <hermes-venv-python> tests/smoke_test.py
"""
import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP_DB = str(Path(tempfile.gettempdir()) / "hermes_bridge_smoke.sqlite")
if os.path.exists(TMP_DB):
    os.remove(TMP_DB)
os.environ["HERMES_BRIDGE_NOTES_DB"] = TMP_DB

# 어댑터 모듈 로드
spec = importlib.util.spec_from_file_location("hmg", ROOT / "bin" / "hermes_mcp_gateway.py")
hmg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hmg)

failures = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(name)


print("== 1) 도구 등록 ==")
tools = asyncio.run(hmg.mcp.list_tools())
names = sorted(t.name for t in tools)
expected = ["hermes_inquiry", "hermes_memo", "hermes_notes", "hermes_schedule", "hermes_send"]
check("5개 도구 등록", names == expected, f"got={names}")

print("== 2) 노트 스토어 memo upsert + dedup ==")
import json
r1 = json.loads(hmg.hermes_memo("meeting", "고객A 미팅", "로그인 문구 수정 요청", tags=["customerA"]))
r2 = json.loads(hmg.hermes_memo("meeting", "고객A 미팅", "로그인 문구 수정 요청", tags=["customerA"]))  # 동일 → dedup
check("dedupeKey 자동 파생", bool(r1.get("dedupe_key")), f"key={r1.get('dedupe_key')}")
check("동일 내용 재호출 시 같은 note_id(upsert)", r1["note_id"] == r2["note_id"])

r3 = json.loads(hmg.hermes_memo("meeting", "고객B 미팅", "결제 연동 일정 확인"))  # 다른 내용 → 신규
check("다른 내용은 새 note_id", r3["note_id"] != r1["note_id"])

import sqlite3
n = sqlite3.connect(TMP_DB).execute("SELECT COUNT(*) FROM notes").fetchone()[0]
check("행 수 = 2 (dedup 동작)", n == 2, f"rows={n}")

print("== 3) 노트 검색 (hermes_notes) ==")
found = json.loads(hmg.hermes_notes(query="로그인"))
check("query='로그인' 검색 1건", len(found) == 1 and found[0]["title"] == "고객A 미팅", f"hits={len(found)}")
by_cat = json.loads(hmg.hermes_notes(category="meeting"))
check("category='meeting' 2건", len(by_cat) == 2, f"hits={len(by_cat)}")
empty = json.loads(hmg.hermes_notes(query="존재하지않는단어"))
check("무매칭 검색 0건", len(empty) == 0)

print("== 4) dedupe canonical_json 결정성 ==")
k1 = hmg._derive_dedupe_key("a", "b", "c")
k2 = hmg._derive_dedupe_key("a", "b", "c")
k3 = hmg._derive_dedupe_key("ab", "", "c")  # 구분자 없는 연결이면 'abc'로 충돌했을 케이스
check("동일 입력 동일 키", k1 == k2)
check("tuple 경계 모호성 없음 (a|b|c != ab||c)", k1 != k3)

print(f"\n== 결과: {'ALL PASS' if not failures else 'FAIL: ' + ', '.join(failures)} ==")
sys.exit(1 if failures else 0)
