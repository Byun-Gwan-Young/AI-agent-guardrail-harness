"""Run the complete unittest suite and report frozen baseline/new test groups.

Each test module runs under a time limit (--module-timeout, seconds; C-18-4, DM-68): a test still running at the limit
is interrupted with an error, the module's remaining tests are reported as errors, and the module is listed in
timed_out_modules. The run never waits without end.
"""
import argparse
import json
from pathlib import Path
import signal
import sys
import time
import unittest


class ModuleTimeout(Exception):
    pass


class TimedModule(unittest.TestSuite):
    """One discovered module's suite, run under a time limit (SIGALRM interrupts a test that is still running)."""

    def __init__(self, tests, name, limit, timed_out):
        super().__init__(tests)
        self.name, self.limit, self.timed_out = name, limit, timed_out

    def run(self, result, debug=False):
        def interrupt(_signum, _frame):
            if self.name not in self.timed_out:
                self.timed_out.append(self.name)
            raise ModuleTimeout(f'module {self.name} passed its time limit of {self.limit} s')
        outer_left, _ = signal.getitimer(signal.ITIMER_REAL)  # an enclosing limit (a test of this runner) resumes
        previous = signal.signal(signal.SIGALRM, interrupt)
        start = time.monotonic()
        signal.setitimer(signal.ITIMER_REAL, self.limit)
        try:
            for test in self:
                if result.shouldStop:
                    break
                if time.monotonic() - start >= self.limit:
                    if self.name not in self.timed_out:
                        self.timed_out.append(self.name)
                    for left in iterate(test):
                        result.startTest(left)
                        result.addError(left, (ModuleTimeout, ModuleTimeout(f'module {self.name} time limit'), None))
                        result.stopTest(left)
                    continue
                test(result)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
            if outer_left:
                signal.setitimer(signal.ITIMER_REAL, max(outer_left - (time.monotonic() - start), 0.001))
        return result


def iterate(suite):
    if isinstance(suite, unittest.TestSuite):
        for test in suite:
            yield from iterate(test)
    else:
        yield suite


def timed(discovered, limit, timed_out):
    """The discovered suite with each module suite (discover's top level) wrapped in TimedModule."""
    modules = []
    for module in discovered:
        names = sorted({type(t).__module__ for t in iterate(module)})
        modules.append(TimedModule(list(module), ','.join(names) or 'unknown', limit, timed_out))
    return unittest.TestSuite(modules)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'tests/fixtures/p0-2-baseline-test-ids.json')
    parser.add_argument('--module-timeout', type=float, default=300.0)
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
    timed_out = []
    result = unittest.TextTestRunner(verbosity=1,resultclass=Result).run(
        timed(unittest.defaultTestLoader.discover(str(ROOT / 'tests'),pattern='test_*.py'), args.module_timeout,
              timed_out))
    report = {'groups':groups,'total':{k:sum(g[k] for g in groups.values()) for k in groups['baseline']},
              'missing_baseline_ids':sorted(baseline-seen), 'network_attempts':attempts,
              'module_timeout_seconds':args.module_timeout, 'timed_out_modules':timed_out,
              'python':sys.version, 'executable':sys.executable,
              'failures':[{'test':t.id(),'traceback':trace} for t,trace in result.failures],
              'errors':[{'test':t.id(),'traceback':trace} for t,trace in result.errors]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if result.wasSuccessful() and not baseline-seen and not timed_out else 1


if __name__ == '__main__':
    sys.exit(main())
