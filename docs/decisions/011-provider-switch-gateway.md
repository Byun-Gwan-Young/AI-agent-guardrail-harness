# D-27 / D-25: 업스트림을 설정으로 고르고, 프로토콜을 매번 명시한다

## 업스트림 설정화 (D-27)

- `proxy.py` 의 Groq 고정 주소를 없애고 설정 파일의 `upstream` 에서 읽는다.
  키 **값**은 설정에 두지 않는다. 설정에는 값을 담은 환경변수 **이름**만 둔다.

  | 키 | 기본값 | 뜻 |
  |---|---|---|
  | `base_url` | `https://api.groq.com/openai/v1` | https origin + 경로, 끝 슬래시·질의 금지 |
  | `chat_path` | `/chat/completions` | 게이트웨이는 끝 슬래시 형태 (리다이렉트로 POST 가 깨지지 않게) |
  | `api_key_env` | `GROQ_API_KEY` | 실행 창에서 키를 담는 환경변수 이름 |

- 기본 `guardrail.yaml`(Groq, v0.1)과 `guardrail-deadlock-v0.2.yaml`(Groq, v0.2)은 그대로 둔다.
  게이트웨이 실행은 새 파일 `guardrail-deadlock-v0.2-kmu.yaml` 을 `GUARDRAIL_CONFIG` 로 명시 선택한다.
  이 파일은 v0.2 Groq 설정과 `criteria_version` 외 `upstream` 만 다르다(테스트).
- 업스트림 식별자(base URL, 호스트, chat 경로, 키 환경변수 이름, 설정 파일 이름)를 세션 로그 meta
  `upstream` 에 남기고, 실행기가 세션 시작 직후 그것을 `conditions.json` 에 복사한다.
  매니페스트 `model.provider` 는 이 기록의 호스트에서 온다. 기록이 없는 과거 세션(G0-8)은 null 이며
  `notes` 에 이유를 적는다. 코드나 사람의 기억으로 제공자를 채우지 않는다.
- 실행기는 `--api-key-env` 로 읽을 환경변수를 정하고, 프록시가 설정한 이름과 다르면 실행 전에 멈춘다.
  Groq 키가 게이트웨이로, 또는 그 반대로 나가는 사고를 막는다.
- 비밀값 검사(D-11)는 패턴에 더해, 검사 시점에 설정된 해당 환경변수의 **값 자체**가 세션 파일에 있는지
  본다. 검사한 변수 이름과 설정 여부를 결과에 남긴다.

## 프로토콜 명시 강제 (D-25)

- `--runner-protocol` 은 output-contract-v2 에서 필수다. 없으면 모델 호출 전에 오류다(기본값 없음).
- output-contract-v1 에는 줄 수 없다. 프로토콜은 수집 정책에서 나온다.
- `conditions.json` 과 매니페스트에 프로토콜 식별자가 남는다.
- 7-2 실행 명령에는 `--output-contract`, `--runner-protocol`, `--collection-policy` 를 항상 적는다.

## A-1-v3 모델

- A-1-v3 는 아직 실행 기록이 없으므로 같은 시나리오 ID 에서 `model` 을
  `accounts/fireworks/models/gpt-oss-120b` 로 바꿨다. 실행 전 기록은 `reports/a-1-v3/preflight-kmu.json`
  에 새로 저장하고 이전 기록은 보존한다. A-1-v2(G0-8, Groq)는 바꾸지 않는다.
- **같은 가중치라도 서버가 다르다.** A-1-v2(Groq)와 A-1-v3(Fireworks) 결과는 제공자를 구분해 비교한다.

## 게이트웨이 probe

`tools/probe_gateway.py` (사용자 실행). 요청 본문을 실행기 코드로 만든다. v8 역할 시스템 메시지,
실행기의 실제 도구 정의(`convert_tools`), output-contract-v2 strict 응답 형식을 그대로 쓴다.

- 변형 1 `v8-final-strict` (기본) : 최종 보고 요청 그대로. 계약 통과 여부를 본다
- 변형 2·3 `v8-tools-reasoning-low` / `-high` (옵션) : 도구 정의를 포함한 요청. 둘은 `reasoning_effort`
  만 다르다. **두 응답의 `reasoning_tokens` 를 비교**해 게이트웨이가 이 값을 실제로 전달하는지 본다
  (문서상 도구와 함께 보내면 제거하고 재시도할 수 있다). 판단은 사용자 보고로 한다
- 각 요청 전후로 `/credits/` 를 읽어 `used` 차이를 기록한다. `used` 가 없으면 null + unmeasured
- 키는 설정이 지정한 환경변수에서만 읽고, 저장 전 응답에서 가린다
- 기존 `tools/probe_groq_strict.py` 의 동작은 그대로다(공용 도우미만 분리)
