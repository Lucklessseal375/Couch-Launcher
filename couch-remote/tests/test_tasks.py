import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402


class TaskManagerTest(unittest.TestCase):
    def test_list_shape(self):
        t = server.task_list()
        self.assertGreater(t["memTotal"], t["memUsed"] > 0)
        for a in t["apps"]:
            self.assertEqual(set(a), {"id", "name", "exe", "bytes", "hung"})
            self.assertTrue(a["name"])

    def test_cpu_is_a_percentage(self):
        server.cpu_percent()
        v = server.cpu_percent()
        self.assertTrue(v is None or 0 <= v <= 100)

    def test_only_listed_windows_can_be_acted_on(self):
        with self.assertRaises(ValueError):
            server.task_action(0, "force")  # not a window the task manager lists


if __name__ == "__main__":
    unittest.main()
