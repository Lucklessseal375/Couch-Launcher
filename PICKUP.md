# PICKUP — Couch gaming PC + TV launcher

## 1. Current goal
A couch-gaming setup for a Windows 11 PC on a Samsung TV with DualSense controllers:
- **`couch-remote/`** — a full-screen TV launcher driven by the controller, plus a phone remote (web page) on the home Wi-Fi.
- Design: Steel Ball Run poster look (purple polka dots, pink "Couch" script with cyan rim, Johnny cyan `#5ec8ef`, Gyro green, gold horseshoe, Gyro's steel ball spinning on the selected tile, ゴゴゴ on focus change) + PS5 layout (square tiles, white focus ring, white ✕ Play pill, coloured ✕○△ hints). User OK'd copyrighted art for private home use; it stays on this PC.
- Stack: Python 3.13 stdlib HTTP server + **pygame** (SDL) for the controller; pages are single HTML files (no build), opened in Edge `--app` full screen.
- Working style the user asked for: **ponytail mode (full)** — smallest complete change, no extras, end replies with "skipped / risk".
- **Taste Skill** was requested but is **not installed** (third-party plugin with Node scripts + a Stop hook; user must run `/plugin marketplace add Leonxlnx/taste-skill` and `/plugin install taste-skill@taste-skill` themselves). No Taste Skill dials are in use.

## 2. Completed (all verified unless noted)
- `couch-setup.ps1` / `CHECKLIST.md` — one-time Windows tuning (already run) + manual checklist (Steam "start in Big Picture" must stay OFF).
- `couch-remote/server.py` — HTTP server on :8765: launcher/remote pages, `/api/*` (launch, keys, text, mouse, power, window), Steam library scan + cover/hero art, controller reader (pygame thread → event stream to the launcher, only when it's in front), focus handling (`focus_window` with AttachThreadInput; `focus_what_opens` focuses new windows after a launch, skipping overlays/cloaked windows), return-to-launcher watcher, boot-only 20 s "keep launcher in front" guard.
- `couch-remote/web/launcher.html` — TV UI (sounds synthesized in WebAudio; nothing selected at start so ✕ can't launch by accident).
- `couch-remote/web/remote.html` — phone remote (D-pad, touchpad, typing, apps, power), themed to match. **No PIN** (user's choice).
- `couch-remote/apps.json` — app tiles + `games` (GTA V Enhanced via Epic, art from Steam CDN app 3240220).
- `couch-remote/tests/test_gate.py` — 5 tests (network gate, VDF parser). `python -m unittest discover tests` → OK.
- Icons/assets: `make_icon.py` → `icon.ico`, `web/icon.png`; `make_steelball.py` → `web/steelball.png`; `web/poster.webp` (user's poster).
- Startup: Task Scheduler task **"Couch Launcher"** (at logon) runs `conhost.exe --headless python server.py --open`. Desktop shortcut does the same. Verified working after reboot, no click needed.
- Windows: removed Steam's RUNASADMIN compat flag; moved old Startup-folder shortcuts to `couch-remote/old-startup/`.

## 3. Current state & uncommitted changes
- Repo was just `git init`-ed in this pause; everything is in the first WIP commit. `profiles/` (Edge sign-ins, 610 MB), logs and `__pycache__` are git-ignored on purpose.
- Working: launcher, controller, phone remote, startup, game launching, no black flash on launch (launcher no longer minimizes).
- **Partially done / unverified:** last UI polish in `web/launcher.html` (inactive rows fade to 55 %, light sweep on the focused tile, tile shadows, +1vh space under the Play pill). JS syntax checks OK, **not yet looked at on screen** — the user stopped the preview screenshot.
- Not verified with a real game: the no-black-flash change and the overlay filter in `visible_windows()`.

## 4. Next steps (ordered)
1. Screenshot-check the UI polish: open `http://127.0.0.1:8765/launcher?preview` in the browser pane at 1920×1080, finish non-infinite animations via `document.getAnimations()`, review; **close the preview tab afterwards** (see gotchas).
2. Reload the TV launcher: `POST /api/window {"action":"close-launcher"}` then `{"action":"launcher"}` (header `X-Couch: 1`).
3. Work the open issues in `.scratch/couch-launcher/issues/` (01 sleep timer & 02 restore points = user commands; 03 move `PROFILES` to `%LOCALAPPDATA%`; 04 cache GTA art locally — needs download OK; 05 controller battery idea).
4. If the user installs Taste Skill, re-run UI improvements with it (it targets websites; adapt to a 10-foot TV UI).

## 5. Gotchas & decisions
- **Controller presses go only to the newest launcher page** (`emit` → `LISTENERS[-1]`). Any preview tab of `/launcher` steals the controller from the TV → always close preview tabs, then reload the TV launcher.
- Edge: use `--app` + `--start-fullscreen`, **not `--kiosk`** (kiosk is InPrivate → loses sign-ins). Keep the occlusion flags (`CalculateNativeWinOcclusion` off, no backgrounding) — without them the launcher shows gray until clicked at boot. `--autoplay-policy=no-user-gesture-required` is needed for sounds.
- Firewall allows `python.exe`, not `pythonw.exe` → start via `conhost --headless python.exe`, never pythonw.
- The `<use>` SVG bug: outer `viewBox` must be `0 0 2 2` for symbols defined as `-1 -1 2 2`.
- Fonts/QR lib load non-blocking (no waiting on the internet at boot) — keep it that way.
- Don't change Windows system/security settings (Claude can't); give the user commands instead.
- Steam is not started at boot by anything; it only opens when picked in the launcher.
- Don't reintroduce: PIN, keyboard/mouse mapping of the controller for desktop apps (user rejected), launcher minimizing on launch (caused black flash), opening with a tile pre-selected.
