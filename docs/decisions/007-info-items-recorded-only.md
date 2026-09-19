# P0-4: info_items 는 기록만 한다 (선택지 C)

PM 결정 D-22. A-1-v2 의 대화 판정 지표는 `open_issues_count` 하나다.
`info_items` 는 출력 계약·관측에 그대로 남지만 progress 계산에 쓰지 않는다.

## 근거

- 지정 로그(A-1 4차 실행)의 유효 최종 출력에서 developer·reviewer 는 `info_items` 를 한 번도
  채우지 않았다(모두 null). null 은 `new_info_ratio` 를 unmeasured 로 만들고, stagnant 는 모든
  선택 지표 측정을 요구하므로 해당 역할 step 에서 stagnant 가 구조적으로 불가능했다.
- 선택지 A(계약에서 null 금지)는 로그 기준 11 step 계약 위반과 step 3 세션 중단,
  B(null 을 [] 로 계산)는 "모름" 을 "없음" 으로 계산해 거짓 교착 위험과 progress-v3 가 필요했다.
- C 는 계약·프롬프트 구조·계산식(progress-v2 / deadlock-v0.2)을 바꾸지 않는다. 지표 선택은
  시나리오 설정이다. 재계산 결과 : `reports/p0-4/info-items-options.json`
  (`tools/p0_4_info_items_options.py`, 저장된 P0-2 관측 입력만 변환).

## 변경

- `scenarios/A-1-v2-ambiguous-task-query.yaml` : `progress_metric.conversation: [open_issues_count]`.
  실행 기록이 없으므로 같은 시나리오 ID 에서 고쳤다. 새 실행 전 기록 `reports/p0-4/A-1-v2-preflight.json`.
- 역할 지시문 정리 : 계약에 이유 필드가 없으므로 "모르면 null 과 이유" 를 "모르면 null" 로 고쳤다.
  reviewer 에 developer 와 같은 `info_items` 문장을 넣어 세 역할을 맞췄다. 다른 문구는 그대로다.
- 기존 A-1 은 바꾸지 않는다 (`new_info_ratio` 선택 유지).

## 위험

새 정보만으로 진전하는 구간(파일·쟁점 변화 없이 정보만 쌓이는 구간)을 stagnant 로 볼 수 있다.
파일럿 C 군(보존율)에서 확인한다.
