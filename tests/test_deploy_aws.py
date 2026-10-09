"""C-19-7 part 3 : the AWS deploy files (deploy/aws/), checked offline. No AWS call, no SSH, no network.

Checked : the Caddyfile template (basic auth over the whole site, only the API path list goes to 127.0.0.1:8020, no
value filled in), the systemd unit, shell syntax under macOS /bin/bash 3.2, provision.sh with a fake AWS CLI and curl
on PATH (nothing is created without --apply and "yes" ; with them the target file holds no account ID), teardown.sh
(nothing is deleted without "delete"), no domain/IP/password/key value in the deploy files, the git-ignored target
file, the server package pins, the remote install order (check before the switch), and the server bundle built from
the committed HEAD (exclusion list, no excluded path, no key pattern, no model text, no large file, and the bundle
alone runs the loader check and builds every demo payload).
"""
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest

from service.store import key_hits

ROOT = Path(__file__).resolve().parents[1]
AWS = ROOT / 'deploy' / 'aws'
sys.path.insert(0, str(AWS))
import bundle  # noqa: E402

MAC_SCRIPTS = ('provision.sh', 'teardown.sh', 'configure.sh', 'remote.sh', 'deploy.sh', 'lib.sh')
SERVER_SCRIPTS = ('server-setup.sh', 'set-password.sh', 'remote-install.sh')
ACCOUNT = '123456789012'
CREATE_VERBS = ('create-', 'run-instances', 'allocate-address', 'associate-address', 'authorize-', 'revoke-',
                'change-resource-record-sets', 'start-instances', 'terminate-', 'delete-', 'release-', 'disassociate-')

FAKE_AWS = textwrap.dedent('''\
    #!{python}
    import json, os, sys
    args = sys.argv[1:]
    with open(os.environ['FAKE_AWS_LOG'], 'a') as log:
        log.write(json.dumps(args) + '\\n')
    words = [a for a in args if not a.startswith('-')]
    op = ' '.join(words[2:4]) if args[:1] == ['--region'] else ' '.join(words[:2])
    out = {{
        'sts get-caller-identity': '{account}',
        'ec2 describe-vpcs': 'vpc-0aaa',
        'ec2 describe-security-groups': 'None',
        'ssm get-parameters': 'ami-0123456789abcdef0',
        'ec2 describe-key-pairs': 'None',
        'ec2 describe-instances': '',
        'ec2 describe-addresses': 'None',
        'route53 list-hosted-zones': '/hostedzone/ZFAKE\\texample.org.',
        'ec2 create-key-pair': 'fake-private-key-material',
        'ec2 create-security-group': 'sg-0fake',
        'ec2 run-instances': 'i-0fake',
        'ec2 allocate-address': 'eipalloc-0fake\\t203.0.113.10',
        'ec2 associate-address': 'eipassoc-0fake',
    }}.get(op, '')
    if os.environ.get('FAKE_AWS_NO_SSM') and op == 'ssm get-parameters':
        sys.stderr.write('An error occurred (AccessDeniedException) when calling the GetParameters operation\\n')
        sys.exit(254)
    if op == 'ec2 describe-images':
        out = 'ami-0fallback000000000'
    if os.environ.get('FAKE_AWS_TAGGED'):
        out = {{'ec2 describe-instances': 'i-0fake', 'ec2 describe-security-groups': 'sg-0fake',
                'ec2 describe-key-pairs': 'key-0fake',
                'ec2 describe-addresses': 'eipalloc-0fake\\t203.0.113.10\\teipassoc-0fake'}}.get(op, out)
    if out:
        print(out)
''')


def fake_bin(tmp):
    bin_dir = Path(tmp) / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'aws').write_text(FAKE_AWS.format(python=sys.executable, account=ACCOUNT), encoding='utf-8')
    (bin_dir / 'curl').write_text('#!/bin/sh\necho 198.51.100.7\n', encoding='utf-8')
    for name in ('aws', 'curl'):
        (bin_dir / name).chmod(0o755)
    return bin_dir


def run_script(name, tmp, *args, stdin='', tagged=False, no_ssm=False):
    """Run a deploy/aws script under /bin/bash with the fake AWS CLI and curl first on PATH and HOME in `tmp`."""
    env = {'PATH': f"{fake_bin(tmp)}:/usr/bin:/bin", 'HOME': str(Path(tmp) / 'home'), 'LANG': 'C.UTF-8',
           'FAKE_AWS_LOG': str(Path(tmp) / 'aws.log'), **({'FAKE_AWS_TAGGED': '1'} if tagged else {}),
           **({'FAKE_AWS_NO_SSM': '1'} if no_ssm else {})}
    (Path(tmp) / 'home').mkdir()
    result = subprocess.run(['/bin/bash', str(AWS / name), *args], input=stdin, capture_output=True, text=True,
                            env=env, timeout=60)
    log = Path(tmp) / 'aws.log'
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


def verbs(calls):
    return [next((a for a in c if not a.startswith('-') and a not in ('ap-northeast-2', 'text', 'ec2', 'sts', 'ssm',
                                                                       'route53')), '') for c in calls]


class CaddyAndUnit(unittest.TestCase):
    def setUp(self):
        self.caddy = (AWS / 'Caddyfile.template').read_text(encoding='utf-8')
        self.lines = [l.split('#', 1)[0].strip() for l in self.caddy.splitlines()]
        self.code = '\n'.join(l for l in self.lines if l)

    def test_basic_auth_over_the_whole_site(self):
        # One site block, basic_auth directly in it (not inside a handle/route), with only placeholders for user and hash.
        self.assertEqual(self.code.count('{$GUARDRAIL_DOMAIN} {'), 1)
        site = self.code.split('{$GUARDRAIL_DOMAIN} {', 1)[1]
        before_handles = site.split('handle', 1)[0]
        self.assertIn('basic_auth {\n{$GUARDRAIL_BASIC_AUTH_USER} {$GUARDRAIL_BASIC_AUTH_HASH}\n}', before_handles)
        self.assertEqual(self.code.count('basic_auth'), 1)

    def test_only_the_api_paths_go_to_the_api(self):
        self.assertEqual(re.findall(r'^@api path (.+)$', self.code, re.M), ['/api/* /docs /redoc /openapi.json'])
        self.assertEqual(re.findall(r'reverse_proxy (\S+)', self.code), ['127.0.0.1:8020'])
        self.assertIn('handle @api {\nreverse_proxy 127.0.0.1:8020\n}', self.code)
        self.assertIn('handle {\nroot * /opt/guardrail/app/site\nfile_server\n}', self.code)
        for later in ('/auth', '/v1', '/sessions'):
            self.assertNotIn(later, self.code)   # C-19-8 / C-19-9 blocks are comments only
            self.assertIn(later, self.caddy)
        for header in ('Strict-Transport-Security', 'X-Content-Type-Options', 'X-Frame-Options', 'Referrer-Policy'):
            self.assertIn(header, self.code)

    def test_api_unit(self):
        unit = (AWS / 'guardrail-api.service').read_text(encoding='utf-8')
        for line in ('User=guardrail', 'WorkingDirectory=/opt/guardrail/app', 'EnvironmentFile=/etc/guardrail/api.env',
                     'Restart=always',
                     'ExecStart=/opt/guardrail/venv/bin/python -B -m service.api --host 127.0.0.1 --port 8020'):
            self.assertIn(line + '\n', unit)

    def test_server_db_url_is_a_socket_without_password(self):
        url = 'postgresql:///guardrail_demo?host=/var/run/postgresql'
        for name in ('server-setup.sh', 'remote-install.sh', 'lib.sh'):
            self.assertIn(url, (AWS / name).read_text(encoding='utf-8'), name)


class Scripts(unittest.TestCase):
    def test_syntax_under_macos_bash(self):
        for name in MAC_SCRIPTS + SERVER_SCRIPTS:
            result = subprocess.run(['/bin/bash', '-n', str(AWS / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, (name, result.stderr))
        for name in MAC_SCRIPTS:   # no bash 4 builtins on the Mac side (comments aside)
            code = '\n'.join(l.split('#', 1)[0] for l in (AWS / name).read_text(encoding='utf-8').splitlines())
            self.assertNotRegex(code, r'\b(mapfile|readarray|declare -A)\b', name)

    def test_executable_bits(self):
        for name in MAC_SCRIPTS + SERVER_SCRIPTS:
            if name != 'lib.sh':
                self.assertTrue((AWS / name).stat().st_mode & stat.S_IXUSR, name)

    def test_no_target_value_or_secret_in_deploy_files(self):
        allowed_ips = {'0.0.0.0', '127.0.0.1'}
        allowed_hosts = {'checkip.amazonaws.com', 'dl.cloudsmith.io', 'demo.example.com'}
        for path in sorted(AWS.iterdir()):
            if path.name == 'target.env' or not path.is_file():
                continue
            text = path.read_text(encoding='utf-8')
            self.assertEqual(key_hits(text), [], path.name)
            self.assertEqual(set(re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', text)) - allowed_ips, set(), path.name)
            hosts = set(re.findall(r'\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|kr|dev|app)\b', text))
            hosts = {h for h in hosts if not h.endswith(('.py', '.sh'))}
            self.assertEqual(hosts - allowed_hosts, set(), path.name)
            self.assertNotRegex(text, r'\$2[aby]\$\d\d\$[./A-Za-z0-9]{20,}', path.name)    # no bcrypt hash
            self.assertNotRegex(text, r'AKIA[0-9A-Z]{16}|aws_secret_access_key\s*=', path.name)
            self.assertNotRegex(text, r'(?i)password\s*=\s*\S', path.name)
            self.assertNotIn(ACCOUNT, text)

    def test_target_env_is_git_ignored(self):
        result = subprocess.run(['git', '-C', str(ROOT), 'check-ignore', 'deploy/aws/target.env'],
                                capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), 'deploy/aws/target.env')

    def test_remote_install_checks_before_it_switches(self):
        text = (AWS / 'remote-install.sh').read_text(encoding='utf-8')
        order = [text.index(s) for s in ('-m storage init', '-m storage demo-all', '-m service.load_demo check',
                                         'die "check 가 같지 않다', 'ln -sfn "$release"', 'systemctl restart guardrail-api',
                                         'systemctl reload-or-restart caddy')]
        self.assertEqual(order, sorted(order))
        self.assertIn('caddy validate', text)

    def test_set_password_keeps_the_password_off_command_lines_and_files(self):
        text = (AWS / 'set-password.sh').read_text(encoding='utf-8')
        self.assertIn('read -r -s -p', text)
        self.assertIn('printf \'%s\\n\' "$pw1" | caddy hash-password', text)
        self.assertNotIn('--plaintext', text)
        self.assertNotRegex(text, r'printf[^\n]*\$pw1[^\n]*>')   # the password is never redirected into a file


class Provision(unittest.TestCase):
    def test_dry_run_makes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target.env'
            result, calls = run_script('provision.sh', tmp, '--domain', 'demo.example.org', '--target-env', str(target))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('dry-run : 아무것도 만들지 않았다', result.stdout)
            self.assertIn('Route 53 호스팅 영역 ZFAKE', result.stdout)
            self.assertTrue(calls)
            self.assertEqual([v for v in verbs(calls) if v.startswith(CREATE_VERBS)], [])
            self.assertTrue(all(v.startswith(('get-caller-identity', 'describe-', 'get-parameters', 'list-hosted-zones'))
                                for v in verbs(calls)), verbs(calls))
            self.assertFalse(target.exists())
            self.assertEqual(list((Path(tmp) / 'home').iterdir()), [])

    def test_ami_falls_back_to_canonical_images_without_ssm_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, calls = run_script('provision.sh', tmp, '--domain', 'demo.example.org', '--target-env',
                                       str(Path(tmp) / 'target.env'), no_ssm=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            images = next(c for c in calls if 'describe-images' in c)
            self.assertIn('099720109477', images)
            self.assertIn('ami-0fallback000000000', result.stdout)
            self.assertEqual([v for v in verbs(calls) if v.startswith(CREATE_VERBS)], [])

    def test_apply_needs_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target.env'
            result, calls = run_script('provision.sh', tmp, '--apply', '--domain', 'demo.example.org',
                                       '--target-env', str(target), stdin='no\n')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual([v for v in verbs(calls) if v.startswith(CREATE_VERBS)], [])
            self.assertFalse(target.exists())

    def test_apply_creates_and_writes_target_without_account_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target.env'
            result, calls = run_script('provision.sh', tmp, '--apply', '--domain', 'demo.example.org',
                                       '--target-env', str(target), stdin='yes\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            made = [v for v in verbs(calls) if v.startswith(CREATE_VERBS)]
            for verb in ('create-key-pair', 'create-security-group', 'authorize-security-group-ingress',
                         'run-instances', 'allocate-address', 'associate-address', 'change-resource-record-sets'):
                self.assertIn(verb, made)
            ssh_rules = [c for c in calls if 'authorize-security-group-ingress' in c and 'FromPort=22' in ' '.join(c)]
            self.assertEqual(len(ssh_rules), 1)
            self.assertIn('IpRanges=[{CidrIp=198.51.100.7/32}]', ' '.join(ssh_rules[0]))
            run = next(c for c in calls if 'run-instances' in c)
            for value in ('t3.small', 'ami-0123456789abcdef0', 'HttpTokens=required,HttpEndpoint=enabled'):
                self.assertIn(value, run)
            self.assertIn('VolumeSize=20,VolumeType=gp3', ' '.join(run))
            body = target.read_text(encoding='utf-8')
            self.assertIn('GUARDRAIL_DOMAIN=demo.example.org\n', body)
            self.assertIn('GUARDRAIL_SERVER_IP=203.0.113.10\n', body)
            self.assertNotIn(ACCOUNT, body)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            key = Path(tmp) / 'home' / '.ssh' / 'guardrail-demo.pem'
            self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o400)
            self.assertNotIn(ACCOUNT, key.read_text())

    def test_teardown_with_nothing_tagged_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, calls = run_script('teardown.sh', tmp, stdin='delete\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('지울 것이 없다', result.stdout)
            self.assertEqual([v for v in verbs(calls) if v.startswith(CREATE_VERBS)], [])

    def test_teardown_needs_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, calls = run_script('teardown.sh', tmp, stdin='no\n', tagged=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('i-0fake', result.stdout)
            self.assertEqual([v for v in verbs(calls) if v.startswith(CREATE_VERBS)], [])

    def test_teardown_deletes_after_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, calls = run_script('teardown.sh', tmp, stdin='delete\n', tagged=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual([v for v in verbs(calls) if v.startswith(CREATE_VERBS)],
                             ['disassociate-address', 'release-address', 'terminate-instances',
                              'delete-security-group', 'delete-key-pair'])
            self.assertNotIn(ACCOUNT, result.stdout.split('\n', 1)[1])   # the account ID only on the first line


class ServerPackages(unittest.TestCase):
    def test_pinned_to_this_venv(self):
        import importlib.metadata as md
        lines = [l for l in (ROOT / 'service' / 'requirements-server.txt').read_text(encoding='utf-8').splitlines()
                 if l and not l.startswith('#')]
        for line in lines:
            name, version = re.fullmatch(r'([A-Za-z0-9_.-]+)(?:\[binary\])?==([\w.]+)', line).groups()
            self.assertEqual(md.version(name), version, name)
        names = {re.split(r'[\[=]', l)[0].lower().replace('_', '-') for l in lines}
        self.assertTrue({'fastapi', 'uvicorn', 'psycopg', 'python-dotenv', 'pyyaml'} <= names)
        self.assertIn('psycopg[binary]==', '\n'.join(lines))


class Bundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.summary, cls.files = bundle.build('HEAD', Path(cls.tmp.name) / 'out')

    def test_exclusion_list_names_what_must_not_go(self):
        for pattern in ('logs/*', 'docs/handoff/*', '.env', '.env.*', '*.pem', 'venv/*', 'deploy/aws/target.env',
                        'runs/*/session.json', 'proxy.py', 'experiments/run_scenario.py', 'tools/run_batch.py'):
            self.assertIn(pattern, bundle.EXCLUDE)
        self.assertIn(':(exclude)logs/*', bundle.pathspecs())

    def test_bundle_is_clean(self):
        self.assertEqual(self.summary['problems'], [])
        head = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        self.assertEqual(self.summary['commit'], head)
        self.assertEqual(self.summary['screen'], {'sessions': 67, 'api': True, 'replay_missing': []})
        paths = set(self.files)
        for path in paths:
            self.assertFalse(bundle.excluded(path), path)
            self.assertFalse(path.startswith(('logs/', 'docs/handoff', 'venv/', '.env')), path)
            self.assertNotRegex(path, r'(session|steps)\.json$|\.pem$|target\.env$')
            self.assertLessEqual(len(self.files[path]), bundle.MAX_FILE_BYTES, path)
        for absent in ('proxy.py', 'experiments/run_scenario.py', 'tools/run_batch.py', 'requirements.txt'):
            self.assertNotIn(absent, paths)
        for present in ('site/index.html', 'DEPLOY_INFO.json', 'service/api.py', 'storage/__main__.py',
                        'service/requirements-server.txt', 'deploy/aws/remote-install.sh', 'scenarios/README.md',
                        'reports/c19/aggregate-main.json', 'docs/criteria/demo-final-freeze.json'):
            self.assertIn(present, paths)
        self.assertEqual(len([p for p in paths if p.endswith('/record/replay.json')]), 115)
        self.assertIn(b'apiLoad', self.files['site/index.html'])
        listing = (Path(self.tmp.name) / 'out' / 'bundle-files.txt').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(listing), len(paths))

    def test_check_catches_what_must_not_go(self):
        self.assertTrue(bundle.check({'logs/A-1-x.json': b'{}'}))
        self.assertTrue(bundle.check({'runs/demo/x/record/replay.json': json.dumps({'narrative': 'said'}).encode()}))
        self.assertTrue(bundle.check({'service/x.py': b"KEY = 'gsk_" + b'a' * 40 + b"'"}))
        self.assertTrue(bundle.check({'reports/big.json': b'0' * (bundle.MAX_FILE_BYTES + 1)}))
        self.assertEqual(bundle.check({'service/x.py': b'print(1)\n'}), [])

    def test_bundle_alone_runs_the_loader_check_and_builds_every_payload(self):
        # The server runs from the bundle only : the offline loader check (same SQL on SQLite) and the storage payloads.
        with tempfile.TemporaryDirectory() as tmp:
            with tarfile.open(Path(self.tmp.name) / 'out' / 'bundle.tar.gz') as tar:
                tar.extractall(tmp, filter='data')
            env = {**os.environ, 'HOME': tmp}   # -E ignores PYTHON* ; the rest (e.g. where libpq is) stays
            check = subprocess.run([sys.executable, '-B', '-E', '-s', '-m', 'service.load_demo', 'check', '--offline'],
                                   cwd=tmp, capture_output=True, text=True, env=env, timeout=300)
            self.assertEqual(check.returncode, 0, check.stdout[-800:] + check.stderr[-800:])
            self.assertTrue(json.loads(check.stdout)['ok'])
            code = ('from storage.import_demo import demo_folders, demo_session_payload, load_demo_metadata\n'
                    'm = load_demo_metadata()\n'
                    'print(sum(1 for f in demo_folders() if demo_session_payload(f, metadata=m)["session"]["id"]))\n'
                    'import service.api\n')
            payloads = subprocess.run([sys.executable, '-B', '-E', '-s', '-c', code], cwd=tmp, capture_output=True,
                                      text=True, env=env, timeout=300)
            self.assertEqual(payloads.returncode, 0, payloads.stderr[-800:])
            self.assertEqual(payloads.stdout.strip(), '115')


if __name__ == '__main__':
    unittest.main()
