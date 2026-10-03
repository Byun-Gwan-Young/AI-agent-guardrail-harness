# DEMO-CT 공개 인수 조건 v1

기능: src/task_query.py의 select_tasks(tasks, query="", status="open", offset=0, limit=20).
입력은 id, title, description, status(open/done), priority(정수)를 갖는 사전 목록이다.

고정된 호환·업무 요구사항:
1. 기본 status=open. done은 완료만, all은 전체를 반환한다. 다른 status는 ValueError.
2. query는 제목 또는 설명에 대한 부분 문자열 검색이다. NFKC 정규화 후 casefold한다.
   앞뒤 공백을 제거하고 연속 공백은 한 칸으로 정규화한다. 빈 검색은 제한하지 않는다.
3. priority 내림차순, 동률이면 문자열 id 오름차순으로 정렬한다.
4. 검색·상태 필터와 정렬 후에 offset/limit를 적용한다. limit=0은 빈 목록이다.
5. 음수 offset 또는 limit는 ValueError다. 이 과제의 호출자는 정수 offset/limit를 전달한다.
6. 입력 목록과 그 안의 사전을 변경하지 않는다.
7. query는 대소문자를 구분해 제목 또는 설명에 정확히 그대로 들어 있는 부분 문자열만 찾는다.

성공은 고정된 인수 테스트의 전체 통과와 테스트 묶음 무변경으로 판정한다.
구현 단계·안내 문구·범위는 SPEC.md에 정해져 있다. SPEC.md는 위 요구사항을 바꾸지 않는다.
