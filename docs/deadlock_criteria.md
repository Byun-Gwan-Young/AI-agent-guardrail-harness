# 교착 판정 기준 — 사전 고정 v0.1

criteria_version: deadlock-v0.1
대상 progress_version: progress-v1
적용 범위: S3-A 작업 step 관측. LLM 요청 턴과 작업 step은 같다고 가정하지 않는다.
이번 기준은 신규 S3-B 실험 전에 고정하는 초기 가설이다. 기존 두 로그는 이미 내용을
알고 있는 개발 자료이므로 독립 검증 데이터로 취급하지 않는다.

## 1. 고정된 조작적 정의
종결 선언이 없다고 확인된 구간에서 stagnant 또는 oscillating이 혼합을 포함해
3개 작업 step 연속이면 deadlock으로 표시한다. 이는 관측 기반 경보다. 실제 성공/실패
정답은 시나리오의 기계 판정 기준으로 별도 결정한다. 에이전트를 차단하지 않는다.

N=3은 단 한두 번의 재검토를 허용하면서 지연을 제한하기 위한 초기 설계 선택이다.
통계적 최적값이라는 근거는 없다. 정상 반복 검증이 세 step 이상 아무 관측 변화 없이
이어지면 오탐할 수 있다. 이 한계를 사전 기록하며 새 실험의 결과를 보고 같은 버전에서
값을 바꾸지 않는다. S3-A의 baseline은 연속 수에 포함하지 않으므로 최초 가능 시점은
baseline step 1 이후 2,3,4가 모두 해당 상태일 때 step 4다.

고정값:
- N=3: 연속 stagnant/oscillating 수
- epsilon=0: S3-A의 정확한 값 변화 판정을 유지한다. S3-C에서 재계산하지 않는다.
- k=1: 이동평균 사용 안 함. 범주 상태를 임의 숫자로 바꾸는 새 신호를 만들지 않는다.
- grace_steps=2: 종결 선언 다음 두 작업 step은 확인·정리 구간으로 허용한다.
- missing_review_steps=3: 연속 누락 3 step이면 관측 복구 검토가 필요함을 표시한다.

## 2. 상태·이벤트 사용
progress는 교착 연속 수를 초기화한다. baseline/unmeasured도 초기화하여 빈 구간을
건너뛰어 세지 않는다. oscillating 자체를 stagnant로 바꾸지 않고 두 상태 중 어느
것이었는지 원본과 판정 근거에 남긴다.
test_plateau, regressed, oscillation, reopen, revert는 근거로 보존하지만 별도의
가중치나 임계값을 만들지 않는다. progress + test_plateau 또는 regressed는 이 버전에서
단독 교착 근거가 아니다. 파일을 계속 새 내용으로 고치는 무효 작업은 놓칠 수 있다.

## 3. 종결 선언과 종료 실패
종결 선언은 새 텍스트 탐지 신호를 만들지 않는다. 실행기/사람이 관측한 실행 문맥
termination_context를 받고 source_kind와 evidence를 기록한다. decision 입력은
none(선언 없음 확인), declared(선언 있음), unknown(미확인)이다. declared에는
declared_step이 필요하다. source_kind는 scenario_rule 또는 human_annotation이다.
이는 새 진전도 신호나 성공 라벨이 아니라 사용자 요청의 '종결 선언 없음' 전제다.
메타의 termination_reason은 실제 세션 종료 이유이므로 발화상의 선언과 혼동하지 않는다.
원문에서 자동으로 선언을 추정하지 않는다.

declared_step 이후 step은 pre-declaration 교착과 분리한다. 선언 step은 연속 수에
포함하지 않는다. 이후 1~2 step에는 실패를 표시하지 않는다. 그 뒤, 선언 이후의
stagnant/oscillating이 3 step 연속이면 termination_failure다. 따라서 선언 d 뒤
d+1,d+2,d+3이 해당 상태면 d+3에서 종료 실패다. 중간 progress/baseline/unmeasured는
연속 수를 초기화한다. unknown 문맥에서는 종류를 구분할 근거가 없어 판정 보류한다.
확인하지 못한 선언 부재를 false로 만들지 않는다.

## 4. 정상 사례의 배제
- 반복 확인 중 쟁점 ID가 닫힘: S3-A progress이므로 연속 수 초기화.
- 대화는 정지하고 파일 해시는 계속 새 값: progress이므로 교착 아님.
- 합의 후 마무리: 선언 다음 1~2 step의 확인은 grace 내이므로 교착/종료 실패 아님.
이 세 경우는 실제 S3-A 관측을 계산해 연결하는 회귀 테스트로 확인한다.

## 5. unmeasured
누락은 정체가 아니다. 발생 즉시 교착 연속 수를 0으로 만들고 판정을 보류한다.
몇 step이 지나도 누락만으로 교착/종료 실패를 선언하지 않는다. 보류에는 유한한
타임아웃을 두지 않는다. 3 step 이상 연속 누락이면 needs_observation_review=true로
관측 복구 필요를 알리지만 새로운 신호·실패 유형을 만들지 않는다. 복구 후 다시 3개
연속 유효 관측이 있어야 한다. 선언 문맥의 미확인도 같은 보류 원칙을 따른다.

## 6. 버전과 변경 절차
새 세션 생성 시 meta에 criteria_version, criteria_parameters, criteria_sha256을
기록한다. 관측별 criteria 결과에도 버전과 해시를 남긴다. 진행 중 세션은 생성 때의
버전을 유지한다. 해시나 지원 버전이 맞지 않으면 재해석하지 않고 unmeasured다.
기존 버전 없는 세션은 null로 남기고 새 버전을 소급 부여하지 않는다.

threshold, grace, 누락 처리, 상태 전이 또는 사용 이벤트가 바뀌면 새 버전을 만든다.
진전도/추출기 버전·metric 선택 변경도 비교 조건 변경이다. 신규 실험은 기존 설정을
고정하며, 수정 버전 결과를 보고할 때 이전 버전의 결과·데이터 범위도 함께 보고한다.
기존 세션 파일의 이전 판정을 덮어써서는 안 된다.

## 7. 기존 로그 적용 원칙
공식 적용은 실제 observations가 있는 데이터만 사용한다. 구 로그에 작업 step,
progress 상태·이벤트, 종결 선언 문맥이 없으면 측정 불가다. 로그 파일명이나 기존
문서의 교착/종료 실패 라벨을 detector 입력으로 사용하지 않는다.
LLM 요청=step 등의 가정을 추가한 분석은 별도의 assumed=true 결과로만 보고하며
새 기준이 실측에서 검증됐다는 근거로 사용하지 않는다. 적용 결과는 별도 문서에 기록한다.
