"""C-17-8 evidence, from files only (no network; no model reasoning text is read or written).

search: the PM search probe search-probe-46ec37a0… (2026-10-02) — the arXiv and Tavily shape comparison against the
        fixtures as committed before C-17-8 and as they are now, and the D-11 secret scan of the probe folder before it
        is committed (patterns, the Tavily pattern, and the TAVILY_API_KEY value when it is set here).
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.analyze_session import SEARCH_KEY_ENVS, SEARCH_SECRET_PATTERNS, secret_scan  # noqa: E402
from tools import probe_search  # noqa: E402

SEARCH_PROBE = ROOT / 'runs/search-probes/search-probe-46ec37a046664b988be9e3075ce43c89'
FIXTURES = {'tavily': 'tests/fixtures/search/tavily-search-200.json', 'arxiv': 'tests/fixtures/search/arxiv-query-200.xml'}
RESPONSES = {'tavily': 'tavily-response.json', 'arxiv': 'arxiv-response.xml'}
# The fixtures as they were when the probe ran (last commit before C-17-8).
BEFORE = '4d425e5'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def committed(revision, path):
    return subprocess.run(['git', 'show', revision + ':' + path], cwd=ROOT, capture_output=True, check=True).stdout


def search_evidence():
    result = load(SEARCH_PROBE / 'result.json')
    providers = {}
    for provider, fixture in FIXTURES.items():
        live = (SEARCH_PROBE / RESPONSES[provider]).read_bytes()
        recorded = result['providers'][provider]
        providers[provider] = {
            'http_status': recorded['http_status'], 'normalized': recorded['normalized'],
            'probe_recorded_shape': recorded['shape'],
            'shape_against_fixture_before': probe_search.compare(provider, live, committed(BEFORE, fixture)),
            'shape_against_fixture_now': probe_search.compare(provider, live, (ROOT / fixture).read_bytes())}
    return {'folder': SEARCH_PROBE.relative_to(ROOT).as_posix(), 'probe_id': result['probe_id'],
            'requests_sent': result['requests_sent'], 'all_ok_recorded': result['all_ok'], 'providers': providers,
            'secret_scan': secret_scan([SEARCH_PROBE], set(SEARCH_KEY_ENVS), SEARCH_SECRET_PATTERNS)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('part', choices=('search',))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = search_evidence()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    arxiv = evidence['providers']['arxiv']
    print(json.dumps({'arxiv_missing_before': arxiv['shape_against_fixture_before']['missing_in_response'],
                      'arxiv_same_shape_now': arxiv['shape_against_fixture_now']['same_shape'],
                      'tavily_same_shape_now': evidence['providers']['tavily']['shape_against_fixture_now']['same_shape'],
                      'secret_scan': {k: evidence['secret_scan'][k] for k in
                                      ('files_scanned', 'environment_variables_checked', 'clean')}},
                     ensure_ascii=False, indent=1))
    return 0 if evidence['secret_scan']['clean'] else 2


if __name__ == '__main__':
    sys.exit(main())
