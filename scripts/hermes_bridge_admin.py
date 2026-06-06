#!/usr/bin/env python3
"""hermes-bridge 운영 admin (plan-3 Track O1/O2) — notes 스토어 backup/import/retention.

사용 (Hermes venv python 권장):
  python scripts/hermes_bridge_admin.py backup    [--out PATH]
  python scripts/hermes_bridge_admin.py import    --in PATH [--force]
  python scripts/hermes_bridge_admin.py retention [--max-age-days N] [--max-count N] [--dry-run]
  python scripts/hermes_bridge_admin.py stats

DB 경로: --notes-db 또는 $HERMES_BRIDGE_NOTES_DB 또는 ~/.hermes-bridge/notes.sqlite.
backup 은 sqlite3 백업 API(일관 스냅샷). retention 기본은 무제한(경고만) — 명시 설정 시에만 삭제.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

# m12: cp949 콘솔에서 비ASCII(→/← /한글) print 시 UnicodeEncodeError 방지 (어댑터와 동일 가드)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

DEFAULT_DB = os.getenv("HERMES_BRIDGE_NOTES_DB", str(Path.home() / ".hermes-bridge" / "notes.sqlite"))


def _harden(path: str) -> bool:
    """**best-effort** owner-only (m21/M8/F02) — POSIX chmod, Windows icacls. 실패 시 경고+False."""
    try:
        if sys.platform == "win32":
            user = os.environ.get("USERNAME") or os.environ.get("USER")
            if not (user and os.path.exists(path)):
                return False
            import subprocess
            proc = subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", f"{user}:F"],
                                  shell=False, capture_output=True, timeout=10)
            if proc.returncode != 0:
                print(f"[WARN] owner-only ACL 적용 실패(best-effort): {path}")  # F02: 가시화
                return False
            return True
        os.chmod(path, 0o600)
        return True
    except Exception:
        print(f"[WARN] 권한 강화 실패(best-effort): {path}")
        return False


def _connect(db: str) -> sqlite3.Connection:
    return sqlite3.connect(db)


def cmd_backup(args) -> int:
    src = args.notes_db
    if not Path(src).exists():
        print(f"[FAIL] notes DB 없음: {src}", file=sys.stderr)
        return 1
    out = args.out or f"{src}.bak-{int(time.time())}"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    con = _connect(src)
    try:
        dst = _connect(out)
        try:
            con.backup(dst)  # 일관 스냅샷 (WAL 안전)
        finally:
            dst.close()
    finally:
        con.close()
    _harden(out)
    print(f"[ OK ] backup -> {out}")
    return 0


def cmd_import(args) -> int:
    src = args.in_path
    dst = args.notes_db
    if not Path(src).exists():
        print(f"[FAIL] import 원본 없음: {src}", file=sys.stderr)
        return 1
    if Path(dst).exists() and not args.force:
        print(f"[FAIL] 대상 존재: {dst} (--force 로 덮어쓰기, 사전 backup 권장)", file=sys.stderr)
        return 1
    # dedupe_key UNIQUE 보존: 원본의 notes 를 대상에 upsert merge.
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    s = _connect(src)
    d = _connect(dst)
    try:
        d.execute("CREATE TABLE IF NOT EXISTS notes("
                  "id TEXT PRIMARY KEY, category TEXT, title TEXT, body TEXT, "
                  "tags TEXT, dedupe_key TEXT NOT NULL UNIQUE, created_at INTEGER)")
        rows = s.execute("SELECT id,category,title,body,tags,dedupe_key,created_at FROM notes").fetchall()
        d.executemany(
            "INSERT INTO notes(id,category,title,body,tags,dedupe_key,created_at) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(dedupe_key) DO UPDATE SET "
            "category=excluded.category,title=excluded.title,body=excluded.body,tags=excluded.tags",
            rows)
        d.commit()
    finally:
        s.close()
        d.close()
    _harden(dst)  # m21: import 대상 DB owner-only
    print(f"[ OK ] import {len(rows)} notes -> {dst} (dedupe merge)")
    return 0


def cmd_retention(args) -> int:
    db = args.notes_db
    if not Path(db).exists():
        print(f"[FAIL] notes DB 없음: {db}", file=sys.stderr)
        return 1
    if args.max_age_days is None and args.max_count is None:
        print("[WARN] retention 설정 없음(무제한). --max-age-days 또는 --max-count 명시 시에만 삭제.")
        return 0
    con = _connect(db)
    try:
        victims: set[str] = set()
        if args.max_age_days is not None:
            cutoff = int(time.time()) - args.max_age_days * 86400
            ids = [r[0] for r in con.execute("SELECT id FROM notes WHERE created_at < ?", (cutoff,))]
            victims.update(ids)
        if args.max_count is not None:
            ids = [r[0] for r in con.execute(
                "SELECT id FROM notes ORDER BY created_at DESC LIMIT -1 OFFSET ?", (args.max_count,))]
            victims.update(ids)
        if args.dry_run:
            print(f"[DRY ] 삭제 대상 {len(victims)} notes (실삭제 안 함)")
            return 0
        con.executemany("DELETE FROM notes WHERE id=?", [(i,) for i in victims])
        con.commit()
        print(f"[ OK ] retention: {len(victims)} notes 삭제")
    finally:
        con.close()
    return 0


def cmd_stats(args) -> int:
    db = args.notes_db
    if not Path(db).exists():
        print(f"notes DB 없음: {db}")
        return 0
    con = _connect(db)
    try:
        n = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        size = Path(db).stat().st_size
        print(f"notes={n}  db_size={size}B  path={db}")
    finally:
        con.close()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="hermes_bridge_admin")
    p.add_argument("--notes-db", default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup").add_argument("--out", default=None)
    pi = sub.add_parser("import"); pi.add_argument("--in", dest="in_path", required=True); pi.add_argument("--force", action="store_true")
    pr = sub.add_parser("retention")
    pr.add_argument("--max-age-days", type=int, default=None)
    pr.add_argument("--max-count", type=int, default=None)
    pr.add_argument("--dry-run", action="store_true")
    sub.add_parser("stats")
    args = p.parse_args(argv)
    return {"backup": cmd_backup, "import": cmd_import,
            "retention": cmd_retention, "stats": cmd_stats}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
