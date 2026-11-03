"""Run lifecycle tests against a disposable local PostgreSQL cluster on Windows.

Usage: python tools/test_account_lifecycle_postgres.py --pg-bin "C:/Program Files/PostgreSQL/18/bin"
The configured application database is never used.
"""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    base = Path(tempfile.gettempdir()).resolve()
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

    def run(*command):
        # A Windows postgres child can inherit pipe handles and prevent
        # communicate() from completing after pg_ctl has already exited.
        with tempfile.TemporaryFile() as output:
            result = subprocess.run([str(arg) for arg in command], stdout=output,
                                    stderr=subprocess.STDOUT, creationflags=flags,
                                    timeout=90)
            output.seek(0)
            diagnostic = output.read().decode(errors='replace')
        if result.returncode:
            print(diagnostic)
            raise RuntimeError('PostgreSQL test setup failed')

    with tempfile.TemporaryDirectory(prefix='guardrail-account-tests-', dir=base) as temp:
        root = Path(temp).resolve()
        # TemporaryDirectory cleanup must only touch our generated test directory.
        if root.parent != base or not root.name.startswith('guardrail-account-tests-'):
            raise RuntimeError('Unexpected temporary path')
        data = root / 'data'
        run(args.pg_bin / 'initdb.exe', '-D', data, '-U', 'postgres',
            '--auth=trust', '--encoding=UTF8', '--locale=C')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        run(args.pg_bin / 'pg_ctl.exe', '-D', data, '-l', root / 'postgres.log',
            '-o', f'-h 127.0.0.1 -p {port}', '-w', 'start')
        try:
            env = os.environ.copy()
            env['GUARDRAIL_DB_URL'] = f'postgresql://postgres@127.0.0.1:{port}/postgres'
            env['RUN_ACCOUNT_DB_TESTS'] = '1'
            result = subprocess.run([sys.executable, '-m', 'unittest',
                                     'backend.test_account_lifecycle_db'],
                                    env=env, cwd=repo)
        finally:
            run(args.pg_bin / 'pg_ctl.exe', '-D', data, '-m', 'fast', '-w', 'stop')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
