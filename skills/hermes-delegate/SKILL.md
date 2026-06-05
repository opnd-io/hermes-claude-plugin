---
name: hermes-delegate
description: 일정·메시징·비개발 업무기록·외부 문의는 Hermes에 위임한다. 코드 작성/테스트/디버깅/리팩터링/PR 작업에는 사용하지 않는다.
---

## 역할 경계

- **Claude**: 개발 메모리·코드 컨텍스트(코드 작성/수정/테스트/빌드/디버깅/PR).
- **Hermes**: 비개발 업무 메모리·실행(일정·메시지·회의록·외부 문의).
- 위임은 **단방향**(Claude → Hermes). Hermes는 Claude를 다시 호출하지 않는다.

## 호출 규칙

- 비개발 문의 → `hermes_inquiry`
- 회의·반복 알림(cron, gateway 상시 전제) → `hermes_schedule`
- 메모 저장 → `hermes_memo`, 메모 조회/검색 → `hermes_notes`
- 메시지 발송 → `hermes_send`
- **코드 수정·테스트·빌드·배포 절차 자체는 Hermes에 넘기지 않는다.**

> 어댑터 도구의 표면/API 매핑은 `docs/plan-2-plugin.md` §1(어댑터 계약)을 SoT로 따른다.

## 응답 규칙

- 호출 **전**: 저장/전송될 정보를 한 줄로 요약.
- 호출 **후**: 처리 결과·대상·시각·실패 여부를 구조화해 보고. 단, 보고는 **동기 ack 한정**이며 cron 발화/메시지 최종 전달은 폴링(`GET /api/jobs/{id}` last_status) 또는 deliver 채널 도착으로만 확인됨을 명시한다.

## 부작용 정책 (권한)

- `hermes_send` / `hermes_schedule`(쓰기) = **Ask** 권한.
- `hermes_inquiry` / `hermes_notes` / read = Allow.
- side-effect가 강한 조직은 이 skill을 둘로 분리해 `send`/`schedule-write`만 `disable-model-invocation`(수동 호출)으로 둔다.
