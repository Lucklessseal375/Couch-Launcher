import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log


class StartThen(unittest.TestCase):
    def test_goes_on_once_the_log_says_signed_in(self):
        log = Path(tempfile.mkdtemp()) / "EpicGamesLauncher.log"
        sent = []
        write = lambda: (time.sleep(1), log.write_text("FAccountService::OnLoginComplete - 0 TRUE"))
        threading.Thread(target=write).start()
        with mock.patch.object(server.subprocess, "Popen") as popen:
            t0 = time.time()
            server.start_then([r"C:\Epic\EpicGamesLauncher.exe", "-silent"], log, "OnLoginComplete",
                              lambda: sent.append(time.time() - t0), 30)
        self.assertEqual(popen.call_args[0][0], [r"C:\Epic\EpicGamesLauncher.exe", "-silent"])
        self.assertEqual(len(sent), 1)
        self.assertTrue(0.9 < sent[0] < 3, sent)  # waited for the log, didn't sit out the limit

    def test_old_log_from_before_start_doesnt_count(self):
        log = Path(tempfile.mkdtemp()) / "launcher.log"
        log.write_text("User 'x' is now signed in")  # last run's log
        sent = []
        clock = iter(range(0, 1000, 10))  # each time.time() call moves 10 s on, so the limit comes fast
        with mock.patch.object(server.subprocess, "Popen"), \
                mock.patch.object(server.time, "time", lambda: next(clock) + log.stat().st_mtime + 1), \
                mock.patch.object(server.time, "sleep"):
            server.start_then(["x.exe"], log, "is now signed in", lambda: sent.append(1), 60)
        self.assertEqual(sent, [1])  # still goes on after giving up


class LaunchGta(unittest.TestCase):
    def setUp(self):  # never let a test reach the real open_url / Popen: they launch things on the TV
        gta = {"id": "gta5", "name": "GTA", "kind": "url", "target": "com.epicgames.launcher://x", "rockstar": True}
        for name, kw in [("load_apps", {"return_value": ([], [])}), ("load_games", {"return_value": [gta]}),
                         ("load_choices", {"return_value": {"played": {}}}), ("save_choices", {}),
                         ("open_url", {}), ("start_then", {})]:
            p = mock.patch.object(server, name, **kw)
            setattr(self, name, p.start())
            self.addCleanup(p.stop)

    def launch(self, rockstar_running):
        with mock.patch.object(server, "exe_running", return_value=rockstar_running):
            server.launch_app("gta5")
        time.sleep(0.2)  # the Rockstar wait runs on its own thread

    def test_rockstar_closed_starts_it_first(self):
        self.launch(rockstar_running=False)
        self.open_url.assert_not_called()  # the link waits for Rockstar
        self.assertEqual(self.start_then.call_args[0][0], [server.ROCKSTAR_EXE])
        self.start_then.call_args[0][3]()  # Rockstar signed in: now the link goes
        self.open_url.assert_called_once_with("com.epicgames.launcher://x")

    def test_rockstar_open_sends_link_straight_away(self):
        self.launch(rockstar_running=True)
        self.open_url.assert_called_once_with("com.epicgames.launcher://x")
        self.start_then.assert_not_called()


if __name__ == "__main__":
    unittest.main()
