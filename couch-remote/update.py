"""Keeps a Couch install up to date with GitHub's main branch (the repo is public: no sign-in needed).

server.py calls check() at startup and every few hours while nothing is playing. A git checkout (the PC Couch is
developed on) is never touched. An update is applied only after the new server.py imports cleanly, so a broken
push can't stop Couch from starting. Per-PC files are never in GitHub's ZIP, so they're kept; config.json is in it
but holds this PC's weather city, so an existing one is kept too.
"""
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = "Lucklessseal375/Couch-Launcher"
KEEP = {"couch-remote/config.json"}  # tracked, but this PC's own once it exists
log = logging.getLogger("couch")


def installed_sha(root):
    try:
        return (root / "couch-remote" / "cache" / "version").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def latest_sha():
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/commits/main",
                                 headers={"Accept": "application/vnd.github.sha", "User-Agent": "couch-updater"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode().strip()


def imports_cleanly(new_remote):
    """The new server.py loads (syntax, imports, module-level code) in its own folder, without starting anything."""
    r = subprocess.run([sys.executable, "-c", "import server"], cwd=str(new_remote), capture_output=True,
                       timeout=120, creationflags=0x08000000)
    if r.returncode:
        log.warning("update: new server.py doesn't load, keeping this version: %s", r.stderr.decode(errors="ignore")[-400:])
    return r.returncode == 0


def apply(root, zip_path, sha):
    """Copies the ZIP's files over root. Returns whether install-couch.ps1 changed (its admin steps need a re-run)."""
    with tempfile.TemporaryDirectory() as d:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(d)
        top = next(Path(d).iterdir())  # GitHub's ZIP holds one folder, <repo>-<sha>
        if not imports_cleanly(top / "couch-remote"):
            return None
        installer = root / "install-couch.ps1"
        text = lambda p: p.read_bytes().replace(b"\r\n", b"\n") if p.exists() else b""  # a git copy has CRLF, the ZIP LF
        old = text(installer)
        for f in top.rglob("*"):
            rel = f.relative_to(top).as_posix()
            dst = root / rel
            if f.is_dir() or (rel in KEEP and dst.exists()):
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
        changed = text(installer) != old
    cache = root / "couch-remote" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "version").write_text(sha, encoding="utf-8")
    if changed:
        (cache / "installer-changed").write_text(sha, encoding="utf-8")
    return changed


def check(root):
    """Updates root to GitHub's main if it's behind. Returns True when files changed (Couch should restart)."""
    if (root / ".git").exists():
        return False
    try:
        sha = latest_sha()
        if not sha or sha == installed_sha(root):
            return False
        with tempfile.TemporaryDirectory() as d:
            zip_path = Path(d) / "couch.zip"
            req = urllib.request.Request(f"https://github.com/{REPO}/archive/{sha}.zip", headers={"User-Agent": "couch-updater"})
            with urllib.request.urlopen(req, timeout=120) as r, open(zip_path, "wb") as out:
                shutil.copyfileobj(r, out)
            changed = apply(root, zip_path, sha)
        if changed is None:
            return False
        log.info("updated to %s%s", sha[:7], " (run Install Couch.cmd once: the installer changed)" if changed else "")
        return True
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.TimeoutExpired) as e:  # offline at sign-in, GitHub down
        log.info("update check skipped: %s", e)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps({"updated": check(Path(__file__).resolve().parent.parent)}))
