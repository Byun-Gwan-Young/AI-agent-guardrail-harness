"""Exclusion and replacement list of the demo main run (C-18-7 part 1, DM-78, DM-79; C-18-8 part 1, DM-81). Rules
only; nobody picks sessions by hand, and the list is made the same way before and after the reruns.

  demo_exclusions.py --plan demo-main-v1 --plan demo-main-v1-lr2 --plan demo-main-v1-mr2 [--output <file>]

Sessions: every runs/demo/<id> whose conditions.json batch.plan_id is one of --plan. A session is excluded when one rule
holds (first match):
- env_search_unavailable : a DEMO-LR session of demo-main-v1 (DM-78 ③: arXiv returned 429 or timed out during the main
  run; every LR session of that plan goes, whatever its ending, and the LR supplement plan stands in for them)
- env_search_key_invalid : one of its search calls came back 401 or 403 (DM-81 ①: a mistyped search key; the
  search provider refused the key, so the session's searches say nothing about the task)
- incomplete_after_retry : ended in runner_error and is itself a rerun (batch.rerun_of): the second failure of an item,
  which is not run a third time (DM-79 ③, DM-81 ③). evidence.cause gives the 502/504 rule its failing turn fits
- env_upstream_timeout   : ended in runner_error on a 502 the proxy made itself (its body "Upstream connection failed",
  an httpx request error) after waiting at least the earlier 120 s limit (DM-79: proxy read limit)
- env_upstream_502       : ended in runner_error on a 502 the upstream sent
- run_interrupted        : ended in user_interrupted (the window was stopped by hand; not a model or provider result)
A first runner_error that fits neither 502 rule is listed under unresolved and not excluded; the tool then exits 1.
replaced_by: the session of these plans whose batch.rerun_of names this one (tools/run_batch.py --rerun-failed); else,
for an excluded session of a plan that is not a supplement, the session of a supplement plan (demo-main-v1-<x>) with
the same item (DM-78 ④, DM-81 ①). A supplement session for an item that still has another candidate (a rerun, a valid
session, a second supplement session) is listed under unresolved instead.
items: per plan item, the valid session(s), or the reason code of the last session tried when none is valid.
Sessions still running (no summary.json) are listed under unfinished and nothing is decided for them.

Read per session: conditions.json, summary.json (termination_reason, error line), search/records.jsonl (outcome and
HTTP status counts) and, for a runner_error, the failing turn of the proxy log (logs/demo/<id>.json, else the
session.json copy): status code, upstream wait and whether the proxy logged an empty body. No model text is read.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEMO_RUNS = ROOT / 'runs' / 'demo'
PROXY_LOGS = ROOT / 'logs' / 'demo'
VERSION = 'demo-exclusions-v2'
MAIN_PLAN = 'demo-main-v1'
SEARCH_TASK = 'DEMO-LR-'
KEY_REFUSED = (401, 403)  # the search provider refused the key (DM-81 ①)
PROXY_FAILURE = 'Upstream connection failed'  # proxy.py: the body of the 502 it makes on an httpx request error
EARLIER_LIMIT_MS = 120_000  # the proxy's upstream limit when the main run started (DM-79)
CODES = ('env_search_unavailable', 'env_search_key_invalid', 'incomplete_after_retry', 'env_upstream_timeout',
         'env_upstream_502', 'run_interrupted')
RULES = {
    'env_search_unavailable': f'{MAIN_PLAN} 의 DEMO-LR 세션 전체 (DM-78 ③, 종료 분류와 무관)',
    'env_search_key_invalid': '검색 호출 중 HTTP 401·403 (키 거절) 이 하나라도 있음 (DM-81 ①, 종료 분류와 무관)',
    'incomplete_after_retry': 'runner_error + 재실행 세션 (batch.rerun_of 있음) : 두 번째 실패, 세 번째는 돌리지 않음 '
                              '(DM-79 ③, DM-81 ③). 원인은 evidence.cause (502·504 규칙)',
    'env_upstream_timeout': 'runner_error + 프록시가 만든 502 ("Upstream connection failed") + 업스트림 대기 120 초 이상 (DM-79)',
    'env_upstream_502': 'runner_error + 업스트림이 보낸 502 (DM-78 ②)',
    'run_interrupted': 'user_interrupted 로 끝남 (창을 손으로 멈춤)',
}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def search_outcomes(folder):
    path = Path(folder) / 'search' / 'records.jsonl'
    if not path.is_file():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    return dict(sorted(Counter(f"{r.get('outcome')}:{r.get('http_status')}" for r in rows).items()))


def key_refusals(folder):
    path = Path(folder) / 'search' / 'records.jsonl'
    if not path.is_file():
        return 0
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    return sum(1 for r in rows if r.get('http_status') in KEY_REFUSED)


def failing_turn(session_id, folder, logs_root):
    """The last turn the proxy did not answer with 200 (block-mode refusals, 403, are not failures)."""
    path = Path(logs_root) / (session_id + '.json')
    if not path.is_file():
        path = Path(folder) / 'session.json'
    if not path.is_file():
        return None
    turns = [t for t in load(path).get('turns') or [] if t.get('status_code') not in (200, 403)]
    if not turns:
        return None
    turn = turns[-1]
    return {'turn': turn.get('turn'), 'status_code': turn.get('status_code'),
            'upstream_ms': round(turn.get('upstream_ms') or 0), 'empty_body': turn.get('response_body') == {}}


def runner_error_code(summary, turn):
    """(code or None, why)."""
    error = summary.get('error') or ''
    if turn is None:
        return None, 'no failing turn in the proxy log'
    if turn['status_code'] == 504:
        return 'env_upstream_504', None  # a cause only (incomplete_after_retry): the gateway cut the wait (DM-81 ③)
    if turn['status_code'] != 502:
        return None, f"failing turn status {turn['status_code']}"
    made_by_proxy = PROXY_FAILURE in error
    if made_by_proxy and turn['empty_body'] and turn['upstream_ms'] >= EARLIER_LIMIT_MS:
        return 'env_upstream_timeout', None
    if not made_by_proxy:
        return 'env_upstream_502', None
    return None, f"proxy-made 502 after {turn['upstream_ms']} ms (below the {EARLIER_LIMIT_MS} ms limit)"


def sessions_of(plans, runs_root):
    found = []
    for folder in sorted(Path(runs_root).iterdir()) if Path(runs_root).is_dir() else []:
        conditions_path = folder / 'conditions.json'
        if not conditions_path.is_file():
            continue
        conditions = load(conditions_path)
        batch = conditions.get('batch') or {}
        if batch.get('plan_id') in plans:
            found.append((folder, conditions, batch))
    return found


def build(plans, *, runs_root=DEMO_RUNS, logs_root=PROXY_LOGS):
    plans = sorted(set(plans))
    entries, unfinished, unresolved = {}, [], []
    for folder, conditions, batch in sessions_of(plans, runs_root):
        session_id = folder.name
        scenario_id = (conditions.get('scenario') or {}).get('scenario_id') or session_id.rsplit('-', 1)[0]
        base = {'plan_id': batch['plan_id'], 'item': batch.get('item'), 'lane': batch.get('lane'),
                'account_label': conditions.get('account_label'), 'rerun_of': batch.get('rerun_of'),
                'git_commit': conditions.get('git_commit'), 'git_dirty': conditions.get('git_dirty')}
        summary_path = folder / 'summary.json'
        if not summary_path.is_file():
            unfinished.append({'session_id': session_id, **base})
            continue
        summary = load(summary_path)
        reason = summary.get('termination_reason')
        entry = {**base, 'termination_reason': reason, 'steps': summary.get('steps'), 'excluded': None,
                 'replaced_by': None, 'evidence': {}, 'notes': []}
        outcomes = search_outcomes(folder)
        if outcomes or scenario_id.startswith(SEARCH_TASK):
            entry['evidence']['search_outcomes'] = outcomes
        if scenario_id.startswith(SEARCH_TASK) and not outcomes:
            entry['notes'].append('no_search_attempt')
        if batch['plan_id'] == MAIN_PLAN and scenario_id.startswith(SEARCH_TASK):
            entry['excluded'] = 'env_search_unavailable'
        elif key_refusals(folder):
            entry['excluded'] = 'env_search_key_invalid'
        elif reason == 'runner_error':
            turn = failing_turn(session_id, folder, logs_root)
            entry['evidence']['failing_turn'] = turn
            entry['evidence']['runner_error'] = (summary.get('error') or '')[:200]
            code, why = runner_error_code(summary, turn)
            if batch.get('rerun_of'):
                entry['excluded'] = 'incomplete_after_retry'
                entry['evidence']['cause'] = {'code': code, 'why': why}
            elif code == 'env_upstream_504':
                unresolved.append({'session_id': session_id, 'why': 'failing turn status 504 (first failure)'})
            else:
                entry['excluded'] = code
                if code is None:
                    unresolved.append({'session_id': session_id, 'why': why})
        elif reason == 'user_interrupted':
            entry['excluded'] = 'run_interrupted'
        entries[session_id] = entry
    for session_id, entry in entries.items():
        if entry['rerun_of'] in entries:
            entries[entry['rerun_of']]['replaced_by'] = session_id
    supplement_replacements(entries, unresolved)
    valid = Counter()
    for entry in entries.values():
        if entry['excluded'] is None:
            valid[entry['item']] += 1
    items = sorted({e['item'] for e in entries.values()} | {u['item'] for u in unfinished})
    counts = Counter(e['excluded'] for e in entries.values() if e['excluded'])
    return {'exclusions_version': VERSION, 'plans': plans, 'rules': RULES,
            'sessions': dict(sorted(entries.items())),
            'counts': {'sessions': len(entries), 'excluded': sum(counts.values()),
                       'by_code': {code: counts.get(code, 0) for code in CODES},
                       'replaced': sum(1 for e in entries.values() if e['replaced_by']),
                       'unfinished': len(unfinished), 'unresolved': len(unresolved)},
            'items_without_valid_session': [i for i in items if not valid[i]],
            'items': item_states(entries, items, unfinished),
            'git_commits': dict(Counter(f"{e['git_commit']} dirty={e['git_dirty']}" for e in entries.values())),
            'unfinished': unfinished, 'unresolved': unresolved}


def is_supplement(plan_id):
    return plan_id != MAIN_PLAN and plan_id.startswith(MAIN_PLAN + '-')


def supplement_replacements(entries, unresolved):
    """An excluded session of a plan that is not a supplement, with no rerun, is replaced by the supplement session of
    the same item. A supplement session with any other candidate for its item is unresolved instead."""
    for supplement_id, supplement in sorted(entries.items()):
        if not is_supplement(supplement['plan_id']) or supplement['rerun_of']:
            continue
        item = supplement['item']
        others = {k: e for k, e in entries.items() if e['item'] == item and k != supplement_id}
        siblings = sorted(k for k, e in others.items() if is_supplement(e['plan_id']) and not e['rerun_of'])
        valid = sorted(k for k, e in others.items() if not is_supplement(e['plan_id']) and e['excluded'] is None)
        open_ends = sorted(k for k, e in others.items()
                           if not is_supplement(e['plan_id']) and e['excluded'] and e['replaced_by'] is None)
        why = (f'several supplement sessions for {item}: {siblings}' if siblings
               else f'{item} already has a valid session: {valid}' if valid
               else f'{item} has no excluded session left to replace' if not open_ends
               else f'{item} has several excluded sessions without a replacement: {open_ends}'
               if len(open_ends) > 1 else None)
        if why:
            unresolved.append({'session_id': supplement_id, 'why': why})
            continue
        entries[open_ends[0]]['replaced_by'] = supplement_id


def item_states(entries, items, unfinished):
    """Per item: the valid session(s), else the code of the session(s) nothing replaced (the last one tried)."""
    states = {}
    running = {u['item'] for u in unfinished}
    for item in items:
        tried = {k: e for k, e in entries.items() if e['item'] == item}
        valid = sorted(k for k, e in tried.items() if e['excluded'] is None)
        if valid:
            states[item] = {'state': 'valid', 'sessions': valid}
        elif item in running:
            states[item] = {'state': 'unfinished', 'sessions': []}
        else:
            ends = sorted(k for k, e in tried.items() if e['replaced_by'] is None)
            states[item] = {'state': 'no_valid_session', 'sessions': ends,
                            'codes': sorted({tried[k]['excluded'] for k in ends})}
    return states


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--plan', action='append', required=True)
    parser.add_argument('--runs-root', type=Path, default=DEMO_RUNS)
    parser.add_argument('--logs-root', type=Path, default=PROXY_LOGS)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = build(args.plan, runs_root=args.runs_root, logs_root=args.logs_root)
    text = json.dumps(result, ensure_ascii=False, indent=1) + '\n'
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(json.dumps({'counts': result['counts'], 'items_without_valid_session': result['items_without_valid_session'],
                      'git_commits': result['git_commits'], 'unfinished': [u['session_id'] for u in result['unfinished']],
                      'unresolved': result['unresolved']}, ensure_ascii=False, indent=1))
    return 1 if result['unresolved'] else 0


if __name__ == '__main__':
    sys.exit(main())
