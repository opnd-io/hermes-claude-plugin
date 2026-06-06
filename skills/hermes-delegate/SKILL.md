---
name: hermes-delegate
description: 일정·메시징·비개발 업무기록·외부 문의는 Hermes에 위임한다. 코드 작성/테스트/디버깅/리팩터링/PR 작업에는 사용하지 않는다. (조회·문의·메모 = 본 skill / 발송·예약 = hermes-delegate-write)
---

## 역할 경계

- **Claude**: 개발 메모리·코드 컨텍스트(코드 작성/수정/테스트/빌드/디버깅/PR).
- **Hermes**: 비개발 업무 메모리·실행(일정·메시지·회의록·외부 문의).
- 위임은 **단방향**(Claude → Hermes). Hermes는 Claude를 다시 호출하지 않는다.

## 호출 규칙 (read/low-risk — Allow)

- 비개발 문의 → `hermes_inquiry(input, mode="sync")`. 풀 에이전트 루프 예상 시 `mode="async"`(처음부터 선택, in-flight 전환 불가), 진행 중 재폴링은 `hermes_inquiry(run_id=...)`. 컨텍스트 체이닝은 `previous_response_id`(sync).
- 메모 저장 → `hermes_memo`(어댑터 로컬 SQLite, 저부작용), 메모 조회/검색 → `hermes_notes`.
- **발송·예약**(`hermes_send`/`hermes_schedule`)은 부작용이 커 별도 skill `hermes-delegate-write`에서 다룬다.
- **코드 수정·테스트·빌드·배포 절차 자체는 Hermes에 넘기지 않는다.**

> 어댑터 도구의 표면/API 매핑은 `docs/plan-2-plugin.md` §1 + `docs/plan-3-implementation.md`를 SoT로 따른다.

## 응답 규칙 (verbatim / no-fabrication — plan-3 C10)

- 호출 **전**: 저장/전송될 정보를 한 줄로 요약.
- 호출 **후**: 어댑터의 구조화 결과를 **그대로** 보고한다. 다음을 지킨다:
  1. **실패를 성공으로 재작성 금지**. 어댑터가 `{"error","kind",...}`(canonical schema)를 반환하면 "처리됨"이라 보고하지 말고 실패와 `kind`를 그대로 전한다. `kind="empty_output"`(200인데 빈 출력)은 **성공 아님** — anomaly로 보고.
  2. **load-bearing 필드 보존**: `job_id` / `next_run_at` / `response_id` / `run_id` 를 요약하며 누락하지 않는다(후속 폴링·체이닝에 필요).
  3. 어댑터가 파싱한 것 외 결과를 임의 요약/재해석하지 않는다.
- 보고는 **동기 ack 한정**. cron 발화/메시지 최종 전달은 폴링(`hermes_schedule(job_id=...)`) 또는 deliver 채널 도착으로만 확인됨을 명시.
