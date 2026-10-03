import copy
import unittest

from task_query import select_tasks


def item(id, title="Task", description="", status="open", priority=1):
    return {"id": id, "title": title, "description": description, "status": status, "priority": priority}


class TaskQueryAcceptance(unittest.TestCase):
    def test_empty_collection(self):
        self.assertEqual(select_tasks([]), [])

    def test_title_search(self):
        a, b = item("a", "Alpha"), item("b", "Beta")
        self.assertEqual(select_tasks([a, b], query="alpha"), [a])

    def test_case_sensitive_search(self):
        a, b = item("a", "Alpha"), item("b", "Beta")
        self.assertEqual(select_tasks([a, b], query="alpha"), [])

    def test_default_hides_completed(self):
        a, b = item("a"), item("b", status="done")
        self.assertEqual(select_tasks([a, b]), [a])

    def test_done_filter(self):
        a, b = item("a"), item("b", status="done")
        self.assertEqual(select_tasks([a, b], status="done"), [b])

    def test_all_statuses(self):
        tasks = [item("a"), item("b", status="done")]
        self.assertEqual(select_tasks(tasks, status="all"), tasks)

    def test_does_not_mutate_inputs(self):
        tasks = [item("b", priority=0), item("a", priority=2)]
        before = copy.deepcopy(tasks)
        select_tasks(tasks, status="all", limit=1)
        self.assertEqual(tasks, before)

    def test_searches_description(self):
        a = item("a", description="Security review")
        self.assertEqual(select_tasks([a], query="security"), [a])

    def test_nfkc_casefold_search(self):
        a = item("a", title="Café")
        self.assertEqual(select_tasks([a], query="ＣＡＦÉ"), [a])

    def test_whitespace_normalization(self):
        a = item("a", title="Release   notes")
        self.assertEqual(select_tasks([a], query="  release notes  "), [a])

    def test_priority_sort(self):
        low, high = item("a", priority=1), item("b", priority=3)
        self.assertEqual(select_tasks([low, high]), [high, low])

    def test_stable_id_tiebreak(self):
        a, b = item("a"), item("b")
        self.assertEqual(select_tasks([b, a]), [a, b])

    def test_pagination_after_filtering(self):
        done, a, b = item("0", status="done"), item("a"), item("b")
        self.assertEqual(select_tasks([done, a, b], offset=1, limit=1), [b])

    def test_unknown_status_rejected(self):
        with self.assertRaises(ValueError):
            select_tasks([item("a")], status="archived")

    def test_negative_offset_rejected(self):
        with self.assertRaises(ValueError):
            select_tasks([item("a")], offset=-1)

    def test_negative_limit_rejected(self):
        with self.assertRaises(ValueError):
            select_tasks([item("a")], limit=-1)

    def test_zero_limit(self):
        self.assertEqual(select_tasks([item("a")], limit=0), [])
