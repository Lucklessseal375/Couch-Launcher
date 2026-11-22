# Session Handoff

_Session of 2026-11-22. Repo: `C:\Users\eli\Documents\CouchSetup` (branch `main`, all work committed; last commit `17b0d29`). Read `PICKUP.md` §6 gotchas and `CLAUDE.md` too._

## 1. Primary Objective
A PS5-style, controller-driven TV launcher ("Couch") for a Windows PC: a Python stdlib server (`couch-remote/server.py`, port 8765) plus a full-screen Edge page (`couch-remote/web/launcher.html`) and a phone remote (`web/remote.html`), themed after JoJo Part 7, Steel Ball Run.

## 2. Current State & Completed Work
**Look / design** (`web/launcher.html`)
- Redesign "Steel Ball Run at night": tokens `--obsidian #150f0b`, `--ink #f3e6cf`, `--dim #bfae96`, `--gold #f2b844` (focus ring), `--bib #13809a` (Play button, 4.6:1 with white), `--serif "Aoboshi One"` (titles, row and card headings, hard Johnny-cyan offset shadow on `#d-title`), Archivo for UI.
- Home backdrop `.sky` (blurred `::before` plus sharp masked `::after`, `--art/--f0/--f1`), with a bottom fade mask (`--low`) that hides the logo printed on `poster.webp`. `SKIES` = poster, sbr-riders, sbr-race; `IDLE_ART` = SKIES + `img/sbr-desert.jpg` (cropped official key visual).
- Screensaver (10 min idle): dimmed art, new picture every minute, drifting, rolling steel ball (25% chance).
- Easter eggs: search names (`EGGS`: Johnny, Tusk, Gyro, Valentine...), L1 R1 L1 R1 Golden Spin (`comboPress`), Sept 25 note, marquee ribbon on `.card::before`.
- Long titles step down (`#d-title.long`), ™ stripped; inactive rows at opacity .62.

**Launcher features**
- PC row and Menu (`pcItems()`): Phone remote, Audio output, Sound, Turn off controller, **Power** (`powerMenu`: Sleep/Restart/Shut down), **Volume** (`volumeMenu`), **Storage** (`storageMenu`), **Media gallery** (`mediaGallery`), **Task manager** (`taskManager`/`taskActions`), **Controls** (`showControls`), Desktop.
- `choose()` gained `gauges` (`#dlg-gauges`, shared `gauge()` HTML); `openModal(..., sound="")` is silent; `modal.prompts` and `modal.move` overrides.
- Now playing polls `/api/running` every 3 s.
- Launch music: the intro (or `Sound.fanfare`) plays on the TV during "Starting…" and fades in `hideStarting()`.
- Held keys don't repeat Enter/Back (`e.repeat && !k`).
- One battery icon per controller (`showPad("full,low")`). Toasts for `shot` and `mic:*`.

**Server** (`couch-remote/server.py`, `audio.py`)
- YouTube tile (`apps.json` id `youtube`, `tv: true`) → `edge_tv()`: Edge with `--remote-debugging-port=0` and a black data: start page. A CDP session (`Cdp` class) sets `Emulation.setUserAgentOverride` with `TV_HINTS` (Samsung Tizen) and stays attached. `TV_EXIT_JS` plus `Runtime.addBinding("couchExit")` closes the window on ○ at YouTube's last screen. `end_profile_edge()` kills Edge lingering on the profile (before launch, and after close only if the window is gone). On close, `open_launcher()`. `TV_PIDS`/`TV_KEYS` map the pad to remote keys only while that window is in front.
- Task manager: `task_list()` (CPU via `GetSystemTimes`, memory, per-window process-tree working set, `IsHungAppWindow`), `task_action()` (switch/close/force; only listed windows). `close_window()` = WM_SYSCOMMAND SC_CLOSE; Steam windows → `steam://exit`. Force on Steam → `taskkill /IM steam.exe /T /F`.
- `open_url()`: runs the registered `HKCR\<scheme>\shell\open\command`, and falls back to `os.startfile` on OSError (Steam needs elevation, WinError 740).
- Now playing: `focus_what_opens` watches up to 180 s; `RUNNING{name,windows,game_seen,is_game}`; `pick_running(cands, game_seen)` ignores leftover store-launcher windows after the game window was seen (games only, not app tiles).
- Controller (`act()`): `create` → `take_screenshot()` (SendInput Win+PrtScn, rumble "shot", emit "shot"). `mic` (SDL button 15) → `toggle_mic()`. PS: if launcher in front and a game is running → `focus_window(running)`, else `open_launcher()` (no longer skips when Steam runs).
- Endpoints: `GET /api/tasks`, `/api/running`, `/api/media`, `/api/volume`, `/api/storage`; `POST /api/tasks {id,action}`, `/api/volume {level|muted|mic}`; `/media/<file>` serves the Screenshots folder only. `/api/window` actions are logged.
- `audio.py`: `volume_state()`, `set_volume(level, muted)`, `set_mic_muted()` (IAudioEndpointVolume via raw COM vtables).
- `screenshots_dir()` (FOLDERID_Screenshots = `C:\Users\eli\Pictures\Screenshots`), `media_list()`, `fixed_drives()`.
- Tests: `couch-remote/tests/test_gate.py`, `tests/test_tasks.py` (20 tests, all pass: `python -m unittest discover -s tests` from `couch-remote`).

## 3. Architectural & Key Decisions
- Stack stays Python stdlib plus pygame/SDL (controller) and ctypes Win32/COM. No new dependencies in the server. Pillow was installed for the user only as a dev tool, for cropping.
- Identity is Steel Ball Run, not PlayStation.com colours. PS5 features borrow layout and behaviour only (user chose: "PS5 layout, SBR look").
- **PS button wins over Steam** (user chose). The user must turn off Steam's guide-button action in Steam → Settings → Controller. Never change Steam settings ourselves.
- YouTube = the TV app (youtube.com/tv), not YouTube Music. The user dropped Music: it has no TV version, and a desktop site plus homemade arrow-key navigation looked wrong.
- Controller-to-key mapping only for our TV window (`TV_PIDS`). The user rejected general keyboard/mouse mapping for desktop apps.
- Close = what the X button does (SC_CLOSE); apps may ask to save. Force close only for hung or still-open apps, behind a confirmation.
- Copyrighted music isn't downloaded; the user supplies `web/audio/<song>` and `web/audio/sbr/bgm-loop.mp3`. Official SBR key art was downloaded with the user's OK.
- Ponytail mode: smallest complete change; commit when work completes (user asked "commit keep working").
- Restart the server with: kill the `python …server.py` process, then `Start-ScheduledTask -TaskName 'Couch Launcher'`. Reload the TV page: POST `/api/window {"action":"close-launcher"}` then `{"action":"launcher"}` (needs header `X-Couch: 1`).

## 4. Failed Attempts & Gotchas (Do Not Repeat)
- `/api/key`, phone, PS and controller input all type into the real TV. Never activate tiles in `/launcher?preview`; never send `enter`. The user stopped one key-sending test: ask before pressing keys on the TV.
- The `--user-agent` flag alone no longer works for youtube.com/tv (client hints leak "Windows / Edge"). `--disable-features=UserAgentClientHint` does nothing. A DNR extension can't strip `Sec-CH-UA`. Only the CDP `userAgentMetadata` override works.
- YouTube mutes `console.log`; use `Runtime.addBinding`. `Page.addScriptToEvaluateOnNewDocument` needs `Page.enable` first. `Cdp.send()` swallows events, so read them in a dedicated loop.
- Edge lingers windowless after `/json/close`; a later launch on that profile shows a blank new-tab page ("weird VM"). Hence `end_profile_edge`.
- Windows scales the TV display (4K at 300%; screen captures need `SetProcessDPIAware`). Don't add `--force-device-scale-factor`.
- Steam ignores WM_CLOSE. Killing steamwebhelper respawns it. steam.exe can't be started directly (needs elevation).
- `os.startfile` from a server thread once silently failed for Epic links (hence `open_url`, which tries the direct command first).
- Headless Edge `--dump-dom`/`--screenshot` are unreliable; use `dev/shoot.py` or CDP.
- Python heredocs: `\r\n` and `\s` escapes get mangled. Write scripts with the Write tool or use raw strings. `tests/test_gate.py` has CRLF line endings.
- Hooks open launcher/remote HTML as file:// tabs in the browser pane; close them.
- The launcher vanished once at 12:05:43 (clean close, cause unknown). Now logged via `window:` lines.
- The stray 63× sleep was a held Enter key (fixed).
- **Don't minimize Epic/Rockstar windows during a launch** (tried 2026-11-22, commits 6b4eadc, d9867c4; reverted). While it was in, every GTA launch hung: Rockstar sign-in stuck loading, then "Game launch validation timed out" (`Documents\Rockstar Games\Launcher\launcher.log`). Rockstar's UI is embedded Chromium. If hiding launchers is wanted again, cover them instead (e.g. keep Couch on top), never minimize.
- Rockstar sign-in window can draw black while its log says "Finished loading Social Club UI" (`Documents\Rockstar Games\Social Club\socialclub_launcher.log`). Deleting `%LOCALAPPDATA%\Rockstar Games\Social Club\Launcher\Renderer` fixed the black window, but that cache also holds Rockstar's auto sign-in: afterwards GTA launches from Epic stuck on the sign-in logo (log stops at "Client is ready to attempt a launch") until the user signed in once in the standalone Rockstar Games Launcher with Auto Sign In ticked. Then GTA worked (2026-11-22 ~15:25).
- **Don't open store links through `explorer.exe`** (commit daaa5ec, reverted in e8db8a6): explorer can't parse the Epic GTA link and opens Documents instead. After reverting server code, restart the server: the user hit the old code once because I didn't.
- **The server's job object is not why cold Epic fails.** The scheduled task does run the server inside a job, but Epic started cold from a job I created, and from the server itself (Epic tile, 15:16). `CREATE_BREAKAWAY_FROM_JOB` is refused (WinError 5) even outside a job, so don't use it.

## 5. Immediate Next Steps
1. Done 2026-11-22: the user tested Create screenshot, mute, PS back to game, Volume, Storage and two-controller batteries on the TV; all work.
2. PS returned to the game in the user's test, so Steam didn't take over then. The user hasn't confirmed that Steam's guide-button action is off.
3. GTA V launches from Couch when Epic is already running (verified by the user 2026-11-22). **Still broken: GTA with Epic fully closed.** Couch's log says "opened … link", but no Epic process appears and Epic writes no log (13:27, 13:28, 15:10). Epic started cold without a link works. Fix in 8b3a63c (`start_epic_then`): when Epic isn't running, start it with `-silent`, wait for "OnLoginComplete" in its log, then send the link. Unit-tested only; not yet tried on the TV with Epic closed (at 15:25 the user closed GTA, not Epic).
   A leftover Rockstar launcher (`PlayGTAV.exe` + `Launcher.exe` from an earlier try) blocks the next GTA launch: Epic holds the link until it's closed, then GTA starts (15:25 press → game at 15:26 after closing the leftover via Couch's Task manager). "Game launch validation timed out" (14:52, 15:24, Nov 20) each came right after another Rockstar launcher run. The user's own finding (2026-11-22): GTA runs from Couch when both Epic and the Rockstar launcher are already open. So don't auto-close Rockstar's launcher; if anything, so Couch now makes sure both are open (apps.json `rockstar: true` on GTA): if `Launcher.exe` isn't running it starts Rockstar's launcher, waits up to 60 s for "is now signed in" in its log, then sends the Epic link (which itself starts Epic first if needed). Shared helper `start_then`; tests in `tests/test_epic.py`. Verified on the TV 2026-11-22 15:30: with Epic and Rockstar both closed, Couch started Rockstar, the user signed in (40 s), Couch started Epic (3 s), sent the link, and GTA ran at 15:31:45. Rockstar asked for a sign-in again that time: Auto Sign In apparently isn't being kept, which Couch can't fix.
   Store launchers now stay *behind* Couch during a game launch (`keep_behind` in `focus_what_opens`; covered, never minimized). A sign-in window still asking after 15 s comes forward; no game window after 90 s → the newest launcher comes forward. Tests: `tests/test_cover.py`. Not yet tried on the TV; if GTA hangs again, revert this commit first. Now playing tracking/clearing for GTA also not checked.
4. Optional, offered: Game clips (hold Create → Game Bar "record that"; the user must enable background recording), Downloads row, in-game quick menu. All deferred as riskier.
5. Leftovers: `couch-remote/profiles/web-youtube` holds the YouTube sign-in (issue 03); `Screenshot (2).png` was a test capture; the "UI UX Pro Max" plugin wasn't in the catalog (closest: "UI Design Review", "Design").

## 6. Reference Context / Code Snippets
```powershell
# restart server (scheduled task, independent of the agent shell)
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ? { $_.CommandLine -like '*server.py*' } | % { Stop-Process -Id $_.ProcessId -Force }
Start-ScheduledTask -TaskName 'Couch Launcher'
```
```bash
# reload TV launcher; screenshots via headless page
H='-H X-Couch:1 -H Content-Type:application/json'
curl -s -X POST $H -d '{"action":"close-launcher"}' http://127.0.0.1:8765/api/window; sleep 2
curl -s -X POST $H -d '{"action":"launcher"}' http://127.0.0.1:8765/api/window
python couch-remote/dev/shoot.py steps.json <out_dir>   # steps: {"url": ".../launcher?preview", "steps":[{"js":"...","wait":ms,"shot":"x.png"}]}
```
- Log: `couch-remote/server.log` (`launch … asked by`, `opened … link`, `TV mode:`, `task manager:`, `window:`).
- Controller map (`server.py` `buttons`): A=a(✕), B=b(○), X=x(□), Y=y(△), L1/R1, START=options, BACK=create, GUIDE=guide, 15=mic.
- Config: `couch-remote/apps.json` (apps/games; `kind` url|exe|web, `tv: true`), `choices.json` (hidden/pinned/played), `config.json` (`edge`, `port`).
