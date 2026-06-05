# HANDOFF — 다음 세션 인계

**작성** 2026-06-04 · **상태** 기획 수렴 완료(R4 잔존 0건), 어댑터 미빌드.

## 1. 지금까지 (DONE)

- Hermes Agent **v0.15.1 실소스**(`C:/Users/tgkim/AppData/Local/hermes/hermes-agent`) 대조로 기획 2안 작성·검증.
- Codex(GPT-5.x) + Claude **4라운드 교차검토** → 수렴 0건:
  - R1: cron=캘린더 아님(FEAS-01 발화 gateway 필수), 4-tool→API 매핑, send=API server toolset 제외, memo≠bounded memory 등 반영.
  - R2: one-shot 폴링 404 모호성→deliver ack, inquiry 사전 라우팅, dedupe 설계.
  - R3/R4: §A 바이트 동일(sha1 입증), 표현 정직화 → **양측 CONVERGED**.
- 본 repo = **2안(플러그인화)** 산출물. 1안(하네스 직접 연동)은 `docs/plan-1-harness-integration.md`(자매, §1 동일).

## 2. 다음 (TODO — 빌드 로드맵, `docs/plan-2-plugin.md` §2)

- **P1 어댑터 구현** ← *여기서 시작*. `bin/hermes-mcp-gateway`(Python 권장). `bin/README.md`가 빌드 spec.
  - 5도구 등록 + API 클라이언트(httpx) + 노트 SQLite + 표면별 라우팅/폴링.
- **P2 패키징** — semver, `/reload-plugins` 워크플로, `scripts/install.sh` 보강, README.
- **P3 managed-env** — `docs/plan-2-plugin.md` §3.5: managed allowlist deny 환경은 dual-delivery 우회 불가(admin 승인 필수). install.sh가 안내.
- **P4 운영** — backup/import, retention, runbook, 배포 채널.

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
