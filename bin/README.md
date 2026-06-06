# bin/ — Hermes MCP 어댑터

`.mcp.json` 이 이 디렉토리의 stdio MCP 서버를 띄운다. **빌드 불요(D6=B)** — wrapper 가 Hermes venv python 으로 어댑터 `.py` 를 직접 실행한다. SoT: `docs/plan-3-implementation.md` (§5.1) + `docs/plan-2-plugin.md` §1.

## 구성

```
bin/
├── hermes-mcp-gateway        # POSIX sh 런처 → Hermes venv python 으로 hermes_mcp_gateway.py 실행
├── hermes-mcp-gateway.cmd    # Windows 런처(동일 역할)
├── hermes_mcp_gateway.py     # 어댑터 본체 (5 MCP tool)
└── hermes-mcp-gateway.sha256 # 무결성 체크섬(transport/corruption — install 이 검증, D1)
```

- 런처는 `~/.hermes-bridge/env.{sh,cmd}`(install 이 기록, W4)에서 `HERMES_VENV_PY`/`HERMES_BIN` 절대경로를 읽어 PATH 미상속 환경에서도 해석한다.
- 컴파일/번들 없음 — Hermes 가 보장하는 `mcp`/`httpx`/`pydantic`(Python 3.11) 재사용. onedir PyInstaller 는 fallback(미채택 기본).

## 어댑터 계약 (5 도구)

| 도구 | Hermes 표면 | 요청 | 응답 |
|---|---|---|---|
| `hermes_inquiry` | `POST /v1/responses`(sync) / `POST /v1/runs`+`GET /v1/runs/{id}` poll(async, run_id 재폴링) | `{input, previous_response_id?, mode, run_id?}` | `output_text` 파싱(빈 출력=anomaly) |
| `hermes_schedule` | `POST /api/jobs`(생성) / `GET /api/jobs/{id}`(job_id 상태) | `{name≤200, schedule, prompt≤5000, deliver, repeat?, skills?, job_id?}` | `{"job":{...}}`→job.id / 3-state(fired/failed/delivery_failed/pending) |
| `hermes_memo` | 어댑터 SQLite(WAL) | `{category, title, body, tags[], dedupeKey?}` | `note_id` |
| `hermes_notes` | 어댑터 SQLite | `{query?, category?, tags?, limit?}` | `[{note_id, ...}]`(limit clamp) |
| `hermes_send` | **`hermes send` CLI subprocess**(argv-only, API server 아님) | `{target, message}`(첨부 `MEDIA:<path>` 임베드) | 전송 상태 / exit 0·1·2 매핑 |

## 핵심 설계 (plan-3)

1. **send = `hermes send` CLI**(D1) — Hermes Python import 없음(frozen 안전). MEDIA 는 message 임베드(Hermes `extract_media` 가 파싱, `--file` 아님). yuanbao/plugin-live 는 gateway 미가동 시 구조화 에러.
2. **schedule 발화는 gateway 필수**(§1.3) — 생성은 API server, 발화·전달은 gateway 60초 tick. 상태는 `hermes_schedule(job_id=...)` 폴링.
3. **memo = 어댑터 SQLite**(bounded MEMORY.md 금지) — `dedupe_key NOT NULL UNIQUE`, 미지정 시 `sha1(canonical_json)` 자동 파생, upsert.
4. **inquiry in-flight 전환 불가** — 짧으면 sync(`/v1/responses`), 풀 루프는 처음부터 async(`/v1/runs` poll).
5. **canonical error schema** `{error, kind, status?, details?}` — 모든 tool boundary. MEDIA 가드(C1)/UTF-8 인코딩(W3)/telemetry(O5, 옵션).

테스트: `<hermes_venv>/python -m unittest discover -s tests` (E1 로컬). 운영: `scripts/hermes_bridge_admin.py`, `docs/runbook.md`.
