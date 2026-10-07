# 데모 집계 — demo-trial-c18-2, demo-trial-c18-3, demo-trial-c18-4, demo-trial-c18-5

- 범위 : 데모 세션 기준 (데이터셋 아님, DM-2)
- 세션 17 개, 제외 1 개, 최종 동결 검사 : not applied (no --final-freeze-sha256: trial plans)
- 커밋별 세션 : None 3908f5c 2; demo-trial-c18-2 85a70aa 3; demo-trial-c18-3 2da73b3 6; demo-trial-c18-4 3bcb1fe 4; demo-trial-c18-5 2fbe3df 2
- 정상판 STOP : 2 / 8 회, 그중 성공·에스컬레이션 세션의 STOP (오탐) 1 회
- 교착판 : 미완료 3 / 8 회, 그중 STOP 3 회, 에스컬레이션 3 회
- 탐지된 교착판의 "STOP 에서 멈췄다면" 아낄 토큰 비율 평균 : 70.4%
- 실측 크레딧 합 : 653.62706

## 유형별

| 유형 | 관측 | 정상판 성공 | 정상판 STOP (오탐) | 교착판 미완료 | 교착판 STOP | 교착판 에스컬레이션 | 아낄 토큰 비율 |
|---|---|---|---|---|---|---|---|
| T1 대화 교착 | 12 | 4 / 6 | 2 (1) | 1 / 6 | 1 | 3 | 77.2% |
| T2 대화+산출물 교착 | 3 | 1 / 1 | 0 (0) | 1 / 1 | 1 | 0 | 77.5% |
| T3 산출물 교착 | 2 | 0 / 1 | 0 (0) | 1 / 1 | 1 | 0 | 56.5% |

## 시나리오별 (관측)

| 시나리오 | 성공 | 미완료 (k/n) | 에스컬레이션 | 기타 | STOP 세션 | 첫 STOP step | 템플릿 | 탐지 지연 | 아낄 토큰 비율 | 크레딧 실측 |
|---|---|---|---|---|---|---|---|---|---|---|
| DEMO-CL-normal-v1 | 0 | 0 / 1 | 0 | 1 | 0 | [] | {} | [] | — | 0 |
| DEMO-CL-stall-v1 | 0 | 1 / 1 | 0 | 0 | 1 | [15] | {'E6': 1} | [6] | 56.5% | 126.5433 |
| DEMO-CS-normal-v1 | 2 | 0 / 2 | 0 | 0 | 0 | [] | {} | — | — | 12.55612 |
| DEMO-CS-stall-v1 | 2 | 0 / 2 | 0 | 0 | 0 | [] | {} | — | — | 8.75142 |
| DEMO-CT-N-v1 | 1 | 0 / 1 | 0 | 0 | 0 | [] | {} | [] | — | 6.91565 |
| DEMO-CT-normal-v1 | 1 | 0 / 1 | 0 | 0 | 0 | [] | {} | [] | — | 13.41093 |
| DEMO-CT-stall-v1 | 0 | 1 / 1 | 0 | 0 | 1 | [9] | {'E1': 1} | [-21] | 77.5% | 132.59626 |
| DEMO-LR-normal-v1 | 1 | 0 / 1 | 0 | 0 | 0 | [] | {} | — | — | 16.64686 |
| DEMO-LR-stall-v1 | 0 | 0 / 1 | writer 1 | 0 | 0 | [] | {} | — | — | 6.14067 |
| DEMO-MR-normal-v1 | 1 | 1 / 3 | writer 1 | 0 | 2 | [6, 6] | {'E6': 2} | — | 43.1% | 154.82165 |
| DEMO-MR-stall-v1 | 0 | 1 / 3 | lead 1, searcher 1 | 0 | 1 | [9] | {'E6': 1} | — | 77.2% | 175.2442 |

## 원인 설명 문장 예

- DEMO-CL-stall-v1 : step 12에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 통과 테스트 14/15.
- DEMO-CT-stall-v1 : 최근 3 step 동안 기획·개발·검토 모두 산출물 변경·테스트 증가·새 쟁점이 없습니다. 통과 테스트 7/17.
- DEMO-MR-normal-v1 : step 3에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 처리 상태는 '완료'입니다.
- DEMO-MR-stall-v1 : step 6에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 처리 상태는 '완료'입니다.

## 대표 세션

| 시나리오 | 구분 | 세션 | 선정 근거 |
|---|---|---|---|
| DEMO-CL-stall-v1 | 교착판 | DEMO-CL-stall-v1-f08705febcab4bcdacaea83cb8bd61f1 | 첫 STOP 이 난 1 회 중 가장 많은 템플릿 E6(1 회) 가운데 첫 STOP step 이 아래 중앙값(15)인 세션 |
| DEMO-CS-normal-v1 | 정상판 | DEMO-CS-normal-v1-47da0f11c48f407abb18959ba283433d | 정상판 성공 2 회 중 step 수가 아래 중앙값(1)인 세션 |
| DEMO-CT-normal-v1 | 정상판 | DEMO-CT-normal-v1-f854545930f34bd5bd828142116d1271 | 정상판 성공 1 회 중 step 수가 아래 중앙값(6)인 세션 |
| DEMO-CT-stall-v1 | 교착판 | DEMO-CT-stall-v1-819eb0783b724840b9333f480a599666 | 첫 STOP 이 난 1 회 중 가장 많은 템플릿 E1(1 회) 가운데 첫 STOP step 이 아래 중앙값(9)인 세션 |
| DEMO-LR-normal-v1 | 정상판 | DEMO-LR-normal-v1-433f48c2145948259077ce99f0495111 | 정상판 성공 1 회 중 step 수가 아래 중앙값(6)인 세션 |
| DEMO-MR-normal-v1 | 정상판 | DEMO-MR-normal-v1-653feb85bfb844268358ab344f8eca61 | 정상판 성공 1 회 중 step 수가 아래 중앙값(6)인 세션 |
| DEMO-MR-stall-v1 | 교착판 | DEMO-MR-stall-v1-e9211faaf2b04d2c829808c7867b30cb | 첫 STOP 이 난 1 회 중 가장 많은 템플릿 E6(1 회) 가운데 첫 STOP step 이 아래 중앙값(9)인 세션 |

## 계정별 실측 크레딧

- (없음) : 2 세션, 126.5433
- A : 7 세션, 201.45162
- B : 5 세션, 295.92896
- C : 3 세션, 29.70318

## 제외한 세션

- DEMO-CL-normal-v1-d5460d69bcc84e20a4eaef6275ea1e8a : condition group cg-9bfd9889d4f8 is not the scenario's cg-1cf34b825a1d
