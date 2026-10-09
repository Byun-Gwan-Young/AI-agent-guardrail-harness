"""Offline contract tests for the service API over the unified Storage shape."""

import copy
import json
import sqlite3
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from service import api, load_demo, queries
from service.store import RecordError, Store, sqlite_store
from storage.import_demo import demo_folders, demo_session_payload, load_demo_metadata


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _unified_store_from_current_demo_source():
    """Build the current Storage read shape in SQLite without touching PostgreSQL."""
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.executescript(
        """
        CREATE TABLE scenarios (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            scenario_key TEXT NOT NULL,
            scenario_hash TEXT NOT NULL,
            schema_version TEXT,
            name TEXT,
            task_kind TEXT,
            config TEXT
        );
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            scenario_id INTEGER NOT NULL,
            status TEXT,
            termination_reason TEXT,
            phase TEXT,
            guardrail_mode TEXT,
            model TEXT,
            steps_reached INTEGER,
            total_tokens INTEGER,
            first_stop_step INTEGER,
            started_at TEXT,
            ended_at TEXT,
            execution_config TEXT,
            session_data TEXT,
            validity TEXT,
            exclusion_code TEXT,
            rerun_of TEXT,
            replaced_by TEXT,
            source TEXT
        );
        CREATE TABLE judgements (
            session_id TEXT,
            step INTEGER,
            judgement_ns INTEGER,
            reason TEXT,
            stagnant_run INTEGER,
            rule_id TEXT
        );
        """
    )

    metadata = load_demo_metadata()
    scenario_ids = {}
    next_scenario_id = 1

    for folder in demo_folders():
        payload = demo_session_payload(folder, metadata=metadata)
        scenario = payload['scenario']
        identity = (scenario['scenario_key'], scenario['scenario_hash'])
        if identity not in scenario_ids:
            scenario_ids[identity] = next_scenario_id
            conn.execute(
                """
                INSERT INTO scenarios (
                    id, project_id, scenario_key, scenario_hash, schema_version,
                    name, task_kind, config
                ) VALUES (?, 3, ?, ?, ?, ?, ?, ?)
                """,
                (
                    next_scenario_id,
                    scenario['scenario_key'], scenario['scenario_hash'], scenario['schema_version'],
                    scenario['name'], scenario['task_kind'], _json(scenario['config']),
                ),
            )
            next_scenario_id += 1

        session = payload['session']
        conn.execute(
            """
            INSERT INTO sessions (
                id, scenario_id, status, termination_reason, phase, guardrail_mode,
                model, steps_reached, total_tokens, first_stop_step, started_at,
                ended_at, execution_config, session_data, validity, exclusion_code,
                rerun_of, replaced_by, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session['id'], scenario_ids[identity], session['status'], session['termination_reason'],
                session['phase'], session['guardrail_mode'], session['model'], session['steps_reached'],
                session['total_tokens'], session['first_stop_step'], session['started_at'], session['ended_at'],
                _json(session['execution_config']), _json(session['session_data']), session['validity'],
                session['exclusion_code'], session['rerun_of'], session['replaced_by'], session['source'],
            ),
        )

        for judgement in payload['judgements']:
            criteria = judgement.get('criteria') or {}
            conn.execute(
                """
                INSERT INTO judgements (
                    session_id, step, judgement_ns, reason, stagnant_run, rule_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session['id'], judgement.get('step_id'), judgement.get('judgement_ns'),
                    criteria.get('reason'), criteria.get('consecutive_steps'), criteria.get('criteria_version'),
                ),
            )

    conn.commit()
    store = Store(lambda: conn, 'sqlite')
    # _unified_schema consults the cache first; this keeps the test socket-free
    # while executing the exact unified query branch.
    store._guardrail_unified_schema = True
    return store


class UnifiedApiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy = sqlite_store(load_demo.build_rows())
        cls.unified = _unified_store_from_current_demo_source()
        cls.addClassCleanup(cls.legacy.close)
        cls.addClassCleanup(cls.unified.close)

    def test_summary_contract_matches_legacy_except_load_timestamp(self):
        old = copy.deepcopy(queries.summary(self.legacy))
        new = copy.deepcopy(queries.summary(self.unified))
        # Unified Storage has no fake aggregate-load timestamp. The key remains,
        # but its value is intentionally not part of the compatibility contract.
        old['aggregates'][0].pop('loaded_at', None)
        new['aggregates'][0].pop('loaded_at', None)
        self.assertEqual(new, old)

    def test_scenarios_contract_and_order_match_legacy(self):
        self.assertEqual(queries.scenarios(self.unified), queries.scenarios(self.legacy))

    def test_all_session_public_values_match_legacy_by_id(self):
        old_rows = {r['session_id']: r for r in queries.sessions(self.legacy, {})}
        new_rows = {r['session_id']: r for r in queries.sessions(self.unified, {})}
        self.assertEqual(new_rows, old_rows)

    def test_steps_contract_matches_legacy(self):
        session_ids = sorted(
            r['session_id'] for r in queries.sessions(self.legacy, {'validity': 'valid'})
        )[:5]
        for session_id in session_ids:
            self.assertEqual(
                queries.steps(self.unified, session_id),
                queries.steps(self.legacy, session_id),
                session_id,
            )

    def test_unified_check_reproduces_legacy_check(self):
        aggregate = load_demo.load_json(load_demo.ROOT / load_demo.AGGREGATE)
        old = queries.check(self.legacy, aggregate)
        new = queries.check(self.unified, aggregate)
        self.assertTrue(new['ok'])
        self.assertEqual(new['headline'], old['headline'])
        self.assertEqual(new['sessions_by_validity'], old['sessions_by_validity'])
        self.assertEqual([x['check'] for x in new['comparisons'] if not x['same']], [])


    def test_demo_scenario_metadata_ignores_non_demo_same_key(self):
        conn = self.unified.connect()
        try:
            conn.execute(
                """
                INSERT INTO scenarios (
                    id, project_id, scenario_key, scenario_hash, schema_version,
                    name, task_kind, config
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    999999, 999, "DEMO-CL-normal-v1", "user-copy", "scenario-v2",
                    "WRONG USER PROJECT TITLE", "T3", "{}",
                ),
            )
            conn.commit()
            self.assertEqual(
                queries.scenarios(self.unified),
                queries.scenarios(self.legacy),
            )
        finally:
            conn.execute("DELETE FROM scenarios WHERE id = ?", (999999,))
            conn.commit()

    def test_fastapi_uses_the_same_public_contract(self):
        client = TestClient(api.create_app(self.unified))
        self.assertEqual(client.get('/api/sessions?validity=valid').json()['count'], 67)
        self.assertEqual(client.get('/api/scenarios').json()['scenarios'], queries.scenarios(self.legacy))
        self.assertEqual(client.get('/api/summary').json()['headline'], queries.summary(self.legacy)['headline'])


class LegacyWriterRetired(unittest.TestCase):
    def test_postgres_store_write_helpers_refuse_before_connecting(self):
        store = Store(lambda: self.fail('must not connect'), 'postgres')
        with self.assertRaisesRegex(RecordError, 'writer is retired'):
            store.apply_schema()
        with self.assertRaisesRegex(RecordError, 'writer is retired'):
            store.replace_all({})

    def test_load_demo_schema_and_load_commands_do_not_open_postgres(self):
        with mock.patch('service.load_demo.postgres_store') as postgres:
            self.assertEqual(load_demo.main(['schema']), 2)
            self.assertEqual(load_demo.main(['load']), 2)
            postgres.assert_not_called()


if __name__ == '__main__':
    unittest.main()
