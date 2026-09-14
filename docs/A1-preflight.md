# A-1 단계별 실행 점검표

확정 조건: 검증 온도 0.0 × 2회, 측정 온도 0.3 × 3회, max_steps 18, step당 최대 LLM 호출 2회, max_tokens 1200. 남은 시나리오 규모는 A-1 실측 후 결정한다. 이 문서를 준비하면서 실제 시나리오나 외부 API를 실행하지 않았다.

## 이번 변경과 비교 해석

`context_buffer_messages: 12`를 A-1 YAML 및 JSON 스키마에 추가했다. 에이전트마다 별도의 BufferedChatCompletionContext를 생성한다. `--no-context-buffer`는 무제한 문맥으로 전환하며, `--context-buffer-messages N`은 명시적 덮어쓰기다. 최종 적용값을 conditions.json과 프록시 meta/request_params에 기록한다. YAML의 온도 0.0은 유지하고 측정 시 CLI로 0.3을 지정한다.

**메시지 수를 제한하며 토큰 수의 절대 상한을 보장하지 않는다.** 현재 AutoGen 0.5.7은 최근 최대 12개의 문맥 메시지를 모델에 노출한다. 시스템 메시지·도구 정의는 별도이며 메시지 하나가 길어질 수도 있다. 내부 저장 리스트 자체의 메모리 크기를 제한하는 기능도 아니다. 따라서 이전 8,000 입력 토큰 가정은 여전히 강제되는 토큰 한도가 아니다. 긴 발화·도구 결과까지 포함한 엄밀한 토큰 한도는 별도 작업이 필요하다.

이는 **실험 실행기의 비용 통제 설정**이며, 2학기의 컨텍스트 압축·개입 기술이나 탐지기 개선으로 보고하지 않는다. 탐지 기준 버전은 변경하지 않았다. 성공률·쟁점 유지에 미치는 영향은 미지수다.

이번 두 검증은 버퍼 적용 1회와 미적용 1회다. 같은 온도·seed 요청값을 사용해도 **동일 조건의 반복 실험이 아니므로 결정성 검증으로 해석하지 않는다. 두 출력이 같더라도 결정성을 증명하지 않는다.** 입력량 차이는 에이전트 행동 차이도 반영하므로 버퍼 효과의 인과 추정값으로 단정하지 않는다. 비교 그래프는 호출별 prompt_tokens를 보여주며 CSV의 agent·step_id로 역할과 호출 수를 함께 확인한다.

## 1. 실행 전

- [ ] 두 PowerShell 창의 작업 폴더를 `C:\Users\관영\guardrail`로 지정한다.
- [ ] 변경된 실행기·프록시를 사용하기 위해 프록시를 재시작한다. 기존 대화가 있다면 먼저 정상 종료 여부를 확인한다.
- [ ] 가상환경 및 CLI 확인: `.\venv\Scripts\python.exe experiments/run_scenario.py --help`. 버퍼/seed-probe 옵션이 보여야 한다.
- [ ] YAML은 max_steps 18, max_llm_calls_per_step 2, max_tokens 1200, context_buffer_messages 12, seed_support unverified, seed null인지 확인한다. fixture와 인수 조건은 변경하지 않는다.
- [ ] `guardrail.yaml`은 log.truncate null, criteria_version deadlock-v0.1이며 모델의 seed_supported가 검증 전 true로 설정되지 않았는지 확인한다.

프록시 창에서 기동:

```powershell
.\venv\Scripts\python.exe -m uvicorn proxy:app --host 127.0.0.1 --port 8000 --log-level info
```

실행기 창에서 상태 확인(업스트림 실시간 호출 없음):

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz | ConvertTo-Json
```

기대값은 status `ok`, uptime 0 이상의 수, active_sessions 0 이상의 정수다. 기존 미종료 로그가 있으면 active_sessions가 0이 아닐 수 있다. 재시작 직후 upstream_reachable 및 upstream_checked_at은 null이 정상이며, policy_version도 현재 설정상 null이다. HTTP 성공과 status ok는 **로컬 프록시 기동만** 확인하며 업스트림 연결 성공을 뜻하지 않는다. degraded나 연결 거부면 실험을 시작하지 않는다.

실행기 창에서 키 설정(명령·출력에 키 문자열을 적지 않음):

```powershell
$taskCredential = [System.Management.Automation.PSCredential]::new('groq', (Read-Host 'GROQ API key' -AsSecureString))
$env:GROQ_API_KEY = $taskCredential.GetNetworkCredential().Password
Remove-Variable taskCredential
$env:GUARDRAIL_PROXY_URL = 'http://127.0.0.1:8000'
```

키를 echo하거나 env 전체를 덤프하지 않는다. 실행기가 Authorization으로 프록시에 전달하므로 프록시 창에 키를 복사할 필요는 없다. 완료 후 실행기 창에서 `Remove-Item Env:GROQ_API_KEY`로 제거한다.

## 2. 검증 두 번: 사용자가 순서대로 실행

검증 seed 요청값은 **42를 제안·명시**한다. 이 값은 검증 probe이며 지원이 확인된 실험 seed로 기록하지 않는다. 두 번 모두 같은 probe 값을 사용한다. seed_support는 unverified 그대로 유지한다.

실행기 창에서 비교용 새 폴더를 만든다. 아래 블록은 준비만 하며 이후 명령은 각각 수동으로 실행한다.

```powershell
$taskBatch = Join-Path (Join-Path (Get-Location) 'runs') ('A1-validation-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskBatch | Out-Null
```

버퍼 적용 1회:

```powershell
.\venv\Scripts\python.exe experiments/run_scenario.py scenarios/A-1-ambiguous-task-query.yaml --temperature 0.0 --context-buffer-messages 12 --seed-probe 42 --run-index 1 --output-root (Join-Path $taskBatch 'buffered')
```

첫 실행의 결과·오류를 확인한 뒤 버퍼 미적용 1회:

```powershell
.\venv\Scripts\python.exe experiments/run_scenario.py scenarios/A-1-ambiguous-task-query.yaml --temperature 0.0 --no-context-buffer --seed-probe 42 --run-index 2 --output-root (Join-Path $taskBatch 'unbuffered')
```

seed가 원인으로 명시된 오류가 나면 그대로 두 번째 실행을 강행하지 않는다. 아래 seed 확인 절차를 따른다. 지원되지 않는 probe는 두 조건 모두 동일하게 제거한 새 비교 쌍으로 다시 시작한다.

## 3. 실행 중 관찰·중단 신호

- [ ] 시작 시 출력되는 session_id와 run_directory를 확인한다. step마다 agent, prompt_tokens_per_call, prompt_tokens_sum이 출력된다. 값이 null이면 사용량 관측 누락이며 0이 아니다.
- [ ] 동일 step이 **관측 재전송** 때문에 4회 이내 반복되는 것은 허용된다. 새 LLM 작업이 같은 step으로 계속 재실행되거나 step별 호출 2회·전체 36회·18 step을 넘으면 Ctrl+C로 중단한다. 관측 제출 실패는 실행기가 자동 중단한다.
- [ ] 입력 토큰이 예산 가정 8,000/호출을 넘거나 최근 같은 역할 호출 대비 급증하면 수동 중단 후 크기 원인을 확인한다. 8,000은 비용 점검선으로 제안한 값이며 코드의 강제 한도나 교착 기준이 아니다. 미적용 실행의 증가 자체는 관측 대상이다.
- [ ] 토큰 사용량 null이 지속되거나 관측 누락, suite ID 변경, 401/403, seed 관련 400, 429 재시도 소진, 프록시 저장 오류가 발생하면 추가 실험을 중지한다. fixture_unchanged=false면 원본을 점검한다.
- [ ] 교착 경보만으로 실패 정답을 확정하지 않는다. on_criteria_alert는 observe_only이며, max_steps 도달과 사용자 중단도 교착 라벨이 아니다.

Ctrl+C를 한 번 누르면 가능할 경우 세션을 user_interrupted로 종료하고 요약을 남긴다. 강제 프로세스 종료·두 번째 Ctrl+C·프록시 장애에서는 마지막 저장까지 보장할 수 없다. 인수 검사는 별도 스레드의 subprocess이므로 중단 후 최대 검사 timeout 동안 정리가 지연될 수 있다.

## 4. 실행 후 파일 확인

| 파일 | 확인할 항목 |
|---|---|
| `logs/{session_id}.json` 또는 프록시 지정 로그 폴더 | status ended, meta 온도·buffer·criteria_version, turns의 prompt_tokens/seed_audit, 관측 step 연결 |
| run 폴더의 `conditions.json`, `scenario.yaml` | 실제 적용 버퍼(12/null), 온도 0.0, seed_probe 42, seed_support unverified, 요청 seed, 라이브러리 버전 |
| `steps.json` | step별 역할·llm_calls·llm_turns·acceptance·관측·오류. 첫 turn은 프록시 LLM turn이고 step과 같지 않을 수 있음 |
| `observations/{step}.pending.json`, `.ack.json` | payload/step ID 동일성, ack.persisted true. pending은 성공 후에도 원본 요청 증거로 남기므로 pending 존재만으로 실패가 아님 |
| `prompt-trend.json` | 호출별 prompt_tokens, step별 합계(null 보존), seed_audit. 종료 시 세션 사본으로 재구성됨 |
| `session.json` | 프록시 로그 사본. 사용량이 빠진 요청이 있는지 확인 |
| `summary.json` | 전후 통과 수, total_tokens/known subtotal, 누락 step 수, criteria_latest/alerts, termination_reason, error/cleanup_errors, fixture_unchanged |
| `workspace/.runner-reports/*` | summary.json, junit.xml, process.json의 실제 인수 검사 결과 |

기대 시작 결과는 16개 중 7통과/9실패다. suite ID는 승인된 값과 같아야 한다. fixture_unchanged=true, 관측 누락 0, meta.conditions_mixed=false가 기대값이다. 결과가 다르면 기대값에 맞춰 수정하지 말고 원인을 조사한다.

오프라인 비교(각 output-root에 이번 실행 한 개만 있는 조건):

```powershell
$taskBuffered = (Get-ChildItem (Join-Path $taskBatch 'buffered') -Directory | Select-Object -First 1).FullName
$taskUnbuffered = (Get-ChildItem (Join-Path $taskBatch 'unbuffered') -Directory | Select-Object -First 1).FullName
.\venv\Scripts\python.exe experiments/compare_context.py $taskBuffered $taskUnbuffered --output (Join-Path $taskBatch 'comparison')
```

comparison/prompt-comparison.svg에서 입력 토큰 증가 곡선을, CSV에서 step·역할별 값을 확인한다. comparison.json의 other_conditions_equal=true를 확인하되, 버퍼 차이는 의도적으로 제외된 비교다. null은 그래프에서 선을 끊고 표시하며 0으로 그리지 않는다. 측정 3회에는 이 검증 둘을 섞어 분산을 계산하지 않는다.

## 5. seed 확인

- [ ] 각 프록시 turn의 seed_audit.requested_seed=42, forwarded=true, forwarded_seed=42인지 확인한다. 이는 프록시가 업스트림 요청 body에 넣은 값이다. 네트워크 오류 시 실제 서버 수신까지 증명하지는 않는다.
- [ ] response_status, request_succeeded 및 오류 응답 out을 확인한다. HTTP 200은 seed를 포함한 요청이 성공했다는 증거이며 seed 적용·결정성 증거가 아니다. model_applied_seed는 null로 남긴다.
- [ ] seed가 거부됐다고 명시한 응답은 보존한다. 다른 원인의 400을 seed 미지원으로 해석하지 않는다. 미지원 확인 시 guardrail.yaml의 해당 모델 seed_supported=false, 시나리오 seed_support=unsupported 및 seed=null로 두고 probe 없이 재검증한다.
- [ ] 지원으로 승격하려면 모델/엔드포인트가 seed를 실제 지원한다는 명시적 근거(제공자 명세 또는 명시적 응답)를 기록한다. 성공 응답만으로 자동 승격하지 않는다. 확인되면 YAML seed_support=supported, seed=42 및 guardrail.yaml의 `models.openai/gpt-oss-120b.seed_supported: true`를 함께 설정하고 프록시를 재시작한다. 이전 unverified 로그는 수정하지 않는다.

현재 지원 판정은 내리지 않았다. 버퍼가 다른 두 실행으로 seed 결정성도 평가할 수 없다. 지원 여부가 계속 불명확하면 unverified와 seed=null을 유지하고 한계를 보고한다.

## 6. 실패·재실행

- [ ] 실패 폴더와 프록시 로그를 보존한다. 사용량이 있으면 실패 검증 비용에도 포함한다.
- [ ] summary의 reason/error/cleanup_errors와 프록시 status를 확인한다. ended 키를 재사용하지 않는다. 새 실행은 UUID를 새로 생성한다.
- [ ] 강제 중단으로 active가 남았으면 실행 프로세스가 완전히 종료된 것을 확인한 뒤 해당 세션만 종료한다:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/sessions/end -Headers @{'X-Guardrail-Session'='<중단한 세션 ID>'} -ContentType 'application/json' -Body '{"termination_reason":"user_interrupted"}'
```

- [ ] 새 taskBatch/output-root를 지정해 재실행한다. 실패 폴더 안 workspace를 원본으로 사용하지 않는다. 실행기가 승인된 fixture를 다시 복사하게 한다.
- [ ] seed·버퍼·모델·프록시 설정을 고쳤으면 변경 전후를 같은 조건의 비교로 묶지 않는다. 필요 시 두 검증을 모두 새 조건으로 다시 수행한다.

## 7. 검증 통과 후 측정 준비

온도 0.3, 버퍼 12, 18 step, 1200 출력으로 A-1을 run-index 1·2·3 각각 실행한다. 지원 확인 전에는 seed_probe를 측정 명령에 넣지 않는다. 지원 확인 후에는 YAML의 고정 seed를 사용한다. 아래는 1회용 명령 템플릿이며 자동 3회 실행 루프를 만들지 않았다.

```powershell
.\venv\Scripts\python.exe experiments/run_scenario.py scenarios/A-1-ambiguous-task-query.yaml --temperature 0.3 --context-buffer-messages 12 --run-index 1 --output-root runs/A1-measurement-새폴더
```

각 측정의 총토큰을 A-1 추정 23,400~39,000과 비교하고, 실패·사용량 누락도 별도로 보고한다. 남은 규모는 사용자가 결정한다. A-2~C-11은 아직 작성·실행하지 않는다.

검증 결과: 네트워크 없는 버퍼/곡선 테스트 5개, 프록시 기록 테스트 11개, 실행기 helper 테스트 10개 통과. 실제 시나리오 실행 및 실제 prompt_tokens/seed 지원 검증은 아직 수행하지 않았다.
