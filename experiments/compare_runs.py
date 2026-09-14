"""Compare two manually executed runs without calling a model."""
import argparse
import json
from pathlib import Path


def read(root, name):
    return json.loads((root / name).read_text(encoding='utf-8'))


def compare(left, right):
    conditions = []
    outputs = []
    for root in (left, right):
        value = read(root, 'conditions.json')
        conditions.append({k: v for k, v in value.items() if k not in ('session_id', 'run_index')})
        steps = read(root, 'steps.json')
        outputs.append([{'agent': s['agent'], 'text': s['text'], 'llm_calls': s['llm_calls'],
                         'file_hashes': s['acceptance']['artifact']['file_hashes'],
                         'suite_id': s['acceptance']['artifact']['test_suite_id'],
                         'test_summary': s['acceptance']['summary']} for s in steps])
    return {'same_conditions': conditions[0] == conditions[1],
            'same_observed_outputs': outputs[0] == outputs[1],
            'step_counts': [len(x) for x in outputs],
            'note': 'Two equal outputs do not prove determinism. IDs, clocks and absolute report paths are excluded.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.left, args.right), ensure_ascii=False, indent=2))
