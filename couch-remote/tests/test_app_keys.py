import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log

STREMIO = {"id": "stremio", "kind": "exe", "target": "%LOCALAPPDATA%\\Programs\\Stremio\\stremio-shell-ng.exe",
           "keys": {"a": "enter", "b": "backspace"}, "back_closes": True}
APPS = [STREMIO, {"id": "epic", "kind": "exe", "target": "C:\\Epic\\EpicGamesLauncher.exe"}]


class KeyApp(unittest.TestCase):
    def test_app_in_front_is_found_by_its_program(self):
        with mock.patch.object(server, "load_apps", return_value=(APPS, set())):
            self.assertIs(server.key_app("stremio-shell-ng.exe"), STREMIO)
            self.assertEqual(server.key_app("epicgameslauncher.exe"), {})  # no "keys"
            self.assertEqual(server.key_app(""), {})

    def test_every_key_in_apps_json_exists(self):
        for a in json.loads(server.APPS_FILE.read_text(encoding="utf-8"))["apps"]:
            for button, key in a.get("keys", {}).items():
                self.assertIn(key, server.KEYS, f"{a['id']}: {button}")


HOME = "https://web.stremio.com/#/?streamingServerUrl=http%3A%2F%2F127.0.0.1%3A11470"
STREMIO_FIRST = next(a for a in json.loads(server.APPS_FILE.read_text(encoding="utf-8"))["apps"]
                     if a["id"] == "stremio")["back_closes"]


class BackOrClose(unittest.TestCase):
    def run_back(self, url, front=7):
        with mock.patch.object(server, "app_page_url", return_value=url), \
                mock.patch.object(server, "press") as press, \
                mock.patch.object(server.time, "sleep"), \
                mock.patch.object(server.user32, "GetForegroundWindow", return_value=front), \
                mock.patch.object(server.user32, "PostMessageW") as post, \
                mock.patch.object(server, "window_exe", return_value="stremio-shell-ng.exe"), \
                mock.patch.object(server, "open_launcher") as launcher:
            server.back_or_close(7, "backspace", STREMIO_FIRST)
        return press, post, launcher

    def test_back_anywhere_else_just_goes_back(self):
        for url in ("https://web.stremio.com/#/detail/series/tt9813792/tt9813792%3A4%3A10",
                    "https://web.stremio.com/#/detail/series/tt9813792?season=4", "https://web.stremio.com/#/settings",
                    ""):  # opened some other way: Couch can't tell, so never closes it
            press, post, _ = self.run_back(url)
            press.assert_called_once_with("backspace")
            post.assert_not_called()

    def test_back_on_the_board_closes_stremio(self):
        for url in (HOME, "https://web.stremio.com/#/"):
            press, post, launcher = self.run_back(url)
            press.assert_not_called()
            post.assert_called_once_with(7, 0x0010, 0, 0)
            launcher.assert_called_once()

    def test_another_window_in_front_is_never_closed(self):
        _, post, _ = self.run_back(HOME, front=9)
        post.assert_not_called()


class PageScript(unittest.TestCase):
    def test_every_page_script_in_apps_json_exists(self):
        for a in json.loads(server.APPS_FILE.read_text(encoding="utf-8"))["apps"]:
            if a.get("page_script"):
                self.assertTrue((server.ROOT / a["page_script"]).is_file(), a["page_script"])

    def test_runs_until_the_page_says_it_worked(self):
        answers = iter([None, False, True])  # page not up, script says not yet, then done
        cdp = mock.Mock()

        def connect(url):
            v = next(answers)
            if v is None:
                raise ConnectionError("not up yet")
            cdp.send.return_value = {"result": {"type": "boolean", "value": v}}
            return cdp
        with mock.patch.object(server, "app_page", return_value={"webSocketDebuggerUrl": "ws://x"}), \
                mock.patch.object(server, "Cdp", side_effect=connect), \
                mock.patch.object(server.time, "sleep") as sleep:
            server.run_page_script("load()")
        self.assertEqual(sleep.call_count, 2)
        cdp.send.assert_called_with("Runtime.evaluate", expression="load()", returnByValue=True)

    def test_gives_up_when_the_app_has_no_devtools(self):
        clock = iter(range(0, 1000, 5))
        with mock.patch.object(server, "app_page", return_value={}), \
                mock.patch.object(server.time, "time", lambda: next(clock)), \
                mock.patch.object(server.time, "sleep"):
            server.run_page_script("load()", limit=30)  # returns instead of looping forever


class HeldDirection(unittest.TestCase):
    def test_couch_keeps_a_steady_pace(self):
        self.assertEqual({server.repeat_gap(n, True) for n in range(1, 40)}, {0.11})

    def test_other_apps_speed_up_to_25_a_second(self):
        gaps = [server.repeat_gap(n, False) for n in range(1, 40)]
        self.assertEqual(gaps, sorted(gaps, reverse=True))  # never slows down while held
        self.assertAlmostEqual(gaps[0], 0.10)
        self.assertAlmostEqual(min(gaps), 0.04)
        self.assertLess(sum(gaps[:7]), 1.0)  # full speed within a second


if __name__ == "__main__":
    unittest.main()


class FitPageToScreen(unittest.TestCase):
    def run_fit(self, sizes):
        cdp = mock.MagicMock()
        cdp.send.side_effect = lambda method, **kw: {"result": {"value": sizes}} if method == "Runtime.evaluate" else {}
        cdp.s.recv.return_value = b""  # the app closes right away
        with mock.patch.object(server, "Cdp", return_value=cdp), \
                mock.patch.object(server, "app_page", return_value={"webSocketDebuggerUrl": "ws://x:1/p"}):
            server.fit_page_to_screen()
        return [c for c in cdp.send.call_args_list if c.args[0] == "Emulation.setDeviceMetricsOverride"]

    def test_page_wider_than_the_screen_is_fitted(self):
        (call,) = self.run_fit([1280, 720, 1366])
        self.assertEqual((call.kwargs["width"], call.kwargs["height"]), (1280, 720))
        self.assertFalse(server.FITTING[0])

    def test_page_that_fits_is_left_alone(self):
        self.assertEqual(self.run_fit([1920, 1080, 1920]), [])
