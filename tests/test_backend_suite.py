"""DM-108 : run backend/test_*.py with the offline suite.

They sit outside tests/, so tools/run_offline_tests.py (which discovers tests/ only) never ran them, and a fixture change
in tests/test_backend_sessions.py broke 18 of them unnoticed after the backend-foundation merge.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_tests(loader, standard_tests, pattern):
    standard_tests.addTests(unittest.TestLoader().discover(str(ROOT / 'backend'), pattern='test_*.py',
                                                           top_level_dir=str(ROOT)))
    return standard_tests
