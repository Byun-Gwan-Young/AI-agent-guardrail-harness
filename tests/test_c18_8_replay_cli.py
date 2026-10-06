"""replay_demo.py's command line (found in C-18-8 part 4): the `pages` action used to stop with UnboundLocalError because
main() also bound a local named `pages` in the `index` branch. Offline: the committed trial records."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import aggregate_demo, replay_demo


class Cli(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.aggregate = self.root / 'aggregate.json'
        self.aggregate.write_text(json.dumps(aggregate_demo.aggregate(['demo-trial-c18-5']), ensure_ascii=False))

    def run_main(self, *argv):
        out = io.StringIO()
        with mock.patch('sys.argv', ['replay_demo.py', *argv]), contextlib.redirect_stdout(out):
            code = replay_demo.main()
        return code, out.getvalue()

    def test_pages_action(self):
        code, out = self.run_main('pages', str(self.aggregate), '--output-dir', str(self.root / 'replay'))
        result = json.loads(out)
        self.assertEqual((code, result['replay_missing'], result['index']), (0, [], 'index.html'))
        self.assertTrue(result['pages'])
        self.assertEqual(sorted(p.name for p in (self.root / 'replay').iterdir()),
                         sorted(result['pages'] + ['index.html']))

    def test_index_action(self):
        self.run_main('pages', str(self.aggregate), '--output-dir', str(self.root / 'replay'))
        output = self.root / 'replay' / 'list.html'
        code, _ = self.run_main('index', str(self.aggregate), '--pages', str(self.root / 'replay'), '--output',
                                str(output))
        self.assertEqual(code, 0)
        self.assertEqual(output.read_text(encoding='utf-8'), (self.root / 'replay' / 'index.html').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
