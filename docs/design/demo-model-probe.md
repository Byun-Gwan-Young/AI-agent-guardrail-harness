# 데모 모델 probe (C-16 파트 5, DM-12)

- 목적 : 게이트웨이의 GPT·Claude 계열 모델을 데모에 넣을지 PM 이 정하기 전에 **크레딧 단가와 도구 호출 호환성**을 확인한다
- 도구 : `tools/probe_gateway.py` (실행은 PM. 코딩 에이전트는 오프라인 테스트만 한다, DM-14)

## 1. 추가된 기능

| 옵션 | 동작 |
|---|---|
| `--list-models` | 게이트웨이 `GET /models/` 의 모델 ID 목록만 출력. 다른 필드는 버린다 |
| `--model <ID>` (반복 가능) | 모델마다 같은 요청 2 개를 보낸다. 요청 본문의 차이는 `model` 필드뿐 |
| `--with-v3-strict` (C-17-7) | `--scenario` 의 대화 과제 최종 요청을 닫힌 목록 enum 있음·없음으로 한 번씩 보낸다 (DM-20). 결정 문서 019 파트 2 |

`--model` 을 주면 모델마다 보내는 요청 :
- `short-no-tools` : 도구·`response_format`·`reasoning_effort` 없이 "Reply with the single word OK." 한 줄. 어떤 채팅 모델도 받을 수 있는 최소 요청
- 도구 호출 요청 : 실행기의 실제 도구 정의·v8 역할 시스템 메시지. 시나리오 `reasoning_effort` 가 `high` 면 `v8-tools-reasoning-high`, 아니면 `-low`
  - A-1-v4 를 주면 high 다 (데모 조건)

결과 `result.json` 의 `model_summary` (모델별) :
- 요청마다 HTTP 상태, 오류 메시지, prompt·completion·reasoning 토큰, 도구 호출이 돌아왔는지, 요청 전후 크레딧 차 (`monthly_allocated.used`)
- `token_rates` : 두 요청의 (prompt, completion, 크레딧) 으로 `크레딧 = prompt × a + completion × b` 를 정확히 푼 값 (1M 토큰당)
  - 두 식으로 푼 해이므로 오차 추정이 없다. 캐시 토큰은 구분하지 않는다

## 2. A-1-v4 1 세션을 다른 모델로 돌릴 때의 크레딧 환산 (C-11 방식)

```
크레딧 ≈ 세션 prompt 토큰 × (a / 1e6) + 세션 completion 토큰 × (b / 1e6)
```

- 검증된 형태 : 주력 모델은 a = 150, b = 600 (1M 토큰당 크레딧) 으로 A-1-v3 (16.43025) 과 A-1-v4 (130.815) 의 실측 크레딧이 소수점까지 일치한다 ([demo-budget.json](demo-budget.json) `rate_check`)
- A-1-v4 토큰 : prompt 444,636, completion 106,866 (`reports/a-1-v4/manifest-c14.json`)
- 한계
  - 다른 모델은 같은 과제에서도 토큰 수가 다르다 (추론 토큰량, 도구 호출 횟수, step 수). 위 식은 **토큰이 같다고 가정한 환산**이지 그 모델의 세션 비용 예측이 아니다
  - 모델이 `reasoning_effort` 를 지원하지 않으면 completion 쪽이 크게 달라질 수 있다
  - probe 의 `reasoning_tokens` 로 확인한다

## 3. 판단에 쓰는 값 (PM)

- 도구 호출 요청에서 `tool_call_returned: true` 인가 (도구 호환성)
- 오류가 있으면 그 메시지 : `reasoning_effort` 미지원, `tools` 미지원 등
- `token_rates` 와 위 환산값
- 한 모델당 요청 2 회라 신뢰성은 확인하지 않는다

## 4. probe 결과 기록 (`gateway-probe-9d2b2053…`, 2026-09-29, C-17-7)

- 단가(1M 토큰당 크레딧, 요청 2 개로 푼 값) : gpt-oss 150 / 600, Claude Sonnet 5 2,000 / 10,000, Claude Haiku 4.5 1,000 / 5,000, gpt-5.5 5,000 / 30,000 (DM-25 표와 같음)
- 도구 요청에서 돌려준 도구 호출 수 : gpt-oss 1, Claude Sonnet 5·Haiku 4.5·gpt-5.5 각 3 (한 응답의 다중 호출, 결정 문서 019 파트 3)
- gpt-6-sol·gpt-6-luna : 짧은 요청 200, 도구 요청 400 (`param: reasoning_effort`, `/chat/completions` 에서 도구와 추론 강도를 함께 받지 않음). 재시도하지 않았다. 원인 기록은 결정 문서 019 파트 3
- 값의 출처 : `reports/c17-7/evidence.json` (`tools/c17_7_evidence.py`)

