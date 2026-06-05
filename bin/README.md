# bin/ — Hermes MCP 어댑터 (빌드 대상)

이 디렉토리에 `hermes-mcp-gateway` 실행 파일을 빌드한다. `.mcp.json`이 이를 stdio MCP 서버로 띄운다.
**현재 미빌드 상태** — 이 어댑터가 P1의 핵심 산출물이다. 빌드 전까지 플러그인은 로드 시 어댑터 경로 해석 실패.

## 어댑터 계약 (SoT: `docs/plan-2-plugin.md` §1)

5개 도구를 노출하고, 각각을 서로 다른 Hermes 표면으로 라우팅한다 (호스트 루트 `http://127.0.0.1:8642`, 경로별 `/v1` vs `/api` 분기):

| 도구 | Hermes 경로 | 요청 | 응답 파싱 |
|---|---|---|---|
| `hermes_inquiry` | `POST /v1/responses` (장시간은 `POST /v1/runs` 202+SSE 사전 라우팅) | `{input, previous_response_id?}` | `output[].content[].text` (type==`output_text`) |
| `hermes_schedule` | `POST /api/jobs` (cron, 캘린더 아님) | `{name≤200, schedule, prompt≤5000, deliver, repeat?}` | `{"job":{...}}` → `job.id` |
| `hermes_memo` | 어댑터 SQLite 노트 스토어 | `{category, title, body, tags[], dedupeKey}` | `note_id` |
| `hermes_notes` | 어댑터 SQLite 노트 스토어 | `{query?, category?, tags?, limit?}` | `[{note_id, ...}]` |
| `hermes_send` | `messages_send` (`hermes mcp serve`) / gateway | `{target, message}` (첨부 `MEDIA:<path>`) | 전송 상태 |

## 런타임 (권장: Python)

- Hermes와 동일 스택 → `httpx` + `mcp` SDK + 표준 `sqlite3` 재사용.
- 단일 실행 파일: PyInstaller/zipapp 패키징. 릴리스 시 SHA256 체크섬 동봉 → `scripts/install.sh`에서 검증.
- 대안: Node(`@modelcontextprotocol/sdk`) — Hermes 비의존, 단 공급망 표면 증가 시 의존성 최소.

## 핵심 구현 주의 (검토에서 확인된 함정 — docs/review-deep-research.md)

1. **schedule 발화는 gateway 필수** — `POST /api/jobs` 생성은 API server로 되지만, 발화·전달은 gateway 스케줄러(60초 tick)가 떠 있어야 함. one-shot 리마인더는 `deliver`를 채널 타깃으로 두어 전달 도착을 1차 ack로 사용.
2. **send는 API server toolset에서 제외** — `/v1/*`로 보내면 안 됨. `messages_send`(mcp serve) 또는 gateway 경로.
3. **memo는 bounded MEMORY.md 금지** — 어댑터 자체 SQLite 노트 스토어(`~/.hermes-bridge/notes.sqlite`). `dedupe_key NOT NULL UNIQUE`, 미지정 시 `sha1(canonical_json({category,title,body}))` 자동 파생, `INSERT … ON CONFLICT(dedupe_key) DO UPDATE`.
4. **inquiry는 in-flight 전환 불가** — 짧은 질의는 `/v1/responses` 동기, 풀 루프는 처음부터 `/v1/runs` async.
5. **X-Hermes-Session-Key** = Honcho 장기메모리 per-chat 스코프(MEMORY.md 아님).

## 빌드 후

```
bin/
├── hermes-mcp-gateway          # 실행 파일 (shebang 또는 컴파일 바이너리)
└── hermes-mcp-gateway.sha256   # 무결성 체크섬
```
