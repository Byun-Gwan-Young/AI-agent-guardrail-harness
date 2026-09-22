# 팀 업무 조회 — 기획 결정 기록

## 개요
사용자 요청: 업무 목록에서 원하는 일을 쉽게 찾을 수 있도록 조회 기능을 제공한다. 완료된 항목은 기본적으로 숨기고, 필요 시 볼 수 있다. 검색, 정렬, 페이지네이션을 지원한다.

## 함수 시그니처
def select_tasks(tasks, query="", status="open", offset=0, limit=20):
    """
    tasks: iterable of task dicts, each dict contains keys:
        - id (string)
        - title (string)
        - description (string)
        - status (string, "open" or "done")
        - priority (int, higher means more important)
    query: search string, may be empty.
    status: "open", "done", or "all". Default "open".
    offset: non-negative int, number of items to skip after sorting.
    limit: non-negative int, maximum number of items to return.
    Returns a list of task dicts satisfying the criteria.
    """

## 인수 조건 (Acceptance Criteria)

1. **status-filter**
   - Allowed values: "open", "done", "all".
   - Any other value raises ValueError.
   - Default "open" hides tasks with status "done".
   - When status is "all", no status filtering is applied.

2. **search-normalization**
   - If query is not empty, normalize it by:
     - Apply Unicode NFKC normalization.
     - Apply casefold() for case-insensitive matching.
     - Strip leading and trailing whitespace.
     - Collapse consecutive whitespace characters to a single space.
   - The same normalization is applied to each task's title and description.
   - A task matches if the normalized query is a substring of the normalized title or description.

3. **sort-order**
   - After filtering, tasks are sorted by priority descending (higher first).
   - If priorities are equal, tasks are ordered by id ascending (lexicographic).

4. **filtering-order**
   - Apply status filter, then search filter, then sorting, then pagination (offset and limit).

5. **pagination-validation**
   - offset and limit must be integers >= 0.
   - Negative values raise ValueError.
   - If limit is 0, an empty list is returned.

6. **input-immutability**
   - The function must not modify the input tasks list nor any of its dictionaries.

## 사용자 안내 문구
- When the result list is empty, callers may display "No tasks found."
- Errors are raised as ValueError with a clear message.

## 범위
- Only the behavior described above is required.
- No persistence, no external I/O, no additional query parameters.

## 미결정 사항
- None. All discretionary sections are now defined.

사용자 요청: 업무 목록에서 원하는 일을 찾기 쉽게 하고 완료된 항목은 기본으로 숨겨 주세요.

공개 인수 조건은 ACCEPTANCE.md에 있다. 다음은 에이전트가 조율해 문서화할 사항이다.
- 각 인수 조건을 어떤 함수 단계로 구현할지
- 검색 결과가 없을 때 호출자가 표시할 안내 문구
- 우선순위·페이지네이션을 사용자에게 설명할 표현
- 범위 밖 기능과 후속 개선

이 파일의 초기 상태는 미결정이다. 테스트의 요구사항을 바꾸거나 가상의 실패를 만들지 않는다.
