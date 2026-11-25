import shutil
import subprocess
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

    def test_rollback_puts_the_old_files_back_and_skips_that_version(self):
        r = self.root / "couch-remote"
        (r / "server.py").write_text("old")
        (r / "cache" / "version").write_text("old111")
        self.run_apply({"couch-remote/server.py": "new", "couch-remote/added.py": "x"})
        self.assertTrue(update.rollback(self.root))
        self.assertEqual((r / "server.py").read_text(), "old")
        self.assertFalse((r / "added.py").exists())
        self.assertEqual(update.installed_sha(self.root), "old111")
        with mock.patch.object(update, "latest_sha", return_value="abc123"),                 mock.patch.object(update.urllib.request, "urlopen") as fetch:
            self.assertFalse(update.check(self.root))  # the version that crashed isn't installed again
        fetch.assert_not_called()
        self.assertFalse(update.rollback(self.root))  # nothing left to roll back

    def test_unsigned_version_is_not_downloaded(self):
        with mock.patch.object(update, "latest_sha", return_value="new222"),                 mock.patch.object(update, "signature", return_value=None),                 mock.patch.object(update, "apply") as apply:
            self.assertFalse(update.check(self.root))
        apply.assert_not_called()


KEYGEN = r"C:\Windows\System32\OpenSSH\ssh-keygen.exe"  # the one update.py uses


@unittest.skipUnless(Path(KEYGEN).exists(), "needs ssh-keygen")
class Signatures(unittest.TestCase):
    """Real signatures with throwaway keys: only this PC's update-signers key counts, and only for that commit."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = Path(d.name)
        self.root = self.d / "Couch"
        (self.root / "couch-remote").mkdir(parents=True)
        for name in ("ours", "theirs"):
            subprocess.run([KEYGEN, "-q", "-t", "ed25519", "-N", "", "-f", str(self.d / name), "-C", name], check=True, stdin=subprocess.DEVNULL, capture_output=True)
        pub = (self.d / "ours.pub").read_text().split()[:2]
        (self.root / "couch-remote" / "update-signers").write_text("couch-update " + " ".join(pub) + chr(10))

    def sign(self, key, sha):
        msg = self.d / "msg"
        msg.write_text(sha)
        subprocess.run([KEYGEN, "-Y", "sign", "-n", "couch-update", "-f", str(self.d / key), str(msg)],
                       check=True, capture_output=True, stdin=subprocess.DEVNULL)
        return (self.d / "msg.sig").read_bytes()

    def test_our_signature_for_this_commit_passes(self):
        self.assertTrue(update.verified(self.root, "abc123", self.sign("ours", "abc123")))

    def test_another_key_or_another_commit_fails(self):
        self.assertFalse(update.verified(self.root, "abc123", self.sign("theirs", "abc123")))
        self.assertFalse(update.verified(self.root, "abc123", self.sign("ours", "evil999")))

    def test_rfc8032_vectors(self):
        import ed25519
        pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e3970"
                            "1cf9b46bd25bf5f0595bbe24655141438e7a100b")
        self.assertTrue(ed25519.verify(pk, b"", sig))
        self.assertFalse(ed25519.verify(pk, b"x", sig))

    def test_garbage_signature_fails_quietly(self):
        self.assertFalse(update.verified(self.root, "abc123", b"-----BEGIN SSH SIGNATURE-----\nnot base64!\n"))

    def test_no_signers_file_means_no_update(self):
        sig = self.sign("ours", "abc123")
        (self.root / "couch-remote" / "update-signers").unlink()
        self.assertFalse(update.verified(self.root, "abc123", sig))


class Supervise(unittest.TestCase):
    def run_codes(self, codes, rolled_back=True):
        import server
        codes = list(codes)
        with mock.patch.object(server.update, "rollback", return_value=rolled_back) as rb,                 mock.patch.object(server.time, "sleep"):
            rc = server.supervise(lambda: codes.pop(0))
        return rc, rb, codes

    def test_restarts_after_an_update(self):
        rc, rb, left = self.run_codes([75, 0])
        self.assertEqual((rc, left), (0, []))
        rb.assert_not_called()

    def test_updated_version_crashing_rolls_back_and_runs_again(self):
        rc, rb, left = self.run_codes([75, 1, 0])
        rb.assert_called_once()
        self.assertEqual((rc, left), (0, []))

    def test_crash_is_restarted(self):
        rc, rb, left = self.run_codes([1, 0])
        self.assertEqual((rc, left), (0, []))
        rb.assert_not_called()

    def test_crashing_again_and_again_gives_up(self):
        rc, _, left = self.run_codes([1, 1, 1, 0])
        self.assertEqual((rc, left), (1, [0]))


if __name__ == "__main__":
    unittest.main()
