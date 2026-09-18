"""Offline three-stage replay. Never infer historical artifact snapshots."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artifact_hook import make_observation
from deadlock_policy import evaluate_criteria
from experiments.observation_collection import INDEPENDENT, PROTOCOLS, collection_metadata, validate_final_response
from experiments.run_scenario import termination_context
from progress_signal import calculate_progress
from scenario_schema import load_scenario
from tools import replay_role_progress as p01


def replay(log, scenario, saved_p01):
    rules = {a.id: a.system_message.strip().splitlines()[0] for a in scenario.agents}
    previous = p01.replay(log, rules)
    for field in ('rows', 'summary', 'new_pin', 'legacy_byte_match'):
        if p01.encoded(previous[field]) != p01.encoded(saved_p01[field]):
            raise p01.LegacyMismatch('saved P0-1 differs: ' + field)
    turns = {t['turn']: t for t in log['turns']}
    history, rows, first = [], [], None
    for original, prior in zip(log['observations'], previous['rows']):
        linked = original['llm_turns']
        last = max(linked) if linked else None
        turn = turns.get(last, {})
        receipt = validate_final_response(request=turn.get('request_body'),
            response=turn.get('response_body'), status_code=turn.get('status_code'),
            turn=turn.get('turn'), step_turns=linked)
        current = {k: copy.deepcopy(v) for k, v in original.items() if k not in ('progress', 'criteria')}
        current['agent_id'] = prior['role_mapping']['agent_id']
        gap = p01.discarded(original)
        parsed = copy.deepcopy(receipt['value'])
        if parsed is not None:
            parsed.update(agent_id=current['agent_id'], step_id=current['step_id'])
        first, termination = termination_context(first, parsed, current['step_id'],
            scenario.termination_context_collection.declarer_agent)
        restored = gap and parsed is not None
        if restored:
            current = make_observation(step_id=current['step_id'], agent_id=current['agent_id'],
                llm_turns=linked, text=parsed['narrative'], progress_source=current['progress_source'],
                progress_metric=current['progress_metric'], artifact=original.get('artifact'),
                structured={k: parsed[k] for k in ('open_issue_ids', 'info_items')},
                termination_context=termination)
        # Previously collected values remain byte-for-byte input values. No workspace read.
        metadata = collection_metadata(INDEPENDENT, receipt, current.get('conversation'),
            current.get('artifact'), current['progress_source'], current['progress_metric'])
        current['collection'] = metadata
        current['progress'] = calculate_progress(history, current, version='progress-v2')
        result = {'progress': current['progress'],
                  'criteria': evaluate_criteria(history + [current], previous['new_pin'])}
        row = {'step_id': current['step_id'], 'agent_id': current['agent_id'],
               'original': prior['old'], 'p0_1': prior['new'], 'p0_2': result,
               'original_discarded': gap, 'conversation_restored': restored,
               'final_receipt': receipt, 'observation': copy.deepcopy(current),
               'artifact_status': 'unmeasured' if current.get('artifact') is None else 'stored_snapshot',
               'p0_1_classification': prior['classification']}
        rows.append(row); history.append(current)
    return {'legacy_byte_match': True, 'p0_1_saved_match': True,
            'collection_policy': INDEPENDENT, 'runner_protocol': PROTOCOLS[INDEPENDENT],
            'pin': previous['new_pin'], 'rows': rows,
            'summary': {'steps': len(rows),
                'conversation_restored_steps': [r['step_id'] for r in rows if r['conversation_restored']],
                'discarded_not_restored_steps': [r['step_id'] for r in rows if r['original_discarded'] and not r['conversation_restored']],
                'discarded_artifact_null_steps': [r['step_id'] for r in rows if r['original_discarded'] and r['observation'].get('artifact') is None],
                'progress_state_changed_steps': [r['step_id'] for r in rows if r['p0_1']['progress']['state'] != r['p0_2']['progress']['state']],
                'actual_stop_step': {'value': None, 'status': 'unmeasured'},
                'measured_detection_latency': {'value': None, 'status': 'unmeasured'}}}


def markdown(report):
    lines = ['# P0-2 3단계 오프라인 비교', '',
        '원본 → P0-1 → P0-2. 회복된 대화만 복원하며 폐기된 산출물은 null/unmeasured다.',
        '실제 실행 재현/세션 유효성 판정이 아니다. G0-5 우선순위는 변경하지 않았다.', '',
        '| step | progress 원본 → P0-1 → P0-2 | criteria 원본 → P0-1 → P0-2 | 대화 복원 | 원본 turn | 산출물 |',
        '|---|---|---|---|---|---|']
    for r in report['rows']:
        states = ' → '.join(r[k]['progress']['state'] for k in ('original','p0_1','p0_2'))
        decisions = ' → '.join(r[k]['criteria']['decision'] for k in ('original','p0_1','p0_2'))
        recovery = '복원' if r['conversation_restored'] else '미복원' if r['original_discarded'] else '기존 유지'
        lines.append(f"| {r['step_id']} | {states} | {decisions} | {recovery} | {r['final_receipt']['source_turn']} | {r['artifact_status']} |")
    lines += ['', '## 자동 집계', '', '```json', json.dumps(report['summary'],ensure_ascii=False,indent=2), '```', '',
              'replay.json은 단계별 전체 판정·이벤트·지표 누락 사유·관측·최종 출력 원문 연결을 보관한다.',
              'P0-4 info_items null과 직전 동일 역할의 누락은 progress.metrics의 unmeasured 사유로 구분한다.',
              '공유 산출물 재관측은 p0_1_classification.shared_artifact_events에 남긴다.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--scenario', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.previous.resolve().parent:
        raise ValueError('Do not overwrite previous replay directory')
    raw = args.input.read_bytes(); previous_raw = args.previous.read_bytes()
    report = replay(json.loads(raw), load_scenario(args.scenario), json.loads(previous_raw))
    report.update(input_path=str(args.input), input_sha256=p01.digest(raw),
                  previous_path=str(args.previous), previous_sha256=p01.digest(previous_raw),
                  scenario_sha256=p01.digest(args.scenario.read_bytes()))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    table = markdown(report)
    (args.output / 'comparison.md').write_text(table)
    print(json.dumps({'legacy_byte_match': report['legacy_byte_match'],
                      'p0_1_saved_match': report['p0_1_saved_match'], **report['summary']},ensure_ascii=False))
    print(table)


if __name__ == '__main__':
    main()
