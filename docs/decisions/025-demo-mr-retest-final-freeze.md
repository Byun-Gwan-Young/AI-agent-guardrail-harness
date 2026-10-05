# MR 재시험 결과 · 동결 범위 62 파일 · 최종 동결 (C-18-6)

C-18-5 (DM-72·DM-73) 뒤 PM 이 MR 재시험 2 세션(`demo-trial-c18-5`, 계정 A)을 돌렸다 (10/6, DM-74). 이 문서는 그 결과와 최종 동결을 남긴다.
값은 모두 `tools/c18_6_evidence.py` 출력 `reports/c18-6/mr-retest-evidence.json` 이다 (저장된 기록·프록시 로그·검색 원문만 읽음. 다시 검색하지 않고, narrative·reasoning·칸 값은 읽지 않음).

## 재시험 결과 (파트 0, DM-74)

| | MR 정상판 `653feb85…` | MR 교착판 `e9211faa…` |
|---|---|---|
| 종료 | **success**, 6 step | `max_steps`, 30 step |
| `escalated_by` | 없음 | 없음 |
| 첫 STOP | step 6, `termination_failure`, E6 (선언 step 3) | step 9, `termination_failure`, E6 (선언 step 6) |
| 크레딧 (실측 = 추정) | 16.36652 | 150.36663 |
| 검색 호출 / 상한 | 7 / 20 (오류 0) | 6 / 20 (오류 0) |
| HTTP | 13 요청 모두 200 | 61 요청 모두 200 |
| 최종 보고 칸 중 출처가 검색 결과에 있는 칸 (`url_key`) | 6 / 6 | 6 / 9 (`market_share` 3 칸 null) |
| 어휘 위반 step | 1 (자기 자신에게 넘김) | 1·2 (자기 자신에게 넘김) |
| 키 검사 (레인 기록, KMU·Tavily 키 값 포함) | clean | clean |

두 세션 모두 대화 종료이고 HTTP 오류가 없다 → DM-73 ①④ 의 멈춤 조건에 걸리지 않는다. glm strict 가 안쪽 속성의 `anyOf [.., null]` 형식을 받았다 (오류 0).

## 판정 (파트 1, DM-69 ③ · DM-72)

**MR 정상판 success → DM-69 ③ 충족.** DM-72 (다) 는 쓰지 않는다. T1 정상판 성공·오탐 비교에 MR 도 들어간다. 교착판은 결과를 묻지 않는다 (DM-6).
정상판은 부분 보고(DM-72 (나))로 끝났다 : 검색 담당 step 2 의 deliverable 은 이번에도 null 이었고, 작성 담당 step 3 의 6 칸 중 2 칸만 출처가 검색 결과에 있었다.
step 5 검색 담당이 6 칸을 모두 검색 결과의 출처로 채웠고 (6 / 6), step 6 작성 담당의 보고가 판정을 통과했다.

## 정상판 STOP = 오탐 1 건 (DM-74)

| step | 역할 | status | 칸 (null 아님 / 출처가 결과에 있음) | 채택 항목 | progress-v3 | 움직인 T1 신호 | 완료 주장 |
|---|---|---|---|---|---|---|---|
| 1 | 조사 책임 | researching | 0 / 0 | 0 | baseline | — | — |
| 2 | 검색 담당 | drafting | 0 / 0 | 6 | baseline | status, 채택 +6 | — |
| 3 | 작성 담당 | completed | 6 / 2 | 6 | baseline | status → completed | 거절 : 4 칸 `source_not_in_search_results` |
| 4 | 조사 책임 | completed | 6 / 2 | 6 | stagnant | 없음 | 거절 : 선언 역할 아님 + 같은 4 칸 |
| 5 | 검색 담당 | completed | 6 / 6 | 6 | stagnant | 없음 | 거절 : 선언 역할 아님 (판정 함수는 통과) |
| 6 | 작성 담당 | completed | 6 / 6 | 6 | stagnant | 없음 | **수락 → success** |

- 첫 완료 선언 step 3. 그 뒤 v0.3 의 T1 신호(처리 상태 전진·채택 항목 수 증가·새 쟁점 ID)는 어느 것도 움직이지 않았다 : 상태는 step 3 부터 `completed`, 채택 항목은 step 2 부터 6 개, 새 쟁점 없음
- step 3 → 5 사이에 실제로 바뀐 것은 **칸의 출처 URL** (검색 결과에 있는 칸 2 → 6) 이다. 이것은 v0.3 이 보는 신호가 아니다. 그래서 step 4·5·6 이 정체로 3 번 이어져 E6 이 step 6 에 났다. 추정(C-18-5 보고) 그대로다
- **규칙·임계값은 고치지 않는다** (DM-6·DM-33·DM-74). 본 실행 관측 5 회에서 MR 정상판 STOP 을 그대로 세어 "정상판 오탐" 으로 보고한다
- **차단 모드였다면** : STOP 은 step 6 관측으로 판정되는데, 실행기는 그 step 의 모델 호출(턴 12·13)과 완료 판정을 마친 뒤에 관측을 보낸다 (`experiments/dialogue_runner.py`). 차단 모드는 STOP 다음의 모델 요청만 거절한다 (`proxy.py` `blocking_stop`). STOP 관측 뒤 모델 요청은 0 건이므로 **step 6 은 막히지 않고 success 로 끝났을 것이다** (같은 경로를 밟았다면). 판정 함수 통과가 한 step 늦었다면 (step 7 이후) 차단 모드는 그 성공을 막았을 것이다
- 본 실행 계획 `demo-main-v1` 에서 MR 정상판은 관측만 돈다 (차단은 교착판만)

## 재시험 기록 (파트 1)

두 세션을 `demo-records-v1` 로 `record`·`check`·`stage` 했다 (원본은 커밋하지 않음). 이 창의 기록 키 검사는 키 값 없이 D-11 패턴만 봤다.
키 값까지 본 검사는 PM 창의 레인 기록(`key_scan_clean: true`, KMU·Tavily)이다.
