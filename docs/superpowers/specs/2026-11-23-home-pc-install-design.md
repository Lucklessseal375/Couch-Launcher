# Couch on every PC at home (private GitHub repo + installer)

_Design, 2026-11-23. Approved by the user ("Yes")._

## Intent
The user wants Couch in a **private** GitHub repo so they can put it on their other computers at home. Art and git history ship as they are (private, their own use). What's missing is installing Couch on a fresh PC and having it fit that PC.

## Goals
- One script on a new PC: Python + pygame, the "Couch Launcher" logon task, the phone-remote firewall rule, a desktop shortcut.
- Tiles fit each PC: app tiles whose program isn't installed are hidden; GTA only where its folder exists; Steam games already auto-detected.
- Fix: no stray screenshot when a streamed (virtual) controller connects.
- README section "Set up Couch on another PC"; the old `couch-setup.ps1` marked as this-PC tuning only.
- Push to a private GitHub repo the user creates; they sign in to GitHub themselves on first push.

## Non-goals / anti-goals
- No public release, no art or history scrubbing.
- Never committing secrets: `cache/` (Sunshine login), `profiles/` (browser sign-ins), logs, `choices.json` stay git-ignored.
- The installer never changes unrelated Windows settings (the old tuning script stays separate and optional).

## Approaches
- **Chosen:** a PowerShell installer + per-PC auto-hiding in the server + git push to a user-created private repo.
- Rejected: a packaged .exe/zip release (more moving parts for a few home PCs); a public generic release (user wants private).

## Builder's calls
- Hide rule: `kind: exe` tile hidden if its `target` file is missing; `kind: url` tile hidden if its scheme has no registered handler (`HKCR\<scheme>`); optional `"needs": "<path>"` on any entry hides it when that path is missing (GTA: `D:\GTAVEnhanced`). `kind: web` always shown.
- Stray screenshot: ignore the Create/Back button for 3 s after a controller connects.
- Installer runs as the user; only the firewall step needs admin (it asks via an elevated `netsh`/`New-NetFirewallRule` call and continues if declined).
