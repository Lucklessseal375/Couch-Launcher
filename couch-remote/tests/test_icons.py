import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log

YOUTUBE = {"icons": [{"src": "/a/16.png", "sizes": "16x16", "purpose": "any"},
                     {"src": "/a/192.png", "sizes": "192x192"},
                     {"src": "/a/mono512.png", "sizes": "512x512", "purpose": "monochrome"},
                     {"src": "/a/mask512.png", "sizes": "512x512", "purpose": "maskable"}]}


class Icons(unittest.TestCase):
    def test_manifest_picks_biggest_plain_icon(self):
        self.assertEqual(server.manifest_icon(YOUTUBE, "https://www.youtube.com/manifest.webmanifest"),
                         "https://www.youtube.com/a/192.png")

    def test_msix_logo_ignores_other_args(self):
        self.assertIsNone(server.msix_logo(["--flag", "C:\\x.exe"]))

    def test_cached_icon_is_served_without_a_fetch_and_failures_are_remembered(self):
        tmp = Path(tempfile.mkdtemp())
        app = {"id": "web1", "kind": "web", "target": "https://example.invalid/"}
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(server, "ICON_CACHE", tmp).start()
        mock.patch.object(server, "load_apps", return_value=([app], None)).start()
        fetch = mock.patch.object(server, "web_icon_png", return_value=False).start()
        self.assertIsNone(server.app_icon("web1"))
        self.assertIsNone(server.app_icon("web1"))
        self.assertEqual(fetch.call_count, 1)  # the second miss came from the .none marker
        (tmp / "web1.none").unlink()
        (tmp / "web1.png").write_bytes(b"x")  # a hand-dropped override
        self.assertEqual(server.app_icon("web1"), tmp / "web1.png")
        self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
