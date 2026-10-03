# 데모 크레딧 실측 · preflight v0.3 · DEMO-CL (C-18-1)

가이드라인 부록 C-18-1. 근거 결정 : DM-58 ③ ④ (단가·실측 크레딧·키 검사 커밋), DM-59 (C-18 나누기), DM-2~DM-6, DM-10, DM-37, DM-38, DM-57.

## 파트 0 — C-17-8 결정 반영 (DM-58)

### 게이트웨이 단가 (`tools/gateway_prices.py`, `gateway-prices-v1`)

크레딧 per 1M 토큰. 1 크레딧 = $0.001 (C-11). 표에 없는 모델은 지금처럼 `unmeasured` 다.

| 모델 | 입력 | 캐시 입력 | 출력 | 출처 |
|---|---|---|---|---|
| `glm-5.3-flash` | 150 | **30** | 500 | 입력·출력 : probe `gateway-probe-a41f8d51…` (요청 2 개의 정확한 해). 캐시 입력 : 아래 역산 |
| `qwen3.8-flash` | 150 | 모름 | 470 | probe `a41f8d51…` |
| `gpt-5.4-nano` | 200 | 모름 | 1,250 | probe `a41f8d51…` |
| `gpt-oss-120b` | 150 | 모름 | 600 | C-11 (기존 `analyze_session.PRICE_PER_M` 의 $0.15 / $0.60, 그대로 둔다) |

**glm 캐시 입력 단가 역산** (`tools/c18_1_evidence.py prices` → `reports/c18-1/evidence-prices.json`)

- 근거 : probe `gateway-probe-44ec8e43…` 의 glm 두 번째 요청 (`v3-final-strict-enums`). prompt 1,094 중 cached 1,088, completion 610, 크레딧 0.33854
- 식 : `캐시 단가 = (크레딧 − (prompt − cached) × 입력 단가 − completion × 출력 단가) ÷ cached`
- 값 : (0.33854 − 6 × 0.00015 − 610 × 0.0005) ÷ 1,088 = 0.03264 ÷ 1,088 = 0.00003 크레딧 = **1M 당 30** (입력 단가의 1/5)
- 확인 : 같은 probe 의 첫 요청 (cached 0, prompt 1,094, completion 204) 은 입력·출력 단가만으로 0.2661 이 남김없이 맞는다 (잔차 0)
- 한계 : 단가는 요청 한두 개의 정확한 해다. 세 번째 요청으로 확인하지 않았고, 게이트웨이 문서와 대조하지 않았다

**추정값 (`credits_estimated`)** = 프록시 로그 usage × 단가. `(prompt − cached) × 입력 + cached × 캐시 입력 + completion × 출력`.

- 캐시 단가를 모르는 모델은 캐시 토큰을 입력 단가로 센다 (`cached_price: unknown …`, 위쪽 값)
- usage 가 빠진 턴이 있으면 `status: incomplete` (그 턴은 세지 않음)
- usage 에 나타나지 않는 할인은 반영하지 못한다. 그래서 위쪽 값이다 (DM-58 ③ 이유)
- gpt-oss 세션의 매니페스트 `credits` 는 바이트 그대로다 (테스트)

### 실측 크레딧 (`experiments/gateway_usage.py`, `gateway-usage-v1`)

- **누가·언제** : scenario-v2 실행 (산출물 과제·대화 과제 모두) 의 실행기가 `/credits/` 를 두 번 읽는다
  - 첫 번째 : 프록시 세션을 열고 프록시 설정을 확인한 뒤, **첫 모델 요청 전**
  - 두 번째 : `/sessions/end` 와 로그 저장 **뒤**
  - 주소는 프록시 세션 meta 의 `upstream.base_url` + `/credits/`, 키는 실행기가 이미 가진 `KMU_API_KEY` 를 Authorization 헤더로만 보낸다. 파일·로그에 쓰지 않는다
- **필드** : probe 와 같다 (`monthly_allocated.used`, 없으면 `total.used`. 테스트로 두 상수가 같은지 확인. 실행기는 probe 를 import 하지 않는다)
- **기록** : `summary.json` 의 `gateway_usage` = `{status, value, field, before, after, exact_only_if_alone: true, note}`. `before`·`after` 에 읽은 시각(`read_at`)·HTTP 상태·값
- **매니페스트** (v0.6, 산출물·대화 과제) : `credits_estimated` (위 추정) 와 `credits_measured` (`gateway_usage` 그대로) 를 나란히 둔다. v0.6 의 `credits` 는 `credits_estimated` 로 이름을 옮겼다. v0.6 매니페스트가 있는 실제 세션은 0 개라 버전을 올리지 않고 제자리에서 바꿨다 (DM-51·DM-54 ③ 원칙)
- **동시 실행** : 차이에는 두 읽기 사이의 같은 키 사용이 모두 들어간다 (병렬 세션, probe, 다른 도구). `exact_only_if_alone: true` 와 두 읽기 시각, 매니페스트 `run.started_at`·`ended_at` 으로 겹친 세션을 찾는다
- **실패** : 조회 실패(네트워크·HTTP 오류·필드 없음)는 세션을 막지 않는다. 값은 `unmeasured` 와 사유. 첫 읽기를 못 했으면 두 번째도 하지 않는다
- **scenario-v1 (데이터셋) 경로** : 읽지 않는다. 데이터셋 경로의 동작은 바뀌지 않는다
- 오프라인 테스트에서 이 읽기는 메모리 안의 프록시로 가서 404 (`unmeasured`) 가 되거나, 테스트가 바꿔 끼운 가짜 읽기를 쓴다. 가짜 업스트림에는 채팅 요청만 간다 (테스트)

### 키 검사 결과 커밋 (DM-58 ④)

`reports/c17-7/evidence-keycheck.json` (PM 이 `KMU_API_KEY` 를 넣고 실행, `clean: true`, hits 없음) 을 커밋했다.
`reports/c17-8/evidence-models-keycheck.json`·`evidence-search-keycheck.json` 도 작업 트리에 추적되지 않은 채 있다. 지시 범위 밖이라 커밋하지 않았다.
