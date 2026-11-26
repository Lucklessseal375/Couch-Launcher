import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log


class Installed(unittest.TestCase):
    def test_exe_needs_its_program(self):
        self.assertFalse(server.installed({"kind": "exe", "target": r"C:\nope\missing.exe"}))
        self.assertTrue(server.installed({"kind": "exe", "target": sys.executable}))

    def test_url_needs_a_handler(self):
        self.assertFalse(server.installed({"kind": "url", "target": "nosuchscheme12345://x"}))
        self.assertTrue(server.installed({"kind": "url", "target": "https://example.com"}))

    def test_web_always_shown(self):
        self.assertTrue(server.installed({"kind": "web", "target": "https://www.youtube.com/tv"}))

    def test_needs_path_hides_any_kind(self):
        self.assertFalse(server.installed({"kind": "web", "target": "https://x", "needs": r"C:\nope\folder"}))
        self.assertTrue(server.installed({"kind": "web", "target": "https://x", "needs": r"%SystemRoot%\System32"}))

    def test_unknown_kind_or_no_target_stays(self):
        self.assertTrue(server.installed({"kind": "something"}))

    def test_exe_with_no_target_gets_no_tile(self):
        self.assertFalse(server.installed({"kind": "exe"}))


if __name__ == "__main__":
    unittest.main()
