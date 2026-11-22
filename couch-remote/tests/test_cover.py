import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

COUCH, EPIC, SIGNIN, GAME = 1, 2, 3, 4
EXE = {EPIC: "epicgameslauncher.exe", SIGNIN: "socialclubhelper.exe", GAME: "gta5_enhanced.exe"}


class CoverStoreLaunchers(unittest.TestCase):
    def run_launch(self, timeline, titles, is_game=True, foreground=lambda t: COUCH):
        """timeline: {second: window that appears then}. Returns [(second, window focused)]."""
        clock, shown, focused = [0.0], [], []

        def sleep(s):
            clock[0] += s
            for at, h in timeline.items():
                if clock[0] >= at and h not in shown:
                    shown.append(h)

        server.RUNNING.update(name="GTA", windows=[], game_seen=False, is_game=is_game)
        with mock.patch.object(server.time, "time", lambda: clock[0]), \
                mock.patch.object(server.time, "sleep", sleep), \
                mock.patch.object(server, "visible_windows", lambda: list(shown)), \
                mock.patch.object(server, "window_exe", lambda h: EXE.get(h, "msedge.exe")), \
                mock.patch.object(server, "window_title", lambda h: titles(h, clock[0])), \
                mock.patch.object(server, "find_launcher", lambda: COUCH), \
                mock.patch.object(server, "focus_window", lambda h: focused.append((round(clock[0]), h))), \
                mock.patch.object(server.user32, "GetForegroundWindow", lambda: foreground(clock[0])):
            server.focus_what_opens([])
        return focused

    def test_auto_sign_in_never_shows_a_launcher(self):
        title = lambda h, t: "Rockstar Games - Sign In" if t < 10 else "Rockstar Games Launcher"
        focused = self.run_launch({2: SIGNIN, 12: EPIC, 30: GAME}, title)
        self.assertNotIn(EPIC, [h for _, h in focused])
        self.assertNotIn(SIGNIN, [h for _, h in focused])
        self.assertEqual(focused[-1][1], GAME)

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

    def test_app_tiles_still_focus_their_windows(self):
        focused = self.run_launch({2: EPIC}, lambda h, t: "Epic Games Launcher", is_game=False)
        self.assertEqual(focused[0][1], EPIC)


if __name__ == "__main__":
    unittest.main()
