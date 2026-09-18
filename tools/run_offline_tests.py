"""Run the complete unittest suite and report frozen baseline/new test groups."""
import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'tests/fixtures/p0-2-baseline-test-ids.json')
    args = parser.parse_args()
    baseline = set(json.loads(args.baseline.read_text()))
    attempts = []
    def audit(event, _args):
        if event in ('socket.connect', 'socket.getaddrinfo', 'socket.sendto'):
            attempts.append(event)
            raise RuntimeError('Network access blocked during offline tests')
    sys.addaudithook(audit)
    groups = {g:dict(executed=0,passed=0,failures=0,errors=0,skipped=0) for g in ('baseline','new')}
    seen = set()
    class Result(unittest.TextTestResult):
        def group(self, test):
            identity = getattr(test, 'test_case', test).id()
            return groups['baseline' if identity in baseline else 'new']
        def startTest(self, test):
            super().startTest(test); seen.add(test.id()); self.group(test)['executed'] += 1
        def addSuccess(self, test):
            super().addSuccess(test); self.group(test)['passed'] += 1
        def addFailure(self, test, err):
            super().addFailure(test,err); self.group(test)['failures'] += 1
        def addError(self, test, err):
            super().addError(test,err); self.group(test)['errors'] += 1
        def addSkip(self, test, reason):
            super().addSkip(test,reason); self.group(test)['skipped'] += 1
        def addSubTest(self, test, subtest, err):
            super().addSubTest(test,subtest,err)
            if err is not None:
                self.group(test)['failures' if issubclass(err[0],test.failureException) else 'errors'] += 1
    result = unittest.TextTestRunner(verbosity=1,resultclass=Result).run(
        unittest.defaultTestLoader.discover(str(ROOT / 'tests'),pattern='test_*.py'))
    report = {'groups':groups,'total':{k:sum(g[k] for g in groups.values()) for k in groups['baseline']},
              'missing_baseline_ids':sorted(baseline-seen), 'network_attempts':attempts,
              'python':sys.version, 'executable':sys.executable,
              'failures':[{'test':t.id(),'traceback':trace} for t,trace in result.failures],
              'errors':[{'test':t.id(),'traceback':trace} for t,trace in result.errors]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if result.wasSuccessful() and not baseline-seen else 1


if __name__ == '__main__':
    sys.exit(main())
