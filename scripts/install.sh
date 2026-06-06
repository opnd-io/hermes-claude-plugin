#!/usr/bin/env bash
# hermes-bridge — 설치 전제 점검 + venv 캡처 (순수 점검 스크립트, curl|sh 금지)
# 계획서 SoT: docs/plan-2-plugin.md §2.3 + docs/plan-3-implementation.md (W2/W4/D1/C7/§14)
#
# 이 스크립트는 점검/안내 + venv 경로 기록만 한다. API 키를 자동 기록하지 않으며,
# 네트워크에서 임의 코드를 받아 실행(curl ... | sh)하지 않는다.
set -euo pipefail

API_BASE="${HERMES_API_BASE:-http://127.0.0.1:8642}"
HERE="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_OUT="$HOME/.hermes-bridge/env.sh"
fail() { echo "  [FAIL] $1"; FAILED=1; }
ok()   { echo "  [ OK ] $1"; }
warn() { echo "  [WARN] $1"; }
FAILED=0

echo "== hermes-bridge preflight =="

# 1) hermes CLI 존재
echo "[1/6] hermes CLI"
HERMES_BIN_ABS=""
if command -v hermes >/dev/null 2>&1; then
  HERMES_BIN_ABS="$(command -v hermes)"
  ok "hermes 발견: $(hermes --version 2>/dev/null | head -1) ($HERMES_BIN_ABS)"
else
  fail "hermes CLI 없음 — Hermes Agent를 먼저 설치하세요."
fi

# 2) Hermes venv python 캡처 + mcp/httpx import sanity (plan-3 W4, D6=B)
echo "[2/6] Hermes venv python (어댑터 실행 인터프리터)"
VENV_PY=""
if [ -n "$HERMES_BIN_ABS" ]; then
  HB_DIR="$(dirname -- "$HERMES_BIN_ABS")"
  for cand in "$HB_DIR/python" "$HB_DIR/python3" "$HB_DIR/python.exe"; do
    [ -x "$cand" ] && VENV_PY="$cand" && break
  done
fi
if [ -n "$VENV_PY" ] && "$VENV_PY" -c "import mcp, httpx" >/dev/null 2>&1; then
  ok "venv python: $VENV_PY (mcp+httpx import OK)"
  mkdir -p "$(dirname -- "$ENV_OUT")"
  # 절대경로를 기록 — Claude Code 가 MCP 를 PATH 미상속 셸로 띄워도 wrapper 가 해석 (opnd-codex #105 교훈)
  {
    echo "# hermes-bridge — install.sh 가 생성. wrapper(bin/hermes-mcp-gateway)가 source 한다."
    echo "export HERMES_VENV_PY=\"$VENV_PY\""
    echo "export HERMES_BIN=\"$HERMES_BIN_ABS\""
  } > "$ENV_OUT"
  ok "경로 기록: $ENV_OUT"
else
  fail "venv python 미발견 또는 mcp/httpx import 실패 — Hermes 설치 확인 (plan-3 FP8)"
fi

# 3) API server env 점검 + strong-key 정의 (~/.hermes/.env, §14)
echo "[3/6] API server 설정"
ENV_FILE="${HERMES_HOME:-$HOME/.hermes}/.env"
if [ -f "$ENV_FILE" ] && grep -q '^API_SERVER_ENABLED=true' "$ENV_FILE" 2>/dev/null; then
  ok "API_SERVER_ENABLED=true ($ENV_FILE)"
else
  fail "API server 미활성. $ENV_FILE 에 추가: API_SERVER_ENABLED=true / API_SERVER_HOST=127.0.0.1 / API_SERVER_PORT=8642 / API_SERVER_KEY=\$(openssl rand -hex 32)"
fi

# 4) API 키 존재 + strong-key 검증 (값은 출력/기록하지 않음, §14)
echo "[4/6] HERMES_API_KEY (strong-key)"
KEY="${HERMES_API_KEY:-}"
if [ -z "$KEY" ]; then
  fail "HERMES_API_KEY 미설정 — 셸 env로 주입하세요 (이 스크립트는 키를 기록하지 않음)."
elif [ "${#KEY}" -lt 32 ]; then
  fail "HERMES_API_KEY 너무 짧음 (${#KEY}자 < 32) — openssl rand -hex 32 권장."
elif printf '%s' "$KEY" | grep -qiE 'changeme|placeholder|your[-_]?key|x{16,}'; then
  fail "HERMES_API_KEY 가 placeholder 로 보임 — 실제 강한 키로 교체."
else
  ok "HERMES_API_KEY 설정됨 (≥32자, 값 비표시)"
fi

# 5) API server 연결 확인 — 키를 argv 노출 없이 (C7: --config 로 헤더 전달, ps/proc 누출 방지)
echo "[5/6] API server 연결 ($API_BASE/v1/models)"
if [ -n "$KEY" ] && command -v curl >/dev/null 2>&1; then
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$KEY" \
    | curl -s -o /dev/null -w '%{http_code}' --config - "$API_BASE/v1/models" 2>/dev/null || echo "000")
  case "$code" in
    200) ok "200 OK" ;;
    401) fail "401 — 키 불일치" ;;
    000) fail "연결 실패 — API server 미기동?" ;;
    *)   fail "예상치 못한 HTTP $code" ;;
  esac
else
  echo "  [SKIP] 키 또는 curl 부재로 생략"
fi

# 6) gateway 가동 여부 (schedule 발화 전제 — §1.3) + 어댑터 무결성 (D1)
echo "[6/6] gateway 상태 + 어댑터 무결성"
if [ -n "$HERMES_BIN_ABS" ]; then
  if hermes gateway status >/dev/null 2>&1; then
    ok "gateway 동작 중 — cron schedule 발화 가능"
  else
    warn "gateway 미가동 — cron job은 생성돼도 발화/전달되지 않음 (§1.3, F2)"
  fi
fi
# D1: 빌드 산출물(wrapper) SHA256 검증 (체크섬 파일 존재 시)
SUM_FILE="$HERE/bin/hermes-mcp-gateway.sha256"
if [ -f "$SUM_FILE" ]; then
  SUMTOOL=""
  if command -v sha256sum >/dev/null 2>&1; then SUMTOOL="sha256sum"
  elif command -v shasum >/dev/null 2>&1; then SUMTOOL="shasum -a 256"; fi
  if [ -z "$SUMTOOL" ]; then
    warn "sha256sum/shasum 부재 — 체크섬 검증 생략 (도구 없음 ≠ 변조)"  # m14: tool-missing≠tamper
  elif ( cd "$HERE/bin" && $SUMTOOL -c "$(basename "$SUM_FILE")" >/dev/null 2>&1 ); then
    ok "어댑터 체크섬 일치 (SHA256)"
  else
    fail "어댑터 체크섬 불일치 — 변조 의심, 재설치 권장 (D1/C9)"
  fi
else
  warn "체크섬 파일 부재 (개발 모드 — 릴리스 시 bin/hermes-mcp-gateway.sha256 동봉)"
fi

echo "== 완료 (FAILED=$FAILED) =="
exit "$FAILED"
