---
name: hermes-delegate-write
description: 외부로 나가는 부작용 작업(메시지 발송·cron 예약 생성)을 Hermes에 위임한다. 발송/예약은 사용자 승인(Ask) 후에만. 단순 조회·문의·메모는 hermes-delegate를 쓴다.
---

## 범위 (write / side-effect — Ask)

부작용이 외부에 도달하는 두 도구만 다룬다:

- 메시지 발송 → `hermes_send(target, message)`. `target='platform:id'`(예 `slack:#biz`, `telegram:-100…`). 첨부는 message에 `MEDIA:<path>` 임베드(어댑터가 경로 denylist/크기/secret/symlink 가드 후 `hermes send`로 전달).
- cron 예약 **생성** → `hermes_schedule(name, schedule, prompt, deliver, repeat?, skills?)`. 발화는 gateway 상시 가동 전제(§1.3). 상태조회(`job_id` 지정)는 read 라 본 skill 밖에서도 가능.

## 부작용 정책 (권한 — plan-3 C2)

- `hermes_send` / `hermes_schedule`(생성) = **Ask** 권한. 사용자 승인 없이 자동 호출 금지.
- side-effect가 강한 조직은 본 skill에 **`disable-model-invocation`**(모델 자동 호출 차단, 수동 호출만)을 적용한다.
- 권한은 Claude Code 호스트의 permission 시스템이 강제한다(어댑터는 in-process 승인 대기를 두지 않음). 예시 `.claude/settings.json`:

```jsonc
{
  "permissions": {
    "ask": [
      "mcp__hermes-bridge__hermes_send",
      "mcp__hermes-bridge__hermes_schedule"
    ],
    "allow": [
      "mcp__hermes-bridge__hermes_inquiry",
      "mcp__hermes-bridge__hermes_notes",
      "mcp__hermes-bridge__hermes_memo"
    ]
  }
}
```

## 응답 규칙

- 호출 **전**: 발송/예약 대상·내용을 한 줄 요약 + 승인 요청.
- 호출 **후**: hermes-delegate의 verbatim/no-fabrication 규칙 동일 적용 — 어댑터가 `{"error","kind"}`(예: `gateway_down`, `media`, `usage`)를 반환하면 **"보냈다"고 보고 금지**. `job_id`/전송상태 등 load-bearing 필드 보존. 최종 전달은 deliver 채널 도착으로만 확인됨을 명시.
