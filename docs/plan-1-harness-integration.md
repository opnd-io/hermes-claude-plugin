# 1안 — Claude Code 하네스에 Hermes 연동 계획서

**버전** v0.4 (R3 교차검토 수렴) · **기준일** 2026-06-04 · **대상 런타임** Hermes Agent v0.15.1
**범위** *이 머신의* Claude Code 하네스에 Hermes를 **로컬 연동**(재배포 아님). 개인/소규모 팀.
**Ground-truth** `C:/Users/tgkim/AppData/Local/hermes/hermes-agent` 소스 직접 검증. **§1 어댑터 계약 본문(1.1~1.5)은 2안과 바이트 동일(SoT)** (제목 줄은 상대 문서 참조라 제외).
**파일 경로 규약**: 이하 `api_server.py`=`gateway/platforms/api_server.py`, `security.md`=`website/docs/user-guide/security.md`, 루트 `SECURITY.md`는 별도 명시.

---

## 0. 목표와 비범위

**목표**: Claude=개발 메모리/실행, Hermes=비개발(메시징·일정·메모) 메모리/실행 분리. Claude→Hermes **단방향** 위임을 *이 하네스 설정*에 직접 배선.

**비범위**: 재배포 플러그인 패키징(→2안), 원격 HTTPS 노출, Claude API MCP connector(원격 HTTPS only라 로컬 stdio 불가), 캘린더 SaaS.

**1안의 정체성**: `.mcp.json`(project) 또는 `~/.claude.json`(user scope) + 로컬 skill 배선. **버전·배포 관리 없음**, 대신 가장 단순·빠름·이 머신 밀착.

---

## 1. 어댑터 계약 §A (본문 1.1~1.5는 2안과 바이트 동일 — SoT)

> 검토에서 확인된 빌드 차단급 결함(4-tool→API 매핑 0건)을 해소. 도구는 **서로 다른 표면에 분산**.

### 1.1 도구→표면 매핑

| 도구 | 표면/경로 | 요청 | 응답(파싱) | 발화·전달 gateway | 근거(소스) |
|---|---|---|---|---|---|
| `hermes_inquiry` | `POST /v1/responses` | `{input, previous_response_id?}` + header `X-Hermes-Session-Key`(선택) | 비스트림: `output[].content[].text` where `type=="output_text"`; 스트림: `response.output_text.delta/done` | 불요(API server 동기) | api_server.py:2741-2765, 2288 |
| `hermes_schedule` | `POST /api/jobs` (생성) | `{name(필수,≤200), schedule(필수), prompt(≤5000), deliver, repeat?, skills?}` | `{"job":{...}}` → `job.id` 추출 | **생성=불요 / 발화·전달=gateway 필수**(§1.3) | api_server.py:3102-3149, cron/jobs.py:550 |
| `hermes_memo` | 어댑터 노트 스토어(§1.2) | `{category, title, body, tags[], dedupeKey}` | `note_id` | 불요 | Hermes 구조화 memo 부재: memory_tool.py:652-701 |
| `hermes_notes` | 어댑터 노트 스토어(§1.2) | `{query?, category?, tags?, limit?}` | `[{note_id, title, ...}]` | 불요 | memo 검색/조회 (FEAS-02 해소) |
| `hermes_send` | `messages_send`(`hermes mcp serve`) / gateway | `{target, message}` (첨부 `MEDIA:<path>`) | 전송 상태 문자열 | **플랫폼별**(§1.4) | mcp_serve.py:734-765, send_message_tool.py:150 |

> `deliver` 기본 `"local"`(에이전트 로컬 적재). 팀 채널 전달은 `deliver`를 채널 타깃(예: `slack:#biz`)으로 명시. `X-Hermes-Session-Key`는 **Honcho 등 장기메모리 provider의 per-chat 스코프**(Honcho 구성 시 유효, API_SERVER_KEY 필수)이며 bounded MEMORY.md/USER.md(HERMES_HOME 전역)는 이 키로 스코프되지 않음.

### 1.2 노트 스토어 (memo/notes — 검토 H4·FEAS-02 해소)
Hermes `memory` 툴은 bounded(MEMORY.md ~2,200/USER.md ~1,375자, tips.md:122) + description *"Do NOT save … completed-work logs"*(memory_tool.py:666) → **회의록 누적 금지**. 구조화 슬롯(category/tags/dedupeKey) 부재(MEMORY_SCHEMA=action/target/content만). → 어댑터 자체 노트 스토어:
- 저장소: `~/.hermes-bridge/notes.sqlite`
- DDL: `notes(id TEXT PRIMARY KEY, category TEXT, title TEXT, body TEXT, tags TEXT /*json array*/, dedupe_key TEXT NOT NULL UNIQUE, created_at INTEGER)`
- `dedupe_key`는 **NOT NULL 필수** — 미지정 시 어댑터가 `sha1(canonical_json({category,title,body}))`로 자동 파생(구분자 없는 단순 연결의 tuple 모호성·오덮어쓰기 방지, canonical JSON; NULL 다중 허용 시 dedup 무력화 방지). `hermes_memo` = `INSERT … ON CONFLICT(dedupe_key) DO UPDATE`(upsert, **write-only 아님**); `hermes_notes` = `SELECT … WHERE category=? AND tags LIKE ? AND (title|body LIKE :query) LIMIT :limit`.
- bounded `memory`(USER.md)는 "이해관계자 선호/역할" 같은 **좁은 영속 사실**에만 한정.

### 1.3 schedule 발화·전달 의존성 (검토 FEAS-01 — CRITICAL 해소)
**생성**(`POST /api/jobs`)은 API server가 `jobs.json`에 영속 → gateway 불요. **그러나 발화(due 시 실행)·전달은 gateway 프로세스 필수**: cron 스케줄러 `tick()`을 *"the gateway calls every 60 seconds from a background thread"*(cron/scheduler.py:4-5). → **gateway 미가동 시 cron job은 생성돼도 절대 fire 안 됨**(`schedule=once` 미팅 알림 포함). ∴ `hermes_schedule`은 **gateway 상시 가동 전제**이며, 어댑터는 생성 후 `GET /api/jobs/{id}`의 `last_status`로 발화 여부를 폴링 보고.

### 1.4 send 경로·첨부 (검토 H2·H3·M1·FEAS-07 해소)
- `send_message`는 **API server toolset 제외**(`tests/gateway/test_api_server_toolset.py:53 assert "send_message" not in tools`) → send는 `/v1/*` 아님, `messages_send`(mcp serve) 또는 gateway.
- **표준 vs yuanbao 분기는 어댑터가 구현 안 함** — Hermes 내부 `_send_to_platform`이 `target` prefix로 결정. 어댑터는 `{target, message}` **패스스루**.
- built-in(telegram/slack/signal/email/sms/matrix)=one-shot standalone(gateway 프로세스 불요), plugin standalone=fallback, **yuanbao=running gateway adapter 필수**.
- 첨부: `message`에 `MEDIA:<local_path>` → 7 플랫폼(telegram/discord/matrix/weixin/signal/yuanbao/feishu) native. "text-only 차단"은 오류 — 차단 대신 §5 가드.

### 1.5 비동기 종결 관측 (표면별 — 검토 M3·FEAS-08 해소)
단방향(callback 없음) → 어댑터의 **client-pull 폴링**(단방향 원칙 위배 아님):
- `hermes_inquiry`: **사전 라우팅(in-flight 전환 불가, FRESH-02)** — 짧은 동기 질의는 `POST /v1/responses`(동기), 풀 에이전트 루프 예상 질의는 **처음부터** `POST /v1/runs`(202)+`GET /v1/runs/{id}/events`(SSE) 폴링. 이미 시작된 `/v1/responses`를 사후 async로 바꿀 수 없음.
- `hermes_schedule`: 생성 시 `job.id`+`next_run_at` 스냅샷 후 `GET /api/jobs/{id}` 폴링 — `last_run_at` 설정 시 발화됨(`last_status`/`last_error`로 성공/실패), 미설정+`next_run_at` 경과 시 미발화(gateway 미가동 경고). **404/미발화 모호성 회피: one-shot 리마인더는 `deliver`를 채널 타깃으로 두어 전달 메시지 도착 자체를 1차 ack로 사용**(FRESH-01). `/v1/runs/{id}/events`는 cron에 적용 안 됨.
- `hermes_send`: `messages_send` 직접 반환값만(run id 없음).
- 보고는 **"동기 ack" 한정** — 비동기 cron 발화/최종 전달은 폴링 또는 deliver 채널 도착으로만 확인.

---

## 2. 단계별 로드맵

| 단계 | 목표 | 핵심 작업 | 산출물 | 통과 기준 |
|---|---|---|---|---|
| **P1 전제** | Hermes 준비 | `~/.hermes/.env` API server enable + `API_SERVER_KEY`(`openssl rand -hex 32`), gateway allowlist/pairing + **상시 가동**(§1.3), terminal.backend docker | `.env`, gateway config | `/v1/models` 200, 무인증 401, gateway up |
| **P2 메시징 파일럿** | 최소 비용 검증 | `hermes mcp serve` 직접 등록(어댑터 0), 10 도구, read/send 차등 | `~/.claude.json` 엔트리 | `messages_read` 성공, gateway up시 `messages_send`(+MEDIA) 성공 |
| **P3 어댑터** | 5 도구 정제 | §1 계약대로 로컬 stdio 어댑터(§2.1 런타임), `/v1/responses`·`/api/jobs`·노트스토어·messages_send 분기 + 폴링 | 어댑터 실행파일, `.mcp.json` | 5 도구 §1 경로로 정상, §1.5 폴링 동작, cron 발화 확인 |
| **P4 역할 경계** | dev/non-dev 라우팅 | `~/.claude/skills/hermes-delegate/` skill + 권한 규칙(send/schedule=Ask) | `SKILL.md` | 코드 작업엔 Hermes 미호출 |
| **P5 운영** | 상시 안전 | backup/import, 로그·세션 retention, runbook | 운영 체크리스트 | 무중단 재기동, key 회전 복구 |

### 2.1 어댑터 런타임 (검토 COMP-ADAPTER-RUNTIME 해소)
- **권장: Python** — Hermes가 Python(venv 존재)이므로 같은 인터프리터/HTTP 클라이언트(`httpx`) + `mcp` SDK 재사용. 노트스토어는 표준 `sqlite3`.
- 대안: Node(`@modelcontextprotocol/sdk`) — Hermes 비의존 stdio 어댑터.
- 빌드: 단일 실행 스크립트(`~/.hermes-bridge/bin/adapter`, shebang) — 컴파일 불요. 1안은 재배포 없으므로 패키징 생략.

### 2.2 전송 토폴로지 대안 (검토 M4 해소)
- **stdio 어댑터(현 권장)** — Claude Code 표준·최단순. 단 크래시 시 자동 재연결 없음(§6).
- 로컬 HTTP MCP 어댑터(127.0.0.1) — 재연결 용이 + 다중 클라이언트 재사용, 단 포트 관리 부담.
- API server `/v1` 얇은 MCP-wrap(4-tool 정제 생략) — 구현 최소지만 **전체 표면 노출 → 역할 경계 흐려짐**.
- **선택 근거**: 1안은 단일 클라이언트(이 하네스)라 stdio 최적. 4-tool(+notes=5) 정제는 dev/non-dev 경계 유지 + tool selection 안정을 위해 얇은 wrap 대비 채택.

---

## 3. 설정 스니펫

### P2 — 직접 등록 (user scope, 어댑터 0)
```json
// ~/.claude.json (user scope) 또는 project .mcp.json
{ "mcpServers": { "hermes": { "command": "hermes", "args": ["mcp", "serve"] } } }
```
> 10 도구(conversations_list, conversation_get, messages_read, attachments_fetch, events_poll, events_wait, messages_send, channels_list, permissions_list_open, permissions_respond) 노출. read는 gateway 불요.

### P3 — 어댑터 경유 (5 도구 정제)
```json
{
  "mcpServers": {
    "hermes-bridge": {
      "command": "${HOME}/.hermes-bridge/bin/adapter",
      "args": ["--api-base", "http://127.0.0.1:8642"],
      "env": { "HERMES_API_KEY": "${HERMES_API_KEY}" },
      "timeout": 120000
    }
  }
}
```
> `--api-base`는 **호스트 루트**(`/v1` 고정 금지 — `/api/jobs`는 /v1 아님). 어댑터가 경로별 prefix(`/v1` vs `/api`) 분기. `timeout` 120s — inquiry는 풀 에이전트 루프라 60s 초과 가능(§1.5 → 장시간 `/v1/runs` async 권장, COMP/FEAS-06).

### P1 — Hermes API server
```bash
# ~/.hermes/.env
API_SERVER_ENABLED=true
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
API_SERVER_KEY=<openssl rand -hex 32 결과>
```
> `API_SERVER_KEY` 미설정 시 **loopback이어도 기동 거부**(api_server.py:4146). loopback 샘플은 약한키도 통과하나(약한키 거부는 network bind에만), 네트워크 노출 전 강한키 필수.

### P4 — skill
```md
---
name: hermes-delegate
description: 일정·메시징·비개발 업무기록·외부 문의는 Hermes에 위임. 코드 작성/테스트/디버깅/리팩터링/PR에는 사용하지 않는다.
---
## 호출 규칙
- 비개발 문의 → hermes_inquiry / 회의·반복알림 → hermes_schedule(cron, gateway 상시) / 메모 → hermes_memo, 조회 → hermes_notes / 발송 → hermes_send
- 코드 수정·테스트·빌드·배포 절차는 위임 금지
## 응답 규칙
- 호출 전: 저장/전송될 정보 1줄 요약 / 호출 후: 결과·대상·시각·실패여부(동기 ack 한정, §1.5) 구조화 보고
```

---

## 4. 분류 backstop (검토 M2·FEAS-03·COMP-TOOLSET-BACKSTOP 해소)

분류는 본질적 **fail-open**(LLM 판단 + skill 문자열). 구조적 backstop 3중:
1. **어댑터 action allowlist** — `inquiry/schedule/memo/notes/send` 5 action만 수용. **메시지 본문 키워드(git/npm/build) 부분문자열 거부는 금지**(정상 비개발 메시지 false-positive — FEAS-03). 콘텐츠 스캔 대신 **action 화이트리스트 + 구조화 intent**만 검증.
2. **Claude 권한 규칙** — `hermes_send`·`hermes_schedule`(쓰기)=Ask, `hermes_inquiry`/`hermes_notes`/read=Allow.
3. **Hermes 배포시 toolset 제한** — `enabled_toolsets`는 **per-call 어댑터 제어 불가**(/v1/responses는 config.yaml `platform_toolsets.api_server`에서 정적 결정, /api/jobs도 미수용 — FEAS-09). → **배포 시 config.yaml에서 api_server 프로파일의 terminal/code 툴 제외**(per-call 아닌 deploy-time 게이트).

---

## 5. 보안 (검토 M5 — "이중 가드" 과신 금지)

> 루트 `SECURITY.md`: env filtering *"not containment"*(:129), LLM 스크리너 *"not boundaries"*(:139). **실제 boundary는 allowlist + 컨테이너 격리뿐.**

| 영역 | 설정 | 근거 |
|---|---|---|
| API server | 127.0.0.1 고정 + `API_SERVER_KEY`(강한키) | api_server.py:65, 4146 |
| gateway | 플랫폼 allowlist + DM pairing(default-deny) + **상시 가동**(§1.3) | gateway-internals.md, security.md |
| terminal | `terminal.backend: docker` | security.md:341(backend: docker), 360(격리 서술) |
| docker env | `docker_forward_env: []` 기본, 꼭 필요한 값만 | security.md:343 |
| MCP subprocess | 명시 `env`만(safe baseline 외 strip) | security.md:464 |
| MEDIA 첨부 | 차단 아님 → 경로 화이트리스트 + 크기 제한 + secret 파일 스캔 | (H2 해소) |
| 부작용 도구 | Claude Ask + Hermes approval (boundary 아님 인지) | SECURITY.md:129,139 |

---

## 6. 테스트 (검토 M6·FEAS-01 등 반영)

| 시나리오 | 기대 | 복구 |
|---|---|---|
| 무인증 API 접근 | 401 또는 기동 거부 | — |
| **gateway down 상태 cron 생성 후 미발화** | 생성은 성공, due 시각에 **fire 안 됨**(§1.3) | gateway 기동 → tick 재개 |
| gateway down + built-in send | 성립(standalone) | — |
| gateway down + yuanbao send | 실패(adapter 필수) | gateway 기동 |
| key 회전 후 구토큰 | 401 | 신키 배포 |
| 동시 N세션 state.db | WAL write-lock 경합 거동(hermes_state.py:386) | retention/prune |
| 어댑터 크래시 복구 | in-memory event queue 손실 범위 | 재시작 |
| `POST /api/jobs` cron 생성 | `{"job":{id,...}}` + pause/run | — |
| **`hermes_notes` 검색** | category/tags/query 필터 정상 | — |
| MEDIA 첨부 전송 | 정상 + 비허용 경로 차단 | — |
| inquiry 장시간(>120s) | `/v1/runs` async 전환 동작 | — |
| stdio MCP 크래시 | Claude 자동 재연결 안 함 → `/reload-plugins`/재시작 | — |

---

## 7. 의사결정 — 1안 vs 2안 (양 문서 공통 표)

| 축 | 1안 (하네스 연동) | 2안 (플러그인) |
|---|---|---|
| 재배포/버전 | ✗ 없음 | ✓ semver, 10분 설치 |
| 설치 난이도 | 낮음(이 머신만) | 중(패키징/reload) |
| 팀 공유 | 어려움 | 쉬움 |
| managed allowlist 환경 | 영향 적음(개인 머신) | **admin allowlist 필요**(#32882/#32883 — 2안 §3.5) |
| 어댑터 수정 반영 | 즉시 | 재패키징 |
| 적합 | 1인·단일 머신·빠른 PoC·자주 바뀌는 로직 | 2+ 머신·팀·버전 재현성 |

**전환 경로(양 문서 공통)**: 1안으로 검증(1안 P2 메시징 파일럿 → P3 어댑터)하여 안정화한 뒤, 동일 어댑터/skill을 2안으로 패키징한다. 즉 1안은 2안의 선행 단계가 될 수 있고, 2안은 1안에서 검증된 산출물을 재배포 단위로 승격한다. 단 managed allowlist 환경은 2안 단독으로 해결 안 됨(2안 §3.5 — admin 승인 필수).

---
*R1→R3 교차검토(Codex+Claude+적대적 verify) 수렴본(잔존 0건). §1은 2안과 SoT 동기화.*
