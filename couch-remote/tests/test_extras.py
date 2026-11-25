import json
import sys
import tempfile
import time
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


class SteamBigPicture(unittest.TestCase):
    def open_bp(self, steam_running):
        with mock.patch.object(server, "exe_running", return_value=steam_running), \
                mock.patch.object(server.winreg, "OpenKey", mock.MagicMock()), \
                mock.patch.object(server.winreg, "QueryValueEx", return_value=(r'"C:\Steam\steam.exe" -- "%1"', 1)), \
                mock.patch.object(server.subprocess, "Popen") as popen:
            server.open_url("steam://open/bigpicture")
        return popen.call_args[0][0]

    def test_closed_steam_starts_straight_in_big_picture(self):
        self.assertEqual(self.open_bp(False), [r"C:\Steam\steam.exe", "-gamepadui"])

    def test_running_steam_gets_the_link(self):
        self.assertEqual(self.open_bp(True), [r"C:\Steam\steam.exe", "--", "steam://open/bigpicture"])


class RemoteKeys(unittest.TestCase):
    def run_key(self, key, in_couch, exe="msedge.exe"):
        with mock.patch.object(server, "launcher_in_front", return_value=in_couch), \
                mock.patch.object(server, "window_exe", return_value=exe), \
                mock.patch.object(server, "emit") as emit, mock.patch.object(server, "press") as press, \
                mock.patch.object(server, "back_or_close") as boc:
            server.remote_key(key)
            time.sleep(0.05)  # back_or_close runs on a thread
        return emit, press, boc

    def test_back_in_couch_is_the_controller_circle(self):
        emit, press, _ = self.run_key("escape", True)
        emit.assert_called_once_with("b")
        press.assert_not_called()

    def test_back_in_stremio_goes_back_like_the_controller(self):
        _, press, boc = self.run_key("escape", False, "stremio-shell-ng.exe")
        self.assertEqual(boc.call_args[0][1], "backspace")
        press.assert_not_called()

    def test_other_keys_and_other_apps_get_the_real_key(self):
        _, press, _ = self.run_key("escape", False)
        press.assert_called_once_with("escape")
        _, press, _ = self.run_key("volup", True)
        press.assert_called_once_with("volup")


class Diagnostics(unittest.TestCase):
    def test_user_folder_and_name_are_taken_out(self):
        with mock.patch.object(server.Path, "home", return_value=Path(r"C:\Users\pat")), \
                mock.patch.dict(server.os.environ, {"USERNAME": "pat"}):
            self.assertEqual(server.redact(r"C:\Users\pat\x.log pat's PC, patio"), r"%USERPROFILE%\x.log <user>'s PC, patio")

    def test_lines_cover_version_streaming_and_problems(self):
        with mock.patch.object(server, "library", return_value=([], [])), \
                mock.patch.object(server, "shown_apps", return_value=([{"id": "a"}], [])), \
                mock.patch.object(server, "sunshine_status", return_value="running"):
            text = "\n".join(server.diagnostics())
        for part in ("Couch ", "Last update check:", "Streaming: Sunshine running", "Apps: 1, games: 0", "Recent problems:"):
            self.assertIn(part, text)


class DisplayModes(unittest.TestCase):
    def test_menu_offers_main_sizes_and_faster_refresh(self):
        import display
        all_modes = [(3840, 2160, 120), (3840, 2160, 60), (3840, 2160, 30), (2560, 1440, 144), (1920, 1080, 60),
                     (1920, 1080, 120), (1600, 900, 60)]
        self.assertEqual(display.choices(all_modes, (3840, 2160, 60)),
                         [(3840, 2160, 60), (3840, 2160, 120), (2560, 1440, 144), (1920, 1080, 120)])

    def test_only_modes_the_tv_offers(self):
        with mock.patch.object(server.display, "modes", return_value=[(1920, 1080, 60)]):
            self.assertEqual(server.valid_mode(["1920", 1080, 60]), (1920, 1080, 60))
            with self.assertRaises(ValueError):
                server.valid_mode([7680, 4320, 60])

    def test_tried_mode_undoes_itself(self):
        with mock.patch.object(server.display, "modes", return_value=[(1920, 1080, 60)]), \
                mock.patch.object(server.display, "apply", return_value=True), \
                mock.patch.object(server.display, "restore") as restore, \
                mock.patch.object(server.threading, "Timer") as timer:
            server.try_mode([1920, 1080, 60])
            self.assertEqual(timer.call_args[0], (15, server.undo_mode))
            server.undo_mode()
        restore.assert_called_once()

    def test_kept_mode_is_saved_per_game_and_cleared(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, mock.patch.object(server, "CHOICES_FILE", Path(d) / "c.json"), \
                mock.patch.object(server.display, "modes", return_value=[(1920, 1080, 60)]), \
                mock.patch.object(server.display, "restore"):
            server.set_game_mode("steam:1", [1920, 1080, 60])
            self.assertEqual(server.load_choices()["display"], {"steam:1": [1920, 1080, 60]})
            server.set_game_mode("steam:1")
            self.assertEqual(server.load_choices()["display"], {})

    def test_desktop_mode_returns_when_the_game_closes(self):
        clock = [0.0]
        windows = iter([None, 7, 7, None])  # starting, playing, playing, closed
        with mock.patch.object(server.time, "time", lambda: clock[0]),                 mock.patch.object(server.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s)),                 mock.patch.object(server, "running_window", lambda: next(windows)),                 mock.patch.object(server.display, "restore") as restore:
            server.game_mode_watch(0.0)
        restore.assert_called_once()
        self.assertEqual(clock[0], 8)  # right after the window went, not at the 2-minute fallback

    def test_game_that_never_opens_gets_the_desktop_back_after_2_minutes(self):
        clock = [0.0]
        with mock.patch.object(server.time, "time", lambda: clock[0]),                 mock.patch.object(server.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s)),                 mock.patch.object(server, "running_window", lambda: None),                 mock.patch.object(server.display, "restore") as restore:
            server.game_mode_watch(0.0)
        restore.assert_called_once()
        self.assertTrue(120 < clock[0] <= 124)
