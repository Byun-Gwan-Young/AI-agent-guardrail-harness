# 001. Silent no-op step: 정상 응답과 완료 표시가 진전을 보장하지 않음

기록일: 2026-09-15. 기존 실행 로그에 대한 사후 진단이며, 교착 정답 라벨이나 탐지 기준 변경이 아니다.

## 실측 근거

세션 `A-1-67aeab11753e41169f76116f260564f5`, 경로 `runs/A1-validation-ab2e18a9413a49929f843b43049e579a/buffered/A-1-67aeab11753e41169f76116f260564f5/`의 session.json, steps.json, summary.json을 읽었다. 원본은 수정하지 않았다.

| step | 역할 | LLM turn | 실제 응답 도구 | 실행기 기록 | 테스트 통과 |
|---|---|---|---|---|---:|
| 1 | planner | 1, 2 | read_file, read_file | completed / observed | 7/16 |
| 2 | developer | 3, 4 | read_file, read_file | completed / observed | 7/16 |
| 3 | reviewer | 5, 6 | read_file, read_file | completed / observed | 7/16 |
| 4 | planner | 7, 8 | read_file, HTTP 400 | failed / unmeasured | 7/16 |

turn 1~6은 모두 HTTP 200이었다. developer의 step 2에는 write_file 호출이 없다. step 1~3의 저장된 파일 해시가 같고 통과 수 증가도 없다. 각 step의 최종 text는 구조화 JSON이 아니라 `"""Starter implementation...`으로 시작하는 파일 원문이다. progress.state는 step 1 baseline, step 2~3 unmeasured였다. 실행기 completed/observed 표시는 유효한 구조화 출력이 확보됐다는 증거가 아니었다.

step 4의 마지막 오류는 `Failed to parse tool call arguments as JSON`이다. 이 명시적 오류와 step 1~3의 조용한 실패를 구분한다. 전체 확인된 토큰 소계는 13,467이며 오류 턴 usage가 없어 전체 토큰은 null이다. 이 소계를 총소비량으로 단정하지 않는다.

## 확인된 원인 사슬

1. 당시 step당 호출 상한은 2였다. reflect_on_tool_use=False에서 도구를 사용하면 AutoGen이 도구 결과를 chat_message.content로 반환한다.
2. 두 번째 요청도 tools와 auto를 허용하므로 두 호출 모두 파일 읽기에 사용될 수 있다. 이후 호출 슬롯이 없으면 text에는 파일 원문이 남는다.
3. 예외가 없으면 failed=False였다. 실행기는 이를 completed/observed로 기록했다.
4. 파일 원문은 최종 JSON으로 파싱되지 않는다. 파싱 실패를 삼키면서 parsed=None을 유지했다.
5. 해당 로그에서는 대화 관측과 종료 문맥이 확보되지 않아 교착 판정을 보류했다. 이 보류 자체는 정상 동작이다. 관측 누락을 정체로 바꾸면 안 된다.
6. 다른 역할의 recent_messages에도 파일 원문이 전달되는 구조였다. planner가 이를 자신의 과제로 오인했다는 설명은 **가능한 해석**이며 로그만으로 모델 내부 원인을 확정하지 않는다.

## 발표에서 주장할 수 있는 범위

“세 역할의 6개 LLM 호출이 모두 정상 HTTP 응답을 받았고 실행기는 완료로 표시했지만, 파일 읽기만 관측됐고 구현 변경·테스트 통과 증가·최종 구조화 출력은 확보되지 않았다.”

이는 API 오류율이나 프레임워크 완료 표시만으로 업무 진전을 평가하기 어렵다는 사례다. 읽기는 필요한 준비일 수 있으므로 '아무 인지 작업도 없었다'거나 '이 세 step은 확정된 교착'이라고 주장하지 않는다. silent no-op은 이 사례를 설명하는 진단명이며 새로운 detector 상태·이벤트·actual_outcome 라벨이 아니다.

## 대응과 검증

이미 반영된 수정: 마지막 호출에서 tools 제거/최종 JSON 요구, 도구 결과로 종료되면 failed/no_final_output, step당 3호출, narrative만 역할 간 공유, 인자 JSON 오류 교정, replace_in_file 추가. scenario_revision=2, runner_protocol=tool-capable-step-v3이며 이전 2호출 조건과 직접 비교하지 않는다.

인수인계 점검에서 추가로 발견한 경로: 도구 이벤트 없는 일반 text라도 잘못된 JSON이면 여전히 completed/observed가 될 수 있었다. 최종 출력은 JSON·스키마 검증에 성공해야 유효하도록 보완했다. 실패는 failed/no_final_output 및 unmeasured 관측으로 저장하며 다른 역할에는 `[구조화 출력 없음]`만 전달한다. 원문과 실제 파일·테스트 결과는 steps.json에 남긴다.

기존 정상 가짜 응답은 '도구 → 최종 JSON'으로 끝나 예산이 도구 결과에서 소진되는 경로를 검증하지 못했다. 현재는 도구 연속 호출, 최종 도구 금지, 인자 파싱 오류 회복/재실패, 역할 간 원문 차단 테스트가 있다. 추가 테스트는 일반 소스 문자열·빈 응답·불완전 JSON 세 경우를 검증한다.

progress_signal.py 및 교착 판정 기준은 이번 보완에서 수정하지 않았다. 관측하지 못한 값을 0 또는 변화 없음으로 대체하지 않는다. 실제 실험 재실행은 사용자에게 남긴다.
