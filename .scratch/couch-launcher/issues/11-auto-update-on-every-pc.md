# Couch updates itself on every PC

Status: ready-for-agent

Asked 2026-11-24 ("Save this for later can you make it auto update on computers?"), parked for later.

## What the user wants
Every PC at home gets new Couch versions from GitHub by itself: no re-downloading the ZIP and no re-running Install Couch.cmd after each fix.

## What's true now
- The repo is private on GitHub (`origin main`). Other PCs install from **Code → Download ZIP**, so they have no git checkout and no GitHub sign-in.
- `install-couch.ps1` is safe to re-run; it creates the "Couch Launcher" logon task that runs `server.py --open`.
- Per-PC files that must survive an update are all git-ignored: `couch-remote/choices.json`, `cache/`, `profiles/`, logs, `install-admin.log`.

## Open questions
- **How a PC reads a private repo without the user's password on it:** a read-only GitHub fine-grained token (the user creates it and pastes it in themselves), Git for Windows plus a one-time sign-in, or making the repo public.
- **When to update:** at sign-in, before Couch starts, is simplest. Never during a game or a stream.
- **Installer changes:** re-run the installer's admin part only when `install-couch.ps1` changed, since it asks for admin.
- **Bad update:** keep the previous copy and fall back to it if the new `server.py` fails to start.

## Sketch
At sign-in the logon task first runs a small updater. It compares the local commit with GitHub's `main` (API or `git fetch`). If they differ, it downloads `main`, swaps the files in (keeping the ignored per-PC files), then starts Couch. Couch could also show "Updated to <commit>" as a toast.
