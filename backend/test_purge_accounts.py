import contextlib
import io
import unittest
from unittest.mock import patch

from psycopg import OperationalError
from backend import purge_accounts


class PurgeWorkerTests(unittest.TestCase):
    def run_worker(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = purge_accounts.main(args)
        return code, output.getvalue()

    def test_default_only_previews(self):
        with patch.object(purge_accounts, 'preview_due_accounts', return_value={'candidate_count': 2}) as preview, patch.object(purge_accounts.accounts, 'purge_due_accounts') as purge:
            self.assertEqual(self.run_worker([])[0], 0)
            preview.assert_called_once_with(100)
            purge.assert_not_called()

    def test_partial_failure_returns_nonzero(self):
        with patch.object(purge_accounts.accounts, 'purge_due_accounts', return_value={'purged_count': 1, 'failed_count': 1}) as purge:
            self.assertEqual(self.run_worker(['--execute', '--limit', '5'])[0], 1)
            purge.assert_called_once_with(5)

    def test_loop_recovers_after_database_failure_without_leaking_secrets(self):
        with patch.object(purge_accounts.accounts, 'purge_due_accounts', side_effect=[OperationalError('private password'), {'failed_count': 0}]) as purge, patch.object(purge_accounts.time, 'sleep', side_effect=[None, KeyboardInterrupt]):
            code, output = self.run_worker(['--execute', '--interval', '60'])
            self.assertEqual(code, 0)
            self.assertEqual(purge.call_count, 2)
            self.assertNotIn('private password', output)
            self.assertIn('database unavailable', output)
