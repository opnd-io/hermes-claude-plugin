# hermes-claude-plugin (plugin name: `hermes-bridge`)

Claude Code 플러그인 — **비개발 업무(메시징 · 일정 · 메모 · 노트)를 Hermes Agent에 단방향 위임**한다.
Claude는 개발 메모리/실행에 집중하고, Hermes는 일정·메시지·회의록 등 비개발 메모리/실행을 맡는다.

> **상태: 기획 수렴 완료(planning converged) · 어댑터 미빌드.**
> 설계는 Codex(GPT-5.x) + Claude 4라운드 교차검토로 **잔존 0건 수렴**. 다음 작업은 `bin/hermes-mcp-gateway` 어댑터 구현(P1).
> 어댑터 빌드 전까지 플러그인은 로드 불가(설계 단계).

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
bin/                         # 어댑터 (빌드 대상, bin/README.md = 빌드 spec)
skills/hermes-delegate/      # dev/non-dev 라우팅 skill
scripts/install.sh           # 전제 점검 (순수, curl|sh 금지)
docs/
  ├── plan-2-plugin.md             # ★ 이 repo의 빌드 SoT (어댑터 계약 §1)
  ├── plan-1-harness-integration.md # 자매안(하네스 직접 연동) — §1은 plan-2와 byte-identical
  ├── review-deep-research.md       # 원 기획서 상세 검토(결함 + 근거)
  └── deep-research-source.md       # 원 deep-research 기획서(출처)
HANDOFF.md                   # 다음 세션 인계 가이드
```

## 빠른 시작 (다음 세션)

1. `docs/plan-2-plugin.md` §1(어댑터 계약) + `bin/README.md`를 읽는다.
2. `bin/hermes-mcp-gateway` 어댑터 구현(Python 권장, 5도구 → API 매핑).
3. `bash scripts/install.sh`로 전제 점검 → Hermes API server + gateway 기동 확인.
4. 로컬 `.mcp.json` 또는 user scope로 등록 후 5도구 동작 검증.
5. 자세한 로드맵·테스트·함정은 **HANDOFF.md** 참조.

## 라이선스 / 보안

- 비밀값(API 키)은 번들 미포함 — 사용자 env(`HERMES_API_KEY`)로만 주입. `.gitignore`가 `.env`/`*.key` 차단.
- 보안 모델은 "allowlist + 컨테이너 격리"가 boundary이며, env filtering/스크리너는 boundary 아님(`docs/review-deep-research.md` 참조).
