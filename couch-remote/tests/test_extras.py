import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log


class SleepRules(unittest.TestCase):
    def setUp(self):
        server.SLEEP["at"] = 0
        self.addCleanup(server.SLEEP.update, at=0)

    def test_timer_sleeps_when_it_runs_out_even_mid_game(self):
        server.SLEEP["at"] = 1000
        self.assertFalse(server.sleep_due(999, 0, 0, False, True))
        self.assertTrue(server.sleep_due(1000, 0, 0, True, True))

    def test_idle_rule_waits_for_nothing_playing(self):
        self.assertTrue(server.sleep_due(0, 3600, 60, False, False))
        self.assertFalse(server.sleep_due(0, 3599, 60, False, False))
        self.assertFalse(server.sleep_due(0, 7200, 60, True, False))  # streaming to the Apple TV
        self.assertFalse(server.sleep_due(0, 7200, 60, False, True))  # a game is open
        self.assertFalse(server.sleep_due(0, 7200, 0, False, False))  # rule off


class Wlan(unittest.TestCase):
    def test_wifi_with_signal(self):
        out = "    Name                   : Wi-Fi\n    State                  : connected\n    SSID                   : Home\n" \
              "    BSSID                  : aa:bb\n    Signal                 : 80%\n"
        self.assertEqual(server.parse_wlan(out), {"kind": "wifi", "signal": 80, "name": "Home"})

    def test_no_wifi_is_wired(self):
        self.assertEqual(server.parse_wlan("There is no wireless interface on the system."), {"kind": "wired"})
        self.assertEqual(server.parse_wlan("    State : disconnected\n"), {"kind": "wired"})


class GameChoices(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        patches = [mock.patch.object(server, "CHOICES_FILE", Path(d) / "choices.json"),
                   mock.patch.object(server, "load_games", lambda: [{"id": "gta5", "name": "GTA V Enhanced", "lastPlayed": 0}]),
                   mock.patch.object(server, "steam_games", lambda: [{"appid": 2, "name": "Cuphead", "lastPlayed": 5}]),
                   mock.patch.object(server, "steam_playtime", lambda: {})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_rename_and_art_show_and_reset(self):
        server.set_choice("rename", "gta5", "GTA")
        server.set_choice("art", "gta5", "/media/Screenshot (3).png")
        g = next(g for g in server.library()[0] if g["key"] == "gta5")
        self.assertEqual((g["title"], g["name"], g["hero"]), ("GTA", "GTA V Enhanced", "/media/Screenshot (3).png"))
        server.set_choice("rename", "gta5", "")
        server.set_choice("art", "gta5", "")
        g = next(g for g in server.library()[0] if g["key"] == "gta5")
        self.assertNotIn("title", g)
        self.assertNotIn("hero", g)

    def test_art_must_be_a_screenshot(self):
        with self.assertRaises(ValueError):
            server.set_choice("art", "gta5", "https://example.com/x.png")

    def test_unhide_one(self):
        server.set_choice("hide", "gta5")
        server.set_choice("hide", "steam:2")
        self.assertEqual([h["key"] for h in server.library()[1]], ["steam:2", "gta5"])
        server.set_choice("unhide", "gta5")
        self.assertEqual(server.library()[1], [{"name": "Cuphead", "key": "steam:2"}])
        self.assertEqual(json.loads(server.CHOICES_FILE.read_text(encoding="utf-8"))["hidden"], ["steam:2"])


class KeepAwake(unittest.TestCase):
    def test_request_made_and_released(self):
        k = mock.Mock()
        k.PowerCreateRequest.return_value = 42
        with mock.patch.object(server.ctypes.windll, "kernel32", k):
            server.keep_awake(True, "Streaming to Apple TV")
            server.keep_awake(True, "again")  # already held: no second request
            self.assertEqual(k.PowerCreateRequest.call_count, 1)
            self.assertEqual(k.PowerSetRequest.call_count, 2)  # display and system
            server.keep_awake(False)
            self.assertEqual(k.PowerClearRequest.call_count, 2)
            k.CloseHandle.assert_called_once()
        self.assertIsNone(server.AWAKE[0])


if __name__ == "__main__":
    unittest.main()
