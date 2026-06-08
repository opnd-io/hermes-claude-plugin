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

## 7. Windows + VSCode 확장 / sandbox 주의 (실측 2026-06-08)

VSCode 확장이 MCP 서버를 띄울 때의 환경은 CLI(`claude mcp list`) 와 다르다. 실측으로 확인된 함정과 어댑터의 대응:

- **notes DB 쓰기 (memo/notes)**: Claude Code MCP sandbox 는 서버에 user-profile(`~/.hermes-bridge`) **읽기(RX)만** 허용할 수 있어 SQLite open 이 `unable to open database file` 로 실패한다. → `_notes_conn` 이 primary 경로 실패 시 **OS temp(`<temp>/hermes-bridge/notes.sqlite`)로 자동 fallback** (telemetry `notes_db_fallback` 로 가시화). temp 는 비영속이므로 **영속 저장이 필요하면 `HERMES_BRIDGE_NOTES_DB` 를 쓰기 가능한 경로**(예: 워크스페이스 하위)로 지정한다.
- **`HERMES_API_KEY` 전달**: `.mcp.json` 의 env 블록은 `${HERMES_API_KEY}` 를 더 이상 선언하지 않는다(미해결 시 확장이 `config-invalid` 로 서버를 즉시 teardown → 도구 0개였음). 어댑터는 런타임에 `os.getenv("HERMES_API_KEY")` 로 **상속된 환경에서 직접 읽는다**. 따라서 inquiry/schedule 가 동작하려면 **확장 프로세스의 환경에 `HERMES_API_KEY` 가 있어야** 한다 — User 환경변수로 설정 후 **VSCode 완전 종료→재실행**(Reload Window 만으로는 새 환경변수 미전파). 키가 없으면 서버는 살아있고 memo/notes/send 는 정상, inquiry/schedule 만 `auth_missing` 반환.
- **venv 부트스트랩**: `.mcp.json` 은 bare `python3` 로 시작 → `_ensure_runtime` 이 `HERMES_VENV_PY`(env) 또는 PATH 의 `hermes` 로 venv 승격(C2). 확장 환경에 둘 다 없으면 부트스트랩 실패하므로 install 이 `HERMES_VENV_PY` 를 기록/전파하도록 한다.
- **ACL**: `harden_perms` 는 Windows 에서 **additive grant 만**(상속 제거 안 함) — 과거 `/inheritance:r` 가 sandbox 컨텍스트에서 owner ACE 를 날려 락아웃을 유발했다. 커스텀 공유 경로는 private 로 만들지 않으므로 민감 노트는 user-profile 하위(기본)에 둔다.
