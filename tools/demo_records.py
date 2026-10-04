"""Demo record rule (C-18-3 part 0, DM-64 ⑤): what of a demo session goes into the repository, and the backup of the rest.

A demo session folder runs/demo/<id>/ holds a few MB (the runner's copy of the proxy log, step records with the model's
reports, the workspace, stored search responses) and its proxy log is logs/demo/<id>.json. 70 sessions of that do
not go into the repository. runs/ and logs/ are ignored (.gitignore, S-29), so nothing of a session is ever added by
a plain `git add`; a session is committed only through `stage` here, which adds the small files of COMMIT_FILES with
`git add -f` and nothing else. The raw files stay local and go into one compressed backup outside the repository
(`backup`), which the PM keeps (team drive). `check --index` finds tracked files that break the rule.

  record   runs/demo/<id> ...   write record/ (manifest, summary tool output, judgement and STOP records)
  check    runs/demo/<id> ...   the commit files of these sessions exist and fit the size limits
  check    --index              every tracked file under runs/demo/ and logs/demo/ keeps the rule
  stage    runs/demo/<id> ...   check, key scan, then git add -f exactly the commit files
  backup   runs/demo/<id> ... --output <file outside the repository>.tar.gz
  --plan <plan id> in place of (or with) the sessions: every runs/demo/ session whose conditions.json batch.plan_id is
  that plan (C-18-4), so a batch's sessions are named without copying their IDs

Offline. `record` and `stage` refuse a folder whose key scan (D-11 patterns, KMU_API_KEY and TAVILY_API_KEY values
when set here) finds anything; `backup` scans the raw files too and refuses before writing. No model text is written
into record/: the judgement record keeps the proxy's decisions, states, explanation sentences and their values only.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.analyze_session import SEARCH_SECRET_PATTERNS, SECRET_PATTERNS  # noqa: E402

RULE_VERSION = 'demo-records-v1'
DEMO_RUNS = ROOT / 'runs' / 'demo'
DEMO_LOGS = ROOT / 'logs' / 'demo'
RECORD_DIR = 'record'
# The only files of a demo session folder that are committed (DM-64 ⑤): runner records of the run and its outcome,
# and the record/ files written here. Everything else (session.json = the proxy log copy, steps.json with the model's
# reports, observations/, workspace/, search/, tool-dispatch.json) and logs/demo/ stay local and go into the backup.
COMMIT_FILES = ('conditions.json', 'summary.json', 'scenario.yaml', 'registered-tools.json', 'prompt-trend.json',
                RECORD_DIR + '/manifest.json', RECORD_DIR + '/demo-summary.json', RECORD_DIR + '/judgements.json')
# Required among them: a run that has no prompt-trend.json or registered-tools.json is still recorded.
REQUIRED_FILES = ('conditions.json', 'summary.json', 'scenario.yaml', RECORD_DIR + '/manifest.json',
                  RECORD_DIR + '/demo-summary.json', RECORD_DIR + '/judgements.json')
MAX_FILE_BYTES = 256 * 1024
MAX_SESSION_BYTES = 1024 * 1024
KEY_ENVS = ('KMU_API_KEY', 'TAVILY_API_KEY')
# Observation fields kept in record/judgements.json: no conversation, evidence or extraction (model text).
JUDGEMENT_FIELDS = ('step_id', 'agent_id', 'observed_at', 'judgement_ns')
COLLECTION_FIELDS = ('final_output_status', 'final_output_reason', 'measurement_status', 'metric_status')
PROGRESS_FIELDS = ('version', 'state', 'events', 'flags', 'coverage_complete', 'conversation_moved', 'artifact_moved',
                   'comparison_step_id', 'pass_count', 't3', 'handoff')
STOP_DECISIONS = ('deadlock', 'termination_failure')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=1) + '\n'


def session_dir(value, runs_root=DEMO_RUNS):
    """A runs/demo/<id> folder given as a path or as the session ID."""
    path = Path(value)
    folder = path if path.is_dir() else Path(runs_root) / value
    folder = folder.resolve()
    if folder.parent != Path(runs_root).resolve() or not (folder / 'conditions.json').is_file():
        raise ValueError(f'not a demo session folder under {Path(runs_root)}: {value}')
    return folder


def plan_sessions(plan_id, runs_root=DEMO_RUNS):
    """The demo session folders a batch plan ran (conditions.json batch.plan_id), in name order."""
    found = []
    for folder in sorted(Path(runs_root).iterdir()) if Path(runs_root).is_dir() else []:
        conditions = folder / 'conditions.json'
        if conditions.is_file() and (load(conditions).get('batch') or {}).get('plan_id') == plan_id:
            found.append(folder.resolve())
    if not found:
        raise ValueError(f'no session under {Path(runs_root)} ran plan {plan_id}')
    return found


def key_scan(paths):
    """D-11 patterns (with the search key pattern) and the KMU_API_KEY / TAVILY_API_KEY values set here."""
    values = {env: os.environ[env] for env in KEY_ENVS if os.environ.get(env)}
    patterns = {**SECRET_PATTERNS, **SEARCH_SECRET_PATTERNS}
    files, hits = [], {}
    for path in paths:
        files += [path] if path.is_file() else sorted(p for p in path.rglob('*') if p.is_file())
    for file in files:
        text = file.read_text(encoding='utf-8', errors='replace')
        found = [name for name, pattern in patterns.items() if pattern.search(text)]
        found += ['env:' + env for env, value in values.items() if value in text]
        if found:
            hits[str(file)] = found
    return {'files_scanned': len(files), 'key_values_checked': sorted(values), 'hits': hits, 'clean': not hits}


def judgements(log):
    """Per observed step: the proxy's progress state, decision, STOP explanation (sentence and values), judgement time."""
    rows = []
    for o in log['observations']:
        criteria = dict(o.get('criteria') or {})
        rows.append({**{k: o.get(k) for k in JUDGEMENT_FIELDS},
                     'collection': {k: (o.get('collection') or {}).get(k) for k in COLLECTION_FIELDS},
                     'progress': {k: (o.get('progress') or {}).get(k) for k in PROGRESS_FIELDS},
                     'criteria': criteria})
    stops = [r for r in rows if r['criteria'].get('decision') in STOP_DECISIONS]
    meta = log['meta']
    return {'record_version': RULE_VERSION, 'session_id': log.get('session_id'),
            'criteria_version': meta.get('criteria_version'), 'criteria_sha256': meta.get('criteria_sha256'),
            'criteria_freeze': meta.get('criteria_freeze'), 'guardrail_mode': meta.get('guardrail_mode'),
            'termination_reason': meta.get('termination_reason'),
            'first_stop_step': stops[0]['step_id'] if stops else None,
            'stop_steps': [r['step_id'] for r in stops], 'steps': rows}


def default_manifest(folder):
    from tools import analyze_session
    return analyze_session.manifest(analyze_session.analyse(folder.name), 'measure', [RULE_VERSION])


def default_summary(folder):
    from tools.summarize_demo_session import summarize
    return summarize(folder)


def record(folder, *, manifest=default_manifest, summary=default_summary):
    """Write record/ for one session. Nothing is written if the folder's key scan is not clean."""
    scan = key_scan([folder])
    if not scan['clean']:
        raise ValueError(f'{folder.name}: key scan found {sorted(scan["hits"])}; nothing written')
    made = {'manifest.json': manifest(folder), 'demo-summary.json': summary(folder),
            'judgements.json': judgements(load(folder / 'session.json'))}
    if made['manifest.json'].get('condition', {}).get('phase') != 'demo':
        raise ValueError(f'{folder.name}: the manifest phase is not demo')
    out = folder / RECORD_DIR
    out.mkdir(exist_ok=True)
    for name, value in made.items():
        (out / name).write_text(dump(value), encoding='utf-8')
    return {'session_id': folder.name, 'written': [RECORD_DIR + '/' + n for n in made], 'key_scan': scan}


def check_session(folder):
    """Problems of one session against the rule (missing required files, files or session over the limits)."""
    problems, sizes = [], {}
    for name in COMMIT_FILES:
        path = folder / name
        if not path.is_file():
            if name in REQUIRED_FILES:
                problems.append(f'{folder.name}/{name}: missing')
            continue
        sizes[name] = path.stat().st_size
        if sizes[name] > MAX_FILE_BYTES:
            problems.append(f'{folder.name}/{name}: {sizes[name]} bytes > {MAX_FILE_BYTES}')
    if sum(sizes.values()) > MAX_SESSION_BYTES:
        problems.append(f'{folder.name}: {sum(sizes.values())} bytes > {MAX_SESSION_BYTES}')
    return {'session_id': folder.name, 'files': sizes, 'bytes': sum(sizes.values()), 'problems': problems}


def git(*args, root=ROOT):
    return subprocess.run(['git', *args], cwd=root, check=True, capture_output=True, text=True).stdout


def check_index(root=ROOT):
    """Tracked files under runs/demo/ and logs/demo/ that break the rule."""
    tracked = [p for p in git('ls-files', '-z', '--', 'runs/demo', 'logs/demo', root=root).split('\0') if p]
    problems, per_session = [], {}
    for path in tracked:
        parts = Path(path).parts
        if parts[0] == 'logs':
            problems.append(f'{path}: proxy logs stay local (backup)')
            continue
        relative = '/'.join(parts[3:])
        if len(parts) < 4 or relative not in COMMIT_FILES:
            problems.append(f'{path}: not a commit file of {RULE_VERSION}')
            continue
        size = int(git('cat-file', '-s', ':' + path, root=root))
        per_session[parts[2]] = per_session.get(parts[2], 0) + size
        if size > MAX_FILE_BYTES:
            problems.append(f'{path}: {size} bytes > {MAX_FILE_BYTES}')
    problems += [f'runs/demo/{s}: {n} bytes > {MAX_SESSION_BYTES}' for s, n in per_session.items()
                 if n > MAX_SESSION_BYTES]
    return {'rule': RULE_VERSION, 'tracked_files': len(tracked), 'sessions': sorted(per_session),
            'problems': problems, 'ok': not problems}


def stage(folders, root=ROOT):
    """git add -f exactly the commit files of these sessions, after the check and a key scan of those files."""
    checks = [check_session(f) for f in folders]
    problems = [p for c in checks for p in c['problems']]
    paths = [f / name for f in folders for name in COMMIT_FILES if (f / name).is_file()]
    scan = key_scan(paths)
    if problems or not scan['clean']:
        reasons = problems + ([f'key scan found {sorted(scan["hits"])}'] if not scan['clean'] else [])
        raise ValueError('not staged: ' + '; '.join(reasons))
    relative = [p.relative_to(root).as_posix() for p in paths]
    git('add', '-f', '--', *relative, root=root)
    return {'staged': relative, 'key_scan': scan}


def backup(folders, output, *, logs_root=DEMO_LOGS, root=ROOT):
    """One .tar.gz outside the repository: each session's folder and proxy log as they are, and a list of their
    sha256. The raw files are scanned for keys first; nothing is written if the scan is not clean."""
    output = Path(output).resolve()
    if output.is_relative_to(Path(root).resolve()):
        raise ValueError('the backup goes outside the repository (the PM keeps it on the team drive)')
    if output.exists():
        raise ValueError(f'{output} exists; a backup is never overwritten')
    members = []
    for folder in folders:
        members += [(p, Path('runs/demo') / folder.name / p.relative_to(folder))
                    for p in sorted(folder.rglob('*')) if p.is_file()]
        log = Path(logs_root) / (folder.name + '.json')
        if log.is_file():
            members.append((log, Path('logs/demo') / log.name))
    scan = key_scan([source for source, _ in members])
    if not scan['clean']:
        raise ValueError(f'key scan found {sorted(scan["hits"])}; no backup written')
    listing = {'backup_version': RULE_VERSION, 'sessions': [f.name for f in folders],
               'proxy_logs_missing': [f.name for f in folders if not (Path(logs_root) / (f.name + '.json')).is_file()],
               'files': [{'path': name.as_posix(), 'bytes': source.stat().st_size,
                          'sha256': hashlib.sha256(source.read_bytes()).hexdigest()} for source, name in members],
               'key_scan': {k: scan[k] for k in ('files_scanned', 'key_values_checked', 'clean')}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        data = dump(listing).encode('utf-8')
        info = tarfile.TarInfo('backup-files.json')
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
        for source, name in members:
            archive.add(source, arcname=name.as_posix(), recursive=False)
    return {'output': str(output), 'bytes': output.stat().st_size,
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'sessions': listing['sessions'],
            'files': len(members), 'proxy_logs_missing': listing['proxy_logs_missing'], 'key_scan': listing['key_scan']}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('record', 'stage', 'backup'):
        command = sub.add_parser(name)
        command.add_argument('sessions', nargs='*', help='runs/demo/<id> or the session ID')
        command.add_argument('--plan', help='every session of this batch plan ID (conditions.json batch.plan_id)')
        if name == 'backup':
            command.add_argument('--output', type=Path, required=True)
    check = sub.add_parser('check')
    check.add_argument('sessions', nargs='*')
    check.add_argument('--plan', help='every session of this batch plan ID (conditions.json batch.plan_id)')
    check.add_argument('--index', action='store_true', help='check the tracked files under runs/demo and logs/demo')
    args = parser.parse_args()
    try:
        folders = [session_dir(s) for s in args.sessions] + (plan_sessions(args.plan) if args.plan else [])
        folders = list(dict.fromkeys(folders))
        if args.action != 'check' and not folders:
            raise ValueError('name sessions or --plan')
        if args.action == 'check':
            result = {'sessions': [check_session(f) for f in folders]}
            if args.index:
                result['index'] = check_index()
            ok = not any(c['problems'] for c in result['sessions']) and result.get('index', {'ok': True})['ok']
            print(dump({**result, 'ok': ok}), end='')
            return 0 if ok else 1
        if args.action == 'record':
            result = [record(f) for f in folders]
        elif args.action == 'stage':
            result = stage(folders)
        else:
            result = backup(folders, args.output)
    except ValueError as error:
        print('error: ' + str(error), file=sys.stderr)
        return 1
    print(dump(result), end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
