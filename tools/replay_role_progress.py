"""Offline, immutable replay with a mandatory stored-v1 byte equivalence gate."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deadlock_policy import evaluate_criteria, pin_criteria
from progress_signal import calculate_progress
from scenario_schema import load_scenario


class LegacyMismatch(ValueError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify_legacy(log):
    history = []
    results = []
    for original in log['observations']:
        current = {k: copy.deepcopy(v) for k, v in original.items() if k not in ('progress', 'criteria')}
        progress = calculate_progress(history, current, version='progress-v1')
        current['progress'] = progress
        criteria = evaluate_criteria(history + [current], log['meta'])
        for field, actual in [('progress', progress), ('criteria', criteria)]:
            if encoded(actual) != encoded(original.get(field)):
                raise LegacyMismatch(f"step {original['step_id']}: stored {field} differs from v1 replay")
        results.append({'progress': progress, 'criteria': criteria})
        history.append(current)
    return results


def identify_agent(observation, turns, rules):
    evidence = []
    for turn_id in observation['llm_turns']:
        turn = turns.get(turn_id, {})
        for index, message in enumerate((turn.get('request_body') or {}).get('messages', [])):
            if message.get('role') != 'system' or not isinstance(message.get('content'), str):
                continue
            content = message['content']
            for agent_id, prefix in rules.items():
                if prefix and (content == prefix or content.startswith(prefix + '\n')):
                    evidence.append({'agent_id': agent_id, 'turn': turn_id,
                                     'path': f'request_body.messages[{index}].content', 'prefix': prefix})
    candidates = {item['agent_id'] for item in evidence}
    return {'agent_id': next(iter(candidates)) if len(candidates) == 1 else None,
            'status': 'measured' if len(candidates) == 1 else 'unmeasured',
            'method': 'unique_request_system_prefix', 'evidence': evidence}


def discarded(observation):
    if observation is None:
        return False
    conversation = observation.get('conversation') or {}
    return (observation.get('artifact') is None
            and conversation.get('reasons', {}).get('output') == 'invalid or missing structured output'
            and all(conversation.get(k) is None for k in ('proposal_values', 'open_issue_ids', 'info_items')))


def info_missing(observation):
    if observation is None:
        return False
    return ('new_info_ratio' in observation['progress_metric'].get('conversation', [])
            and (observation.get('conversation') or {}).get('info_items') is None)


def nonrecurrent(events):
    return [e for e in events if e['kind'] not in ('oscillation', 'reopen', 'revert')]


def classify(original, old_result, current, new_result, previous_global, previous_role, history):
    issue_metric = 'conversation.open_issues_count'
    old_events = old_result['progress'].get('events', [])
    cross_role = bool(previous_global and current.get('agent_id') and previous_global.get('agent_id')
                      and current['agent_id'] != previous_global['agent_id'])
    issue_events = [e for e in old_events if e['metric'] == issue_metric] if cross_role else []
    causes = nonrecurrent(old_events)
    issue_only = (old_result['progress']['state'] == 'progress' and bool(issue_events)
                  and bool(causes) and all(e['metric'] == issue_metric for e in causes))
    old_ids = (previous_role.get('conversation') or {}).get('open_issue_ids') if previous_role else None
    new_ids = (current.get('conversation') or {}).get('open_issue_ids')
    same_role_ids_changed = (set(old_ids) != set(new_ids)) if old_ids is not None and new_ids is not None else None
    shared = []
    artifact = current.get('artifact') or {}
    for event in new_result['progress'].get('events', []):
        if not event['metric'].startswith('artifact.'):
            continue
        matches = []
        for earlier in history:
            other = earlier.get('artifact') or {}
            if previous_role and earlier['step_id'] <= previous_role['step_id']:
                continue
            if earlier.get('agent_id') == current.get('agent_id'):
                continue
            if event['metric'] == 'artifact.files_changed':
                key = event['item']
                same = (other.get('file_hashes') is not None and artifact.get('file_hashes') is not None
                        and other.get('files_scope_id') == artifact.get('files_scope_id')
                        and other['file_hashes'].get(key) == artifact['file_hashes'].get(key))
            elif event['metric'] == 'artifact.test_pass_count':
                same = (other.get('test_suite_id') == artifact.get('test_suite_id')
                        and other.get('test_total_count') == artifact.get('test_total_count')
                        and other.get('test_pass_count') == artifact.get('test_pass_count'))
            else:
                same = other.get('build_status') == artifact.get('build_status')
            if same:
                matches.append(earlier['step_id'])
        if matches:
            shared.append({'event': event, 'previous_global_observations': matches})
    return {'cross_role_issue_events': issue_events,
            'old_progress_issue_only': issue_only,
            'old_progress_mixed_causes': bool(issue_events and causes and not issue_only),
            'same_role_issue_set_changed': {'value': same_role_ids_changed,
                                          'status': 'measured' if same_role_ids_changed is not None else 'unmeasured'},
            'issue_only_progress_removed': issue_only and new_result['progress']['state'] != 'progress',
            'current_discarded_gap': discarded(current),
            'previous_same_role_discarded_gap': discarded(previous_role),
            'current_info_items_null': info_missing(current),
            'previous_same_role_info_items_null': info_missing(previous_role),
            'shared_artifact_events': shared,
            'missing_metrics': {k: v.get('reason') for k, v in new_result['progress'].get('metrics', {}).items()
                                if v.get('status') == 'unmeasured'}}


def replay(log, rules):
    # This gate completes for ALL rows before any new-version calculation.
    legacy = verify_legacy(log)
    turns = {t['turn']: t for t in log['turns']}
    history = []; rows = []; pin = pin_criteria('deadlock-v0.2')
    for original, old in zip(log['observations'], legacy):
        role = identify_agent(original, turns, rules)
        current = {k: copy.deepcopy(v) for k, v in original.items() if k not in ('progress', 'criteria')}
        current['agent_id'] = role['agent_id']
        previous_role = next((o for o in reversed(history) if role['agent_id'] is not None
                              and o.get('agent_id') == role['agent_id']), None)
        progress = calculate_progress(history, current, version='progress-v2')
        current['progress'] = progress
        new = {'progress': progress, 'criteria': evaluate_criteria(history + [current], pin)}
        row = {'step_id': current['step_id'], 'role_mapping': role,
               'old_comparison_step_id': history[-1]['step_id'] if history else None,
               'new_comparison_step_id': progress.get('comparison_step_id'),
               'old': old, 'new': new,
               'classification': classify(original, old, current, new, history[-1] if history else None,
                                          previous_role, history)}
        rows.append(row); history.append(current)
    candidates = [r for r in rows if r['classification']['old_progress_issue_only']]
    removed = [r for r in candidates if r['classification']['issue_only_progress_removed']]
    unresolved = [r for r in rows if r['role_mapping']['status'] == 'unmeasured']
    retained = [r for r in candidates if not r['classification']['issue_only_progress_removed']]
    return {'legacy_byte_match': True, 'new_pin': pin, 'rows': rows,
            'summary': {'steps': len(rows), 'cross_role_issue_progress_candidates': len(candidates),
                        'removed': len(removed), 'retained': len(retained), 'unresolved_roles': len(unresolved),
                        'p0_1_success': bool(candidates) and not retained and not unresolved,
                        'shared_artifact_steps': [r['step_id'] for r in rows if r['classification']['shared_artifact_events']],
                        'first_deadlock_step': rows[-1]['new']['criteria']['first_deadlock_step'] if rows else None,
                        'first_termination_failure_step': rows[-1]['new']['criteria']['first_termination_failure_step'] if rows else None,
                        'measured_detection_latency': {'value': None, 'status': 'unmeasured'},
                        'actual_stop_step': {'value': None, 'status': 'unmeasured'}}}


def explanation(row):
    c = row['classification']; reasons = []
    if c['issue_only_progress_removed']: reasons.append('역할 간 ID만으로 생긴 progress 제거')
    elif c['old_progress_mixed_causes']: reasons.append('기존 ID 변화 + 독립 변화 혼합')
    if row['new']['progress']['state'] == 'baseline': reasons.append('역할 첫 관측')
    if c['shared_artifact_events']: reasons.append('공유 산출물 변경 재관측')
    elif row['new']['progress'].get('artifact_moved'): reasons.append('산출물 변화')
    if c['current_discarded_gap']: reasons.append('P0-2 현재 관측 폐기')
    elif c['previous_same_role_discarded_gap']: reasons.append('P0-2 직전 동일 역할 공백')
    if not c['current_discarded_gap'] and c['current_info_items_null']: reasons.append('P0-4 현재 info_items null')
    if not c['previous_same_role_discarded_gap'] and c['previous_same_role_info_items_null']:
        reasons.append('P0-4 직전 동일 역할 info_items null')
    if c['same_role_issue_set_changed']['value'] is True: reasons.append('동일 역할 쟁점 집합 변화')
    if row['new']['progress']['state'] == 'stagnant': reasons.append('동일 역할 관측 변화 없음')
    if c['missing_metrics'] and row['new']['progress']['state'] == 'progress':
        reasons.append('기존 progress 우선순위 유지')
    if row['role_mapping']['status'] == 'unmeasured': reasons.append('역할 식별 불가')
    return '; '.join(reasons) or '기존 비교 의미 유지'


def markdown(report):
    lines = ['# P0-1 역할별 비교 replay', '',
             '원본 SHA-256: `' + report['input_sha256'] + '`',
             'v1 저장 결과 바이트 일치: `' + str(report['legacy_byte_match']) + '`', '',
             '재현 범위: 저장된 관측의 비교 대상만 변경. 역할 매핑은 요청 시스템 메시지의 명시적 접두문으로 복원했다.',
             '원본 판정·null·종결 문맥은 보존한다. 경보 없음은 실패 기준이 아니다.', '',
             '| step | 역할 | 기존→새 비교 step | progress 기존→새 | criteria 기존→새 | 원인 |',
             '|---|---|---|---|---|---|']
    for row in report['rows']:
        old, new = row['old'], row['new']
        lines.append(f"| {row['step_id']} | {row['role_mapping']['agent_id']} | {row['old_comparison_step_id']} → {row['new_comparison_step_id']} | {old['progress']['state']} → {new['progress']['state']} | {old['criteria']['decision']} → {new['criteria']['decision']} | {explanation(row)} |")
    lines += ['', '## 자동 집계', '', '```json', json.dumps(report['summary'],ensure_ascii=False,indent=2), '```', '',
              '판독 규칙: docs/P0-1-replay-protocol.md. 상세 이벤트·누락 사유·역할 매핑 근거는 replay.json에 있다.',
              '공유 산출물 재관측은 해당 역할이 파일을 수정했다는 뜻이 아니다. 실측 탐지 성능/실제 STOP은 미측정이다.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--scenario', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes(); scenario_raw = args.scenario.read_bytes()
    scenario = load_scenario(args.scenario)
    rules = {a.id: a.system_message.strip().splitlines()[0] for a in scenario.agents}
    report = replay(json.loads(raw), rules)
    report.update(input_path=str(args.input), input_sha256=digest(raw),
                  role_rules_path=str(args.scenario), role_rules_sha256=digest(scenario_raw), role_rules=rules,
                  protocol_sha256=digest((ROOT / 'docs/P0-1-replay-protocol.md').read_bytes()))
    if args.input.read_bytes() != raw:
        raise RuntimeError('Input changed during replay')
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output / 'comparison.md').write_text(markdown(report),encoding='utf-8')
    print(json.dumps({'legacy_byte_match': report['legacy_byte_match'], **report['summary']},ensure_ascii=False))


if __name__ == '__main__':
    main()
