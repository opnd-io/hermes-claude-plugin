# hermes-claude-plugin (plugin name: `hermes-bridge`)

Claude Code 플러그인 — **비개발 업무(메시징 · 일정 · 메모 · 노트)를 Hermes Agent에 단방향 위임**한다.
Claude는 개발 메모리/실행에 집중하고, Hermes는 일정·메시지·회의록 등 비개발 메모리/실행을 맡는다.

> **상태: 구현 완료 · 설치 가능.**
> 어댑터(`bin/hermes_mcp_gateway.py`, 5도구) 빌드 + 단위 50/50 + 실 Hermes e2e 검증 완료.
> `.claude-plugin/marketplace.json` 으로 user scope 설치 가능(`claude plugin marketplace add` + `install`).
> Windows+VSCode 확장/sandbox 호환 근본 수정 반영(notes DB temp fallback / `.mcp.json` env 상속 /
> `harden_perms` additive grant / `busy_timeout`) — 함정·우회 상세는 `docs/runbook.md` §7.

> 참고: GitHub repo 이름은 `hermes-claude-plugin`, **플러그인/ MCP 서버 내부 이름은 `hermes-bridge`**(`.claude-plugin/plugin.json`). MCP 서버명을 colon 없는 `hermes-bridge`로 둔 것은 enterprise managed allowlist 제약(#32883) 회피 목적 — `docs/plan-2-plugin.md` §3.5.

## 동작 개요

```
사용자 → Claude Code → (hermes-delegate skill: dev/non-dev 분류)
                         └─ 비개발 → hermes-bridge MCP 어댑터(stdio)
                                       ├─ hermes_inquiry → POST /v1/responses
                                       ├─ hermes_schedule → POST /api/jobs (cron, gateway 발화)
                                       ├─ hermes_memo/notes → 어댑터 SQLite 노트 스토어
                                       └─ hermes_send → messages_send / gateway (MEDIA 첨부)
```

4개 서로 다른 Hermes 표면을 5개 정제 도구로 노출 → Claude는 "이 작업이 비개발인가?"만 판단.

## 구조

```
.claude-plugin/plugin.json   # 플러그인 manifest (name: hermes-bridge)
.mcp.json                    # 번들 MCP — bin/hermes-mcp-gateway 가리킴
bin/                         # 어댑터 hermes_mcp_gateway.py (5도구, 구현됨) + wrapper/.sha256
skills/hermes-delegate/      # dev/non-dev 라우팅 skill
scripts/install.sh           # 전제 점검 (순수, curl|sh 금지)
docs/
  ├── plan-2-plugin.md             # ★ 이 repo의 빌드 SoT (어댑터 계약 §1)
  ├── plan-1-harness-integration.md # 자매안(하네스 직접 연동) — §1은 plan-2와 byte-identical
  ├── review-deep-research.md       # 원 기획서 상세 검토(결함 + 근거)
  └── deep-research-source.md       # 원 deep-research 기획서(출처)
HANDOFF.md                   # 다음 세션 인계 가이드
```

## 설치 / 사용

1. Hermes Agent 설치 + API server 활성 (`~/.hermes/.env`: `API_SERVER_ENABLED=true`, 강한 `API_SERVER_KEY`).
2. `export HERMES_API_KEY=<강한키>` (≥32자, placeholder 금지 — §14).
3. 전제 점검: `bash scripts/install.sh` (Windows: `pwsh scripts/install.ps1`) → venv 캡처 + 6단계 점검.
4. 플러그인 등록: `claude plugin marketplace add <repo-path>` → `claude plugin install hermes-bridge@hermes-claude-plugin`.
5. `claude mcp list` 에 `hermes-bridge` + 5도구 노출 확인. **Windows+VSCode 환경의 함정/우회는 `docs/runbook.md` §7 필독.**
6. 운영(백업/보존/장애)·계약 상세는 `docs/runbook.md`, 설계 SoT 는 `docs/plan-2-plugin.md`/`plan-3-implementation.md`.

## 라이선스 / 보안

- 비밀값(API 키)은 번들 미포함 — 사용자 env(`HERMES_API_KEY`)로만 주입. `.gitignore`가 `.env`/`*.key` 차단.
- 보안 모델은 "allowlist + 컨테이너 격리"가 boundary이며, env filtering/스크리너는 boundary 아님(`docs/review-deep-research.md` 참조).
