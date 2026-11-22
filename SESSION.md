# Session Handoff

_Session of 2026-11-22, afternoon (second session that day). Repo: `C:\Users\eli\Documents\CouchSetup` (branch `main`, all work committed; last code commit `79a4443`). Read `PICKUP.md` §6 gotchas and `CLAUDE.md` too. The morning session's handoff is in git history (`59af84f`)._

## 1. Primary Objective
A PS5-style, controller-driven TV launcher ("Couch") for a Windows PC: a Python stdlib server (`couch-remote/server.py`, port 8765, started at login by the scheduled task "Couch Launcher" with `--open`) plus a full-screen Edge page (`couch-remote/web/launcher.html`) and a phone remote (`web/remote.html`), themed after JoJo Part 7, Steel Ball Run. This session's focus: make GTA V (Epic + Rockstar) launch reliably and quickly from the TV.

## 2. Current State & Completed Work
**Verified by the user on the TV this session**
- Morning features all work: Create → screenshot, mute button, PS back to game, Volume, Storage, one battery per controller.
- New **Claude** tile (`apps.json` id `claude`): `explorer.exe shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude` (Store app, its folder changes with updates). Opens the Claude desktop app.
- **GTA V from fully closed launchers** (15:30): Couch started Rockstar, the user signed in, Couch started Epic, sent the link, the game ran.

**GTA launch path (server.py)**
- `apps.json` GTA entry has `"rockstar": true`. `launch_app`: if `exe_running("Launcher.exe")` is false, a thread runs `start_then([ROCKSTAR_EXE], ROCKSTAR_LOG, "is now signed in", lambda: open_url(target), 60)`.
- `open_url` (registry command, unchanged otherwise): for `com.epicgames.launcher` links when `EpicGamesLauncher.exe` isn't running, a thread runs `start_then([exe, "-silent"], EPIC_LOG, "OnLoginComplete", send_link, 30)`.
- `start_then(cmd, log_file, signed_in, then, limit)`: starts the launcher, polls its log (both write a fresh log per run, so only a log newer than the start counts), calls `then()` on sign-in or after `limit` seconds.
- `exe_running(name)` (tasklist) replaced the unused `steam_running`.
- **Covering, not minimizing** (`focus_what_opens` + `keep_behind`): during a game launch, Epic/Rockstar windows (new *and* already open; not Steam) stay behind Couch; Couch refocuses itself if one takes the screen, until the game window appears. A window still titled sign-in/log-in after 15 s comes forward; no game window after 90 s → newest launcher comes forward. App tiles unchanged.
- **Warm start** `warm_rockstar()`: 5 s after the server starts with `--open`, starts Rockstar's launcher if it isn't running and keeps its window behind Couch for 90 s (stops early if a launch begins). Epic already starts at login by its own setting (HKCU Run: `EpicGamesLauncher.exe -silent -launchcontext=boot`).
- Tests: `tests/test_epic.py` (start_then, Rockstar-first launch), `tests/test_cover.py` (covering, warm start). 33 tests, all pass (`python -m unittest discover -s tests` from `couch-remote`).

**Unchanged from the morning (see `59af84f` SESSION.md for detail)**: SBR look, screensaver, easter eggs, PC row (Power, Volume, Storage, Media gallery, Task manager, Controls), YouTube TV app via CDP (`edge_tv`), task manager endpoints, controller map, `audio.py` volume/mic.

## 3. Architectural & Key Decisions
- Stack stays Python stdlib + pygame/SDL + ctypes Win32/COM. No new server dependencies.
- SBR identity; PS5 layout/behaviour only. PS button wins over Steam (user must turn off Steam's guide-button action; never change Steam settings ourselves).
- **GTA needs Epic and Rockstar both up and signed in** (user's own finding). Couch starts whichever is missing and waits for its log's sign-in line before sending the link. Don't auto-close Rockstar's launcher.
- **Hide store launchers by covering them with Couch, never by minimizing** (user wanted "just the GTA loading screen").
- **Warm start at login: Rockstar only, kept behind Couch, sign-in left until a GTA press** (user accepted all four recommendations in a grilling round).
- Ponytail mode; commit when work completes. Restart the server only (not the launcher page) when only `server.py`/`apps.json` changed: the page's `/api/events` loop reconnects by itself, and reloading the launcher would cover a running game.
- Restart: kill `python …server.py`, then `Start-ScheduledTask -TaskName 'Couch Launcher'` (runs `--open`, so `open_launcher` focuses Couch: don't restart while the user is in a game).

## 4. Failed Attempts & Gotchas (Do Not Repeat)
- `/api/key`, phone, PS and controller input all hit the real TV. Never activate tiles in `/launcher?preview`; never send `enter`; ask before pressing keys on the TV. **Tests must never reach the real `open_url`/`Popen`**: a test once called a deferred step after its mocks ended and sent `com.epicgames.launcher://x` to the real Epic. Patch in `setUp` with `addCleanup`. Tests also log into the real `server.log` (e.g. "x.exe didn't report signing in"): those lines aren't real launches.
- **Don't minimize Epic/Rockstar windows during a launch** (6b4eadc/d9867c4, reverted): every GTA launch hung (sign-in stuck loading, "Game launch validation timed out").
- **Don't open store links through `explorer.exe`** (daaa5ec, reverted e8db8a6): it can't parse the Epic GTA link and opens Documents. After reverting server code, restart the server (the user hit the old code once because I didn't).
- **The server's job object isn't why cold Epic failed.** Epic started cold from a job I made and from the server (Epic tile). `CREATE_BREAKAWAY_FROM_JOB` is refused (WinError 5) even outside a job; don't use it. What fails is sending a game link while Epic starts from closed; start Epic first instead.
- **Rockstar cache:** a black sign-in window (log says "Finished loading Social Club UI") was fixed by deleting `%LOCALAPPDATA%\Rockstar Games\Social Club\Launcher\Renderer`, but that also wiped Rockstar's auto sign-in. GTA then stuck on the sign-in logo (log stops at "Client is ready to attempt a launch") until the user signed in once in the standalone launcher.
- **A leftover Rockstar launcher from a failed try blocks the next launch**: Epic holds the link until it's closed. "Game launch validation timed out" (14:52, 15:24, Nov 20) each followed another Rockstar run.
- `exe_running("Launcher.exe")` matches any program named Launcher.exe (marked `shortcut:` in code).
- The `Starting…` overlay change that waited for a server "opened" event (d9867c4) was reverted: with hiding gone it ended on Epic's window anyway and could stick 3 min when no window opened.
- RAM is not the slowness: 32 GB @ 3600, ~12.6 GB free, page file 0%. GTA is on an NVMe SSD (D:). Time goes to Rockstar sign-in (40 s when it asks for a password), Epic start (~3 s), Rockstar → game (~14 s warm), then GTA's own load.
- Playwright (plugin installed this session) can't drive Rockstar's window; it only controls browsers it starts. Capture windows with `SetProcessDPIAware` + `ImageGrab` (4K at 300%).
- The Ruflo AI-team connector is present but needs the user to authenticate; its tools only record plans, they don't run agents.
- Older gotchas (YouTube CDP, Edge lingering, Steam elevation, heredoc escapes, hooks opening file:// tabs): see `PICKUP.md` §6 and the morning SESSION.md.

## 5. Immediate Next Steps
1. **Watch the first GTA press after the next login/reboot**: Epic silent + Rockstar warm-started behind Couch → should take the fast path (~14 s to game start) with only Couch's screen, then GTA. `warm_rockstar` hasn't run for real yet (Rockstar was already open when the server restarted at 15:47). If anything hangs, revert `79a4443`, then `121f64e`/`1873803` (covering), in that order.
2. Covering during a launch (`121f64e`, `1873803`) is unit-tested; the user saw Rockstar once before `1873803` (an already-open window). Confirm it stays hidden now.
3. Ask the user to keep **Auto Sign In** ticked in Rockstar's launcher; it asked for a password again at 15:30.
4. Still unconfirmed: Steam's guide-button action turned off; Now playing shows GTA and clears on quit.
5. Optional, offered earlier: Game clips (hold Create), Downloads row, in-game quick menu. Leftovers: `profiles/web-youtube` sign-in location (issue 03), `Screenshot (2).png` test capture.

## 6. Reference Context / Code Snippets
```powershell
# restart server only (don't while a game is running: --open focuses Couch)
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ? { $_.CommandLine -like '*server.py*' } | % { Stop-Process -Id $_.ProcessId -Force }
Start-ScheduledTask -TaskName 'Couch Launcher'
```
```bash
# reload TV launcher page (only when launcher.html changed)
H='-H X-Couch:1 -H Content-Type:application/json'
curl -s -X POST $H -d '{"action":"close-launcher"}' http://127.0.0.1:8765/api/window; sleep 2
curl -s -X POST $H -d '{"action":"launcher"}' http://127.0.0.1:8765/api/window
```
- Logs: Couch `couch-remote/server.log` (`launch … asked by`, `opened … link`, `… started and signed in after N s`, `Rockstar's launcher is closed`, `Epic is closed`, `no game window after 90 s`). Epic `%LOCALAPPDATA%\EpicGamesLauncher\Saved\Logs\EpicGamesLauncher.log` (UTC timestamps, local = UTC−7; `LogUriHandler`, `OnLoginComplete`). Rockstar `Documents\Rockstar Games\Launcher\launcher.log` (`is now signed in`, `Client is ready to attempt a launch`, `[gla]`, `gamelaunch`) and `Documents\Rockstar Games\Social Club\socialclub_launcher.log` (UTF-16: `iconv -f UTF-16LE`).
- Paths: Epic `C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe`; Rockstar `C:\Program Files\Rockstar Games\Launcher\Launcher.exe`; GTA `D:\GTAVEnhanced\` (`PlayGTAV.exe` → `GTA5_Enhanced_BE.exe` → `GTA5_Enhanced.exe`).
- Config: `couch-remote/apps.json` (apps/games; `kind` url|exe|web, `tv: true`, `rockstar: true`, `args` for exe), `choices.json`, `config.json`.
- Controller map (`server.py` `buttons`): A=a(✕), B=b(○), X=x(□), Y=y(△), L1/R1, START=options, BACK=create, GUIDE=guide, 15=mic.
