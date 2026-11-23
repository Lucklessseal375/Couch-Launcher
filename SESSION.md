# Session Handoff

_Sessions of 2026-11-22/23. Repo: `C:\Users\eli\Documents\CouchSetup`, branch `main`, everything committed and pushed to the private GitHub repo **https://github.com/Lucklessseal375/Couch-Launcher** (remote `origin`). Read `PICKUP.md` §6 and `CLAUDE.md` too. Older handoffs are in git history (`59af84f` morning 2026-11-22, `50666d9` afternoon)._

## 1. Primary Objective
**Couch**: a PS5-style, controller-driven TV launcher for a Windows PC, themed after JoJo Part 7, Steel Ball Run. Python stdlib server (`couch-remote/server.py`, port 8765, + pygame for the controller, ctypes Win32/COM) started at sign-in by the scheduled task **"Couch Launcher"**; a full-screen Edge page (`couch-remote/web/launcher.html`); a phone remote (`web/remote.html`). Now also: stream to an Apple TV in another room (Sunshine + Moonlight) and install on the user's other home PCs from the private GitHub repo.

## 2. Current State & Completed Work
**Install on other PCs** (user: "private, for my other computers at home"; art + history included on purpose)
- `install-couch.ps1`: winget Python 3.13 + `pip install --user pygame`, task "Couch Launcher" (`conhost --headless python.exe server.py --open`, at logon), firewall rule "Couch (phone remote)" via an elevated child (continues if declined), desktop shortcut. **Syntax-checked only; never run on another PC.**
- Root `README.md`: 5-step setup. `couch-setup.ps1` = old main-PC-only tuning.
- One `apps.json` for all PCs: `installed(entry)` hides exe tiles whose program is missing, url tiles with no registered handler, and any entry whose `"needs"` path is missing (GTA: `D:\GTAVEnhanced`). Tests `tests/test_installed.py`.

**Streaming to the Apple TV (working, verified by the user)**
- Sunshine 2026.914.233613 + ViGEmBus 1.22.0 installed via winget (with the user's OK). Sunshine service auto-starts ~45 s after login. The Apple TV controller arrives as a virtual "Xbox 360 Controller"; Couch reads it unchanged.
- Sunshine app "Couch": prep commands `couch-remote\stream.cmd on "Apple TV"` / `off` → local-only `POST /api/stream` → `STREAM`, header pill "Streaming to …", `audio_replaced` stands down. `watch_sunshine()` tails `C:\Program Files\Sunshine\config\sunshine.log` (CLIENT CONNECTED/DISCONNECTED).
- PC row **Streaming** tile (all by controller): Connect to Sunshine (one-time login typed on the search keyboard's prompt mode: L1/R1 lowercase/capitals/symbols, Done, dots for secrets; checked against Sunshine, stored DPAPI-encrypted in `couch-remote/cache/sunshine.cred`, forgotten on 401), Pair a device (`GET/POST /api/pin`, PIN by controller; **verified**), Paired devices (unpair), Restart Sunshine, **End stream** (`POST /api/apps/close`; **verified**), Open Sunshine settings, Restart the PC when Sunshine was quit. Sunshine actions: `SUNSHINE_ACTIONS` in server.py. Setup guide: `docs/streaming-setup.md`.

**GTA V (works)**: Couch opens Rockstar's launcher (`warm_rockstar` at login, `start_then` before a launch) and starts Epic first if closed, then sends the Epic link; store launchers are kept behind Couch (covered, never minimized); Starting screen survives brief focus loss; "Starts in about N s" from recorded launch times (`choices.json` `took`). Windows now uses all 32 threads (user unticked msconfig "Number of processors"). Parked notes: `.scratch/couch-launcher/issues/10-gta-launch-speed-and-vanishing.md`.

**UI (PS5/Apple as inspiration, SBR kept)**: live PC tiles (battery ring per controller, fullest-drive ring, newest screenshot), focus tinted by cover/brand colour with a soft PS5-style glow that follows focus, tvOS lift + one gold glint, tvOS edge nudge, time-of-day greeting, weather in header + screensaver (Open-Meteo, `config.json` `weather.city` = El Paso, °F), notifications bell + list (localStorage `couchNotes`), Now playing adds Volume + Microphone, Claude tile, no outlines around words or tiles (titles use soft shadow + glow; title descenders no longer clipped), toasts under the header, Reduce Transparency / Increase Contrast / reduced-motion respected.

**Server fixes**: battery + rumble go through SDL lookups (pygame Controller objects crashed the server once); Create ignored 3 s after a controller connects (stray screenshots on Moonlight connect); tests never touch real `choices.json`, `server.log`, launchers or Sunshine.

Tests: `python -m unittest discover -s tests` from `couch-remote` → 61 pass.

## 3. Architectural & Key Decisions
- Stack stays Python stdlib + pygame/SDL + ctypes. No new server dependencies.
- SBR identity; PS5/Apple used as inspiration only. Boldness in one place (focus glow/tint).
- Couch can't change Windows services/settings or Sunshine's files (no admin); it reads them and asks the user.
- Hide store launchers by **covering** them with Couch, never minimizing.
- GTA needs Epic and Rockstar up and signed in; Couch starts whichever is missing.
- Ponytail mode is on (user chose **ultra**: push back on scope, smallest complete change). Commit when work completes; push to `origin main` (GCM sign-in cached).
- Restart the server only when no game runs (`--open` focuses Couch); reload the TV page only when launcher.html changed; the page's `/api/events` loop reconnects by itself.

## 4. Failed Attempts & Gotchas (Do Not Repeat)
- `/api/key`, phone and controller input hit the real TV; never activate tiles in `/launcher?preview`, never send `enter`. Tests: patch in `setUp` with `addCleanup`, `server.log.disabled = True`.
- Don't minimize Epic/Rockstar windows (GTA hung). Don't open store links via `explorer.exe` (opens Documents). `CREATE_BREAKAWAY_FROM_JOB` is refused; the job object wasn't the cause.
- Deleting Rockstar's `Renderer` cache fixes a black sign-in window but wipes auto sign-in.
- Moonlight: sticks dead = Siri Remote, not the PS5 controller (pair it on the Apple TV, multi-controller "Auto", living-room DualSense off). Quitting Sunshine from its tray stops the service until reboot.
- launcher.html startup order: top-level code (e.g. `tick()`) runs before later `const`s exist (`esc` ~line 960); using one there kills the page silently. Probe late names headless after such changes.
- Backslashes: Python heredocs through Bash mangle `\a`, `\P`… (garbled SESSION.md once, broke `apps.json` once). Use the Edit tool or a script file for strings with backslashes, and `json.load` after editing JSON.
- Hooks open `launcher.html` as a `file://` tab in the browser pane; close it.
- Screenshots: `python couch-remote/dev/shoot.py <steps.json> <out_dir>` (headless 1920×1080). It finishes animations before shots; stub only POSTs (`o.method === 'POST'`), never all fetches (breaks `info`).

## 5. Immediate Next Steps
1. Run `install-couch.ps1` on the next home PC and fix whatever it hits (Python PATH, firewall prompt, task user).
2. Not yet tried for real: Restart Sunshine and removing a paired device from the Streaming menu.
3. Still unconfirmed: Steam's guide-button action off; Now playing tracks and clears GTA.
4. Cosmetic: the virtual (Moonlight) pad shows "Charging" in the header; a device named "off" in `stream.cmd` would hide the pill.
5. Ideas offered earlier, not built: Game clips (hold Create), Downloads row.

## 6. Reference Context / Code Snippets
```powershell
# restart the server (no game running)
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ? { $_.CommandLine -like '*server.py*' } | % { Stop-Process -Id $_.ProcessId -Force }
Start-ScheduledTask -TaskName 'Couch Launcher'
```
```bash
# reload the TV page (needs header X-Couch: 1)
H='-H X-Couch:1 -H Content-Type:application/json'
curl -s -X POST $H -d '{"action":"close-launcher"}' http://127.0.0.1:8765/api/window; sleep 2
curl -s -X POST $H -d '{"action":"launcher"}' http://127.0.0.1:8765/api/window
```
- Logs: Couch `couch-remote/server.log`; Sunshine `C:\Program Files\Sunshine\config\sunshine.log`; Epic `%LOCALAPPDATA%\EpicGamesLauncher\Saved\Logs\EpicGamesLauncher.log` (UTC, local = UTC−7); Rockstar `Documents\Rockstar Games\Launcher\launcher.log`.
- Sunshine API (Basic auth, https://localhost:47990): `/api/pin` (GET pending, POST `{pairing_id, pin, name}`), `/api/clients/list`, `/api/clients/unpair {uuid}`, `/api/restart`, `/api/apps/close`. Names read from `C:\Program Files\Sunshine\assets\web\assets\*.js`.
- Config: `couch-remote/apps.json` (`kind` url|exe|web, `tv`, `rockstar`, `needs`, `args`), `config.json` (`port`, `edge`, `weather`), `choices.json` (git-ignored).
- Controller map: A=✕, B=○, X=□, Y=△, L1/R1, START=options, BACK=create, GUIDE=PS, 15=mic.
