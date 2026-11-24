import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log

COUCH, EPIC, SIGNIN, GAME = 1, 2, 3, 4
EXE = {EPIC: "epicgameslauncher.exe", SIGNIN: "socialclubhelper.exe", GAME: "gta5_enhanced.exe"}


class CoverStoreLaunchers(unittest.TestCase):
    def run_launch(self, timeline, titles, is_game=True, foreground=lambda t: COUCH, before=(), fullscreen=False, exe=""):
        """timeline: {second: window that appears then}. Returns [(second, window focused)]."""
        clock, shown, focused = [0.0], [], []

        def sleep(s):
            clock[0] += s
            for at, h in timeline.items():
                if clock[0] >= at and h not in shown:
                    shown.append(h)

        server.RUNNING.update(name="GTA", windows=[], game_seen=False, is_game=is_game, fullscreen=fullscreen, exe=exe)
        self.filled = []
        with mock.patch.object(server.time, "time", lambda: clock[0]), \
                mock.patch.object(server.time, "sleep", sleep), \
                mock.patch.object(server, "visible_windows", lambda: list(shown)), \
                mock.patch.object(server, "window_exe", lambda h: EXE.get(h, "msedge.exe")), \
                mock.patch.object(server, "window_title", lambda h: titles(h, clock[0])), \
                mock.patch.object(server, "find_launcher", lambda: COUCH), \
                mock.patch.object(server, "focus_window", lambda h: focused.append((round(clock[0]), h))), \
                mock.patch.object(server.user32, "GetForegroundWindow", lambda: foreground(clock[0])), \
                mock.patch.object(server, "borderless_fullscreen", self.filled.append), \
                mock.patch.object(server, "load_choices", return_value={"took": {}}), \
                mock.patch.object(server, "save_choices") as save:  # never the real choices.json
            server.focus_what_opens(list(before))
        self.saved = save.call_args[0][0]["took"] if save.called else None
        return focused

    def test_auto_sign_in_never_shows_a_launcher(self):
        title = lambda h, t: "Rockstar Games - Sign In" if t < 10 else "Rockstar Games Launcher"
        focused = self.run_launch({2: SIGNIN, 12: EPIC, 30: GAME}, title)
        self.assertNotIn(EPIC, [h for _, h in focused])
        self.assertNotIn(SIGNIN, [h for _, h in focused])
        self.assertEqual(focused[-1][1], GAME)
        self.assertEqual(self.saved, {"GTA": 30})  # launch time kept for the next Starting screen

    def test_sign_in_still_waiting_after_15_s_comes_forward(self):
        focused = self.run_launch({2: SIGNIN, 60: GAME}, lambda h, t: "Rockstar Games - Sign In")
        signin = [t for t, h in focused if h == SIGNIN]
        self.assertTrue(signin and 17 <= signin[0] <= 19, focused)
        self.assertEqual(focused[-1][1], GAME)

    def test_no_game_after_90_s_shows_newest_launcher(self):
        focused = self.run_launch({2: EPIC, 5: SIGNIN}, lambda h, t: "Rockstar Games Launcher")
        self.assertIn(SIGNIN, [h for t, h in focused if 90 <= t <= 92])

    def test_launcher_grabbing_the_screen_is_covered_again_until_the_game(self):
        fg = lambda t: EPIC if 20 <= t < 60 else COUCH  # Epic keeps itself in front from 20 s on
        focused = self.run_launch({2: EPIC, 40: GAME}, lambda h, t: "Epic Games Launcher", foreground=fg)
        self.assertIn(COUCH, [h for t, h in focused if 20 <= t < 40])
        self.assertNotIn(COUCH, [h for t, h in focused if t > 40])  # never pulled back over the game

    def test_already_open_launcher_coming_forward_is_covered(self):
        fg = lambda t: SIGNIN if 5 <= t < 30 else COUCH  # Rockstar's open launcher jumps forward as GTA starts
        focused = self.run_launch({0: SIGNIN, 30: GAME}, lambda h, t: "Rockstar Games Launcher", foreground=fg,
                                  before=[SIGNIN])
        self.assertIn(COUCH, [h for t, h in focused if 5 <= t < 30])
        self.assertNotIn(SIGNIN, [h for _, h in focused])
        self.assertEqual(focused[-1][1], GAME)

    def test_app_already_running_isnt_taken_for_the_game(self):
        CLAUDE = 5  # Claude, started at login, opens its window while GTA is starting
        with mock.patch.object(server, "started_after", lambda h, t: h != CLAUDE):
            focused = self.run_launch({2: EPIC, 20: CLAUDE, 40: GAME}, lambda h, t: "Epic Games Launcher")
        self.assertNotIn(CLAUDE, [h for _, h in focused])
        self.assertNotIn(CLAUDE, server.RUNNING["windows"])  # never offered as "Close game"
        self.assertEqual(focused[-1][1], GAME)
        self.assertEqual(self.saved, {"GTA": 40})  # timed by the game's window, not Claude's

    def test_fullscreen_app_fills_the_screen(self):
        STREMIO = 7
        focused = self.run_launch({1: STREMIO}, lambda h, t: "Stremio", is_game=False, fullscreen=True)
        self.assertEqual(self.filled, [STREMIO])
        self.assertEqual(focused[0][1], STREMIO)
        self.run_launch({1: STREMIO}, lambda h, t: "Stremio", is_game=False)
        self.assertEqual(self.filled, [])  # only apps marked "fullscreen"

    def test_app_already_open_comes_back_full_screen(self):
        STREMIO = 7  # open before the press; a second launch opens no window
        EXE[STREMIO] = "stremio-shell-ng.exe"
        self.addCleanup(EXE.pop, STREMIO)
        focused = self.run_launch({}, lambda h, t: "Stremio", is_game=False, before=[STREMIO], fullscreen=True,
                                  exe="stremio-shell-ng.exe")
        self.assertEqual(focused, [(0, STREMIO)])  # right away, not after waiting for a new window
        self.assertEqual(self.filled, [STREMIO])

    def test_app_tiles_still_focus_their_windows(self):
        focused = self.run_launch({2: EPIC}, lambda h, t: "Epic Games Launcher", is_game=False)
        self.assertEqual(focused[0][1], EPIC)


class WarmRockstar(unittest.TestCase):
    def run_warm(self, running, fg_exe, launch_at=None):
        clock, focused = [0.0], []
        server.RUNNING.update(name=None)

        def sleep(s):
            clock[0] += s
            if launch_at is not None and clock[0] >= launch_at:
                server.RUNNING["name"] = "GTA"

        with mock.patch.object(server, "exe_running", return_value=running), \
                mock.patch.object(server.subprocess, "Popen") as popen, \
                mock.patch.object(server.time, "time", lambda: clock[0]), \
                mock.patch.object(server.time, "sleep", sleep), \
                mock.patch.object(server.user32, "GetForegroundWindow", lambda: 9), \
                mock.patch.object(server, "window_exe", lambda h: fg_exe(clock[0])), \
                mock.patch.object(server, "find_launcher", lambda: COUCH), \
                mock.patch.object(server, "focus_window", lambda h: focused.append(round(clock[0]))):
            server.warm_rockstar()
        return popen, focused

    def test_already_running_does_nothing(self):
        popen, focused = self.run_warm(True, lambda t: "socialclubhelper.exe")
        popen.assert_not_called()
        self.assertEqual(focused, [])

    def test_starts_it_and_keeps_couch_in_front(self):
        popen, focused = self.run_warm(False, lambda t: "socialclubhelper.exe" if 3 <= t < 6 else "msedge.exe")
        self.assertEqual(popen.call_args[0][0], [server.ROCKSTAR_EXE])
        self.assertTrue(focused and all(3 <= t <= 6 for t in focused), focused)  # times are rounded

    def test_stops_when_a_game_launch_takes_over(self):
        _, focused = self.run_warm(False, lambda t: "socialclubhelper.exe", launch_at=10)
        self.assertTrue(focused and max(focused) <= 10, focused)


if __name__ == "__main__":
    unittest.main()
