"""Local deterministic acceptance check. No LLM/network calls."""
import argparse
import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


class RecordedResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.cases = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases.append((test.id(), "passed", ""))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.cases.append((test.id(), "failure", self._exc_info_to_string(err, test)))

    def addError(self, test, err):
        super().addError(test, err)
        self.cases.append((test.id(), "error", self._exc_info_to_string(err, test)))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.cases.append((test.id(), "skipped", reason))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / "src"))
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
    result = RecordedResult()
    suite.run(result)
    out = Path(args.report_dir)
    out.mkdir(parents=True, exist_ok=True)
    xml = ET.Element("testsuite", tests=str(result.testsRun), failures=str(len(result.failures)),
                     errors=str(len(result.errors)), skipped=str(len(result.skipped)))
    for name, status, details in result.cases:
        case = ET.SubElement(xml, "testcase", name=name)
        if status != "passed":
            ET.SubElement(case, status).text = details
    ET.ElementTree(xml).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)
    summary = {"tests": result.testsRun, "passed": sum(c[1] == "passed" for c in result.cases),
               "failed": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
               "cases": [{"name": name, "status": status} for name, status, _ in result.cases]}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "cases"}))
    return 0 if result.wasSuccessful() and result.testsRun > 0 and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
