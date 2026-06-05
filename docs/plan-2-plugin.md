# 2안 — Hermes 플러그인화 기획서 (Claude Code Plugin)

**버전** v0.4 (R3 교차검토 수렴) · **기준일** 2026-06-04 · **대상 런타임** Hermes Agent v0.15.1
**범위** Hermes 위임 브리지를 **재배포 가능한 Claude Code 플러그인**(`hermes-bridge`)으로 패키징. 다중 머신·팀.
**Ground-truth** `C:/Users/tgkim/AppData/Local/hermes/hermes-agent` 소스 직접 검증. **§1 어댑터 계약 본문(1.1~1.5)은 1안과 바이트 동일(SoT)** (제목 줄은 상대 문서 참조라 제외).
**파일 경로 규약**: `api_server.py`=`gateway/platforms/api_server.py`, `security.md`=`website/docs/user-guide/security.md`, 루트 `SECURITY.md`는 별도 명시.

---

## 0. 목표와 비범위

**목표**: 1안과 동일한 Claude→Hermes 단방향 위임을, **버전 고정·10분 설치·팀 공유 가능한 플러그인 단위**로 패키징. `.claude-plugin/plugin.json` + 번들 `.mcp.json` + 어댑터 + `hermes-delegate` skill.

**비범위**: Hermes 코어 수정, 원격 HTTPS 노출, Claude API connector(원격 HTTPS only), 캘린더 SaaS.

**2안의 정체성**: **재배포·버전 관리**가 핵심 가치. 대가로 패키징/릴리스/`/reload-plugins` 마찰 + **managed allowlist 환경의 admin 의존**(§3.5).

---

## 1. 어댑터 계약 §A (본문 1.1~1.5는 1안과 바이트 동일 — SoT)

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

## 2. 플러그인 구조 + 로드맵

```
hermes-bridge/
├── .claude-plugin/plugin.json   # manifest
├── .mcp.json                    # 번들 MCP (어댑터 바이너리)
├── bin/hermes-mcp-gateway       # stdio 어댑터(§1 계약, §2.2 런타임)
├── skills/hermes-delegate/SKILL.md
├── scripts/install.sh           # 전제 점검 + 키 안내(§2.3)
└── README.md                    # 설치/운영/managed-env(§3.5)
```

| 단계 | 목표 | 핵심 작업 | 통과 기준 |
|---|---|---|---|
| **P1 전제+스캐폴드** | Hermes 준비 + 골격 | API server enable + `API_SERVER_KEY`(강한키) + gateway 상시(§1.3) / plugin.json + .mcp.json + 어댑터(§1) + skill | `/v1/models` 200, 무인증 401 / 로컬 설치 시 5 도구 §1 경로 호출 |
| **P2 패키징** | 재배포 단위 | semver, `/reload-plugins` 워크플로, install.sh(§2.3), README | 신규 머신 10분 내 설치·동작 |
| **P3 managed-env** | 엔터프라이즈 현실 | §3.5 — admin allowlist 요청 절차 + non-colon 서버명 + 1안 폴백 안내 | managed 환경에서 admin 등록 시 동작 / 미등록 시 명확한 실패 메시지 |
| **P4 운영** | 상시 안전 | backup/import, retention, runbook, 배포 채널 | 무중단 재기동, key 회전 복구 |

### plugin.json
```json
{
  "name": "hermes-bridge",
  "displayName": "Hermes Bridge",
  "version": "0.1.0",
  "description": "Delegate non-development work (messaging/schedule/memo) from Claude to Hermes",
  "skills": "./skills",
  "mcpServers": "./.mcp.json"
}
```
> `skills`는 string|array, `mcpServers`는 string|array|object 모두 유효(Claude Code plugins-reference 스키마 — **외부 문서 의존, 배포 전 PoC 확인**). 번들 `.mcp.json`은 plugin root에서 자동 인식.

### 번들 .mcp.json
```json
{
  "mcpServers": {
    "hermes-bridge": {
      "command": "${CLAUDE_PLUGIN_ROOT}/bin/hermes-mcp-gateway",
      "args": ["--api-base", "http://127.0.0.1:8642"],
      "env": { "HERMES_API_KEY": "${HERMES_API_KEY}" },
      "timeout": 120000
    }
  }
}
```
> `--api-base`는 호스트 루트(`/v1` 고정 금지). `timeout` 120s(inquiry 풀 루프, §1.5). `HERMES_API_KEY`는 사용자 env 주입(번들에 키 미포함 — 공급망/유출 방지).

### 2.2 어댑터 런타임 (검토 COMP-ADAPTER-RUNTIME 해소)
- **권장: Python** — Hermes와 동일 스택, `httpx` + `mcp` SDK, 노트스토어 `sqlite3`. PyInstaller/zipapp으로 단일 실행파일 패키징 가능.
- 대안: Node(`@modelcontextprotocol/sdk`) — Hermes 비의존, npm 번들. 단 공급망 표면 증가 → 의존성 최소.
- 무결성: 릴리스 바이너리 SHA256 체크섬 동봉, `install.sh`에서 검증.
- **전송 토폴로지 대안(검토 M4)**: stdio 어댑터(현 권장, Claude Code 표준) vs 로컬 HTTP MCP(재연결·다중 클라이언트 용이, 포트 관리) vs API server `/v1` 얇은 MCP-wrap(구현 최소, 단 전체 표면 노출→역할 경계 흐려짐). **2안은 재배포 단위라 stdio + 4-tool(+notes) 정제가 일관·안정** — 얇은 wrap 대비 채택.

### 2.3 install.sh 내용 (검토 COMP-INSTALL-SH 해소)
순수 점검·안내 스크립트(**`curl|sh` 금지**, §5):
1. `hermes --version` 존재 확인 → 없으면 안내 후 종료.
2. `~/.hermes/.env`의 `API_SERVER_ENABLED`/`API_SERVER_KEY` 점검 → 없으면 생성 가이드 출력(`openssl rand -hex 32`).
3. `curl -fsS -H "Authorization: Bearer $HERMES_API_KEY" 127.0.0.1:8642/v1/models` 연결 확인.
4. gateway 가동 여부 점검(`hermes gateway status` 류) → schedule 발화 전제(§1.3) 경고.
5. 어댑터 바이너리 SHA256 검증. **키 자동 주입·기록 안 함** — 사용자 env 설정만 안내.

---

## 3. 설정·운영 세부

(§1.5 비동기 관측은 1안과 동일 전재; §4 backstop·§5 보안은 1안과 동기화 + 플러그인 보강 — 각 절 헤더 참조.)

### 3.5 ⚠️ 엔터프라이즈 managed allowlist 현실 (2안 고유 — 검토 FEAS-04 정정)

**검증된 제약** (GitHub anthropics/claude-code):
- **#32882**(`.mcp.json silently ignored when allowedMcpServers configured in managed-settings.json`) + **#32883**(`plugin:name:server colon names cannot be used in allowedMcpServers serverName`) — **둘 다 CLOSED/NOT_PLANNED**(2026-03-10 생성, 2026-04-08 종료). *(외부 문서 의존 — 배포 전 `gh issue view`로 재확인 권장.)*
- changelog: *"Plugins blocked by organization policy (managed-settings.json) can no longer be installed or enabled."*

**핵심 정정 (R1 FEAS-04)**: **dual-delivery는 우회책이 아니다.** `allowedMcpServers`/managed-settings.json은 **admin-only**라, 차단 환경에서는 **플러그인 번들 MCP도, 명시 `.mcp.json`도 self-serve 불가**. 따라서:
- (a) **admin에게 `hermes-bridge`(non-colon 서버명)를 `allowedMcpServers`에 추가 요청** — colon 서버명(#32883)은 admin도 못 넣으므로 명시 `.mcp.json`의 단순 서버명 사용.
- (b) managed 통제 **밖**(개인 머신)이면 **1안 사용**.
- (c) 설치 후 `claude mcp list`로 `hermes-bridge` 노출 확인(번들 무시 감지) → 미노출 시 (a)/(b)로 안내.
- README는 "managed 환경은 admin 승인 필수, 우회 불가"를 명시(과장 금지).

---

## 4. 분류 backstop (1안 §4 동기화 + 플러그인 옵션)
1. **어댑터 action allowlist** — 5 action만, **메시지 본문 키워드 부분문자열 거부 금지**(FEAS-03). action 화이트리스트 + 구조화 intent만.
2. **Claude 권한** — send/schedule-write=Ask, inquiry/notes/read=Allow. 플러그인은 skill을 둘로 분리해 send/schedule-write만 `disable-model-invocation`(수동) 옵션 제공.
3. **Hermes 배포시 toolset 제한** — config.yaml `platform_toolsets.api_server`에서 terminal/code 제외(deploy-time, per-call 어댑터 제어 불가 — FEAS-09).

## 5. 보안 (1안 §5 동기화 + 플러그인 보강 — 검토 M5)
> 루트 `SECURITY.md`: env filtering *"not containment"*(:129), 스크리너 *"not boundaries"*(:139). boundary는 allowlist+컨테이너뿐.

127.0.0.1+강한키(api_server.py:65,4146) / gateway default-deny + 상시 / `terminal.backend: docker`(security.md:341,360) / `docker_forward_env: []`(security.md:343) / MCP env strip(security.md:464) / MEDIA 가드(경로 화이트리스트+크기+secret 스캔) / Ask. **플러그인 추가**: 번들에 키·secret 미포함(공급망), 어댑터 SHA256 검증, `install.sh` `curl|sh` 금지.

## 6. 테스트 (1안 §6 전체 + 플러그인 고유)
1안 §6 전체(무인증401 / **gateway down cron 미발화** / standalone vs yuanbao send / key회전 / 동시세션 WAL / 어댑터크래시 / cron 생성 `{"job":...}` / notes 검색 / MEDIA / inquiry 장시간 async / stdio 재연결) + 플러그인 고유:

| 시나리오 | 기대 |
|---|---|
| 신규 머신 클린 설치 | 10분 내 5 도구 동작(어댑터 경로 해석 + SHA256 검증) |
| `/reload-plugins` 후 .mcp.json 변경 | 반영(안되면 재시작) |
| **managed allowlist deny 환경** | self-serve 불가 → install.sh가 admin 요청/1안 폴백 안내(§3.5, FEAS-04) |
| 버전 업그레이드 | 구→신 어댑터 무중단 교체 |

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
*R1→R3 교차검토(Codex+Claude+적대적 verify) 수렴본(잔존 0건). §1은 1안과 SoT 동기화.*
