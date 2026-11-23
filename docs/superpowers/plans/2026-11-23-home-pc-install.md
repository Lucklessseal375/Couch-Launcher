# Couch on Every Home PC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Couch installs on another home PC with one script and shows only what that PC has; the repo goes to a private GitHub repo.

**Architecture:** `installed(entry)` filters `load_apps()`/`load_games()` in `server.py`; a guard in the controller loop ignores Create for 3 s after a connect; `install-couch.ps1` sets up a PC; README documents it; git remote + push at the end.

**Tech Stack:** Python stdlib server, unittest, PowerShell 5.1, winget, git.

**Spec:** `docs/superpowers/specs/2026-11-23-home-pc-install-design.md`

## Global Constraints
- No new server dependencies; `cache/`, `profiles/`, logs, `choices.json` stay git-ignored.
- Installer changes nothing beyond: Python/pygame install, the "Couch Launcher" logon task, one firewall rule, one desktop shortcut.
- Push only after the user gives the private repo URL; they sign in to GitHub themselves.

## Review Focus
- `apps.json` entry with an unknown `kind` or no `target`: stays visible (don't hide what we can't judge).
- `needs` path with `%VARS%`: expanded before checking.
- Installer run twice: task and rule replaced, not duplicated.
- Installer on a PC where winget Python is already present: skips install.
- A controller connecting while someone presses Create in a game 3 s later: screenshot still taken.

---

### Task 1: Per-PC tiles (`installed`)
**Files:** Modify `couch-remote/server.py` (`load_apps`, `load_games`); Test `couch-remote/tests/test_installed.py`
**Produces:** `installed(entry: dict) -> bool`.
- [ ] Tests: exe with missing target → False; exe with existing target (`sys.executable`) → True; url with scheme `nosuchscheme://` → False; url `https://` → True; web → True; `needs` missing path → False even for web; unknown kind → True; `needs` with `%SystemRoot%` → True.
- [ ] Run → fail; implement (`HKCR\<scheme>` via `winreg.OpenKey`; `os.path.expandvars`); `load_apps`/`load_games` return only installed entries. Run full suite → pass. Commit.

### Task 2: No stray screenshot on connect
**Files:** Modify `couch-remote/server.py` controller loop (CONTROLLERDEVICEADDED and `act("create")`).
- [ ] Track `connected_at = time.time()` on add; `create` within 3 s of it is ignored (logged). Verify by reading the loop; full suite passes. Commit.

### Task 3: Installer + README
**Files:** Create `install-couch.ps1` (repo root); Modify `couch-remote/README.md`, `couch-setup.ps1` header comment.
- [ ] Script: winget Python 3.13 if `python` missing; `python -m pip install --user pygame`; `Register-ScheduledTask "Couch Launcher"` (logon, current user, `conhost.exe --headless <python.exe> <repo>\couch-remote\server.py --open`, `-Force`); firewall rule "Couch (python)" for that python.exe on Private profile via an elevated `Start-Process powershell -Verb RunAs` (continue if declined); desktop shortcut running `Start-ScheduledTask 'Couch Launcher'`. Parse-check: `powershell -NoProfile -Command "[ScriptBlock]::Create((Get-Content install-couch.ps1 -Raw)) | Out-Null"`.
- [ ] README "Set up Couch on another PC" (5 steps); mark `couch-setup.ps1` as this-PC tuning. Commit.

### Task 4: Go live + push
- [ ] Restart server (no game running), reload TV page, check tiles still show here.
- [ ] Ask user for the empty private repo URL; `git remote add origin <url>`; `git push -u origin main` (user signs in). Verify `git ls-remote origin`.
