#!/usr/bin/env bash
# hermes-bridge — 설치 전제 점검 + 키 안내 (순수 점검 스크립트, curl|sh 금지)
# 계획서 SoT: docs/plan-2-plugin.md §2.3
#
# 이 스크립트는 점검/안내만 한다. API 키를 자동 기록하지 않으며, 네트워크에서
# 임의 코드를 받아 실행(curl ... | sh)하지 않는다.
set -euo pipefail

API_BASE="${HERMES_API_BASE:-http://127.0.0.1:8642}"
fail() { echo "  [FAIL] $1"; FAILED=1; }
ok()   { echo "  [ OK ] $1"; }
FAILED=0

echo "== hermes-bridge preflight =="

# 1) hermes CLI 존재
echo "[1/5] hermes CLI"
if command -v hermes >/dev/null 2>&1; then
  ok "hermes 발견: $(hermes --version 2>/dev/null | head -1)"
else
  fail "hermes CLI 없음 — Hermes Agent를 먼저 설치하세요."
fi

# 2) API server env 점검 (~/.hermes/.env)
echo "[2/5] API server 설정"
ENV_FILE="${HERMES_HOME:-$HOME/.hermes}/.env"
if [ -f "$ENV_FILE" ] && grep -q '^API_SERVER_ENABLED=true' "$ENV_FILE" 2>/dev/null; then
  ok "API_SERVER_ENABLED=true ($ENV_FILE)"
else
  fail "API server 미활성. $ENV_FILE 에 아래를 추가하세요:"
  echo "         API_SERVER_ENABLED=true"
  echo "         API_SERVER_HOST=127.0.0.1"
  echo "         API_SERVER_PORT=8642"
  echo "         API_SERVER_KEY=\$(openssl rand -hex 32)   # 강한 키 필수 (네트워크 노출 시 placeholder 거부)"
fi

# 3) API 키 존재 (값은 출력/기록하지 않음)
echo "[3/5] HERMES_API_KEY"
if [ -n "${HERMES_API_KEY:-}" ]; then
  ok "HERMES_API_KEY 환경변수 설정됨 (값 비표시)"
else
  fail "HERMES_API_KEY 미설정 — 셸 env로 주입하세요 (이 스크립트는 키를 기록하지 않음)."
fi

# 4) API server 연결 확인
echo "[4/5] API server 연결 ($API_BASE/v1/models)"
if [ -n "${HERMES_API_KEY:-}" ] && command -v curl >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $HERMES_API_KEY" "$API_BASE/v1/models" || echo "000")
  case "$code" in
    200) ok "200 OK" ;;
    401) fail "401 — 키 불일치" ;;
    000) fail "연결 실패 — API server 미기동?" ;;
    *)   fail "예상치 못한 HTTP $code" ;;
  esac
else
  echo "  [SKIP] 키 또는 curl 부재로 생략"
fi

# 5) gateway 가동 여부 (schedule 발화 전제 — docs §1.3)
echo "[5/5] gateway 상태 (schedule 발화 전제)"
if command -v hermes >/dev/null 2>&1; then
  if hermes gateway status >/dev/null 2>&1; then
    ok "gateway 동작 중 — cron schedule 발화 가능"
  else
    echo "  [WARN] gateway 미가동 — cron job은 생성돼도 발화/전달되지 않음 (docs/plan-2-plugin.md §1.3)"
  fi
fi

# TODO(P1): bin/hermes-mcp-gateway 어댑터 SHA256 체크섬 검증
# echo "[6] adapter 무결성"; sha256sum -c bin/hermes-mcp-gateway.sha256

echo "== 완료 (FAILED=$FAILED) =="
exit "$FAILED"
