import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


class StartEpicThen(unittest.TestCase):
    def test_sends_link_once_epic_log_says_signed_in(self):
        log = Path(tempfile.mkdtemp()) / "EpicGamesLauncher.log"
        sent = []
        write = lambda: (time.sleep(1), log.write_text("FAccountService::OnLoginComplete - 0 TRUE"))
        threading.Thread(target=write).start()
        with mock.patch.object(server, "EPIC_LOG", log), mock.patch.object(server.subprocess, "Popen") as popen:
            t0 = time.time()
            server.start_epic_then(r"C:\Epic\EpicGamesLauncher.exe", lambda: sent.append(time.time() - t0))
        self.assertEqual(popen.call_args[0][0], [r"C:\Epic\EpicGamesLauncher.exe", "-silent"])
        self.assertEqual(len(sent), 1)
        self.assertTrue(0.9 < sent[0] < 3, sent)  # waited for the log, didn't sit out the 30 s

    def test_old_log_from_before_start_doesnt_count(self):
        log = Path(tempfile.mkdtemp()) / "EpicGamesLauncher.log"
        log.write_text("FAccountService::OnLoginComplete - 0 TRUE")  # last run's log
        sent = []
        clock = iter(range(0, 1000, 10))  # each time.time() call moves 10 s on, so the 30 s limit comes fast
        with mock.patch.object(server, "EPIC_LOG", log), mock.patch.object(server.subprocess, "Popen"), \
                mock.patch.object(server.time, "time", lambda: next(clock) + log.stat().st_mtime + 1), \
                mock.patch.object(server.time, "sleep"):
            server.start_epic_then("x.exe", lambda: sent.append(1))
        self.assertEqual(sent, [1])  # still sends the link after giving up


if __name__ == "__main__":
    unittest.main()
