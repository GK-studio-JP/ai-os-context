import unittest

from ai_os_context.views import scheduler_view


class ViewTests(unittest.TestCase):
    def test_runnable_sorted_by_priority(self):
        rows = [
            {"task":"#2","state":"open","priority":10,"history_safe":True,"blocked_by":[]},
            {"task":"#1","state":"open","priority":90,"history_safe":True,"blocked_by":[]},
            {"task":"#3","state":"open","priority":100,"history_safe":True,"blocked_by":["#9"]},
        ]
        view = scheduler_view("x/y", rows)
        self.assertEqual([row["task"] for row in view["runnable"]], ["#1", "#2"])
        self.assertEqual([row["task"] for row in view["blocked"]], ["#3"])


if __name__ == "__main__":
    unittest.main()
