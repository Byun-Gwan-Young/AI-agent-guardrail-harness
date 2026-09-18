# P0-2 오프라인 적용 범위

도구: tools/replay_preserved_observations.py.

1. 원본 로그의 모든 progress-v1/deadlock-v0.1 저장 결과를 기존 replay의 바이트 비교로 검증한다.
2. P0-1 계산 결과를 reports/p0-1/replay.json과 비교한다. 불일치 시 보존 적용 전에 중단한다.
3. 폐기된 관측의 llm_turns 중 마지막 turn만 후보로 삼는다. 실행기와 동일한
   validate_final_response 전체 조건을 검사한다. 실패 시 이전 turn으로 거슬러 올라가지 않는다.
4. 유효한 대화는 make_observation으로 구조화 관측과 추출 관측을 생성한다.
   역할은 P0-1의 요청 시스템 메시지 근거를 사용한다. 실제 런타임에서는 실행기가 역할을 넣는다.
5. 당시 수집된 산출물만 유지한다. 폐기된 step의 artifact=null을 모델 설명이나
   이후 snapshot으로 채우지 않는다. 지표별 unmeasured를 collection에 명시한다.
6. 동일한 progress-v2/deadlock-v0.2 계산기로 다시 평가한다. 누락 step도 이력에 남긴다.

새 출력은 reports/p0-2/에 보관한다. 원본 로그와 reports/p0-1/은 수정하지 않는다.
기대 복원 개수/step 목록은 도구에 하드코딩하지 않는다. 테스트만 지정 로그의 확인된 사례를 검증한다.
결과에는 원본/P0-1/P0-2 전체 판정, 최종 출력 원문 turn 연결, 실제 제출될 관측을 남긴다.

이는 저장된 입력을 다시 평가한 결과다. 실행 당시 steps.json/산출물 snapshot을
재생성한 것이 아니며 failed·오류·중단 이력을 재분류하지 않는다.
가상 판정과 실제 STOP/실측 탐지 지연은 구분하며 후자는 null/unmeasured로 둔다.
G0-5 우선순위, P0-4 null, G0-12 공유 산출물 비교 방식은 현행 그대로다.

검증 기록: reports/p0-2/tests-core.json 및 tests-final.json.
tests-core-initial.json은 신규 429 테스트의 모의 응답 소진 오류를 보존한 기록이다.
실제 proxy의 재시도에 맞춰 모의 응답을 반복 제공하고 테스트 대기만 제거한 후 재검증했다.
기존 테스트 기대값이나 제품 재시도 동작은 바꾸지 않았다.
