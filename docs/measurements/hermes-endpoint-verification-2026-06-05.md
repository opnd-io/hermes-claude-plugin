# Track 0 — Hermes 엔드포인트 실재성 검증 (2026-06-05)

**목적**: plan-3 의 HTTP 의존 코드 precondition. plan-2 계약(엔드포인트 근거가 외부 Hermes 체크아웃 anchor) 을 실 소스로 확정. Codex 가 "implementable_now 다수가 실은 implementable_if_endpoints_match" 로 지목한 #1 위험 해소.

**검증 대상 소스**: `C:/Users/tgkim/AppData/Local/hermes/hermes-agent` (Hermes Agent, repo 밖, read-only)

| # | 엔드포인트/표면 | 검증 명령 결과 (file:line) | verdict | confidence |
|---|---|---|---|---|
| 0.1 | `POST /v1/responses` output_text 구조 | `api_server.py:2288` `"content": [{"type": "output_text", "text": ...}]`; 스트림 `response.output_text.delta/done` (`:2166`); text part types `{text,input_text,output_text}` (`:143,173`) | **CONFIRMED** | certain |
| 0.2 | `POST /api/jobs` 생성 응답 `{"job":{...}}` | `api_server.py:3147` `return web.json_response({"job": job})` (route `:3103`) | **CONFIRMED** | certain |
| 0.3 | `GET /api/jobs/{id}` 폴링 필드 | `cron/jobs.py:695-698` `next_run_at`/`last_run_at`/`last_status`/`last_error` 필드 실재; route `api_server.py:3152` | **CONFIRMED** | certain |
| 0.4 | `POST /v1/runs`(202) + `GET /v1/runs/{id}/events`(SSE) | `api_server.py:17-21` docstring + `:1130-1134` 라우트 맵 + `:3486` `/v1/runs structured event streaming` | **CONFIRMED** | certain |
| 0.5 | `tools.send_message_tool` + `_send_to_platform` | `tools/send_message_tool.py:158` `def send_message_tool(args, **kw)` (sync), `:573` `async def _send_to_platform(...)`, `_handle_send` reads `args.get("target")`/`args.get("message")`, target=`platform:ref` 분기 | **CONFIRMED** | certain |

## 계약 정합성 핵심 발견 (plan-3 영향)

1. **plan-2 계약 숫자 정확**: `api_server.py:3061-3062` `_MAX_NAME_LENGTH = 200`, `_MAX_PROMPT_LENGTH = 5000` — plan-2 §1.1 의 "name≤200 / prompt≤5000" 과 **정확히 일치**.

2. **백엔드가 입력검증을 이미 강제** (B5 재평가 근거):
   - `api_server.py:3120-3124` name 미입력 → 400 "Name is required", name>200 → 400 "Name must be ≤ 200"
   - `:3127-3129` prompt>5000 → 400 "Prompt must be ≤ 5000"
   - create job repeat 양수 검증 → 400 "Repeat must be a positive integer"
   - PATCH(`:3188-3194`) 도 동일 검증
   - **함의**: 어댑터측 name/prompt/repeat 재검증은 **중복** (백엔드 SoT). B5 는 (a) 빠른 로컬 에러 UX 또는 (b) 백엔드 미경유 필드(예: limit)만으로 축소. 어댑터 단독 강제는 불필요 — 백엔드 400 을 구조화 에러로 surface 하면 충분.

3. **send 인자 스키마 정확**: 어댑터 `send_message_tool({"action":"send","target":target,"message":message})` (bin/hermes_mcp_gateway.py:206) 가 `_handle_send` 의 `args.get("target")`/`args.get("message")` 와 정확히 매칭. `send_message_tool` 은 sync 함수라 `asyncio.to_thread` 위임도 적절 (`_send_to_platform` 만 async).

4. **send 도 자체 검증**: `_handle_send` 가 "Both 'target' and 'message' are required" 검증 → 어댑터 L202-203 와 중복 (무해).

## 결론

- Track 0 의 5개 엔드포인트 **전부 CONFIRMED (certain)** — 어떤 의존 Track 도 drop/재설계 불요.
- B1 (`/v1/runs` async) 는 0.4 CONFIRMED 로 **진행 가능** (조건부 drop 해제).
- B5 (입력검증) 는 백엔드 중복으로 **축소** — 백엔드 400 surface + limit 만 어댑터 검증.
- **단, 본 검증은 정적 소스 read 기준.** 실 런타임 200/202/SSE 동작은 Track E.2 실백엔드 e2e 에서 별도 확인 (정적 CONFIRMED ≠ 런타임 PASS, CLAUDE.md § Verification Discipline).

## 외부 소스 버전 pin (Codex R2 #11 해소)

- `git -C <hermes> rev-parse HEAD` = `40420a619b588049f138889add2417cb9dcb7b91`
- `git describe --tags` = `v2026.5.29-644-g40420a619`
- `hermes --version` = `Hermes Agent v0.15.1 (2026.5.29)` (plan-2 대상 런타임과 일치)

## R2.5/R3.5 추가 실증 (D1 해결 + Codex R3 blocker)

| # | 검증대상 | 결과 (file:line) | verdict |
|---|---|---|---|
| D1 | `hermes send` CLI 실재 | `hermes_cli/send_cmd.py:355` 서브파서, `main.py:12038` 등록. flags `-t/--to`,`-f/--file`,`-s/--subject`,`--json`,`-l/--list`, positional message. exit 0 ok/1 backend/2 usage | CONFIRMED |
| R3-B4 | CLI cold-start latency | 실측 `hermes --version` 0.53s, `hermes send --help` 0.47s ≪ `.mcp.json` 120s timeout | CONFIRMED (무시 가능) |
| R3-B2 | `--file` 의미 = 첨부 아님 | `send_cmd.py:401-406` `_read_message_body`: `--file PATH` = **메시지 본문을 파일에서 읽기**(stdin `-`). 첨부 아님 | CONFIRMED |
| R3-B2b | MEDIA 올바른 경로 | `send_message_tool.py:150` description "include MEDIA:<local_path> in the message"; `:261` `extract_media(message)` 가 message 에서 MEDIA: 파싱→native 첨부; `:262` `filter_media_delivery_paths` Hermes 자체 가드 | CONFIRMED |
| R3-B1 | yuanbao/plugin-live = gateway 필요 + graceful | `send_message_tool.py:_send_yuanbao` `get_active_adapter()` None→`_error("Yuanbao adapter is not running. Start the gateway...")`; plugin-live `:565` `_error("No live adapter... Is the gateway running?")` — **crash 아닌 구조화 에러 반환** | CONFIRMED |

**계약 정정 (plan v0.4 반영)**:
1. **send MEDIA**: 어댑터는 `MEDIA:<path>` 를 **message 에 임베드한 채** `hermes send`(positional/stdin)로 전달 — `--file` 사용 금지(본문 읽기 전용). C1 가드는 message 에서 추출한 MEDIA 경로를 전송 전 검증. Hermes `extract_media`+`filter_media_delivery_paths` 가 2차 가드.
2. **send 플랫폼 분기**: CLI 가 bot-token/standalone(telegram/discord/slack/signal 등) gateway-free 처리; yuanbao/plugin-live 는 gateway 미가동 시 구조화 에러 반환(B4/F2 와 동일 의존, plan-2 §1.4 일치). 어댑터는 exit 1 + 에러 surface, 새 코드 경로 불요.
3. **send stateless**: `hermes send` 는 `previous_response_id` 미지원(fire-and-forget). context 필요는 inquiry(`/v1/responses`)만 — 불변.

## E2-HTTP real-Hermes live 실행 결과 (2026-06-06)

실 Hermes API server(temp HERMES_HOME, API-server-only, 공유 .env/gateway/메시징 미접촉)를 8651에 기동 후 `tests/e2e_http_live.py` 실행:

| 시나리오 | 표면 | 결과 |
|---|---|---|
| schedule create | 실 `POST /api/jobs` | **PASS** — `job_id=6b144104b8ce`, `next_run_at=2099-01-01T00:00:00+09:00` |
| schedule status | 실 `GET /api/jobs/{id}` | **PASS** — `state=pending` (3-state 판정 정확) |
| inquiry | 실 `POST /v1/responses` | 실 Hermes **500**(temp home 모델 provider 미설정) → 어댑터 **canonical `http_5xx`** 정확 매핑(에러 경로 실검증) |

- **schedule(생성+상태)는 실 Hermes 라운드트립 전수 검증.** 어댑터 HTTP 호출/응답 파싱/3-state 로직이 실 `/api/jobs` 와 정합.
- **inquiry success-with-model 만 미검증**: 실 모델 응답은 model provider(사용자 model API key)가 설치된 API server 필요. temp 인스턴스엔 모델 미설정이라 500. 어댑터의 inquiry HTTP/에러 경로는 실 Hermes로, success 파싱은 stub(실소켓)+mock 으로 검증 완료 → 미검증은 *Hermes 가 실 모델 텍스트를 반환하는지* 1점(어댑터 아닌 환경/secret 영역).
- 정리: temp gateway 종료, temp dir 제거, 사용자 실 gateway(PID 105728) 무접촉.
