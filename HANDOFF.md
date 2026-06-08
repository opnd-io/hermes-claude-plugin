# HANDOFF — 다음 세션 인계

**작성** 2026-06-04 · **갱신** 2026-06-08 · **상태** 구현 완료(P1 어댑터 + P2 패키징) · user scope 설치 + Windows/VSCode sandbox 근본수정 완료.

## 1. 지금까지 (DONE)

- Hermes Agent **v0.15.1 실소스**(`C:/Users/tgkim/AppData/Local/hermes/hermes-agent`) 대조로 기획 2안 작성·검증.
- Codex(GPT-5.x) + Claude **4라운드 교차검토** → 수렴 0건:
  - R1: cron=캘린더 아님(FEAS-01 발화 gateway 필수), 4-tool→API 매핑, send=API server toolset 제외, memo≠bounded memory 등 반영.
  - R2: one-shot 폴링 404 모호성→deliver ack, inquiry 사전 라우팅, dedupe 설계.
  - R3/R4: §A 바이트 동일(sha1 입증), 표현 정직화 → **양측 CONVERGED**.
- 본 repo = **2안(플러그인화)** 산출물. 1안(하네스 직접 연동)은 `docs/plan-1-harness-integration.md`(자매, §1 동일).

## 2. 로드맵 진행 (`docs/plan-2-plugin.md` §2)

- ✅ **P1 어댑터 구현** — `bin/hermes_mcp_gateway.py` (5도구 + httpx API + 노트 SQLite + 표면별 라우팅/폴링). 단위 50/50 + 실 Hermes e2e PASS.
- ✅ **P2 패키징** — `.claude-plugin/{plugin,marketplace}.json`, `bin/*.sha256` 무결성, `scripts/install.{sh,ps1}`. `claude plugin install hermes-bridge@hermes-claude-plugin` (user scope) 동작.
- ✅ **Windows/VSCode sandbox 근본수정 (2026-06-08)** — notes DB temp fallback / `.mcp.json` env 상속(config-invalid teardown 회피) / `harden_perms` additive grant / `busy_timeout`. 상세 `docs/runbook.md` §7 + 글로벌 솔루션 `claude-code-plugin-mcp-windows-sandbox-failures`.
- ⏳ **P3 managed-env** — `docs/plan-2-plugin.md` §3.5: managed allowlist deny 환경은 우회 불가(admin 승인 필수). install 이 안내.
- ◐ **P4 운영** — backup/import/retention(`scripts/hermes_bridge_admin.py`) + runbook 작성됨. 배포 채널(팀 마켓플레이스/태그) 정식화 잔여.

> **현재 머신 런타임 메모**: VSCode 확장의 env 미전파(완전종료 필요) 때문에, 인라인 env + venv python 절대경로의 **user-scope `hermesbridge` 서버**(`~/.claude.json`)로 운영 중 — 플러그인 본래 서버는 완전종료 후 env 전파 시 동작. 상세 §7 of runbook / 솔루션 doc.

## 3. 어댑터 계약 (요약 — SoT는 `docs/plan-2-plugin.md` §1)

| 도구 | 표면 | 핵심 |
|---|---|---|
| `hermes_inquiry` | `POST /v1/responses` | 짧으면 동기, 풀루프면 처음부터 `/v1/runs`(202+SSE). **in-flight 전환 불가.** |
| `hermes_schedule` | `POST /api/jobs` | cron(캘린더 아님). 응답 `{"job":{...}}`→`job.id`. **발화는 gateway 상시 필수.** |
| `hermes_memo` / `hermes_notes` | 어댑터 SQLite | `~/.hermes-bridge/notes.sqlite`. dedupe_key NOT NULL, 미지정 시 `sha1(canonical_json(...))`, ON CONFLICT DO UPDATE. |
| `hermes_send` | `messages_send`/gateway | **API server toolset 제외.** 첨부 `MEDIA:<path>`(7 플랫폼). built-in standalone, yuanbao는 adapter 필수. |

## 4. 빌드 시 함정 (검토 확인됨 — `docs/review-deep-research.md`)

1. cron 발화 = gateway 60초 tick (생성만 API server). gateway 미가동 → 생성돼도 fire 안 됨.
2. send → `/v1/*` 금지 (toolset 제외). messages_send/gateway 경로.
3. memo → bounded MEMORY.md 금지(메모리 툴이 "completed-work logs 저장 금지" 명시). 어댑터 노트 스토어 사용.
4. inquiry는 LLM 풀 루프 → 60s timeout 위험. timeout 120s + 장시간 async 사전 라우팅.
5. 분류 backstop은 fail-open — 메시지 본문 키워드 부분문자열 거부 금지(false-positive). action allowlist + deploy-time config.yaml `platform_toolsets.api_server` 제한.
6. 보안: env filtering/스크리너는 boundary 아님("not containment"). 실제 boundary = allowlist + 컨테이너.

## 5. 필수 테스트 (`docs/plan-2-plugin.md` §6)

무인증 401 / gateway down 시 cron 미발화 / built-in vs yuanbao send / key 회전 401 / 동시세션 state.db WAL 경합 / 어댑터 크래시 복구 / `POST /api/jobs` 생성 / `hermes_notes` 검색 / MEDIA 첨부+비허용 경로 차단 / inquiry 장시간 async / 신규 머신 10분 클린 설치 / managed allowlist deny 폴백 안내.

## 6. 외부 확인 1건 (배포 전)

GitHub anthropics/claude-code **#32882/#32883**(managed allowlist vs plugin MCP, both not-planned) — Hermes 소스 밖. 배포 전 `gh issue view`로 상태 재확인 (plan §3.5에 hedge됨).

## 7. 참고 원본 위치

- Hermes 소스: `C:/Users/tgkim/AppData/Local/hermes/hermes-agent` (v0.15.1)
- 원본 기획서/검토 사본: 이 repo `docs/` (Downloads 원본에서 복사)
