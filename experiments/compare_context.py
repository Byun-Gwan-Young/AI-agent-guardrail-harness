"""Offline buffered/unbuffered prompt-token comparison; no model requests."""
import argparse
import csv
import html
import json
from pathlib import Path


def compare(left, right, output):
    output.mkdir(parents=True, exist_ok=False)
    rows, conditions, series = [], [], []
    for label, root in [('buffered', left), ('unbuffered', right)]:
        conditions.append(json.loads((root / 'conditions.json').read_text(encoding='utf-8')))
        trace = json.loads((root / 'prompt-trend.json').read_text(encoding='utf-8'))
        points = []
        for step in trace:
            for turn, tokens in zip(step['llm_turns'], step['prompt_tokens_per_call']):
                rows.append({'run': label, 'step_id': step['step_id'], 'agent': step['agent'],
                             'llm_turn': turn, 'prompt_tokens': tokens})
                points.append((turn, tokens))
        series.append(points)
    with (output / 'prompt-comparison.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['run', 'step_id', 'agent', 'llm_turn', 'prompt_tokens'])
        writer.writeheader(); writer.writerows(rows)
    ignored = {'session_id', 'run_index', 'context_buffer_messages'}
    normalized = [{k: v for k, v in c.items() if k not in ignored} for c in conditions]
    result = {'context_buffers': [c.get('context_buffer_messages') for c in conditions],
              'other_conditions_equal': normalized[0] == normalized[1],
              'warning': 'Different context conditions; not a determinism test or causal performance estimate.',
              'missing_prompt_tokens': [sum(y is None for _, y in s) for s in series]}
    (output / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    xmax = max([x for s in series for x, _ in s] + [1])
    ymax = max([y for s in series for _, y in s if y is not None] + [1])
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="900" height="420" viewBox="0 0 900 420">',
           '<rect width="900" height="420" fill="white"/>',
           '<text x="60" y="25">Observed prompt tokens per LLM call (missing values are gaps)</text>',
           '<path d="M60 50V350H850" fill="none" stroke="black"/>',
           f'<text x="5" y="55">{ymax}</text><text x="20" y="350">0</text>',
           f'<text x="60" y="375">LLM turn 1</text><text x="800" y="375">{xmax}</text>']
    for index, (label, color) in enumerate([('buffered', '#2563eb'), ('unbuffered', '#dc2626')]):
        commands = []
        previous = False
        for x, y in series[index]:
            if y is None:
                previous = False
                continue
            px, py = 60 + (x - 1) / max(1, xmax - 1) * 790, 350 - y / ymax * 300
            commands.append(('L' if previous else 'M') + f'{px:.2f},{py:.2f}')
            previous = True
            svg.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="3" fill="{color}"/>')
        svg.append(f'<path d="{" ".join(commands)}" fill="none" stroke="{color}" stroke-width="2"/>')
        svg.append(f'<text x="{60 + index * 280}" y="405" fill="{color}">{html.escape(label)}</text>')
    svg.append('</svg>')
    (output / 'prompt-comparison.svg').write_text('\n'.join(svg), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('buffered_run', type=Path)
    parser.add_argument('unbuffered_run', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.buffered_run, args.unbuffered_run, args.output), indent=2))
