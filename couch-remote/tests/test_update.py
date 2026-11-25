import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import update  # noqa: E402


def github_zip(path, files):
    """A ZIP shaped like GitHub's: everything inside one <repo>-<sha>/ folder."""
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(f"Couch-Launcher-abc/{name}", text)


class ApplyUpdate(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root, self.zip = Path(d.name) / "Couch", Path(d.name) / "u.zip"
        (self.root / "couch-remote" / "cache").mkdir(parents=True)
        (self.root / "couch-remote" / "config.json").write_text('{"city": "Here"}')
        (self.root / "couch-remote" / "choices.json").write_text("mine")
        (self.root / "install-couch.ps1").write_text("old installer")

    def run_apply(self, files, loads=True):
        github_zip(self.zip, files)
        with mock.patch.object(update, "imports_cleanly", return_value=loads):
            return update.apply(self.root, self.zip, "abc123")

    def test_new_files_in_this_pcs_settings_kept(self):
        changed = self.run_apply({"couch-remote/server.py": "new", "couch-remote/config.json": '{"city": "There"}',
                                  "install-couch.ps1": "old installer"})
        r = self.root / "couch-remote"
        self.assertEqual((r / "server.py").read_text(), "new")
        self.assertEqual((r / "config.json").read_text(), '{"city": "Here"}')
        self.assertEqual((r / "choices.json").read_text(), "mine")
        self.assertEqual(update.installed_sha(self.root), "abc123")
        self.assertFalse(changed)

    def test_line_endings_alone_arent_an_installer_change(self):
        (self.root / "install-couch.ps1").write_bytes(b"line 1\r\nline 2\r\n")  # a git checkout's CRLF
        self.assertFalse(self.run_apply({"install-couch.ps1": "line 1\nline 2\n"}))

    def test_changed_installer_is_flagged(self):
        self.assertTrue(self.run_apply({"install-couch.ps1": "new installer"}))
        self.assertTrue((self.root / "couch-remote" / "cache" / "installer-changed").exists())

    def test_broken_update_is_not_applied(self):
        self.assertIsNone(self.run_apply({"couch-remote/server.py": "syntax error ("}, loads=False))
        self.assertFalse((self.root / "couch-remote" / "server.py").exists())
        self.assertEqual(update.installed_sha(self.root), "")

    def test_git_checkout_never_updates(self):
        (self.root / ".git").mkdir()
        with mock.patch.object(update, "latest_sha") as latest:
            self.assertFalse(update.check(self.root))
        latest.assert_not_called()

    def test_offline_skips_quietly(self):
        with mock.patch.object(update, "latest_sha", side_effect=OSError("no network")):
            self.assertFalse(update.check(self.root))


if __name__ == "__main__":
    unittest.main()
