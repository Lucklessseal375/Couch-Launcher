import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log

APPS = [{"id": "stremio", "kind": "exe", "target": "%LOCALAPPDATA%\\Programs\\Stremio\\stremio-shell-ng.exe",
         "keys": {"a": "enter", "b": "backspace"}},
        {"id": "epic", "kind": "exe", "target": "C:\\Epic\\EpicGamesLauncher.exe"}]


class AppKeys(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(server, "load_apps", return_value=(APPS, set()))
        p.start()
        self.addCleanup(p.stop)

    def test_app_in_front_gets_its_keys(self):
        self.assertEqual(server.app_keys("stremio-shell-ng.exe"), {"a": "enter", "b": "backspace"})

    def test_app_without_keys_gets_none(self):
        self.assertEqual(server.app_keys("epicgameslauncher.exe"), {})
        self.assertEqual(server.app_keys(""), {})

    def test_every_key_in_apps_json_exists(self):
        apps = __import__("json").loads(server.APPS_FILE.read_text(encoding="utf-8"))["apps"]
        for a in apps:
            for button, key in a.get("keys", {}).items():
                self.assertIn(key, server.KEYS, f"{a['id']}: {button}")


if __name__ == "__main__":
    unittest.main()
