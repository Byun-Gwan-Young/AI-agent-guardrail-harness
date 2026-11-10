"""Export the existing demo's curated records without modifying its source."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def collect_reference():
    source = ROOT / 'tools' / 'demo_ui.py'
    # strftime %-m/%-d is not supported on Windows. Only this in-memory copy changes.
    code = source.read_text(encoding='utf-8').replace('%-m/%-d', '%m/%d')
    scope = {'__name__': 'frontend_reference_export', '__file__': str(source)}
    exec(compile(code, str(source), 'exec'), scope)
    aggregate = json.loads((ROOT / 'reports/c19/aggregate-main.json').read_text(encoding='utf-8'))
    return scope['collect'](aggregate, runs_root=ROOT / 'runs/demo', root=ROOT)

if __name__ == '__main__':
    target = ROOT / 'frontend/public/records.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    data = collect_reference()
    target.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'Exported {len(data["sessions"])} curated demo sessions.')
