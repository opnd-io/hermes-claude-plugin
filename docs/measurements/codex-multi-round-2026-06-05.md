# Codex Multi-Round 페어 측정 — plan-3 구현 계획서 (2026-06-05)

**대상** `docs/plan-3-implementation.md` (plan-2-plugin.md 구현 계획서 신규 작성)
**목표** `/goal "코덱스와 페어로 구현 계획서 수렴 0"` — 잔존 blocking 0 도달
**패턴** `/pair` multi-round adversarial (Claude draft → Codex audit → Claude verify/revise 반복)
**결과** **CONVERGED** — 5 Codex 라운드, exhaustiveness 58→92, 잔존 blocking 0.

## 라운드 궤적

| Round | 역할 | Score | 주요 산출 |
|---|---|---|---|
| R1 | Codex blind audit | 58/100 | 47 이슈, Open Dissent 5. → Track W(Windows)/O(운영) 신설, Tier 격상, A5 모순 해소, 수용기준 정의 |
| R1.5 | Claude verify (Track 0 실증) | — | 외부 Hermes 소스로 5 엔드포인트 CONFIRMED, 계약 숫자 일치, `/v1/runs` 실재 → Codex 6 finding self-reject 유도 |
| R2 | Codex adversarial | 74/100 | 25 CLOSED/16 PARTIAL/6 NOT-CLOSED. 신규 blocking 3(mcp serve 중첩/PyInstaller/frozen-import) |
| R2.5 | Claude runtime | — | `send_message_tool` 결합(agent.redact/tools.registry) 확인 → frozen-import 회피 근거 |
| R3 | Codex final exhaustiveness | 83/100 | 잔존 2 blocking(R3-B1 yuanbao 분기, R3-B2 MEDIA `--file` 오용) + STILL-OPEN 4 |
| R3.5 | Claude runtime | — | `hermes send` CLI 실증(`send_cmd.py`), `--file`=본문읽기 실증, yuanbao graceful 에러, cold-start 0.5s 실측, HEAD pin |
| R4 | Codex convergence verify | 88/100 | 잔존 2 — 정합성 텍스트(E2 stale `--file`, #43 과잉 주장)만 |
| R5 | Codex final convergence | **92/100** | **잔존 blocking 0 → CONVERGED** (v1.0). 2건 closure 확인, 새 모순 없음, MEDIA 전 문서 일관 |
| R6 | opnd-codex 위임패턴 페어 (Workflow: 4채굴→매핑→Codex 적대) | — | 36 패턴 채굴 → adopt 6(이미 반영)/adapt 9/reject 16. Codex cargo-cult 양방향 검증 + 신규 HIGH 2 발굴(empty-success, verbatim/no-fabrication) |
| R6-final | Codex 통합 수렴 확인 | **96/100** | **잔존 blocking 0 유지 → CONVERGED** (v1.1). B7/B8/C10/O5 상보·충돌 0, reject 목록 정확 |
| R7 | D6 빌드도구 결정 (Codex 상의, 사용자 위임) | — | **B(Hermes venv 재사용) primary / onedir PyInstaller fallback / zipapp 개발용**. Codex+Claude 독립 일치. needs-user 0, Open Dissent 0 (v1.2) |
| R8 | 홀리스틱 페어검토 (Codex 전체 통독, 사용자 "플랜 페어 검토") | 8/7/7/8 | **GO-WITH-CONDITIONS** — 증분 7라운드가 놓친 글로벌 6건(track순서/notes DDL 미배정/폴링 surface/`.mcp.json` 계약/error schema/E1 FP8). 6건 v1.3 적용 |
| R8-final | 조건충족 확인 | **9/10** | 5/6 CLOSED, 1 잔존(§2↔§13 A5 순서)→v1.4 수정 → **GO 무조건**. 구현 착수 ready |

## 핵심 수렴 결정

| 결정 | 결과 | 근거 |
|---|---|---|
| **D1 send 아키텍처** | `hermes send` CLI(argv-only) | direct-import/중첩 MCP serve/frozen-import 3 blocker 동시 해소. `send_cmd.py:355` 실증 |
| MEDIA 전달 | message 에 `MEDIA:<path>` 임베드(`--file` 아님) | `--file`=본문읽기, `extract_media`가 첨부 처리(`send_message_tool.py:261`) |
| yuanbao/plugin-live | gateway 미가동 시 CLI 구조화 에러 surface(정직 scoping) | `_send_yuanbao` get_active_adapter None→error. plan-2 §1.4 일치 |
| A5 에러핸들링 | 전 tool boundary try/except→구조화 에러 의무 | MCP=interceptor 경계 자체, crash=stdio 끊김 |
| 빌드도구(D6) | **미결 — needs-user** | zipapp(경량/system Python) vs PyInstaller(.exe 자기완결/AV·냉시작 위험) |

## Open Dissent 최종

- D1~D5: 해소(D1 RESOLVED, D2-D5 Codex 채택)
- **D6: needs-user 유지** — 빌드도구 선택(zipapp 기본 권장, PyInstaller 는 Windows AV/냉시작/WAL PoC 통과 시)

## 잔존 (계획서 결함 아님)

- **needs-user 1**: D6 빌드도구 선택
- **external-gated**: E2 런타임 e2e(실 Hermes + gateway 환경 필요), F1-F4(admin/user_env/anthropic 의존)

## R6 — opnd-codex 위임패턴 통합 (v1.0→v1.1)

**계기**: "다른 에이전트에 위임"이라는 공통 substrate 관점에서 성숙한 레퍼런스(opnd-codex)의 패턴을 hermes-bridge 에 참고.

- **공통 substrate**: 좁은 어댑터 경계 위임 + 정직한 실패보고 + bounded wait + 식별자 pass-through + 사용자 가시 복구안내.
- **표면 차이**: opnd-codex = stateful Codex 런타임(thread/turn/approval/broker/job-state) 브리지 → 무거움. hermes-bridge = thin HTTP+CLI+SQLite 위임. **무게 베끼면 cargo-cult**.
- **결과**: adopt 6(위임 정체성 패턴 — 이미 plan-3 반영 확인)/adapt 9(경량 보강)/reject 16(background job 생태계 전체 — 적용 대상 부재).
- **신규 HIGH 2 (진짜 갭)**: B7 empty-success anomaly(200+빈 출력 → 빈 성공 위장 금지), C10 verbatim/no-fabrication(Hermes 에러 성공 재작성 금지 + load-bearing 필드 보존).
- **§18 reject 목록 문서화** = 미래 cargo-cult 방지(왜 안 넣는지 명시). R-2 Codex CLI dual-registration 도 reject(범위 외) + 포터빌리티 사실 노트(`codex mcp add` 로 zero-code 등록 가능).

## 비용/효율

- Codex 호출 6회(R1~R5 + R6-final) + Workflow 1회(R6: 4채굴+매핑+Codex 적대), Claude runtime verify 3회(R1.5/R2.5/R3.5) 병행
- Claude runtime 실증이 Codex sandbox 한계(외부 소스 read, 런타임 측정) 보완 — R1.5가 Codex R1 과장 finding 6건 self-reject 유도(adversarial 균형)
- R6 의 핵심 가치 = "이미 반영됨 확인"(대부분) + 신규 HIGH 2 + **reject 문서화** — 패턴을 무분별 추가하지 않고 적용성 판정으로 plan 비대화 방지
