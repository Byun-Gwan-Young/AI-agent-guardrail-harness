"""C-19-7 part 4 (DM-94 ①) : the rehearsal plan is the presentation plan with another plan ID only (offline).

batch_plans/demo-live-rehearsal-v1.yaml and batch_plans/demo-live-v1.yaml must list the same sessions (scenario, mode,
repeat) in the same order, deal them to the same lanes, and both require the final freeze; only plan_id (and the
comment and description lines) differ, so a rehearsal run leaves the presentation items unrun.
"""
import unittest
from pathlib import Path

import yaml

from tools.run_batch import lane_items, load_plan

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / 'batch_plans' / 'demo-live-v1.yaml'
REHEARSAL = ROOT / 'batch_plans' / 'demo-live-rehearsal-v1.yaml'


class RehearsalPlan(unittest.TestCase):
    def test_same_items_lanes_and_conditions_other_id(self):
        live, rehearsal = load_plan(LIVE), load_plan(REHEARSAL)
        self.assertEqual((live['plan_id'], rehearsal['plan_id']), ('demo-live-v1', 'demo-live-rehearsal-v1'))
        self.assertEqual(rehearsal['items'], live['items'])
        self.assertTrue(live['requires_final_freeze'] and rehearsal['requires_final_freeze'])
        for lane in (1, 2):
            self.assertEqual(lane_items(rehearsal, lane, 2), lane_items(live, lane, 2))
        self.assertEqual([i.key for i in lane_items(rehearsal, 1, 2)], ['DEMO-CT-stall-v1:block:1'])
        self.assertEqual([i.key for i in lane_items(rehearsal, 2, 2)], ['DEMO-CL-stall-v1:block:1'])

    def test_only_the_id_and_description_differ(self):
        live, rehearsal = (yaml.safe_load(p.read_text(encoding='utf-8')) for p in (LIVE, REHEARSAL))
        differ = {k for k in set(live) | set(rehearsal) if live.get(k) != rehearsal.get(k)}
        self.assertEqual(differ, {'plan_id', 'description'})


if __name__ == '__main__':
    unittest.main()
