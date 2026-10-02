# Search response fixtures (C-17-6)

Offline test inputs for `experiments/search_tools.py` and `tools/probe_search.py`. The **shapes** follow the
providers' documentation as read on 2026-10-02; the **content** is synthetic (example.com/.org/.net URLs, invented
arXiv IDs and titles). Nothing here came from a real API call. The real shapes are checked by the PM with
`tools/probe_search.py`, which compares a live response with these files.

| File | Shape source |
|---|---|
| `tavily-search-200.json` | Tavily Search API reference, `POST https://api.tavily.com/search`, 200 response example (https://docs.tavily.com/documentation/api-reference/endpoint/search). Top level `query`, `answer`, `images`, `results`, `response_time`, `request_id`; result items `title`, `url`, `content`, `score`, `raw_content`. Fields the reference shows only for options this tool does not request (`favicon`, `published_date`, item `images`, `usage`) are left out |
| `tavily-error-432.json` | Same reference, error status codes (432 plan limit). The `{"detail": {"error": ...}}` body form is an assumption to check with the probe |
| `arxiv-query-200.xml` | arXiv API User's Manual (https://info.arxiv.org/help/api/user-manual.html), Atom response: feed `link`, `title`, `id`, `updated`, `opensearch:totalResults`/`startIndex`/`itemsPerPage`; entry `id`, `updated`, `published`, `title`, `summary`, `author/name`, `arxiv:affiliation`, `link` (alternate, pdf), `arxiv:primary_category`, `category`, `arxiv:comment`, `arxiv:journal_ref`, `arxiv:doi` |
| `arxiv-error-400.xml` | Same manual, errors section: an Atom feed with one entry whose `id` is under `http://arxiv.org/api/errors` and whose `summary` is the message |
