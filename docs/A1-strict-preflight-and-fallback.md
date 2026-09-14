# 식별자 제거·최종 프롬프트 분리 / strict 검증 준비

## 완료 범위

- 모델 출력은 narrative, open_issue_ids, info_items, completion_declared 네 필드만 포함한다. agent_id와 step_id는 출력 스키마에 없으며 현재 호출 에이전트·step으로 실행기가 부여한다. 모델이 이 필드를 추가하면 잘못된 출력으로 처리하며 값 비교·자동 교정을 하지 않는다.
- 두 목록은 unknown일 때 null을 허용한다. 누락된 필드를 빈 목록으로 만들지 않는다. 내부 관측에서는 기존 conversation 구조로 변환한다.
- 최종 호출의 시스템 메시지는 보고 지시와 스키마만으로 새로 구성한다. 이전 역할 시스템 지침·도구 목록·부분 수정 지침·도구 사용 continuation·오류 재시도 안내를 활성 지시로 재전달하지 않는다.
- 과거 사용자 문맥에서는 task, initial_issue_ids, acceptance, recent_messages만 선택한다. assistant/tool 이력은 관측 자료로 직렬화하고 실행 지시로 따르지 않도록 구분한다. 파일 내용 자체에 지시처럼 보이는 문자열이 있을 수 있지만 이를 작업 지침으로 재생하지 않는다.
- 마지막 사용자 메시지도 FINAL_ONLY 단독이며 'otherwise use a registered tool'과 결합하지 않는다. 앞선 작업용 호출은 기존 도구 지침을 사용한다.
- runner_protocol=tool-capable-step-v4-preflight, scenario_revision=3, output_contract=flat-state-v2. **이전 세 실행과 직접 비교하거나 합산해 같은 조건의 반복으로 취급하지 않는다.** 조건 파일에는 strict_support=unverified를 기록한다.
- max_steps=18, 호출 상한=3, max_tokens=1200 및 인수 suite ID는 유지한다. 판정 기준·progress 신호는 변경하지 않았다.

**아직 실행기의 최종 요청에 strict response_format을 적용하지 않았다.** 지금은 1·2번 수정과 지원 검증 스크립트만 준비했다. 사용자가 엔드포인트 검증 후 승인하면 A 실행기 연동 또는 B를 구현한다.

## 사용자가 실행할 최소 검증

프로젝트 경로: `C:\Users\관영\guardrail`. 실행기 창에 GROQ_API_KEY가 이미 설정됐다면 그대로 사용한다. 새로 설정할 경우 키 값을 명령문에 넣지 않는다.

```powershell
$probeCredential = [System.Management.Automation.PSCredential]::new('groq', (Read-Host 'GROQ API key' -AsSecureString))
$env:GROQ_API_KEY = $probeCredential.GetNetworkCredential().Password
Remove-Variable probeCredential
```

검증 명령 **한 번**:

```powershell
.\venv\Scripts\python.exe experiments/probe_strict_output.py --output-root runs/strict-probes
```

이 스크립트는 `https://api.groq.com/openai/v1/chat/completions`에 직접 **POST 1회**만 한다. SDK 재시도·프록시 재시도·리다이렉트·자동 fallback은 없다. 모델은 openai/gpt-oss-120b, temperature=0.0, reasoning_effort=low, max_tokens=256이다. seed와 tools는 보내지 않는다. response_format은 json_schema / strict:true이며 실제 사용할 네 필드 스키마를 전달한다. 이 max_tokens는 probe에만 적용되며 A-1 설정은 바꾸지 않는다. 총 입력 토큰 상한을 뜻하지 않는다.

생성 폴더 `runs/strict-probes/strict-probe-{uuid}`:

- request.json: 실제 요청 body. Authorization이나 키는 저장하지 않음.
- response.json: HTTP 상태와 응답 body. HTTP 응답 전에 연결이 실패하면 없을 수 있음.
- result.json: 검증 판정·사용량·모델·엔드포인트·UTC 시각. runner_config_changed=false.

정상 기대 content:

```json
{
  "narrative": "probe",
  "open_issue_ids": [],
  "info_items": [],
  "completion_declared": false
}
```

정상 판단: HTTP 200, finish_reason=stop, tool_calls 없음, 네 필드의 타입·필수 필드·추가 필드 금지 검증 통과. 이때 outcome=probe_passed, strict_request_accepted=true, schema_valid=true다. 실제 narrative 문구가 기대 예시와 조금 달라도 스키마 수용 시험은 통과할 수 있다. 원문으로 내용도 확인한다.

**1건 통과는 이 요청·스키마가 엔드포인트에서 수용됐다는 실행 증거다. 100% 신뢰성이나 내부 constrained decoding 자체를 증명하는 실험은 아니다.** 성공 로그를 확인한 다음 최종 호출에만 strict를 연결한다. 도구 작업 호출에는 적용하지 않는다.

| 결과 | 판별·다음 행동 |
|---|---|
| 200·스키마 정상 | 지원 확인 근거로 보존. A 연동 승인 판단 |
| response_format/json_schema/strict 또는 해당 모델의 명시적 미지원 오류 | 원문을 근거로 A 미지원 여부 확인 후 B로 전환 |
| 스키마 제약 위반 오류 | 스키마 호환성 문제일 수 있음. 모델 자체 미지원과 구분 |
| 401/403 | 인증·권한 문제. 미지원 증거 아님 |
| 429·5xx·연결/시간초과 | 환경 문제. inconclusive; 자동 재시도하지 않음 |
| finish_reason=length·refusal·200이지만 잘못된 필드 | 이 검증은 통과하지 못함. 출력 제한·거절·준수 실패를 구분해 원문 검토 |

오류는 자동으로 supported/unsupported 설정에 쓰지 않는다. 사용자가 result.json과 response.json을 확인해 후속 결정을 내린다. 이번 작업에서 실제 API 요청은 실행하지 않았다.

## B: A 미지원 시 설계만 준비

새 protocol은 예를 들어 tool-report-step-v1로 분리하고 시나리오 revision도 올린다. A/이전 실행과 섞지 않는다.

1. 앞의 최대 두 호출은 기존 작업 도구를 사용한다.
2. 마지막 호출에는 report_state만 제공한다. tool_choice는 `{"type":"function","function":{"name":"report_state"}}`로 지정한다. 자동 선택으로 계속 읽기만 하는 경로를 남기지 않는다.
3. 인자는 동일한 네 필드다. agent_id, step_id, session_id는 실행기가 부여한다. report_state는 파일을 수정하지 않고 보고 payload만 검증·기록한다.
4. 유효한 보고 **한 건** 수신은 step 종료다. 도구 이름만 맞거나 인자 검증이 실패한 호출은 완료로 인정하지 않는다. 같은 응답에 다른 도구·복수 보고가 섞이면 모호한 완료로 수용하지 않는다. 보고를 받은 뒤 추가 final JSON 호출을 만들지 않는다.
5. 보고 성공은 과제 성공이 아니다. completion_declared는 실행기가 식별한 reviewer의 보고에서만 종료 문맥에 반영한다. 과제 성공은 기존 인수 테스트·suite 유지 조건을 함께 만족해야 한다.
6. 미등록 도구·잘못된 인자는 기존 failed/unmeasured 및 같은 step 재실패 중단 정책을 유지한다. 3회 한도를 넘어 재시도하지 않는다. report_state 인자 역시 JSON이므로 실패 내성은 계속 필요하다.

현재 B 도구·종료 처리 코드는 추가하지 않았다.

## 미등록 도구 인자를 상태로 회수하는 편의 기능

**실시간 자동 복구는 지금 넣지 않는 것을 권한다.** 진단 자료로 회수할 가치는 있지만, 공급자가 거부한 생성물을 유효한 step 완료·종결 선언으로 승격하면 실패율과 관측 데이터의 정의가 달라진다. 과거 'json' 인자는 기존 중첩 state/agent_id 구조라 새 네 필드 계약과 그대로 일치하지도 않는다.

나중에 넣는다면 원래 failed 판정을 유지한 채 quarantined_report_candidate로 분리해 사람이 검토하는 오프라인 경로부터 시작한다. JSON 파싱·전체 스키마 검증을 통과한 payload만 보관하고 eval, 도구 실행, 자의적인 필드 삭제·identity 치환은 하지 않는다. candidates를 detector 입력·actual_outcome·completion_declared로 자동 반영하지 않는다. 정식 복구를 도입할 때만 별도 프로토콜·검증 테스트로 승격한다.

## 검증 결과

전체 **118개 테스트 통과**. 식별자 없는 계약/식별자 주입 거부, null 유지, 최종 지시 분리, 실제 직렬화 요청의 tools 제거, runner 부여 역할 기록, probe의 1회 요청·429 무재시도·성공/잘림/잘못된 필드 구분을 확인했다. 모든 HTTP 검증은 가짜 transport이며 실제 Groq 요청은 사용자가 실행한다.
