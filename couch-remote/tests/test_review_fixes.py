import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import update  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log


class Range(unittest.TestCase):
    """A real server on this PC only, serving one fake song."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        song = Path(d.name) / "a.mp3"
        self.data = bytes(range(256)) * 1000  # bigger than one 64 KB piece
        song.write_bytes(self.data)
        p = mock.patch.object(server, "music_files", return_value=[song])
        p.start()
        self.addCleanup(p.stop)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.url = f"http://127.0.0.1:{srv.server_port}/music/0"

    def get(self, rng=None):
        req = urllib.request.Request(self.url, headers={"Range": rng} if rng else {})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers.get("Content-Range"), r.read()

    def test_whole_file_and_pieces(self):
        n = len(self.data)
        self.assertEqual(self.get(), (200, None, self.data))
        self.assertEqual(self.get("bytes=10-19"), (206, f"bytes 10-19/{n}", self.data[10:20]))
        self.assertEqual(self.get("bytes=100-"), (206, f"bytes 100-{n - 1}/{n}", self.data[100:]))
        self.assertEqual(self.get("bytes=-5"), (206, f"bytes {n - 5}-{n - 1}/{n}", self.data[-5:]))
        self.assertEqual(self.get("bytes=-"), (200, None, self.data))  # malformed: ignored

    def test_past_the_end(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get(f"bytes={len(self.data)}-")
        self.assertEqual(e.exception.code, 416)
        self.assertEqual(e.exception.headers.get("Accept-Ranges"), "bytes")

    def test_empty_file_is_served_and_ignores_range(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        empty = Path(d.name) / "a.mp3"
        empty.write_bytes(b"")
        p = mock.patch.object(server, "music_files", return_value=[empty])
        p.start()
        self.addCleanup(p.stop)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.url = f"http://127.0.0.1:{srv.server_port}/music/0"
        self.assertEqual(self.get(), (200, None, b""))
        self.assertEqual(self.get("bytes=0-"), (200, None, b""))

    def test_head_sends_headers_without_a_body(self):
        req = urllib.request.Request(self.url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers.get("Content-Length"), str(len(self.data)))
            self.assertEqual(r.read(), b"")


class Odds(unittest.TestCase):
    def test_key_app_survives_an_entry_without_a_target(self):
        with mock.patch.object(server, "load_apps", return_value=([{"id": "x", "keys": {"a": "enter"}}], set())):
            self.assertEqual(server.key_app("game.exe"), {})

    def test_empty_link_handler_goes_to_windows(self):
        with mock.patch.object(server.winreg, "OpenKey"), \
                mock.patch.object(server.winreg, "QueryValueEx", return_value=("", 1)), \
                mock.patch.object(server.os, "startfile") as startfile, \
                mock.patch.object(server.subprocess, "Popen") as popen:
            server.open_url("odd://x")
        startfile.assert_called_once_with("odd://x")
        popen.assert_not_called()

    def test_vanished_file_sorts_last(self):
        self.assertEqual(server.mtime(Path(r"C:\nope\gone.png")), 0)

    def test_charge_probed_only_for_a_wireless_dualsense(self):
        self.addCleanup(server.PADS.__setitem__, slice(None), list(server.PADS))
        self.addCleanup(server.CHARGING.__setitem__, 0, None)
        with mock.patch.object(server, "dualsense_charging", return_value=True) as probe:
            for name, level, calls in (("Xbox Controller", "full", 0), ("DualSense Wireless Controller", "wired", 0),
                                       ("DualSense Wireless Controller", "full", 1)):
                server.PADS[:] = [{"name": name, "level": level}]
                server.check_charging()
                self.assertEqual(probe.call_count, calls)
        self.assertIs(server.CHARGING[0], True)

    def test_update_zip_without_couch_in_it_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            for names in ((), ("readme.txt",)):
                z = Path(d) / "c.zip"
                with zipfile.ZipFile(z, "w") as f:
                    for n in names:
                        f.writestr(n, "x")
                self.assertIsNone(update.apply(Path(d), z, "abc"))


if __name__ == "__main__":
    unittest.main()
