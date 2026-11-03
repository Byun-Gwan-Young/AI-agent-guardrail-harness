import unittest
from pathlib import Path


class StorageSchemaResolvedContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = Path("storage/schema.sql").read_text(encoding="utf-8")
        cls.readme = Path("storage/README.md").read_text(encoding="utf-8")

    def test_project_mode_constraint_is_documented_in_schema(self):
        self.assertIn("chk_projects_mode_observe_block", self.schema)
        self.assertIn("mode IN ('observe', 'block')", self.schema)

    def test_session_mode_constraint_is_documented_in_schema(self):
        self.assertIn("chk_sessions_guardrail_mode_observe_block", self.schema)
        self.assertIn("guardrail_mode IS NULL OR guardrail_mode IN ('observe', 'block')", self.schema)
        self.assertIn("ADD COLUMN IF NOT EXISTS guardrail_mode VARCHAR(20)", self.schema)

    def test_key_prefix_is_not_null_contract(self):
        self.assertIn("key_prefix TEXT NOT NULL", self.schema)
        self.assertIn("ALTER COLUMN key_prefix SET NOT NULL", self.schema)

    def test_cross_team_contracts_are_explicit_in_readme(self):
        for phrase in (
            "Live scenario identity 전달 경로",
            "Lossless live polling cursor",
            "Demo 조회 API와 Live 조회 API의 경계",
        ):
            self.assertIn(phrase, self.readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
