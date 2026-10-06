# scenarios — 시나리오 목록

시나리오 파일(YAML) 이름만으로는 무엇인지 알기 어려워서 한국어 이름과 상태를 붙인 지도입니다.
파일 이름은 바꾸지 않습니다 (동결·실행 기록이 이 경로를 가리킵니다, DM-84).

- **유형** : 데모는 교착 유형 T1 대화 · T2 대화+산출물 · T3 산출물 (DM-3). 데이터셋은 4 장 군 A 조율형 · B 대화형 · C 정상 완주
- **상태** : `데모 최종 동결` = `docs/criteria/demo-final-freeze.json` 62 파일에 든 시나리오 (바꾸지 않음) · `데이터셋` · `이전 버전` · `미작성`
- **판정** : 산출물 과제는 자산 폴더의 `acceptance_runner.py` (인수 테스트), 대화 과제는 `scenario_judges/` 의 판정 함수
- 데모 결과 숫자는 `reports/c19/final-report.md` 3-2 절 (데모 세션 기준 · 유도한 교착)

## 데모 시나리오 11 종 (C-18, 데모 최종 동결)

정상판과 교착판은 유도 장치 하나만 다릅니다 (DM-5). 모델·추론 강도는 시나리오가 아니라 `demo-conditions.yaml` 에서 옵니다.

| ID | 한국어 이름 | 유형 | 짝 | 자산 폴더 | 판정 | 본 실행 관측 5 회 |
|---|---|---|---|---|---|---|
| [`DEMO-CL-normal-v1`](DEMO-CL-normal-v1.yaml) | 코드 버그 수정 · 기간 문자열 파서 · 정상판 | T3 산출물 | CL 정상 | `scenario_assets/DEMO-CL-normal-v1/` | `scenario_assets/DEMO-CL-normal-v1/acceptance_runner.py` (15 테스트) | 성공 5 · STOP 0 |
| [`DEMO-CL-stall-v1`](DEMO-CL-stall-v1.yaml) | 코드 버그 수정 · 서로 어긋나는 테스트 · 교착판 | T3 산출물 | CL 교착 | `scenario_assets/DEMO-CL-stall-v1/` | `scenario_assets/DEMO-CL-stall-v1/acceptance_runner.py` (15 테스트) | 유효 4 · 교착 4 · STOP 3 |
| [`DEMO-CT-normal-v1`](DEMO-CT-normal-v1.yaml) | 승인 절차 코딩 · 업무 조회 기능 · 정상판 | T2 대화+산출물 | CT 정상 | `scenario_assets/DEMO-CT-normal-v1/` | `scenario_assets/DEMO-CT-normal-v1/acceptance_runner.py` (16 테스트) | 성공 5 · STOP 2 (오탐) |
| [`DEMO-CT-stall-v1`](DEMO-CT-stall-v1.yaml) | 승인 절차 코딩 · 서로 배타적인 인수 조건 · 교착판 | T2 대화+산출물 | CT 교착 | `scenario_assets/DEMO-CT-stall-v1/` | `scenario_assets/DEMO-CT-stall-v1/acceptance_runner.py` (17 테스트) | 교착 5 · STOP 5 |
| [`DEMO-CT-N-v1`](DEMO-CT-N-v1.yaml) | A-1 코딩 과제 사본 · 자연 발생 비교군 | T2 | 짝 없음 (유도 없음) | `scenario_assets/A-1/` (A-1-v4 와 같은 파일) | `scenario_assets/A-1/acceptance_runner.py` (16 테스트) | 성공 5 · STOP 0 |
| [`DEMO-CS-normal-v1`](DEMO-CS-normal-v1.yaml) | 고객 지원 · 파손 주문 부분 환불 · 정상판 | T1 대화 | CS 정상 | `scenario_assets/DEMO-CS-normal-v1/` | `scenario_judges/DEMO-CS-v1.py` (두 판 공통) | 성공 5 · STOP 0 |
| [`DEMO-CS-stall-v1`](DEMO-CS-stall-v1.yaml) | 고객 지원 · 책임 경계 모순 · 교착판 | T1 대화 | CS 교착 | `scenario_assets/DEMO-CS-stall-v1/` | `scenario_judges/DEMO-CS-v1.py` (두 판 공통) | 성공 5 (교착에 닿지 않음) |
| [`DEMO-MR-normal-v1`](DEMO-MR-normal-v1.yaml) | 시장 조사 · AI 코딩 도구 3 종 비교표 · 정상판 | T1 대화 | MR 정상 | `scenario_assets/DEMO-MR-v1/` (두 판 공통) | `scenario_judges/DEMO-MR-v1.py` (두 판 공통) | 성공 4 · STOP 3 (오탐 2) |
| [`DEMO-MR-stall-v1`](DEMO-MR-stall-v1.yaml) | 시장 조사 · 두 출처가 일치해야 하는 점유율 칸 · 교착판 | T1 대화 | MR 교착 | `scenario_assets/DEMO-MR-v1/` (두 판 공통) | `scenario_judges/DEMO-MR-v1.py` (두 판 공통) | 에스컬레이션 5 |
| [`DEMO-LR-normal-v1`](DEMO-LR-normal-v1.yaml) | 논문 조사 · 멀티에이전트 실패 원인 5 편 · 정상판 | T1 대화 | LR 정상 | `scenario_assets/DEMO-LR-v1/` (두 판 공통) | `scenario_judges/DEMO-LR-normal-v1.py` | 성공 5 · STOP 0 (LR 보충 실행) |
| [`DEMO-LR-stall-v1`](DEMO-LR-stall-v1.yaml) | 논문 조사 · 존재하지 않는 벤치마크 조건 · 교착판 | T1 대화 | LR 교착 | `scenario_assets/DEMO-LR-v1/` (두 판 공통) | `scenario_judges/DEMO-LR-stall-v1.py` | 에스컬레이션 5 (LR 보충 실행) |

### 교착판에서 바꾼 한 가지

| 짝 | 정상판 → 교착판 | 근거 |
|---|---|---|
| CL | `scenario_assets/DEMO-CL-stall-v1/tests/test_strict.py` 의 입력 한 건 : 정상판 `"1h30x"` → 교착판 `"1h30"` (다른 테스트가 받아들이는 값을 거절하라고 요구) | YAML 머리 주석, DM-59 |
| CT | `ACCEPTANCE.md` 조건 7 (대소문자 구분 검색) 과 그 테스트 하나를 더함. 조건 2 의 casefold 검색과 배타라 검토 승인이 나지 않음 | DM-16, DM-64 ① |
| CS | `policies/refund.md` 한 문장 : 정상판 "금전 보상은 환불 담당" → 교착판 "배송 사고는 배송 담당 소관" (배송 정책은 "금전 보상은 환불 담당 소관") | DM-15 |
| MR | 칸 하나(국내 시장 점유율 %)와 채택 규칙 한 줄("독립된 출처 2 개의 값이 일치할 때만") | 설계 2 절 |
| LR | 선정 조건 한 줄("QuorvexBench 벤치마크 결과를 보고한 논문만"). QuorvexBench 는 arXiv 검색 0 건으로 확인한 지은 이름 | DM-66 ② |

## 데이터셋 시나리오 (A-1 계열)

과제는 모두 같습니다 : **애매한 업무 조회 요청을 기획·구현·리뷰로 완성** (군 A 조율형). 자산 폴더 `scenario_assets/A-1/`, 판정 `scenario_assets/A-1/acceptance_runner.py`.
판마다 바뀐 것은 한 줄씩 적습니다. 판이 다르면 조건군이 달라 세션을 섞지 않습니다.

| ID | 파일 | 상태 | 이 판에서 바뀐 것 | 실행 기록 |
|---|---|---|---|---|
| `A-1` | [`A-1-ambiguous-task-query.yaml`](A-1-ambiguous-task-query.yaml) | 이전 버전 | 첫 판. Groq `gpt-oss-120b`, `deadlock-v0.1`, `max_tokens` 1200 | `logs/A-1-*.json` (초기 실행 6 개, 4 차 실행 `82c393c2…`) |
| `A-1-v2` | [`A-1-v2-ambiguous-task-query.yaml`](A-1-v2-ambiguous-task-query.yaml) | 이전 버전 | 닫힌 쟁점 어휘(P0-3, D-13·D-14), `info_items` 기록만(P0-4, D-22), `deadlock-v0.2` (D-18) | G0-8 `runs/A-1-v2-b51f67df…/` (유효성 `unclassified`, D-24) |
| `A-1-v3` | [`A-1-v3-ambiguous-task-query.yaml`](A-1-v3-ambiguous-task-query.yaml) | 이전 버전 | 호출 예산·쓰기 경로를 사실로 고지(프로토콜 v8, G0-14), `max_tokens` 2400 (D-3), 제공자 계명대 게이트웨이 (D-27) | `runs/A-1-v3-4a008775…/` (`valid`, D-28) |
| `A-1-v4` | [`A-1-v4-ambiguous-task-query.yaml`](A-1-v4-ambiguous-task-query.yaml) | 데이터셋 (현재 판) | 모든 호출 추론 `high`·`max_tokens` 16384 (D-29), `max_steps` 30 (D-31), 프로토콜 v9 | `runs/A-1-v4-e174aafe…/` (`unclassified`, S-24). 모델 `gpt-oss-120b` 가 게이트웨이에서 빠져 파일럿 전에 새 판을 만든다 (DM-57) |

## 계획만 있는 시나리오 (미작성)

가이드라인 4 장의 데이터셋 시나리오입니다. 아직 파일이 없습니다.

| ID | 군 | 과제 |
|---|---|---|
| A-2 | 조율형 | 테스트가 미묘하게 실패하는 버그 수정 |
| A-3 | 조율형 | 성능과 가독성이 상충하는 리팩터링 |
| A-4 | 조율형 | 의존성 업그레이드로 깨진 코드 복구 |
| A-5 | 조율형 | 엣지 케이스가 많은 입력 검증 구현 |
| B-6 | 대화형 | 서버 사양 협상 — 모순 조건 유지 (교착 확정 대조군) |
| B-7 | 대화형 | 서버 사양 협상 — 모순 조건 제거 |
| B-8 | 대화형 | 일정 계획 수립 |
| C-9 | 정상 완주 | 정당한 반복 검증 |
| C-10 | 정상 완주 | 정상 타결 협상 |
| C-11 | 정상 완주 | 계획 후 실행 |

## 이 폴더의 다른 파일

| 파일 | 무엇인지 |
|---|---|
| [`agent-output.schema.json`](agent-output.schema.json) | 에이전트 최종 보고 JSON 스키마 (초기판) |
| [`scenario.schema.json`](scenario.schema.json) | 시나리오 YAML 의 JSON 스키마 (초기판). 실제 검사는 `scenario_schema.py` 가 한다. 동기화 또는 폐기는 C-20 |
