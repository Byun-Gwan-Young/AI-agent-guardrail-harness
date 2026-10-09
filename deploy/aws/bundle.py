"""C-19-7 (DM-91 ⑤) : the server bundle — only committed files of one git ref, checked before anything leaves the Mac.

  venv/bin/python -B deploy/aws/bundle.py build --out DIR [--ref main]

1. `git archive <ref>` of the INCLUDE paths minus the EXCLUDE paths (both lists below) : the query API (service/), the
   storage layer (storage/), the few modules they import, and the small committed demo records the loader and the API
   read. The proxy, the runner, the batch runner, keys, raw session logs, docs/handoff and venv never go.
2. The demo screen is built on the Mac with `tools/demo_ui.py build --api` from a full `git archive <ref>` in a temporary
   folder (the build reads the proxy code and configuration for the system page ; those files stay on the Mac) and goes
   into the bundle as site/index.html.
3. Checks on every bundled file (a failure stops with no bundle) : no path matches EXCLUDE, no file over
   MAX_FILE_BYTES, no key pattern (D-11 patterns and the key values set in this shell, service.store.key_hits), no model
   text field (narrative, reasoning text, message content) in any JSON file.
4. Writes DIR/bundle.tar.gz, DIR/bundle-files.txt (path and bytes per line) and DIR/remote-install.sh (the committed
   copy), and prints a JSON summary. Offline : git and the local Python only.
"""
import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from service.store import forbidden_fields, key_hits  # noqa: E402

BUNDLE_VERSION = 'guardrail-server-bundle-v1'
# What the server needs : the API and loader code, the modules they import (service.store -> tools.analyze_session ->
# experiments protocol constants, scenario_schema, json_subset, progress_schema, tools.gateway_prices), the deploy files,
# and the committed demo records the loader (storage demo-all, service.load_demo check) and the API read.
INCLUDE = (
    'service/',
    'storage/',
    'deploy/aws/',
    'tools/analyze_session.py',
    'tools/gateway_prices.py',
    'experiments/step_execution.py',
    'experiments/issue_contract.py',
    'experiments/output_contract.py',
    'scenario_schema.py',
    'json_subset.py',
    'progress_schema.py',
    'reports/c19/aggregate-main.json',
    'reports/c18-8/exclusions.json',
    'reports/c18-8/account-corrections.json',
    'docs/criteria/demo-final-freeze.json',
    'scenarios/README.md',        # Korean scenario names (service/load_demo.scenario_rows) ; the YAMLs stay
    'batch_plans/',
    'runs/demo/*/summary.json',
    'runs/demo/*/scenario.yaml',
    'runs/demo/*/conditions.json',
    'runs/demo/*/record/*.json',
)
# Never on the server (DM-91 ⑤), even if an INCLUDE path would reach it. Checked again on the bundled file list.
EXCLUDE = (
    'logs/*',                     # proxy session logs (raw)
    'docs/handoff/*',             # PM hand-over documents
    'venv/*', '.venv/*',          # local virtual environments
    '.env', '.env.*', '*/.env', '*/.env.*',   # key files
    '*.pem', '*.key', '*id_rsa*', '*id_ed25519*',
    'deploy/aws/target.env',      # deploy target values (git-ignored anyway)
    'runs/*/session.json',        # raw session files (model text) and other large per-step files ('*' crosses '/')
    'runs/*/steps.json',
    'runs/*/observations/*',
    'runs/*/workspace/*',
    'runs/*/search/*',
    'runs/*/tool-dispatch.json',
    'runs/*/prompt-trend.json',
    'proxy.py', 'experiments/run_scenario.py', 'experiments/dialogue_runner.py', 'tools/run_batch.py',
)
MAX_FILE_BYTES = 1024 * 1024
TEXT_SUFFIXES = {'.py', '.json', '.yaml', '.yml', '.md', '.txt', '.sql', '.sh', '.service', '.template', '.example',
                 '.html', '.toml', '.cfg', ''}


def git(*args, **kwargs):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True, **kwargs)


def excluded(path):
    return any(fnmatch.fnmatch(path, pattern) for pattern in EXCLUDE)


def pathspecs():
    # git's default pathspec wildcard is fnmatch without FNM_PATHNAME ('*' also matches '/'), the same as excluded().
    return list(INCLUDE) + [f':(exclude){p}' for p in EXCLUDE]


def archive_members(ref, specs=None):
    """{path: bytes} of the committed files of `ref` (all of them, or those the pathspecs pick)."""
    data = git('archive', '--format=tar', ref, '--', *(specs or [])).stdout
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if member.isfile():
                out[member.name] = tar.extractfile(member).read()
    return out


def build_screen(ref, workdir):
    """site/index.html : the demo screen in query API mode, built from a full archive of `ref` in a temporary folder."""
    full = Path(workdir) / 'full'
    full.mkdir()
    data = git('archive', '--format=tar', ref).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(full, filter='data')
    output = Path(workdir) / 'index.html'
    result = subprocess.run([sys.executable, '-B', str(full / 'tools' / 'demo_ui.py'), 'build', '--api',
                             '--aggregate', str(full / 'reports' / 'c19' / 'aggregate-main.json'),
                             '--output', str(output), '--runs-root', str(full / 'runs' / 'demo')],
                            capture_output=True, text=True, cwd=full)
    if result.returncode != 0:
        raise SystemExit(f'demo screen build failed: {result.stdout[-500:]} {result.stderr[-500:]}')
    return output.read_bytes(), json.loads(result.stdout)


def check(files):
    """Problems in the bundle file map {path: bytes} (empty when it may leave the Mac)."""
    problems = []
    for path, body in sorted(files.items()):
        if excluded(path):
            problems.append(f'excluded path: {path}')
        if len(body) > MAX_FILE_BYTES:
            problems.append(f'file over {MAX_FILE_BYTES} bytes: {path} ({len(body)})')
        if Path(path).suffix in TEXT_SUFFIXES:
            text = body.decode('utf-8', errors='replace')
            for hit in key_hits(text):
                problems.append(f'key pattern {hit}: {path}')
            if path.endswith('.json'):
                try:
                    found = forbidden_fields(json.loads(text))
                except ValueError:
                    found = []
                if found:
                    problems.append(f'model text field {found[0]}: {path}')
    return problems


def build(ref='main', out=None):
    commit = git('rev-parse', '--verify', f'{ref}^{{commit}}', text=True).stdout.strip()
    files = archive_members(commit, pathspecs())
    with tempfile.TemporaryDirectory() as workdir:
        screen, screen_info = build_screen(commit, workdir)
    files['site/index.html'] = screen
    info = {'bundle_version': BUNDLE_VERSION, 'ref': ref, 'commit': commit,
            'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'screen': {'sessions': screen_info['sessions'], 'api': screen_info['api'],
                       'replay_missing': screen_info['replay_missing']},
            'files': len(files) + 1, 'bytes': sum(len(b) for b in files.values())}
    files['DEPLOY_INFO.json'] = (json.dumps(info, ensure_ascii=False, indent=1) + '\n').encode('utf-8')
    problems = check(files) + (['screen sessions missing replay.json'] if screen_info['replay_missing'] else [])
    summary = {**info, 'bytes': sum(len(b) for b in files.values()), 'problems': problems}
    if problems or out is None:
        return summary, files
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        for path, body in sorted(files.items()):
            member = tarfile.TarInfo(path)
            member.size, member.mode, member.mtime = len(body), 0o644, 0
            tar.addfile(member, io.BytesIO(body))
    (out / 'bundle.tar.gz').write_bytes(buffer.getvalue())
    (out / 'bundle-files.txt').write_text(''.join(f'{p}\t{len(b)}\n' for p, b in sorted(files.items())),
                                          encoding='utf-8')
    (out / 'remote-install.sh').write_bytes(files['deploy/aws/remote-install.sh'])
    summary.update({'bundle': str(out / 'bundle.tar.gz'), 'bundle_bytes': len(buffer.getvalue()),
                    'bundle_sha256': hashlib.sha256(buffer.getvalue()).hexdigest()})
    return summary, files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    one = sub.add_parser('build')
    one.add_argument('--ref', default='main')
    one.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    summary, _ = build(args.ref, args.out)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 1 if summary['problems'] else 0


if __name__ == '__main__':
    sys.exit(main())
