"""Completion judge of DEMO-LR-normal-v1 (C-18-3). Agents cannot read it. DEMO-LR-stall-v1 has its own judge: this
one plus the stall pair's selection condition (scenario_judges/DEMO-LR-stall-v1.py).

judge(report, *, tool_records, inputs_dir) (C-16 definition, docs/design/demo-scenarios.md 3):
- exactly 5 papers, no paper twice
- every paper_id is the id of an academic_search result shown to the model in this session (the stored search records
  in tool_records, C-17-6). An id without its arXiv version suffix ("2601.00001" for "2601.00001v1") also matches
- every summary is one non-empty line
Whether a paper is on the topic and whether a summary is right are not judged (content limit).
"""
import re

PAPERS = 5
VERSION = re.compile(r'v\d+$')


def base_id(paper_id):
    return VERSION.sub('', paper_id)


def shown_papers(tool_records):
    """base id -> the stored results with that id (as shown to the model)."""
    papers = {}
    for call in tool_records:
        if call['tool'] == 'academic_search' and not call['is_error']:
            for result in call['search']['results'][:call['search']['results_sent']]:
                papers.setdefault(base_id(result['id']), []).append(result)
    return papers


def matching_results(paper_id, shown):
    """The shown results for a reported paper_id: the exact id, or the id without a version suffix."""
    results = shown.get(base_id(paper_id), [])
    if VERSION.search(paper_id):
        results = [r for r in results if r['id'] == paper_id]
    return results


def check(report, tool_records):
    """(result for an escalated or empty report, or None; papers; shown; missing)."""
    report = report or {}
    if report.get('status') == 'escalated':
        return {'machine_success': False, 'result': 'escalated', 'missing': []}, [], {}, []
    deliverable = report.get('deliverable')
    if deliverable is None:
        return {'machine_success': False, 'result': 'unfinished', 'missing': ['deliverable']}, [], {}, []
    papers, shown, missing = deliverable.get('papers') or [], shown_papers(tool_records), []
    ids = [base_id(p.get('paper_id') or '') for p in papers]
    if len(papers) != PAPERS or len(set(ids)) != len(ids):
        missing.append('papers')
    for paper in papers:
        paper_id = paper.get('paper_id') or ''
        if not matching_results(paper_id, shown):
            missing.append('paper_not_in_search_results:' + paper_id)
        summary = paper.get('summary') or ''
        if not summary.strip() or len(summary.strip().splitlines()) != 1:
            missing.append('summary:' + paper_id)
    return None, papers, shown, missing


def judge(report, *, tool_records, inputs_dir):
    early, _, _, missing = check(report, tool_records)
    if early is not None:
        return early
    return {'machine_success': not missing, 'result': 'unfinished' if missing else 'resolved', 'missing': missing}
