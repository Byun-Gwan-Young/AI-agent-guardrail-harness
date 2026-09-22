import subprocess
import unittest
from unittest.mock import patch

from experiments.run_scenario import enforce_dataset_clean, git_state


class GitStateTests(unittest.TestCase):
    @patch('experiments.run_scenario.subprocess.run')
    def test_records_head_and_dirty_state(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0, stdout='abc123\n'),
                           subprocess.CompletedProcess([], 0, stdout=' M tracked.py\n')]
        self.assertEqual(git_state(), {'git_commit': 'abc123', 'git_dirty': True,
                                      'git_state_status': 'measured', 'git_state_reason': None})

    @patch('experiments.run_scenario.subprocess.run', side_effect=OSError('git unavailable'))
    def test_unavailable_git_is_unmeasured(self, _run):
        state = git_state()
        self.assertEqual(state['git_commit'], None)
        self.assertEqual(state['git_dirty'], None)
        self.assertEqual(state['git_state_status'], 'unmeasured')

    def test_only_dataset_runs_block_a_dirty_tree(self):
        dirty = {'git_dirty': True}
        enforce_dataset_clean(False, dirty)
        with self.assertRaisesRegex(ValueError, 'clean Git working tree'):
            enforce_dataset_clean(True, dirty)
