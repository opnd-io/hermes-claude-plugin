# hermes-bridge 운영 runbook (plan-3 Track O3/O4)

대상: hermes-bridge 플러그인 운영자. SoT 계약/설계는 `docs/plan-2-plugin.md` + `docs/plan-3-implementation.md`.

## 0. 구성 요약

- **wrapper** `bin/hermes-mcp-gateway`(sh) / `.cmd`(Win) → Hermes venv python 으로 `bin/hermes_mcp_gateway.py` 실행 (D6=B).
- **install** `scripts/install.sh` / `install.ps1` → 전제 점검 + venv 경로를 `~/.hermes-bridge/env.{sh,cmd}` 에 기록(W4).
- **notes 스토어** `~/.hermes-bridge/notes.sqlite` (WAL). admin = `scripts/hermes_bridge_admin.py`.
- **telemetry**(옵션) `~/.hermes-bridge/telemetry.jsonl` — `HERMES_BRIDGE_TELEMETRY_DISABLED=1` 로 끔.

## 1. 설치 / 재설치

1. Hermes Agent 설치 + API server 활성(`~/.hermes/.env`: `API_SERVER_ENABLED=true`, 강한 `API_SERVER_KEY`).
2. `export HERMES_API_KEY=<강한키>` (≥32자, placeholder 금지 — §14).
3. `bash scripts/install.sh` (Windows: `pwsh scripts/install.ps1`) → 6단계 점검 통과 확인.
4. Claude Code 에 플러그인 등록 후 `claude mcp list` 에 `hermes-bridge` + 5도구 노출 확인(A4).

## 2. 장애 대응

| 증상 | 원인 | 조치 |
|---|---|---|
| 도구 호출 시 `kind=auth_missing` | `HERMES_API_KEY` 미주입 | env 설정 후 MCP 재기동 |
| `kind=import` ("hermes not found") | venv 경로 변동/Hermes 재설치 (FP8) | `install.sh` 재실행 → `~/.hermes-bridge/env.*` 갱신 |
| `kind=gateway_down` (send/schedule) | Hermes gateway 미가동 또는 yuanbao/plugin-live 어댑터 미기동 | `hermes gateway status` 확인 → gateway 상시 기동(§1.3, F2) |
| `kind=http_5xx`/`timeout` (inquiry) | API server 과부하/장시간 루프 | `mode="async"` 사용 + `hermes_inquiry(run_id=...)` 폴링 |
| `kind=empty_output`, `status=empty` | 200인데 빈 응답 | 빈 성공 아님 — 입력/세션 재확인(B7) |
| `kind=media` (send) | MEDIA 경로가 denylist/대용량/secret/symlink | 첨부 경로 교정(§14 가드) |
| cron 예약 미발화 | gateway 미가동 | `hermes_schedule(job_id=...)` state=pending → gateway 기동 |
| 한글 깨짐 | 인코딩 | `.mcp.json env PYTHONIOENCODING=utf-8` 확인(W3) |

## 3. 무중단 재기동 / key 회전

- **재기동**: MCP 서버는 stdio — Claude Code 가 세션별 기동. `/reload-plugins` 또는 세션 재시작으로 반영(D3). 진행 중 호출은 동기(110s 내) 완결.
- **key 회전**: 어댑터는 매 호출 시 `HERMES_API_KEY` env 를 읽음(회전 친화, FP7). 새 키 주입 후 다음 호출부터 적용 — 진행 중 호출만 구 키. 무중단.

## 4. notes 백업 / 보존 (O1/O2)

```bash
# 백업 (일관 스냅샷)
python scripts/hermes_bridge_admin.py backup --out ~/backups/notes-$(date +%F).sqlite
# 복원 (dedupe merge)
python scripts/hermes_bridge_admin.py import --in ~/backups/notes-2026-06-05.sqlite
# 보존 (기본 무제한 — 명시 시에만 삭제)
python scripts/hermes_bridge_admin.py retention --max-age-days 365 --dry-run
python scripts/hermes_bridge_admin.py retention --max-count 5000
# 현황
python scripts/hermes_bridge_admin.py stats
```

## 5. 배포 채널 (O4)

- **단일 머신/개발**: repo clone 후 `install.sh` (1안 — plan-1).
- **팀/다중 머신**: Claude Code 플러그인 마켓플레이스(또는 내부 git) 로 배포 — semver 태그(D2). 각 머신은 `install.sh` 로 venv 캡처.
- **managed allowlist 환경**: admin 이 `allowedMcpServers` 에 `hermes-bridge`(non-colon) 등록 필요. 미등록 시 `claude mcp list` 에 미노출 → self-serve 불가(F1, plan-2 §3.5). 우회 불가 — admin 승인 또는 1안 폴백.
- **무결성**: 릴리스에 `bin/hermes-mcp-gateway.sha256` 동봉 → install 이 검증(D1). 외부 `hermes` 바이너리는 사용자 신뢰 설치(C9).

## 6. 비상 진단

```bash
# 어댑터 단독 실행(venv python 직접) — 기동/import 확인
<hermes_venv>/python bin/hermes_mcp_gateway.py --help
# 로컬 단위 테스트
<hermes_venv>/python -m unittest discover -s tests
# telemetry 최근 호출(옵션 활성 시)
tail ~/.hermes-bridge/telemetry.jsonl
```
