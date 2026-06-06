# 3안 — hermes-bridge 구현 계획서 (plan-2 실현)

**버전** v1.4 (Codex R1~R8 + R8-final — **GO 무조건**, 구현 착수 ready, quality 9/10) · **기준일** 2026-06-05 · **대상** plan-2-plugin.md 구현
**SoT** 계약은 `docs/plan-2-plugin.md` §1. 본 문서는 §2 로드맵(P1~P4)을 **실행 단위**로 분해.
**출발점** `plan2-implementability` 매트릭스(148 req) + Codex R1(58)→R2(74) 적대적 검증 + 외부 Hermes 소스 실증.
**추적** 요구사항 갱신 = §17 매트릭스. 엔드포인트/CLI 실증 = `docs/measurements/hermes-endpoint-verification-2026-06-05.md`.

> **핵심 원칙**: plan-2 "전부"는 우리 단독 완결 불가(`fully_implementable_by_us=false`). **코드 산출물은 거의 전부 작성 가능하나, 통과 기준 다수가 외부 종속(admin / user_env / Hermes deploy / anthropic harness)에 막힘**. 본 계획서는 (1) 우리가 코딩할 영역(Track 0/A/W/B/C/D/E/O/FP)과 (2) 외부 종속을 코드로 *해결*하지 않고 *감지·진단·가이드·폴백*으로 처리(Track F)을 분리. F 의 감지·진단은 코드, 해결만 외부.

> **현재 어댑터 상태 (Codex R2 #47 — 오해 방지)**: `bin/hermes_mcp_gateway.py`(untracked WIP)는 **본 계획 이전 baseline**으로 **v0.3 비준수**다 — direct send import(A3 변경 대상), A5 wrapper 없음, WAL 없음, stdout 인코딩 미설정, MEDIA 가드 없음, limit clamp 없음. WIP 는 Track A *부분* 통과일 뿐, B/C/FP 미구현.

---

## 0. 범위·비범위·전제

**범위**: plan-2 §1 계약 미구현 갭 + §2 P1~P4 산출물 중 우리가 작성 가능한 코드/문서/테스트.

**비범위 (plan-2 §0)**: Hermes 코어 수정, 원격 HTTPS, Claude API connector, 캘린더 SaaS. **추가**: Track F 외부 종속의 코드적 *우회*(감지·안내까지만).

**플랫폼 전제**: 1차 **Windows 11 (KR, cp949)**. 런처 wrapper `hermes-mcp-gateway`(sh) + `.cmd`(Win) → Hermes venv python(D6=B), 설치 bash + **PowerShell** 양쪽. cp949↔UTF-8 주의 — 특히 `hermes send` **subprocess 자식 출력 디코드**(메모리 `windows-subprocess-cp949-utf8-decode-crash`).

---

## 1. 수렴 진행 (요약 — 전체 로그 §16)

- R1(Codex blind): 47 이슈, 58/100. R2(adversarial): 25 CLOSED/16 PARTIAL/6 NOT-CLOSED, **74/100**.
- **Track 0/2.5 실증 해소**: 5 엔드포인트 CONFIRMED, 계약 숫자 일치, `/v1/runs` 실재→B1 진행, **`hermes send` CLI 실재 확인→D1 해결**. Codex 가 R1 과장 finding 6건 self-reject.
- **D1 해결**: send = **`hermes send` CLI(argv-only)** — direct-import/중첩 MCP/frozen-import 3 blocker 동시 해소.
- R3(final): **83/100**, 2 blocking closable-gap(R3-B1 yuanbao 분기 정직성, R3-B2 MEDIA `--file` 오용) + STILL-OPEN(#11/#33/#35/#43). 둘 다 needs-user 아닌 코드/계획 수정.
- **R3.5(Claude runtime)+v0.4 반영**: `--file`=본문읽기(첨부 아님) 실증→MEDIA 는 message 임베드(`extract_media`)로 정정(R3-B2), yuanbao=gateway 미가동 시 CLI 가 이미 구조화 에러 반환→정직 scoping(R3-B1), cold-start 0.5s≪120s 실측(R3-B4), 외부 Hermes HEAD pin 캡처(#11). → **잔존 blocking 0, needs-user 1(D6)**.

---

## 2. 트랙 구조 (Tier + Effort)

| Track | 제목 | Tier | Effort | 의존 |
|---|---|---|---|---|
| **0** | 엔드포인트/CLI 검증 (정적 완료 / 런타임→E2) | HIGH | S | 완료 |
| **A** | 어댑터 동작화 (loadable artifact gate) | HIGH | M | 0 |
| **W** | Windows/cross-platform 런처·설치·인코딩 | HIGH | M | A |
| **B** | §1 계약 미구현 표면 | HIGH | L | 0,A |
| **C** | 안전·보안 (MEDIA=HIGH, subprocess 보안=HIGH) | HIGH/MED | M | A |
| **FP** | 실패 경로 처리 (failure-path-first) | HIGH | M | A,B,C |
| **D** | 패키징·무결성 (체크섬=HIGH, 릴리스=MED) | HIGH/MED | M | A |
| **E** | 테스트 (로컬+e2e+CI gate) | HIGH | L | A,B,C,FP,D |
| **O** | P4 운영 | MEDIUM | M | A,D |
| **F** | 외부 종속 (감지=코드/해결=외부) | MEDIUM | M | 병렬 |

> **Loadable-artifact HIGH gate (R8 순서 확정)**: 실행 가능한 순서 = **A1/A3/A5(어댑터 코드: wrapper·send CLI·에러핸들링 — 상호 동일 단계, W/D 비의존) → W1/W3/W4(런처·인코딩·venv 캡처) → A2/D1(체크섬 생성·검증) → A4(PoC, external-gated)**. A5 는 어댑터 .py 코드라 A1/A3 와 묶여 W/D 보다 먼저. A4 는 Track A 명목 소속이나 W/D 선행 필요 → W/D 완료 후 마지막. **§13 그래프와 동일 순서**.

---

## 3. Track 0 — 엔드포인트/CLI 검증 (HIGH, S) — **정적 완료**

> 상태: 정적 소스 검증 DONE (measurements 파일). **런타임 존재(실 200/202/SSE/send dry-run)는 E2 이관** (정적 CONFIRMED ≠ 런타임 PASS).

**외부 소스 access (R2 #11)**: `C:/Users/tgkim/AppData/Local/hermes/hermes-agent` read-only. **버전 pin 의무**: 검증 시 `git -C <hermes> rev-parse HEAD` 캡처를 measurements 에 기록(현재 "권장"→"의무" 격상). INCONCLUSIVE → 의존 Track 보류 + 통보.

| # | 표면 | anchor | verdict |
|---|---|---|---|
| 0.1 | `/v1/responses` output_text | `api_server.py:2288,2166,143,173` | CONFIRMED |
| 0.2 | `POST /api/jobs`→`{"job":...}` | `api_server.py:3147` | CONFIRMED |
| 0.3 | `GET /api/jobs/{id}` 폴링필드 | `cron/jobs.py:695-698` | CONFIRMED |
| 0.4 | `/v1/runs`(202)+SSE | `api_server.py:1130-1134,3486` | CONFIRMED |
| 0.5 | **`hermes send` CLI (D1 경로)** | `hermes_cli/send_cmd.py:355`, `main.py:12038`; exit 0/1/2; `-t/--to`,`-f/--file`,`-s/--subject`,`--json`,`-l/--list`, positional message | CONFIRMED |
| 0.5b | `send_message_tool`/`_send_to_platform` (CLI 내부) | `tools/send_message_tool.py:158,573`; `mcp_serve.py:757` 도 동일 위임 | CONFIRMED |
| 0.5c | **`--file`=본문읽기(첨부 아님)**; MEDIA 는 message 임베드 | `send_cmd.py:401-406` `_read_message_body`; `send_message_tool.py:150,261` `extract_media`+`:262` `filter_media_delivery_paths` | CONFIRMED |
| 0.5d | **yuanbao/plugin-live=gateway 필요, graceful 에러** | `send_message_tool.py` `_send_yuanbao` `get_active_adapter()` None→구조화 에러; plugin-live `:565` 동일 | CONFIRMED |
| 0.5e | CLI cold-start 실측 | `hermes --version` 0.53s / `hermes send --help` 0.47s ≪ 120s | CONFIRMED |
| — | name≤200/prompt≤5000 (백엔드 400 강제) | `api_server.py:3061-62,3120-29` | CONFIRMED, 계약일치 |
| — | 외부 Hermes 버전 pin | HEAD `40420a61`, `v2026.5.29-644`, v0.15.1 | CONFIRMED |

**런타임 검증 (→E2)**: 실 200/202 응답, SSE delta/done 실수신, `hermes send` dry-run(자격증명 필요).

---

## 4. Track A — 어댑터 동작화 (HIGH, M)

| # | 작업 | 근거 | 구체 커맨드/산출물 | 수용 기준 |
|---|---|---|---|---|
| A1 | **런처 wrapper (D6 결정=B: Hermes venv 재사용)** | R099, D6 | `bin/hermes-mcp-gateway`(POSIX sh) + `bin/hermes-mcp-gateway.cmd`(Win) = `<hermes_venv>/python "${CLAUDE_PLUGIN_ROOT}/bin/hermes_mcp_gateway.py" "$@"`. venv python 은 install 캡처(W4) 또는 `hermes` 바이너리 위치에서 파생. 번들/컴파일 0 — Hermes 가 mcp/httpx/pydantic 제공(검증: Python 3.11.15 + pydantic_core cp311 .pyd) | wrapper 가 Hermes venv python 으로 어댑터 기동, `--help` 동작 |
| A2 | SHA256 | R101 | `sha256sum bin/hermes-mcp-gateway* > bin/hermes-mcp-gateway.sha256` | 체크섬 파일 |
| A3 | **send = `hermes send` CLI (D1 해결)** | R025, R2 #17-19,35, R3-B1/B2/B4 | `subprocess.run([HERMES_BIN,"send","--to",target,"--json","--",message], shell=False, capture_output=True, encoding="utf-8", errors="replace", timeout=…)` → exit 0 ok/1 backend/2 usage 매핑. `HERMES_BIN`=절대경로(install 시 `command -v hermes` 캡처). **MEDIA: message 에 `MEDIA:<path>` 임베드한 채 positional 전달(`--file` 미사용 — 본문읽기 전용); Hermes `extract_media` 가 파싱**(R3-B2). **yuanbao/plugin-live: gateway 미가동 시 CLI 가 exit 1+구조화 에러 반환→그대로 surface(B4/F2 동일 의존, 새 경로 불요, R3-B1)**. cold-start 0.5s≪120s(R3-B4) | Hermes 미설치/실패 시 crash 대신 구조화 에러; **direct import 제거**(frozen 안전); bot-token standalone gateway-free, plugin-live 는 정직한 gateway-required 에러 |
| A4 | CLAUDE_PLUGIN_ROOT PoC (external-gated, →F4) | R092 | 실 Claude Code 설치 → `claude mcp list`+tool list | `hermes-bridge`+5도구 노출 |
| A5 | 에러 핸들링 — **전 tool boundary** 공통 `tool_error()` | R2 #7,20,21 | HTTP/`raise_for_status`/`r.json()`/sqlite/subprocess/timeout 전부 → **canonical schema(R8)** | 모든 실패 경로서 stdio crash 0 |

> **A5 확정**: MCP 어댑터는 interceptor 부재 + crash=stdio 끊김. **모든 tool boundary try/except→구조화 에러 의무**(단건/다단계 무관). CLAUDE.md "단건 try/catch 금지"는 interceptor 환경 전제라 비적용.
>
> **Canonical 결과 schema (R8 — A5/B7/C10/O5/FP 통일)**: 실패=`{"error": <msg>, "kind": <slug>, "status"?: <state>, "details"?: {…}}`. anomaly(B7)도 `error`+`kind` 포함(`{"error":"no output_text","kind":"empty_output","status":"empty"}`). O5 telemetry 의 `error_kind` 필드 = 본 `kind` 와 동일 vocabulary 재사용. `kind` slug 집합: `http_5xx`/`http_4xx`/`timeout`/`bad_json`/`empty_output`/`sqlite`/`subprocess`/`import`/`venv_drift`/`auth_missing`/`gateway_down`.

---

## 5. Track W — Windows/cross-platform (HIGH, M)

| # | 작업 | 수용 기준 |
|---|---|---|
| W1 | 런처 OS 분기 (`hermes-mcp-gateway` sh / `.cmd` Win) — Hermes venv python 해석 + CLAUDE_PLUGIN_ROOT. `.mcp.json` command 가 OS별 wrapper 해석 | 양 OS 에서 wrapper→venv python→어댑터 기동 |
| W4 | **install 시 Hermes venv 경로 + 버전 sanity 캡처 (D6=B 리스크 완화, Codex)**: `hermes` 위치→venv python 파생, `mcp`/`pydantic` import 가능 + 버전 호환 점검 후 wrapper 에 경로 기록. Hermes 재설치/업글로 경로 변동 시 wrapper 가 **명확한 재설정 메시지**(FP8) | venv 경로 저장 + 버전 호환 확인, 변동 시 graceful 안내 |
| W2 | `scripts/install.ps1` (bash 와 기능 동등 5단계 + strong-key 점검 §14) | Windows 5단계 동작 |
| W3 | **인코딩 전수 (R2 #15 확대)**: ① 어댑터 자체 stdout/stderr UTF-8(`PYTHONIOENCODING=utf-8` in `.mcp.json env` + `sys.stdout.reconfigure`) ② **`hermes send` 자식 stdout/stderr 캡처 `encoding="utf-8", errors="replace"`**(절대 raise 안 함) ③ install 로그 ④ notes 파일 read(BOM=`utf-8-sig`) | 한글 깨짐/디코드 crash 0 (cp949 메모리) |

### 5.1 최종 `.mcp.json` / wrapper 계약 (R8 — A1·A3·W3·C4 조립점, single SoT)

D6=B 확정 후 산출물 계약을 한곳에 고정 (A1/W3/C4 가 가리키던 값 통합):

```jsonc
// .mcp.json (번들) — command 는 bare `python3`(C2 실측 해결), env 화이트리스트(C4)
{ "mcpServers": { "hermes-bridge": {
  "command": "python3",                                              // Claude Code 가 bare name 해석(검증 ✓)
  "args": ["${CLAUDE_PLUGIN_ROOT}/bin/hermes_mcp_gateway.py", "--api-base", "http://127.0.0.1:8642"],
  "env": {
    "HERMES_API_KEY": "${HERMES_API_KEY}",       // 사용자 env (C7, 번들 미포함)
    "PYTHONIOENCODING": "utf-8"                   // W3 인코딩
  },                                              // ❌ HERMES_AGENT_PATH 없음 (D1=CLI 라 obsolete)
  "timeout": 120000
} } }
```

- **C2 해결(실 launcher 검증)**: `claude mcp list` 로 실측 — extensionless 절대경로 `${CLAUDE_PLUGIN_ROOT}/bin/hermes-mcp-gateway` → **✗ Failed**, 절대 `.cmd` → **✗ Failed**, **bare `python3`/`py` + adapter.py → ✓ Connected**. Claude Code(cross-spawn) 는 Windows 에서 interpreter+args(bare name PATHEXT)만 exec. ∴ command=`python3`(POSIX 표준 + Windows 해석 ✓).
- **self-bootstrap(어댑터 `_ensure_runtime`)**: bare `python3`(deps 없을 수 있음)로 시작돼도 `mcp`/`httpx` 부재 시 `HERMES_VENV_PY`(install 기록) 또는 `hermes` 옆 python 으로 **`os.execv` 재실행**(C2 + D6=B 통합). venv python 으로 launch 시 즉시 통과.
- **wrapper**(`bin/hermes-mcp-gateway` sh/cmd)는 manual 실행/디버깅 + install env 캡처용 보조(.mcp.json 은 직접 python3 호출). `HERMES_AGENT_PATH` 제거 확정(R8, D1=CLI).

---

## 6. Track B — §1 계약 미구현 표면 (HIGH, L)

| # | 작업 | 근거 | 수용 기준 |
|---|---|---|---|
| B1 | `/v1/runs`(202) async + **client-pull 폴링**(GET /v1/runs/{id}) + 명시 `mode: sync\|async`(+`run_id` 재폴링) | R055 (0.4 CONFIRMED) | mode=async 시 POST /v1/runs→GET /v1/runs/{id} 폴링(completed/failed/cancelled/**waiting_for_approval→needs_approval**/timeout→run_id). **mode 검증: sync\|async 외 usage error(silent drop 금지)**. **SoT 정정(M3, 구현 시 확인)**: `/v1/runs/{id}/events` SSE 는 `tool.started/completed` 등 lifecycle 이벤트이지 `output_text.delta/done`(그건 `/v1/responses` SSE)이 아님 — async 최종 출력은 run status 의 terminal `output` 필드. ∴ **client-pull 폴링이 정확**(단방향 §1.5 원칙 정합). plan-2 §1.5 의 "SSE delta/done" 문구는 본 항목으로 정정 |
| B2 | schedule 폴링 `GET /api/jobs/{id}` 3-state(발화/미발화/실패) + **사용자 surface(R8 결정)**: 신규 도구 없이 **`hermes_schedule` 에 선택 `job_id` 파라미터** 추가 — `job_id` 미지정=생성(기존), 지정=상태조회 모드(5-tool cap 유지). §18 의 status/result *커맨드* reject 와 무모순(별 도구 아닌 기존 도구 파라미터) | R044/R057-059 | job_id 지정 시 last_run_at=발화/last_error=실패/next_run 경과+미설정=미발화(gateway 경고) 반환 |
| B3 | `X-Hermes-Session-Key` 헤더(선택) | R010/R031 | 헤더 전달, 미설정 무영향 |
| B4 | schedule body `skills?` 필드 | R015 | 포함/미지정 생략 |
| B5 | 입력검증 **축소**(백엔드 name/prompt/repeat 400 강제) | R016/18 + Track0 | 백엔드 400 surface + 어댑터 `limit` clamp 만 |
| B6 | inquiry `previous_response_id` pass-through 유지(이미 구현 R009) — send 는 stateless(`hermes send` context 미지원) | R3-B3 | inquiry context 체이닝 동작, send 는 fire-and-forget 명시 |
| B7 | **empty-success anomaly (Codex 위임패턴 R6 신규 HIGH)**: `/v1/responses` 200 인데 `output_text` 빈 경우 — 현재 `_extract_output_text`(L127-133)는 빈 문자열 silent 반환. → canonical schema `{"error":"no output_text","kind":"empty_output","status":"empty"}`(A5) 로 **구조화 이상** 보고(빈 성공 위장 금지). schedule `job.id` None / send 빈 결과도 동일 | DP-R6 | 200+빈출력 → blank success 아닌 anomaly. "empty-success is failure" 원칙 |
| B8 | **bounded output (Codex R6 MEDIUM)**: notes 응답 `limit` clamp(이미 B5) + SSE/inquiry 누적 출력 상한(unbounded MCP 응답 방지) | DP-R6 | SSE 누적 cap, notes 응답 크기 상한 |
| B9 | **노트 스토어 구현 (R8 신규 — plan-2 §1.2 OPEN 해소)**: `notes(id PK, category, title, body, tags json, dedupe_key NOT NULL UNIQUE, created_at)` DDL + `_derive_dedupe_key`(sha1 canonical) + `INSERT…ON CONFLICT(dedupe_key) DO UPDATE` upsert + `SELECT … category/tags LIKE/(title\|body LIKE) LIMIT` 검색. WIP 어댑터(`hermes_mcp_gateway.py:63-121`)에 초안 존재하나 §line10 baseline=noncompliant → **본 항목이 정식 구현 SoT**(WAL=C3, 권한=C5, retention=O2 와 결합) | plan-2 §1.2, R034-039 | DDL/dedupe/upsert/search 동작(E1.1 단위) |

---

## 7. Track C — 안전·보안 (MEDIA·subprocess=HIGH)

| # | 작업 | Tier | 근거 | 수용 기준 |
|---|---|---|---|---|
| C1 | **MEDIA 가드**(경로 화이트리스트+크기+secret 스캔+**심링크 재확인 §14**) — message 에서 `MEDIA:<path>` 추출→검증→통과(`--file` 아님, R3-B2). Hermes `filter_media_delivery_paths` 가 2차 가드 | HIGH | R052/128, R2 #33 | send 전 필수. path traversal/oversize/secret/TOCTOU 거부(negative test) |
| C8 | **subprocess 보안 (R2 신규 blocking)** | HIGH | R2 Part3 | `shell=False`+`HERMES_BIN` 절대경로+argv-only(문자열 조합 금지)+PATH 하이재킹 방지. message 는 `--`/stdin 으로 전달 |
| C2 | 권한 enforcement: skill 분리(`hermes-delegate-read`/`-write`)+write `disable-model-invocation`+settings 권한 메타 | MED | R120/121, R2 #6 | 신규 `skills/hermes-delegate-write/SKILL.md`. send/schedule=Ask, inquiry/notes=Allow |
| C3 | SQLite WAL + **Windows 엣지(R2 #46)**: `-wal/-shm` 사이드카 권한, OneDrive/네트워크 경로 경고, AV 잠금 폴백(WAL 실패 시 DELETE 모드 graceful). frozen 특이 엣지는 D6=B(real Python)로 primary 에선 무관 — onedir fallback 시에만 점검 | MED | R138 | 동시 write 충돌 회피(E1.2) + 보호 경로 graceful |
| C4 | MCP env strip(broad env 미상속) | MED | R127 | env 화이트리스트만 |
| C5 | notes DB 권한 `chmod 600`(POSIX)/**ACL icacls owner-only(Win, R2 #37)** | MED | R2 #37 | owner-only |
| C6 | deps 상한 pin (`mcp>=1.0,<2`,`httpx>=0.27,<1`) | MED | R2 #38 | requirements 상한 |
| C7 | API key 누출 완화: install curl `-H` inline→`--config`/stdin | MED | R2 #36 | ps/proc 비노출 |
| C9 | 바이너리 무결성/출처: **우리 어댑터** 체크섬+서명/출처 문서(D1). **외부 `hermes` 바이너리는 사용자 자신의 신뢰 설치**(Hermes 를 쓰는 것 자체가 신뢰 전제)라 우리 무결성 범위 밖 — 단 절대경로 해석으로 PATH 하이재킹만 방어(C8). 설치 후 위변조 감지 노트(R3-B5) | MED | R2 Part3, R3-B5 | 우리 산출물 서명 정책 + 외부 바이너리 trust 경계 명시 |
| C10 | **verbatim/no-fabrication 계약 (Codex 위임패턴 R6 HIGH)**: `skills/hermes-delegate` 응답규칙에 — (1) Hermes CLI/API 의 구조화 에러를 **성공으로 재작성 금지**(silent 성공 오보고 금지, send gateway-required 에러 포함) (2) **load-bearing 필드 보존**(job_id/next_run_at/response_id) — Claude 가 요약 시 누락 금지 (3) 어댑터는 결과를 재해석/요약 안 함(verbatim, inquiry `_extract_output_text` 외) | HIGH | DP-R6, opnd-codex codex-rescue.md:47,54-60 | 실패→성공 위장 0, 식별자 필드 보존 |

---

## 8. Track FP — 실패 경로 처리 (HIGH, M) — **신규 (Codex R2: failure-path-first)**

> CLAUDE.md "failure path first". 각 경로 = 구조화 에러 + 복구 안내 (silent 금지).

| # | 실패 경로 | 처리 |
|---|---|---|
| FP1 | 불완전 SSE 프레임 / half-open HTTP 스트림 | 부분수신 명시 + 재요청 안내, timeout |
| FP2 | `hermes send` 자식 hang | `timeout=` + kill, exit 매핑 |
| FP3 | `hermes` 실행파일 부재 / `mcp` extra 미설치 | 구조화 에러 + 설치 안내 |
| FP4 | notes DB 손상 / 구스키마 마이그레이션 / 디스크 풀 | 감지 + 마이그레이션 또는 안전 실패 |
| FP5 | MEDIA 심링크 스왑(스캔 후 TOCTOU) | open 후 `fstat`/실경로 재확인(§14) |
| FP6 | 자식 non-UTF8 stdout/stderr | `errors="replace"`(W3) |
| FP7 | HERMES_API_KEY 미설정/회전 중 401 | 구조화 에러 + 재설정 안내(매 호출 env read 라 회전 친화) |
| FP8 | **Hermes venv python 경로 부재/변동 (D6=B 결정 리스크)**: Hermes 재설치/업글로 venv 이동, 또는 mcp/pydantic 버전 비호환 | wrapper 가 명확한 재설정 메시지(`install 재실행`) — silent 실패 금지. install(W4)이 경로+버전 캡처 |

---

## 9. Track D — 패키징·무결성 (체크섬=HIGH)

| # | 작업 | Tier | 근거 | 수용 기준 |
|---|---|---|---|---|
| D1 | install SHA256 검증(TODO→실행, bash+ps1) | HIGH | R102/109 | 불일치 시 중단+실패 테스트(E) |
| D2 | semver 릴리스 워크플로 | MED | R070 | version bump 규약 |
| D3 | `/reload-plugins` 워크플로+재시작 fallback | MED | R071 | 절차 문서 |
| D4 | 빌드/체크섬 CI gate | MED | R2 #24 | 빌드/체크섬 실패 시 CI fail |
| D5 | managed allowlist recheck = **release gate** | MED | R2 #28 | 배포 전 `gh issue view 32882 32883` |
| D6 | **빌드도구 RESOLVED (R7 Codex 상의)**: **B) Hermes venv 재사용**(A1 wrapper) primary — Hermes 가 어차피 필수 + 호환 Python/deps 보유라 PyInstaller self-contained 가치 redundant + AV 비용 회피. **fallback: PyInstaller `--onedir`**(서명 전제 없는 portable, onefile 아님 — 플러그인은 폴더배포라 AV/냉시작 ↓). zipapp 은 개발/복구용만 | MED→done | R2 Part3, R7 | B wrapper 동작 + onedir fallback 문서 |

---

## 10. Track E — 테스트 (HIGH, L)

> E1(로컬)/E2(실백엔드)/E3(CI) 분리. PASS = § Verification Discipline 4단계 통과 후.

**E1 로컬**: notes 검색/dedupe/upsert(B9, R141) · WAL 동시성+보호경로 폴백(R138) · cron `{"job":...}` 파싱 mock(R140) · 입력검증 경계(B5) · **MEDIA negative(path traversal/secret/oversize/심링크 TOCTOU)** · 권한/env strip negative · A5 에러 wrapper(canonical schema — HTTP/json/sqlite/subprocess 실패 주입) · **FP1-8 각 경로(FP8 venv drift 포함)** · **`hermes send` 자식 non-UTF8 출력 디코드**

**E2 실백엔드**: 401/200 · gateway-down cron 미발화 · key 회전 · standalone vs yuanbao send(plugin-live gateway 미가동 시 구조화 에러) · MEDIA(message 임베드 `MEDIA:<path>` → native 첨부, `--file` 아님) 전송 · inquiry async /v1/runs · adapter crash · stdio reconnect(external-gated) · 클린설치(경로+SHA256) · /reload-plugins(external-gated) · 버전 업그레이드 · managed deny 폴백 · **`hermes` 부재/`mcp` extra 미설치 FP**

**E3 CI gate**: A1 wrapper(venv python 해석) + A2/D1 체크섬 + W1 런처 OS smoke + **onedir fallback 빌드 PoC(AV/냉시작 — fallback 채택 시에만)**

---

## 11. Track O — P4 운영 (MEDIUM, M)

| # | 작업 | 근거 | 수용 기준 |
|---|---|---|---|
| O1 | notes backup/import | R079 | dump/restore, dedupe 보존 |
| O2 | notes retention(TTL/카운트 cap, 설정) | R080 | 설정 가능, 기본 무제한+경고 |
| O3 | runbook(장애/재기동/key 회전/gateway 복구) | R081 | 운영 문서 |
| O4 | 배포 채널 정의 | R082 | 배포 경로 문서 |
| O5 | **위임 호출 관측성 (Codex 위임패턴 R6 — 옵션, LOW)**: best-effort 단일 라인 JSONL 로그(ts/tool/outcome/error_kind/duration_ms + 비동기 종결 correlation 용 schedule `job_id`/inquiry `response_id`; **payload·secret 제외**). `HERMES_BRIDGE_TELEMETRY_DISABLED=1` 비활성, **try/except never-throw**(non-load-bearing). opnd-codex 8-event lifecycle+traceId 풀스택은 background job 전용이라 단순화 | DP-05(유일한 실제 누락), opnd-codex telemetry.mjs | 호출 로그 1줄/호출, 실패해도 본 기능 무영향 |

> **O5 주의 (Codex)**: 새 core Track 아님 — A5(에러 kind)/FP/O 와 어휘 공유, 로깅이 절대 본 위임을 막지 않게(never-throw). opnd-codex telemetry 도 명시적 non-load-bearing.

---

## 12. Track F — 외부 종속 (MEDIUM) — 감지=코드/해결=외부

| # | 외부 종속 | 우리 영역(코드/문서) | 해결 | E2 태그 |
|---|---|---|---|---|
| F1 | managed allowlist(#32882/32883 NOT_PLANNED) | `claude mcp list` 감지(코드)+admin 요청 절차/1안 폴백(문서)+README 정직 명시 | admin | external_gated |
| F2 | gateway 상시 가동 | `hermes gateway status` 점검(install)+미발화 경고(B2) | user_env | external_gated |
| F3 | Hermes deploy-config(API/키/docker/toolset) | install 점검·진단+가이드 | user_env/배포자 | external_gated |
| F4 | harness(CLAUDE_PLUGIN_ROOT/reload/stdio reconnect) | A4 PoC+버전고정 smoke | anthropic | external_gated |

---

## 13. 의존성 그래프

```
Track 0(완료)
   ▼
A1 wrapper → A3 hermes send CLI → A5 에러핸들링
   ▼
W1 런처 / W3 인코딩 / W4 venv 경로·버전 캡처   (wrapper 가 venv python 해석하므로 A1 직후)
   ▼
A2 체크섬 생성 → D1 체크섬 검증(install)
   ▼
A4 PoC (claude mcp list, external-gated)  ← loadable-artifact gate 완료점
   ├───────────────┬───────────────┐
   ▼               ▼               ▼
 B(계약: B9 노트DDL→B1/B2/...)  C1 MEDIA+C8(send 전 필수)·C2~C10   FP(실패경로)
   └───────────────┴───────────────┴──→ E3 CI / E2 e2e
E1(로컬) ← A/B/C/FP 완료분 점진 (Track 0 비블록, 병렬)
O ← A/D 후 · F ← 전구간 병렬(감지 코드+문서)
```
> **순서 핵심(R8)**: A4(PoC)는 D1(체크섬)+W1(런처) 선행 필요 → Track A "A1빌드 후 즉시 A4"가 아니라 **W/D 완료 후** 수행. notes 는 B9(DDL/upsert/search 구현)가 B1 등 다른 B 항목·E1/O 의 선행.

---

## 14. 수용 기준 정의 (모호 제거)

- **시간표현 금지**: plan-2 "10분 설치" 참조 안 함. **deterministic 체크리스트**: ①`claude mcp list` 노출 ②5 도구 ③`/v1/models` 200 ④체크섬 일치 ⑤memo→notes roundtrip ⑥`hermes send --to <test> --json` exit 0.
- **secret scan (+TOCTOU, R2 #33)**: MEDIA 파일 (a)denylist 경로(`.env`,`.ssh`,`*.key`,`*.pem`,credential dir) (b)max size(25MB) (c)MIME 화이트리스트 (d)내용 패턴(AKIA/PEM header/`HERMES_API_KEY=`). **심링크/TOCTOU**: 경로 검증 후 `os.open(O_NOFOLLOW)` 또는 open 후 `fstat` 로 실경로 재확인(스캔한 파일=전송 파일 보장). 1 hit→거부.
- **strong key (+rotation, R2 #34)**: `HERMES_API_KEY` ≥32 hex + placeholder(`changeme`/`xxx`) 거부 + env-source 만(파일 평문 금지 안내). 회전 = 매 호출 env read(코드 친화), install 재점검.

---

## 15. §Open Dissent

| # | 영역 | Claude | Codex | 결정 |
|---|---|---|---|---|
| **D1** | send 아키텍처 | (해결) | `hermes send` CLI 권장 + R3 보강(yuanbao 분기/MEDIA 정직성) | **RESOLVED → `hermes send` CLI(D1-C)**. bot-token standalone gateway-free, yuanbao/plugin-live 는 gateway 미가동 시 구조화 에러(정직, plan-2 §1.4 일치). MEDIA 는 message 임베드(`--file` 아님). direct-import/중첩스트림/frozen-import 3 blocker 해소. R3-B1/B2 closable-gap 닫힘 |
| D2 | 에러핸들링 A5 | (합의) | 전 boundary 구조화 에러 | Codex 채택(§4) |
| D3 | async B1 drop | (합의) | silent drop 금지 | Codex 채택(0.4 CONFIRMED, §6) |
| D4 | 패키징 Tier | (합의) | HIGH | Codex 채택(loadable gate) |
| D5 | Track F 분류 | (합의) | 감지=코드 | Codex 채택(§12) |
| **D6** | 빌드도구 | (사용자 위임→해결) | B 권장(Hermes venv 재사용); onedir fallback | **RESOLVED → B (Hermes venv 재사용)**. 근거: hermes-bridge 는 Hermes 필수 + Hermes 가 호환 Python 3.11/mcp/pydantic 보유(검증) → PyInstaller self-contained 가치 redundant, AV/서명/용량 비용 회피, 신규머신 설치 마찰 최소. fallback=onedir PyInstaller(서명 무전제 portable), zipapp=개발/복구용. 리스크(venv 경로변동/버전결합)는 W4 캡처+FP8 graceful 로 완화. Codex+Claude 독립 일치(R7) |

> **needs-user 잔여: 없음**. D6 는 R7(Codex 상의)에서 B(Hermes venv 재사용)로 해결 — 사용자 위임 결정. D1 도 SoT+실증 해결. **모든 Open Dissent 해소**. 잔존은 external-gated(E2)+optional(O5)뿐.

---

## 16. 수렴 로그 (현재 라운드 = 본 섹션, 헤더 중복 금지)

- **R1(blind)**: 47 이슈, 58/100 → v0.2(Track W/O 신설, Tier 격상, A5 해소, 수용기준 정의).
- **R1.5(Claude verify)**: Track 0 실증, ~42 ACCEPT.
- **R2(adversarial)**: 25 CLOSED/16 PARTIAL/6 NOT-CLOSED, **74/100**. self-reject 6(엔드포인트/계약 과장). 신규 blocking 3(mcp serve 중첩/PyInstaller/frozen-import).
- **R2.5(Claude runtime)**: `hermes send` CLI 실증(`send_cmd.py`)→D1 해결. send_message_tool 결합(agent.redact/tools.registry) 확인→frozen-import 회피 근거.
- **v0.3 반영**: D1 해결(CLI), Track FP 신설, C8/C9 subprocess·무결성 보안, W3 인코딩 전수, NOT-CLOSED 6+PARTIAL 16 closure, 수용기준 TOCTOU/rotation.
- **R3(final exhaustiveness)**: **83/100**, 2 blocking closable-gap(R3-B1/B2)+STILL-OPEN(#11/33/35/43). 모두 needs-user 아님.
- **R3.5(Claude runtime)**: `--file`=본문읽기 실증(R3-B2), yuanbao graceful 에러 실증(R3-B1), cold-start 0.5s 실측(R3-B4), 외부 Hermes HEAD pin 캡처(#11).
- **v0.4 반영**: R3-B1(yuanbao 정직 scoping), R3-B2(MEDIA message 임베드), R3-B3(inquiry previous_response_id B6), R3-B4(cold-start 측정), R3-B5(외부 바이너리 trust 경계 C9), #11(pin), #33(MEDIA TOCTOU §14 확정), #35(D1-C supply-chain), #43(§17 reframe).
- **R4(convergence verify)**: **88/100**, 잔존 2 — 둘 다 정합성 텍스트(R3-B2 §10 E2 stale `--file` 문구, #43 과잉 "매핑 완비" 주장). MEDIA 수정 자체는 7-플랫폼 native 첨부로 정확 확인(`base.py:2860`, `send_message_tool.py:636-735`). external-gated(E2/F) 분류 올바름 재확인.
- **v0.5 반영**: §10 E2 stale `--file`→`MEDIA:<path> message 임베드` 정정, §17 #43 정직 scoping(전수 매핑 미주장).
- **R5(최종 수렴 확인)**: **92/100, 잔존 blocking 0 → CONVERGED**. 2건 closure 확인, 새 모순 없음, MEDIA 전 문서 일관, §16 로그 정확, never-seen blocker 없음.
- **v1.0 (수렴 완료)**: 궤적 58→74→83→88→92. **잔존 blocking 0**. 잔존은 needs-user 1(D6 빌드도구 zipapp vs PyInstaller — §15) + external-gated(E2 런타임 e2e — 실 Hermes 환경 필요)뿐, 계획서 자체 결함 아님. 측정: `docs/measurements/codex-multi-round-2026-06-05.md`.
- **R6(opnd-codex 위임패턴 페어)**: 36 패턴 채굴 → adopt 6(이미 반영)/adapt 9/reject 16. Codex 적대적 검증 — cargo-cult 양방향(node-path/approval/capsule/watchdog/**R-2 Codex dual-registration** reject 전환, async/status/session 은 이미 반영분으로 adapt). **신규 HIGH 2 발굴**: B7(empty-success anomaly), C10(verbatim/no-fabrication). 본질: opnd-codex↔hermes-bridge 공통 substrate=위임, 표면차=stateful 런타임 vs thin HTTP+CLI+SQLite.
- **v1.1 반영**: B7/B8/C10 신규 + O5 옵션 telemetry + §18 위임패턴 catalog(adopt 확인/adapt 보강/**reject 목록 명시=cargo-cult 방지**). 대부분 패턴은 이미 plan-3 반영 확인 — 진짜 추가가치는 신규 HIGH 2 + reject 문서화.
- **R6-final(수렴 확인)**: **96/100, 잔존 blocking 0 → CONVERGED**. B7/B8/C10/O5 기존 Track 과 상보(충돌 0), reject 목록 정확, 새 모순 없음. carve-out(D6/E2/O5)만 잔존. 궤적 58→74→83→88→92→96.
- **R7(D6 결정 — Codex 상의)**: 사용자 위임으로 D6(빌드도구) 결정. Codex+Claude 독립 일치 → **B(Hermes venv 재사용) primary / onedir PyInstaller fallback / zipapp 개발용**. 근거: mcp→pydantic_core 컴파일(.pyd cp311) 확인→zipapp self-containment 불가, Hermes 필수+호환 deps 보유→PyInstaller redundant+AV비용. 반영: A1(wrapper)/W1/W4(venv 캡처)/C3(frozen→fallback만)/FP8(venv 변동 graceful)/E3. **needs-user 0, Open Dissent 0**.
- **R8(홀리스틱 페어검토 — Codex 전체 통독)**: 증분 라운드가 놓친 글로벌 6건 발굴 → **GO-WITH-CONDITIONS(8/7/7/8)**. 수정 적용(v1.3): ①track 순서(A4 를 W/D 뒤로, §2 gate+§13 그래프 재작성) ②**B9 노트DDL 구현 트랙 신설**(plan-2 §1.2 OPEN 해소) ③schedule 폴링 surface=`hermes_schedule` job_id 파라미터(5-tool cap, §18 정합) ④**§5.1 최종 `.mcp.json`/wrapper 계약 명시**(HERMES_AGENT_PATH 제거 확정) ⑤canonical error schema(`{error,kind,status?,details?}`, A5/B7/O5 통일) ⑥E1 FP1-8. + Claude 독립 발견(§1 heading/§13 stale) 동시 수정.
- **R8-final(조건충족 확인)**: 5/6 CLOSED, 1 잔존(§2 gate↔§13 그래프 A5 순서 불일치 — §2 가 A5 를 A2/D1 뒤로 잘못 배치). **v1.4 수정**: A5 는 어댑터 코드라 A1/A3 와 동일 단계(W/D 비의존) → §2 gate 를 §13 에 맞춤(A1/A3/A5→W→A2/D1→A4) + footer 순서 동기. → **GO (무조건), quality 9/10**. 궤적 58→74→83→88→92→96→9/10.
- **구현 + code-review(R-CR, 4 agent + Codex)**: 전 Track 구현(어댑터 ~590줄, wrappers, install.sh/ps1, admin, tests). review = 2 blocking + 9 major + 23 minor. **수정**: M1/M2(MEDIA 가드를 Hermes `MEDIA_TAG_CLEANUP_RE` 정확 정렬 — scanned==transmitted), M3(async=poll 정정 ↑B1), M4(monotonic+per-req budget), M5(waiting_for_approval), M6(mode 검증), M7(last_status/last_delivery_error 3-state), M8(Windows icacls), M9(async/schedule HTTP 테스트 — E1 27→50), m1-m23 대부분. **E1 50 통과**.
- **C1 해결**: reconcile(origin 37be9cb P1 220줄 supersede) + commit + push + **PR #1 merge → main(`42f777f`)**. fresh-clone 정상.
- **C2 해결(실 launcher 검증)**: `claude mcp list` 실측 — extensionless/.cmd 절대경로 ✗, **bare `python3` + adapter.py + self-bootstrap ✓ Connected**. `.mcp.json` command=`python3`(↑§5.1) + 어댑터 `_ensure_runtime` self-bootstrap. **A4 PoC = PASS**(Windows 실런치 연결 확인).
- **E2-HTTP 잔존**: inquiry/schedule live 는 Hermes API server 활성 필요(별도).

---

## 17. 추적 (closure 참조 — R1/R2/R3 전 이슈 해소)

- **closure 맵**: §16 + 각 Track "근거" 컬럼 R### 참조. R2 NOT-CLOSED 6 → #27(§12 external_gated), #35(D1-C supply-chain), #42(§4/7/9 커맨드), #43(↓), #44(§15/16), #47(↓). R3 STILL-OPEN → #11(외부 Hermes HEAD pin `40420a61` measurements 캡처), #33(§14 TOCTOU `O_NOFOLLOW`/`fstat` 확정 + Hermes `filter_media_delivery_paths` 2차), #35(C9 trust 경계), #43(↓).
- **#43 reframe (정직 scoping)**: 148-req 매트릭스 status 갱신은 **구현-단계 산출물**(각 Track 구현 PR 의 D-level 완료 표시)이지 *계획서*의 갭이 아님. **본 §3~12 Track 표는 "단계별 커버리지 뷰"** — 각 Track 이 닫는 요구를 "근거(R###)" 컬럼으로 인용하나, **148개 전수 1:1 매핑을 본 문서가 증명한다고 주장하지 않는다**(전수 매핑 SoT 는 `plan2-implementability` 매트릭스). 전수 trace 가 필요하면 구현 PR 에서 R### 별 status 갱신 시 동시 생성.
- **148-req 매트릭스 갱신**: 구현 PR 에서 각 R### status 를 트랙 완료에 맞춰 갱신.
- **measurements 템플릿** (`docs/measurements/<topic>-<date>.md`): 필드 = 검증대상 / 명령 / 결과(file:line) / verdict(CONFIRMED·REJECTED·INCONCLUSIVE) / confidence + (외부소스 시)`git rev-parse HEAD` pin.

---

## 18. 위임 패턴 레퍼런스 (opnd-codex 대조 — R6 페어)

> **공통 substrate**: opnd-codex(Claude→Codex)와 hermes-bridge(Claude→Hermes)는 둘 다 **"좁은 어댑터 경계로 다른 에이전트에 위임"** — 정직한 실패 보고 / bounded wait / 식별자 pass-through / 사용자 가시 복구 안내가 공통 축. **표면 차이**: opnd-codex 는 stateful Codex 런타임(thread/turn/approval/broker/job-state)을 브리지해 무겁고, hermes-bridge 는 thin HTTP+CLI+SQLite 위임이라 그 무게를 가져오면 안 됨(cargo-cult). 측정: `docs/measurements/codex-multi-round-2026-06-05.md` 동류 + 본 R6 catalog.

### Adopt — 이미 plan-3 에 반영됨 (confirmed, 신규 작업 0)
| 패턴 | hermes-bridge 위치 |
|---|---|
| client-pull 비동기 관측(callback 없는 단방향) | B1(inquiry async)·B2(schedule 폴링)·§1.5 |
| 전 boundary graceful degrade | A5·FP1-7 |
| key out-of-bundle + 매-호출 env read | C7·§2 R097·FP7 |
| target/message 패스스루(분기는 Hermes) | A3·plan-2 §4.1(키워드 substring 차단 금지) |
| bounded resource guards(어댑터 timeout<호스트) | A3·B5·C1·§14·어댑터 110<120 |

### Adapt — 기존 Track 보강 (경량화 반영)
| 패턴 | 반영 |
|---|---|
| **empty-success is failure** | **B7 신규(HIGH)** — 200+빈 output_text → 구조화 anomaly |
| **verbatim/no-fabrication + load-bearing 필드 보존** | **C10 신규(HIGH)** — SKILL.md 응답규칙 |
| bounded transcript/output | B8(SSE 누적 cap, notes 응답 상한) |
| 위임 전 readiness probe + actionable nextSteps[] | F1-4·install §2.3·FP3 출력 구조화 |
| 명시적 async(silent 추론 금지) | B1 `mode: sync\|async`(이미) |
| schedule status 폴링(opnd status/result 의 진짜 analog) | B2(이미) |
| inquiry 컨텍스트 연속성(opnd thread 의 analog) | B6 `previous_response_id`(이미) |
| 관측성(telemetry) | **O5 신규(옵션 LOW)** — best-effort JSONL never-throw |

### Reject — hermes-bridge 표면엔 over-engineering (cargo-cult 방지, 미래 혼동 차단)
| 패턴 | 왜 안 넣나 (적용 대상 부재) |
|---|---|
| background/foreground 모드 + silent 승격 가드 | 5 도구 전부 동기. background job 런타임 없음 |
| status/result/cancel **별도 커맨드/도구** 3종 | enqueue→poll→retrieve job lifecycle = background 전용. schedule 상태조회는 **신규 도구 아닌 `hermes_schedule` 의 `job_id` 파라미터**(B2, 5-tool cap 유지)로 surface. cancel 은 Hermes API 영역 |
| session/thread 영속 + 7축 fingerprint 무효화 | Hermes 가 response_id SoT. 어댑터 측 레지스트리 불필요(B6 pass-through만) |
| approval pending-record + approve/deny + bounded wait | 승인은 호스트 permission(C2 Ask)이 처리. 어댑터 in-process 승인 대기 없음 |
| node-path 다단 fallback | Python MCP + W1/W2/C8 절대경로가 이미 등가 커버(Node 해석 아님) |
| turn-watchdog(stateful turn 스트림 보호) | HTTP/subprocess/SSE timeout(FP1/FP2)으로 충분 |
| secret-safe capsule(Codex 컨텍스트 파일) | 진짜 리스크는 MEDIA exfil → C1 이 커버 |
| SessionStart/End job reaper + Stop review gate + broker(영속연결) + process-tree kill + subcommand router | detached worker/job/broker = 적용 대상 부재 |
| **Codex CLI dual-registration (R-2)** | W1/A4/F4 중복 + 제품경계 흐림 + 2nd consumer 범위 외. **단 사실 노트**: 어댑터는 순수 stdio MCP 라 `codex mcp add hermes-bridge -- /abs/gateway` 로 **추가 코드 0 로 등록 가능**(포터빌리티) — 별도 consumer 가 in-scope 되면 그때 Track 신설 |

---
*v1.4 — Codex R1~R7 수렴 + R8 홀리스틱 페어검토 + R8-final(조건충족) → **GO (무조건)**. 잔존 blocking 0, needs-user 0, Open Dissent 0, quality 9/10. plan-2 §1.2 notes DDL OPEN→B9 해소. 잔존 carve-out: external-gated(E2 런타임 e2e — 실 Hermes 환경), optional(O5 telemetry). **구현 착수 ready — 순서: A1/A3/A5(어댑터 코드) → W1/W3/W4 → A2/D1 → A4(PoC) → B9 노트DDL → B/C/FP → E.** 런타임 검증 1건(blocking 아님): W1 의 Windows extensionless command→.cmd 해석(A4 PoC 에서 실측).*
