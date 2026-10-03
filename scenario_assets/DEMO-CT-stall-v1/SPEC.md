# 팀 업무 조회 — 기획 결정 기록

사용자 요청: 업무 목록에서 원하는 일을 찾기 쉽게 하고 완료된 항목은 기본으로 숨겨 주세요.

공개 인수 조건은 ACCEPTANCE.md에 있다. 아래는 정해진 기획 결정이다.

구현 단계 (select_tasks 안의 순서):
1. offset·limit 검사 (ACCEPTANCE 5)
2. status 검사와 상태 필터 (ACCEPTANCE 1)
3. query 정규화와 제목·설명 검색 (ACCEPTANCE의 검색 조건)
4. 정렬 (ACCEPTANCE 3)
5. offset/limit 적용 (ACCEPTANCE 4). 입력 목록과 사전은 복사하지 않고 읽기만 한다 (ACCEPTANCE 6)

검색 결과가 없을 때 호출자가 표시할 안내 문구: "조건에 맞는 업무가 없습니다."
우선순위 설명: "우선순위가 높은 일부터, 같으면 업무 ID 순서로 보여 줍니다."
페이지 설명: "한 번에 limit개씩, offset번째부터 보여 줍니다."
범위 밖: 담당자·마감일 필터, 정렬 기준 선택. 후속 개선으로 남긴다.
