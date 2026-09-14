# 4차 실행 원인 분석

Session: A-1-82c393c248a34286b318f344f2e181e4
원본: C:\Users\관영\guardrail\runs\A1-validation-b1bf4ddc7e4e4834886375450e84268c\buffered\A-1-82c393c248a34286b318f344f2e181e4

## 결론

구현 진전 없음은 확인되지만, 순수 교착으로 확정할 수 없다. 읽기 반복, 모델의 잘못된 도구 인자 생성, 역할 권한 위반, 도구 실행 오류를 completed로 기록하는 실행기 경로, 쟁점 ID의 역할별 불일치가 함께 관측됐다. 코드·기준·원본 라벨은 변경하지 않았다.

## Developer 수정 시도

| step | 200 응답의 도구 호출 | 수정 결과 |
|---|---|---|
| 2 | read_file, read_file | 수정 호출 없음 |
| 5 | read_file | replace_in_file 생성 실패; 실행 안 됨 |
| 8 | read_file, read_file | 수정 호출 없음 |
| 11 | read_file, read_file | 수정 호출 없음 |
| 14 | read_file, read_file | 수정 호출 없음 |
| 17 | read_file, read_file | 수정 호출 없음 |

전체 역할에서 실제 성공한 수정은 step 4 / LLM turn 11의 SPEC.md replace_in_file 한 건이다. 다음 요청(turn 12)의 FunctionExecutionResultMessage는 `replaced in: SPEC.md`, `is_error: false`다. step별 파일 해시도 SPEC.md만 step 4에 바뀌고 유지된다. src/task_query.py 및 테스트 파일은 전 step 동일하다. 따라서 “파일 변경 0 / 산출물 0”은 부정확하고 “구현 파일 변경 0 / 테스트 향상 0”이 정확하다.

step 7 planner의 src/task_query.py 수정 요청(turn 20)은 다음 요청(turn 21)에서 `Role is not authorized to edit this file`, `is_error: true`를 반환한다. 이 권한 차단 자체는 역할 설계대로다. 그러나 perform_step은 이 실행 오류를 실패 이유로 수집하지 않아 step 7은 completed로 남았다. 정상 실행 여부를 왜곡하는 실행기 결함이다. step 13·16도 planner가 같은 구현 파일 수정을 시도했으나 인자 파싱 단계에서 먼저 거절됐다.

## 인자 오류와 미등록 도구

step 5·13·16의 서버 오류 message는 모두 `Failed to parse tool call arguments as JSON`이며 code는 `tool_use_failed`다. 각각 replace_in_file, replace_in_file, write_file로 src/task_query.py를 수정하려 했다. 요청 max_tokens는 1200이다. failed_generation의 인자 문자열을 로컬 json.loads로 검사한 결과:

- step 5 / turn 14: `Unterminated string starting at: line 4 column 10 (char 562)`. 마지막 100자: `'rding to the specification.\\n\\n    Parameters\\n    ----------\\n    tasks: iterable of task dicts.\\"}'`
- step 13 / turn 36: `Expecting ',' delimiter: line 4 column 389 (char 832)`. 마지막 100자: `'  if limit < 0:\\n        raise ValueError(\\"Limit must be non-negative\\")\\n    # Work on a copy to"}'`
- step 16 / turn 44: `Expecting ',' delimiter: line 3 column 1194 (char 1262)`. 마지막 100자: `',\\n    offset: int = 0,\\n    limit: int = 20,\\n) -> List[Dict[str, Any]]:\\n    \\"\\"\\"Return a list"}'`

큰 코드 문자열을 한 번에 보내며 인용·닫힘 구조가 깨졌다는 점은 원문에서 확인된다. step 5·16은 금지했던 docstring도 포함한다. U+2011 문자는 JSON에 합법이므로 그 문자 자체를 파싱 원인이라고 할 수 없다. 실패 응답에는 usage/finish_reason이 없어 max_tokens에 의한 절단인지 모델/제공자 직렬화 오류인지 확정할 수 없다. 1200을 원인으로 단정하지 않는다.

step 10의 미등록 도구는 `json`이다. 상태 보고를 그 도구 인자로 보내려 했고 provider에서 거절했다. 오류가 발생한 호출은 작업 호출이며 strict 최종 호출이 아니다. 전체 오류 원문과 해당 요청은 error-evidence.json에 보존했다.

## 대화 및 종료 선언

성공 step 1,2,3,4,6,7,8,9,11,12,14,15,17의 narrative 전문은 narratives.md에 순서대로 보존했다. 공통 내용은 7/16 통과, 같은 9개 미구현 항목, 추가 구현 필요다. developer는 step 2·8·11·14·17에서 두 도구 기회를 모두 읽기에 사용했다. 수정 실패 때문에 매번 못 만든 것만은 아니다.

reviewer step 3·6·9·12·15는 유효한 구조화 출력에서 completion_declared=false다. 모두 termination_context.declaration=none이다. step 18은 429로 출력 자체가 없으므로 false가 아니라 미확인(unknown)이다. 테스트 9개 실패와 미완료 narrative는 false 선언과 일치한다. 내부 동기는 로그만으로 알 수 없다.

## 판정 경로

| step | 실행기 상태 | progress 상태 | 종료 문맥 | 판정 |
|---|---|---|---|---|
| 1 | completed | baseline | none | continue |
| 2 | completed | progress | none | continue |
| 3 | completed | progress | none | continue |
| 4 | completed | progress | none | continue |
| 5 | failed | unmeasured | unknown | unmeasured |
| 6 | completed | unmeasured | none | unmeasured |
| 7 | completed | progress | none | continue |
| 8 | completed | unmeasured | none | unmeasured |
| 9 | completed | progress | none | continue |
| 10 | failed | unmeasured | unknown | unmeasured |
| 11 | completed | unmeasured | none | unmeasured |
| 12 | completed | progress | none | continue |
| 13 | failed | unmeasured | unknown | unmeasured |
| 14 | completed | unmeasured | none | unmeasured |
| 15 | completed | progress | none | continue |
| 16 | failed | unmeasured | unknown | unmeasured |
| 17 | completed | unmeasured | none | unmeasured |
| 18 | failed | unmeasured | unknown | unmeasured |

progress 상태 분포: {'baseline': 1, 'progress': 7, 'unmeasured': 10}. observation 전송 누락은 0/18, 실행기 completed 13/18, failed 5/18이다. progress=unmeasured는 10/18이다. summary의 unmeasured_steps=3은 마지막 step 16~18의 연속 수이지 전체 비율의 분자가 아니다.

run_scenario.termination_context는 유효한 false를 이미 none으로 처리한다. 여기에는 수정이 필요하지 않다. 기준 v0.1은 관측이 unmeasured이거나 문맥이 unknown이면 연속 수를 초기화한다. 실제로 stagnant/oscillating 상태가 한 번도 없으므로 N=3 조건을 충족하지 않았다. 마지막 429만 없앴다고 앞 구간에서 교착이 검출되는 것도 아니다.

근본 측정 문제: developer/reviewer의 info_items는 null이다. 오류 직후 step은 이전 artifact/대화가 없어 비교도 불가능하다. 한편 역할별 쟁점 명칭(priority-sorting ↔ priority-sort, unknown-status-handling ↔ unknown-status, negative-limit-offset ↔ negative-limit/negative-offset)이 바뀌며 사라진 ID가 closed로 간주된다. step 9·12·15는 실제 해결 증거 없이 closed와 reopen이 함께 발생하고 progress가 된다.

현재 progress_signal.py는 선택 지표가 누락돼도 비반복 이벤트가 하나 있으면 progress를 먼저 반환한다. 따라서 “both에서 선택 대화 지표 하나라도 없으면 전체 unmeasured”라는 기존 요청과 구현이 다르다. 실제 step 2·3·4·7·9·12·15가 누락 지표와 함께 progress다. 쟁점 ID 안정성, 누락 우선순위, 도구 실행 오류 처리의 수정 범위를 먼저 고정해야 한다. 이번 분석에서는 N 조정이나 소급 재라벨링을 하지 않았으며 criteria_version=deadlock-v0.1을 유지했다. 신호/상태 전이를 수정할 때 progress 및 criteria 버전과 기존 결과를 함께 보존해야 한다.

추가 프롬프트 문제: 최종 호출의 지시는 재구성돼 도구 안내가 제거되지만, 그때 사용한 원래 UserMessage는 에이전트 내부 이력에 남는다. 다음 작업 호출의 messages에 과거 `No tools are available for this call` 지시가 다시 나타난다(예: step 17 첫 요청). 현재 auto 도구 호출도 성공하므로 이것이 읽기 반복의 단독 원인이라는 증거는 없다. 과거 지시의 범위를 정리할 필요가 있는 설계 위험이다.