# 실행기 결함 후보: 회복된 narrative의 역할 간 전달 누락

상태: 기록만 함. 이번 P0-2에서 전달 경로는 수정하지 않는다.

기준 커밋 b86f4f8의 experiments/run_scenario.py:310은 failed step의 parse_output을
생략하며, :324의 history.append는 parsed가 없으면 `[구조화 출력 없음]`을 넣는다.
유효한 최종 보고까지 회복했더라도 앞선 오류 때문에 failed가 유지되면 이 경로를 탄다.

현재도 run_scenario.py의 `if not outcome['failed']`와 history.append는 유지된다.
다음 역할의 context는 `recent_messages: history[cursors[index]:]`를 사용하며,
step_execution.py의 final_messages도 recent_messages를 최종 요청의 사실 정보에 포함한다.
따라서 다른 역할은 회복 보고의 새 쟁점 설명·진행 내용을 이 전달 경로로 받지 못한다.
동일 설명/확인 요청을 반복할 수 있는 정보 누락 경로는 존재한다.

다만 공유 workspace와 acceptance, 각 역할 내부 문맥은 별도로 존재한다.
실제 반복이나 교착의 원인이라고 확정할 수 없다.
반복 유발 여부의 실측: {"value": null, "status": "unmeasured"}.
신규 실행기 모의 테스트는 관측에 narrative가 보존되면서 다음 역할에 placeholder가
전달되는 동작을 확인한다. 이는 실제 세션에서 반복을 유발했다는 검증이 아니다.

## 해결 (2026-09-20, G0-13 / D-15)

`tool-capable-step-v7-issue-ids`(output-contract-v2, 독립 수집 정책) 에서 수정했다.
실패 step 이라도 P0-2 제출 조건을 만족한 검증된 최종 보고(최종 요청 HTTP 원문 검증 + v2 계약 통과)가
있으면 다른 역할의 `recent_messages` 에 그 narrative 를 전달한다. 검증된 보고가 없거나 어휘 위반
(D-17, 계약 위반이라 원문 검증이 invalid) 이면 지금처럼 `[구조화 출력 없음]` 을 전달한다.
v7 로 수행한 실제 실행이 없으므로 프로토콜 버전은 올리지 않았다. v1 계약·v5·v6 경로는 그대로다.
steps.json 의 `shared_narrative_source`(`parsed` / `verified_final_report` / `placeholder`) 로
어느 경로로 전달했는지 남긴다(v2 에서만). 결정 : `docs/decisions/009-verified-narrative-sharing.md`.
반복 유발 여부의 실측은 여전히 `unmeasured` 다 (G0-8 에서 관찰).
