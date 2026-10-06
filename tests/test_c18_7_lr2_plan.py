"""LR supplement plan (C-18-7 part 2, DM-78 ④): the file the PM ran from outside the repository, committed byte for
byte. Offline."""
from pathlib import Path
import unittest

from tools.run_batch import lane_items, load_plan

ROOT = Path(__file__).resolve().parents[1]
LR2 = ROOT / 'batch_plans/demo-main-v1-lr2.yaml'
MAIN = ROOT / 'batch_plans/demo-main-v1.yaml'
# plan_sha256 of every line in runs/demo-batches/demo-main-v1-lr2/lane-1-of-1.jsonl (the supplement run, 10/6)
RAN_SHA256 = '09cc3ef0a108efc72df62078b111591760405bb5258233fdf471f923cd1cf17c'


class LrSupplementPlanTests(unittest.TestCase):
    def test_same_bytes_as_the_run(self):
        self.assertEqual(load_plan(LR2)['plan_sha256'], RAN_SHA256)

    def test_the_lr_items_of_the_main_plan_in_one_lane_under_the_final_freeze(self):
        plan, main = load_plan(LR2), load_plan(MAIN)
        self.assertEqual((plan['plan_id'], plan['requires_final_freeze']), ('demo-main-v1-lr2', True))
        lr = [i for i in main['items'] if i.one_at_a_time]
        self.assertEqual(plan['items'], lr)
        self.assertEqual((len(lr), lane_items(plan, 1, 1)), (13, lr))


if __name__ == '__main__':
    unittest.main()
