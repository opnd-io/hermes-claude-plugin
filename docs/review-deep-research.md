# hermes_deep_research.md 상세 검토 리포트

**검토일**: 2026-06-04 · **대상**: `hermes_deep_research.md` (Claude→Hermes 단방향 위임 구현 기획서, 341줄)
**Ground-truth**: Hermes Agent **v0.15.1** 로컬 소스 (`C:/Users/tgkim/AppData/Local/hermes/hermes-agent`)

## 검토 방법 (Codex 페어 + Claude 6-차원 + 적대적 verify)

3개 독립 소스를 교차 adjudicate:
1. **Codex(GPT-5.x) 독립 검증** — 20 finding (실제 소스 대조)
2. **Claude 6-차원 워크플로** — hermes-mcp-serve / hermes-api-server / hermes-security-ops / claude-side(web) / architecture / consistency-feasibility, 각 차원 후 **적대적 verify** 단계
3. **오케스트레이터 직접 ground-truth anchor** — 핵심 3주장 직접 대조

핵심: 이 기획서는 deep-research 도구 출력(`citeturnXXX` 마커)이라 **문서 단독으로는 모든 사실 주장이 검증 불가**다. 그러나 Hermes 실제 소스가 로컬에 있어 **대부분의 Hermes 주장을 코드로 직접 검증**할 수 있었다 (Claude Code 측 주장은 공식 docs 웹 대조).

---

## 총평

> **현 상태로는 빌드 불가(as-written), 단 수정하면 실행 가능.** 보안·전송 골격(127.0.0.1+API_SERVER_KEY 필수, read=gateway 불요/send=gateway 차등, 단방향, stdio-only 브리지, 10-tool 카운트)은 소스와 **정확히 일치**한다. 문제는 그 정확한 골격 위에 얹은 **4-tool payload/API 매핑이 substrate(실제 API surface) 레벨에서 검증되지 않은 채** 제시된 것이다. "미지가 아니라 미작성" — 매핑 대상 API는 모두 실재하나 기획서가 잇지 않았다.

**Codex·Claude 양측 독립 합의 (Agreed) = 최고 confidence.** 두 모델이 top 결함에 완전 수렴했다.

---

## 교차검증 하이라이트 (적대적 verify가 잡은 리뷰어 false-positive)

**Claude-side F2 "GitHub 이슈 2건 both not-planned framing 이 틀렸다" → 적대적 verify가 REJECT (holds_up: false).**

- 1차 리뷰어가 문서에 **없는** 이슈 번호(16143/48758 등)를 스스로 지어내 "문서와 불일치"라 결함 처리 → 정확한 문서를 거짓 결함화.
- verify 단계가 문서의 두 증상에 **실제 매칭되는** 이슈를 live 확인: **#32882**(`.mcp.json silently ignored when allowedMcpServers configured in managed-settings.json`) + **#32883**(`plugin:name:server names cannot be used in allowedMcpServers`), **둘 다 CLOSED/NOT_PLANNED**, 2026-03-10 생성·2026-04-08 종료(연속 배치).
- **결론: 기획서의 "2건 모두 not planned" 주장은 사실이며 검증 가능.** (오히려 #32882/#32883을 명시하면 강화됨.) Codex도 이 항목을 NEEDS-LIVE-VERIFICATION으로 신중 처리.

> 시사점: 본 검토의 적대적 verify 계층이 의도대로 작동해 "정확한 문서를 잘못 깎는" 오류를 차단했다.

---

## 결함 (severity 순 · Codex+Claude 합의 표기)

### 🔴 CRITICAL

**C1. `schedule` = 캘린더 이벤트로 설계됐으나 Hermes에 캘린더 backing 전무 (cron job뿐)**
*(Agreed: Codex F8 + Claude ARCH-01 verified-critical + anchor ④)*
- 문서: `schedule` payload = `{startAt, endAt, timezone, notifyTargets}` (미팅 캘린더 형태), 역할표 "회의 일정 생성·변경·조회"를 Hermes 위임.
- 실제: `cron/jobs.py create_job()` = `prompt/schedule(문자열)/name/repeat/deliver`만. `parse_schedule()` = `once|interval|cron`만. `POST /api/jobs` 핸들러(api_server.py:3110-3146)도 discrete 일정 필드 0. `grep calendar|appointment|startAt|endAt|attendee` = **0건**.
- cron은 "특정 시각에 **프롬프트를 실행**"하는 리마인더 메커니즘이지 "14:00~15:00 미팅 저장"이 아님.
- **권고**: `schedule`을 (a) cron job(리마인더/반복 프롬프트) 등록으로 재정의하거나 (b) 외부 캘린더(Google Calendar 등)를 별도 backing으로 명시. "캘린더 기능은 현재 Hermes로 backing 불가, cron 근사"라고 한계 정직 표기.

### 🟠 HIGH

**H1. 4-tool→API 매핑이 0건 — "adapter 사실상 필수"의 핵심 정당화 공백 (빌드 차단급)**
*(Agreed: Codex F9/F10 + Claude ARCH-02 & F2 verified)*
- 문서: `inquiry/schedule/memo/send` 4 도메인 도구가 권장안 핵심, "바로 구현 가능 수준으로 좁혔다"(L250). 그러나 각 action→(method/path/body/parsing) 매핑이 mermaid 한 줄(`/v1/responses 또는 Jobs API`)과 산문뿐.
- 실제: 4 도구가 **서로 다른 4개 표면**에 분산 —
  - `inquiry` → `POST /v1/responses` (또는 `/api/sessions/chat`)
  - `schedule` → `POST /api/jobs` (cron, **/v1 아님**)
  - `memo` → **전용 엔드포인트 없음** (agent 내부 memory 툴 간접; `grep /api/memor|/v1/memor` = 0)
  - `send` → `messages_send`(MCP) 또는 gateway (**API server toolset에서 제외**, H3 참조)
- **권고**: 4 action 각각 `[method, path, 요청 body, 응답 파싱, gateway 의존, 실패 모드]` 매핑표 필수. 특히 memo는 직접 엔드포인트 부재 → `/v1/responses`로 agent에 memory 툴 호출을 **지시**하는 간접 경로임을 명시. 이 표 없이는 권장안 ROI/난이도 평가 자체가 검증 불가.

**H2. `send`는 text-only·첨부 범위 밖" 단정이 거짓 — 실제 `MEDIA:<path>` 네이티브 첨부 지원**
*(Agreed: Codex F1-nuance + Claude MCP-5 verified-high & ARCH-04 & F1 verified)*
- 문서 테스트표(L150): "첨부는 범위 밖 → adapter에서 사전 차단하고 '텍스트만 지원' 반환".
- 실제: `messages_send`(mcp_serve.py:734) → `send_message_tool` 위임. 스키마(send_message_tool.py:150): *"To send an image or file, include `MEDIA:<local_path>` … the platform will deliver it as a native media attachment."* telegram/discord/matrix/weixin/signal/yuanbao/feishu 7개 플랫폼 native 첨부. **차단 코드 없음.**
- 이 "사전 차단" 권고는 **작동하는 기능을 막는 안티가드**이자, 진짜 리스크(MEDIA 경로로 secret 파일 유출)를 놓침.
- **권고**: "차단" 제거 → "MEDIA 경로 화이트리스트 + 크기 제한 + 민감파일 스캔"으로 가드. send payload의 `mode/workspace` 필드도 실제 인자(`target/message`)에 없으므로 매핑 또는 제거.

**H3. `send` 경로가 API server full toolset과 충돌 — 통합 토폴로지가 기획서와 다름**
*(Codex F9, CONFIRMED-ISSUE)*
- 실제: `test_api_server_toolset.py`가 `assert "send_message" not in tools` — API server가 만드는 agent toolset은 **메시지 전송 툴을 명시적 제외**.
- 따라서 "adapter → Hermes API server 일원화"로 send까지 처리한다는 암시는 불가. send는 반드시 `messages_send`(MCP) 또는 gateway 경로 별도.
- **권고**: 아키텍처 다이어그램에서 send를 API server가 아닌 gateway/MCP 경로로 분리 명시 (ARCH-07 mermaid 불일치와 연동).

**H4. `memo`(category/tags/dedupeKey)를 받을 구조화 영속 스토어 없음 + bounded ~2,200자라 회의록 누적 부적합**
*(Agreed: Claude ARCH-03 verified & F6 verified)*
- 실제: `MEMORY_SCHEMA`(memory_tool.py:652-701) = `action(add/replace/remove)/target(memory|user)/content`만. category/tags/dedupeKey 슬롯 **전무**.
- 결정적: memory 툴 description이 *"Do NOT save task progress, session outcomes, completed-work logs"* 명시 → 회의록/팔로업 누적과 **정면 모순(스펙이 금지)**. `tips.md:122`: MEMORY.md ~2,200자, 포화 시 consolidate(손실).
- 문서 본문(L17,31)은 "bounded, curated memory"를 정확히 인용하면서 같은 메모리에 회의록 누적 권고 → **자기모순**.
- **권고**: 회의록·팔로업은 bounded MEMORY.md가 아니라 세션 기록/별도 노트 저장소(파일/DB)에. "메모리=좁은 선호/사실, 회의록=별도 저장"으로 데이터 경계 분리.

### 🟡 MEDIUM

**M1. `send`는 gateway가 살아있어야만 동작" 오버심플리피케이션**
*(Agreed: Claude MCP-7 & F3 verified)* — built-in 플랫폼(telegram/slack/signal/email/sms/matrix)은 one-shot 클라이언트로 **gateway 프로세스 없이** standalone 전송(config/creds만 필요); plugin은 `standalone_sender_fn` fallback. **단 yuanbao는 running adapter 필수.** → "gateway 중지=무조건 send 실패가 정상"은 거짓 음성 유발. 플랫폼/설정 의존으로 정정.

**M2. dev/non-dev 분류가 fail-open (런타임 강제 0)**
*(Claude ARCH-06 verified)* — 분류는 순전히 Claude LLM 판단 + skill description 문자열. Hermes/adapter에 "dev 요청 거부" 게이트 부재(`grep reject.*dev|classify|is_dev` = 무관 매칭만). 문서 스스로 "메모리 경계 붕괴 가능성 높음"(L311) 인정하나 완화책이 같은 soft 계층. → 구조적 backstop 추가: (a) adapter action allowlist + 코드 키워드 거부, (b) Claude 권한 Ask 규칙, (c) Hermes `enabled_toolsets`로 코드 실행 툴 차단.

**M3. 단방향(callback 없음)이 비동기 완료·실패를 Claude에 숨김**
*(Claude ARCH-09 verified)* — cron(60초 tick)·send는 미래/비동기. 단방향이면 Claude는 "등록 ack"만 받고 cron 실행 결과·send 최종 전달 성공/실패를 push 못 받음. 보고 규칙(L247) "실패 여부 보고"는 동기 등록 시점만 반영. → adapter가 `events_poll`/`/v1/runs/{id}/events`/`/api/jobs/{id}` 폴링으로 종결 상태 확인하는 보완책 명시.

**M4. 3안 비교에서 더 단순한 대안 2종 누락**
*(Claude ARCH-08 verified)* — "선택지는 세 가지"(L37)는 비망라. 누락: (a) **로컬 HTTP MCP** adapter(stdio 대비 재연결 용이 + 다중 클라이언트), (b) API server `/v1` 표면 **얇은 MCP-wrap**(4-tool 정제 비용 회피). 전송방식(stdio/HTTP)이 직교 축인데 "로컬=stdio, 원격=HTTP"로 묶여 사라짐.

**M5. 보안 "이중 가드" 과신 — Hermes SECURITY.md는 더 겸손함**
*(Codex F17/F19, CONFIRMED-ISSUE)* — SECURITY.md: env filtering은 *"reduces casual exfiltration. It is **not containment**."*, LLM 행동 스크리너는 *"useful. They are **not boundaries**."* → 문서의 "이중 가드=견고한 보안 모델" 프레이밍은 과신. prompt injection은 mitigation이지 boundary 아님. 실제 boundary는 allowlist + 컨테이너 격리.

**M6. 누락된 치명 테스트**
*(Agreed: Claude F8 verified)* — key rotation 후 기존 토큰 401 / **동시 다중 세션 state.db WAL 경합**(hermes_state.py:386 "WAL write-lock contention causes visible TUI freezes" = 실위험) / adapter 크래시 후 in-memory event queue 손실 복구 / `POST /api/jobs` cron 생성·pause·run / MEDIA 첨부 정상+비허용 경로 차단.

**M7. "열린 질문과 한계" 섹션이 더 큰 blocker를 누락**
*(Agreed: Claude F11 verified)* — 한계 3건(향후 표면 추가/로그 보존/managed 충돌)만 정직히 나열하고, 정작 빌드-차단급 미지(H1 매핑 부재, H2 첨부 오판, M1 send 의존성, H4 memo 영속, M6 WAL 경합)는 누락 → 실행 리스크 과소 노출.

**M8. citeturn 마커 전면 검증 불가**
*(Agreed: Codex F16 + Claude F10 verified, UNVERIFIABLE)* — 거의 모든 문장이 deep-research 내부 마커 의존, 공개 URL/이슈번호/SHA 앵커 부재. Hermes 측은 본 검토가 소스로 대체 검증했으나, **Claude Code 측 주장(allowedMcpServers·MCP connector·plugin 번들)은 이 환경 밖**. → 마커를 실제 공개 URL로 치환 + 검증 불가 주장에 "외부 PoC 필요" 라벨.

### 🟢 LOW

| # | 결함 | 근거 | 권고 |
|---|------|------|------|
| L1 | "Jobs API"를 /v1 표면으로 지칭하나 실제는 `/api/jobs` | api_server.py:4114-4121 (Codex F4, Claude API-06/ARCH-05/F12) | adapter base-url을 `/v1` 고정 말고 호스트 루트(`:8642`)로 두고 경로별 prefix 분기. `/v1/jobs` 호출 시 404 함정 |
| L2 | "full toolset, **memory**, skills 제공" — memory는 agent-내부 toolset, REST write API 없음 | `/v1/capabilities` `memory_write_api:false` (Claude API-07) | "memory는 전용 REST 아님, chat/responses 경유 agent 툴" 1줄 명시 |
| L3 | mermaid `schedule` sequence가 본문 flowchart와 불일치 | flowchart=A→H→G 단방향 vs sequence=A가 H·G 병렬 호출 (Claude ARCH-07) | schedule 흐름을 실제 backing(cron)에 맞게 수정 + 호출 토폴로지 통일 |
| L4 | 로그 보존 "문서 미노출" 포괄 단정 과장 | `docker.md:167` "10 archives × 1 MB" 반례 존재 (Claude HSEC-08) | "주 agent.log backup_count는 미노출(소스 기본 3)" + docker 가이드 반례 분리 서술 |
| L5 | `p95 10초/5초`를 근거 없이 SLA처럼 제시 | inquiry/memo는 LLM 추론 동반 → 10초 비현실적 (Claude F7) | 수치 제거 또는 "초기 placeholder, 실측 후 교정" 강등 |
| L6 | .env 샘플 `API_SERVER_KEY=change-me-local-only` | 약한키 거부는 **network-accessible bind에만** 적용; loopback은 통과 (Claude API-05/F5) | loopback 샘플은 동작하나, 네트워크 노출 전 `openssl rand -hex 32`로 교체 경고 추가 |

---

## ✅ 정확한 주장 (ACCURATE — 거짓 결함 방지용 명시)

양측이 소스/docs로 **확인한 정확한 주장** (수정 불요):

- **MCP serve 10개 도구** 카운트 정확 (conversations_list, conversation_get, messages_read, attachments_fetch, events_poll, events_wait, messages_send, channels_list, permissions_list_open, permissions_respond). `events_poll`(커서)·`events_wait`(롱폴)은 별개 도구로 둘 다 실재 — 명칭 오류 아님.
- **`/v1/chat/completions·/v1/responses·/v1/runs·/v1/skills·/v1/toolsets`** 전부 실재. `/v1/responses` stateful(previous_response_id), `/v1/runs` 202 비동기.
- 기본 bind **127.0.0.1:8642** 정확. env 키명(`API_SERVER_ENABLED/HOST/PORT/KEY`) 일치.
- **API_SERVER_KEY 강제** — 키 없으면 loopback 포함 `connect()` 거부(return False). 문서가 오히려 **과소 진술**(start-time 거부를 명시 안 함).
- **0.0.0.0 bind guard** 실재(키 강제 + network-bind placeholder 거부) — 문서가 "코드 차단 아닌 운영 정책"으로 정직 표기.
- **read는 gateway 없이 가능** (로컬 sessions index + state.db 직접 read). **stdio-only** 브리지.
- gateway **default-deny**(allowlist/pairing 없으면 거부), **terminal.backend docker** 권장, **docker_forward_env []** 기본, **MCP env filtering**(safe vars + 명시 env만), **curator**(agent-created 한정·자동삭제 없음·dry-run), **checkpoints**(write_file/patch/파괴적 shell 전 자동 + /rollback), **sessions** SQLite state.db + auto_prune/retention_days(기본 90), **backup/import** — 모두 소스·docs 확인.
- **Claude Code** stdio/HTTP/WS transport, user/project/plugin scope, `/reload-plugins`, `claude mcp reset-project-choices`, 서버별 timeout, **크래시된 stdio 자동 재연결 안 함** — 공식 docs 확인.
- **Claude API MCP connector = 원격 HTTPS only, local stdio 불가, tool-call 중심** — 공식 docs 확인.
- **plugin-bundled MCP vs allowedMcpServers GitHub 이슈 2건 both not-planned** — **#32882 + #32883로 live 검증됨 (사실)**.

---

## 권장 수정 우선순위 (의존성 순)

1. **[C1·H1·H3·L1] adapter 4-tool→API 매핑표 작성** + schedule을 cron 모델로 재정의(또는 외부 캘린더 명시) + send를 gateway/MCP 경로로 분리. → 이게 빌드 가능성의 핵심.
2. **[H2·H4] payload 현실화** — send 첨부(MEDIA) 인정 + 차단 대신 secret 스캔 가드; memo를 세션/파일 저장소로 재배치(bounded 메모리 금지).
3. **[M2·M3·M5] 안전·관찰성 보강** — 분류 fail-open backstop, 비동기 종결 상태 폴링, 보안 프레이밍을 SECURITY.md 수준으로 하향("not containment").
4. **[M6·M7·M8] 정직성** — 누락 테스트 5종 추가, 한계 섹션에 진짜 blocker 반영, citeturn→공개 URL 치환.
5. **[M4·L2~L6] 완결성** — 대안 2종 추가, 작은 사실 정정.

## 최종 권고

**기획서의 전략 방향(Claude=개발 메모리 / Hermes=업무·메시징, 로컬 stdio adapter, 127.0.0.1+key 보안)은 타당하고 소스와 정확히 일치한다.** 그러나 **실행 산출물로는 미완성** — 특히 `schedule`(캘린더 backing 부재)과 4-tool→API 매핑 공백이 빌드를 막는다. 위 1~2번을 채우면 "구현 가능한 기획서"가 된다. 그 전까지는 **메시징 파일럿(`hermes mcp serve` 직접 연결)으로 검증하면서 adapter 매핑표를 별도 설계**하는 것이 안전하다.

---
*검토: Codex(GPT-5.x) 독립 + Claude 6-차원 워크플로 + 적대적 verify 교차 adjudication. Hermes v0.15.1 소스 ground-truth 대조.*
