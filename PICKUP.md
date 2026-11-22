# PICKUP — Couch gaming PC + TV launcher

## 1. Current goal
A couch-gaming setup for a Windows 11 PC on a Samsung TV with DualSense controllers:
- **`couch-remote/`** — a full-screen TV launcher driven by the controller, plus a phone remote (web page) on the home Wi-Fi.
- Design: Steel Ball Run poster look (purple polka dots, pink "Couch" script with cyan rim, Johnny cyan `#5ec8ef`, Gyro green, gold horseshoe, Gyro's steel ball spinning on the selected tile, ゴゴゴ on focus change) + PS5 layout (square tiles, white focus ring, white ✕ Play pill, coloured ✕○△ hints). User OK'd copyrighted art for private home use; it stays on this PC.
- Stack: Python 3.13 stdlib HTTP server + **pygame** (SDL) for the controller; pages are single HTML files (no build), opened in Edge `--app` full screen.
- Working style the user asked for: **ponytail mode (full)** — smallest complete change, no extras, end replies with "skipped / risk".
- UI pass to remove "AI slop" (§4) is done and committed (2fcf0d6).
- apple-design skill (project, `.claude/skills/apple-design`) review + features done 2026-11-21, committed in 784604d: see `.scratch/couch-launcher/ui-review.md`. Added reduced-motion, bigger TV text, Back hint only in dialogs, Sleep without dialog, L1/R1 paging, controller battery (issue 05), 10-min idle dim. New idea issues 06–09; 06 (Resume / Close game) done too, tested on the TV by the user. Server was restarted headless (no `--open`) to load it.
- YouTube and Netflix tiles removed (user wants games only, 2026-11-21); their Edge profiles went to the Recycle Bin. The `web` app kind still works if a site is ever added back.
- □ on a game: Pin to front / Hide (issue 08), saved in `couch-remote/choices.json`; "Hidden games" tile in the PC row brings them back. Committed in b4797cb.
- 2026-11-21 "high-end finished product" round (user: work without asking, send screenshots): **Audio output** picker (PC row + phone Remote tab) via `audio.py` (Windows audio API, no installs); the server holds the chosen output (SAMSUNG) as default for all three roles and switches back within 3 s (`keep_audio`, backs off if something fights it, ignores Steam Remote Play). Real store icons (`/appicon/<id>`, extracted from the exes, cached in `cache/`), GTA art local in `web/img/` (issue 04 done), hours played from Steam's localconfig.vdf, Starting splash (game art + spinning ball until the window takes focus), fully dark idle screen, store descriptions (`meta` in apps.json), bottom fade on the rows, phone shows "Connected" and real icons.

### Skill status (2026-11-21)
- **frontend-design** (Anthropic): enabled on the user's claude.ai account, but it never loaded in the old session (skills load at session start; `/reload-plugins` didn't pick it up). If it isn't in the skill list, read it directly: `C:\Users\eli\.claude\plugins\marketplaces\claude-plugins-official\plugins\frontend-design\skills\frontend-design\SKILL.md`.
- **Taste Skill** (`Leonxlnx/taste-skill`, skill `design-taste-frontend` v2.5.1): **still not installed** (no marketplace or files after `/reload-plugins`). It's third-party with Node scripts + a finish-gate Stop hook, so the user installs it themselves: `claude plugin marketplace add Leonxlnx/taste-skill`, then `claude plugin install taste-skill@taste-skill`. Its rules were read from GitHub (`skills/taste-skill/SKILL.md` + `references/system.md`, `motion.md`, `copy.md`, `layout-v4.md`); the parts that apply are in §4.

- **ui-sound-design** (`dannyjpwilliams/ui-sound-design-skill`, MIT): installed 2026-11-21 in `.claude/skills/ui-sound-design` (files read first: markdown, a preview page, and an optional Node analyzer that runs `ffmpeg` only when called). It was used to audit and redesign the launcher's synth sounds. Fixes: one time base per sound (`now()`), noise nodes disconnected `onended`, stop padding, and no raw sawtooth whir. New sounds: hoof = hollow knock + low thump (randomized), metal = FM `bell()` (steel ball, spurs, chimes). Levels were measured offline as the loudest 50 ms above 200 Hz, since TV speakers drop the lows: move -40, bump -38, back/tab -36, menu/select -35, battery -34, fanfare ~-32, launch -30 dB. The old order was inverted (move loudest, tab 10 dB quieter). Grip taps were kept: move ~47 ms at full strength, bump ~60 ms.

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
- Last session's UI polish (inactive rows fade to 55 %, tile shadows, +1vh under the Play pill) screenshot-checked OK at 1920×1080. (Its light sweep is now on the delete list, §4 C.)
- Vertical row scrolling in `focus()` fixed: `offsetTop` broke once `#rows` had a transform (it becomes the offsetParent), so the previous row peeked under the header as colored stripes. Now uses bounding rects and snaps to row starts. Verified at 1920×1080 and 1280×720, down and back up.

## 3. Current state & uncommitted changes
- **Current state, uncommitted work and next steps live in `SESSION.md`** (handoff, 2026-11-21). The rest of this file is background and gotchas. `profiles/` (the launcher's Edge profile), logs and `__pycache__` are git-ignored on purpose.
- Working: launcher, controller, phone remote, startup, game launching, no black flash on launch (launcher no longer minimizes).
- TV launcher was reloaded after the scroll fix; not looked at on the TV itself.
- Not verified with a real game: the no-black-flash change and the overlay filter in `visible_windows()`.

## 4. UI anti-slop pass — DONE 2026-11-21 (all of A–E applied, plus dialog button glow removed; screenshot-checked; TV launcher reloaded, not looked at on the TV)
**The brief beats the skills.** Keep: purple polka-dot poster (Taste bans violet; overridden), pink Lobster "Couch" logo with cyan rim, horseshoe, steel ball on the focused tile, ゴゴゴ, PS5 layout (square tiles, white focus ring, white ✕ pill, coloured ✕○△ hints). Both skills target marketing sites; apply only what fits a 10-foot TV UI. "Spend boldness in one place": the poster, logo and ゴゴゴ are loud; everything else goes quiet.

`web/launcher.html`:

**A. Type**
- Replace Inter with **Archivo** variable: Google Fonts `family=Archivo:wdth,wght@62..125,400..900`; keep the non-blocking `media="print" onload` load and the Segoe UI fallbacks in `--ui`. Why: Inter is Taste's #1 banned font; heavy condensed Archivo echoes 1890 wood-type race posters (the SBR subject).
- `#d-title`: heavy condensed, about `font: 800 7.2vh/1.02 var(--ui)` then `font-stretch: 75%` (it must come after the `font` shorthand, which resets it). The freed eyebrow space (≈2.2vh) pays for the bigger size; `.details` stays 20vh.
- Delete the `#d-stage` eyebrow ("STAGE III · CAMP": all caps, tracked, "·"-joined, repeats the row name): element, CSS, `STAGES`, its line in `showDetails` (drop the `r` param and the caller's arg).
- Row headings (`section h2`): plain, quiet, sentence case, no letter-spacing; drop the pink-script `b` style (the logo face stays on the logo only).

**B. Copy** (plain words; no puns, no " — " or " · " chrome)
- Delete the greeting: `#greet`, `.brand span` CSS, the greeting line in `tick()`.
- Row names: "Apps", "Games", "PC" (drop "Stage I/II/III": not a sequence).
- Games meta: just `ago()`; drop the GB size and "·". "Never ridden" → "Not played yet". "Saddling up…" → "Loading games…".
- Apps meta: web → "Opens full screen", others empty; give `#d-meta` `min-height: 1.3em` so the pill doesn't jump.
- PC tiles: add a per-item CTA so the pill names the action:

  | Tile | Meta | CTA |
  |---|---|---|
  | Phone remote | Scan a code to control the PC from your phone | Show code |
  | Sound on/off | Menu sounds when you move and select | Turn off / Turn on |
  | Sleep | Wake it with the PC's power button | Sleep |
  | Restart | Closes all apps and restarts the PC | Restart |
  | Shut down | Closes all apps and turns the PC off | Shut down |
  | Desktop | Closes the launcher and shows the desktop | Go to desktop |
- Launch toast "And they're off — X" → "Starting X…" (matches the phone remote).
- Phone overlay heading "Phone Remote" → "Phone remote".
- Hide the ✕ pill until something is selected: `body:not(.chosen) .cta { visibility: hidden; }` (✕ does nothing then).

**C. Decoration & motion (delete)**
- Twinkling stars: 6 `.star` svgs, `.star` CSS, `twinkle`, the `#star` symbol.
- Dust canvas: `#dust` element, CSS, the dust IIFE (also stops a constant rAF loop on the gaming PC).
- Golden spiral: keep it, but static (remove its `spin` animation; keep `@keyframes spin`, the steel ball uses it).
- Backdrop Ken Burns `drift` (+ the `inset: -2vh` / `scale(1.04)` it needed).
- Light sweep on the focused tile (`.item::after`, `sweep`); Taste bans shine sweeps.
- Focus: white ring + drop shadow only (drop the two cyan glows).
- Tile inset top highlight (`inset 0 .15vh 0 …`).
- Glass: PC tiles → solid fill (about `#301866`, no blur, no border); toast → solid, no blur, no left stripe.

**D. App tiles**
- Flat brand colour (no radial gradient wash), no icons (three stores shared one bag icon; the YouTube icon was a drawn look-alike; Taste says real logos or none). The name is set large in condensed Archivo, bottom-left (about `800 3.2vh/.95`, `font-stretch: 75%`).
- Delete the now-unused symbols `i-gamepad i-car i-play i-film i-bag` and the `.app svg.icon` CSS (keep `icon()`: PC tiles and the sound hint use it). In `apps.json`, drop the `icon` keys and the icon sentence in `_help` (the server doesn't read them; the phone remote uses letter swatches).

**E. `web/remote.html`**
- `h2`: drop `text-transform: uppercase` and `letter-spacing` (the headings are already sentence case).
- `#toast`: drop the `border-left` stripe.

**Verify:** at 1920×1080 screenshot the start screen, a game, an app tile, a PC tile and a power dialog; check `document.fonts.check("800 20px Archivo")`; then close the preview tab and reload the TV launcher (§5 step 2).

**Considered and skipped for now**
- Real app logos: needs a one-time script pulling 256 px icons from the exes (Steam, Epic, EA, Ubisoft; e.g. `SHDefExtractIcon` via PowerShell `Add-Type`) plus a download OK for YouTube/Netflix. Offer as a follow-up.
- A `prefers-reduced-motion` rule: `couch-setup.ps1` may have turned Windows animations off, which would also kill the brief's steel ball and ゴゴゴ. Check that first.
- Taste rules that don't fit a TV launcher: section/screen heights, 12-column grid, 400-weight headlines, no violet.

**Taste Skill rules that do apply (reference):** banned fonts Inter, Roboto, Open Sans, Lato, Montserrat, Poppins, Space Grotesk, Plus Jakarta Sans; no tracked capitals, sentence case; one accent; no gradient/ghost/shadowed buttons; no shine sweeps, glows, tilt, bounce/overshoot, twinkle/blinking, parallax; animate only transform/opacity; UI easing `cubic-bezier(.2,.8,.2,1)`; copy: no metaphors, greetings, jokes/slang, exclamation marks or "Learn more"-style buttons; buttons are verb + object.

## 5. Next steps
See `SESSION.md` § Next. Issues: 01 and 02 are the user's own settings, 09 is an open idea; 03–06 and 08 are resolved, 07 is wontfix.
How to check a UI change: open `http://127.0.0.1:8765/launcher?preview` in the browser pane, read DOM state (never activate tiles), **close the preview tab afterwards**, then reload the TV launcher: `POST /api/window {"action":"close-launcher"}` then `{"action":"launcher"}` (header `X-Couch: 1`).

## 6. Gotchas & decisions
- **Controller presses go only to the newest launcher page** (`emit` → `LISTENERS[-1]`). Any preview tab of `/launcher` steals the controller from the TV → always close preview tabs, then reload the TV launcher.
- Edge: use `--app` + `--start-fullscreen`, **not `--kiosk`** (kiosk is InPrivate → loses sign-ins). Keep the occlusion flags (`CalculateNativeWinOcclusion` off, no backgrounding) — without them the launcher shows gray until clicked at boot. `--autoplay-policy=no-user-gesture-required` is needed for sounds.
- Firewall allows `python.exe`, not `pythonw.exe` → start via `conhost --headless python.exe`, never pythonw.
- Browser pane: CSS transitions may not advance between tool calls. Finish them via `document.getAnimations()` before reading rects, or you measure mid-transition positions. A viewport size set with `resize_window` applies per tab; set it again on a new tab.
- 2026-11-21 PS5 overhaul (commit after b4797cb/5166807): OLED obsidian + frosted glass, official SBR key visuals from jojo-portal.com as rotating home backdrops (`web/img/sbr-*.jpg`, cropped text-free), SVG prompt bar (✕ □ △ L1/R1 Options), △ search, □ details, Options menu, L1/R1 = rows, spring motion, Gamepad API fallback when pygame is missing, controller speaker routing over USB (the launcher profile's Edge Preferences get the media permission via `allow_audio_names`; the `--use-fake-ui-for-media-stream` flag was dropped because it shows an "unsupported command-line flag" banner), haptic cues, clip slots in `web/audio/sbr` + Sound settings/soundboard. No copyrighted audio downloaded: the user adds clips (SBR opening is "SPIN" by Kroi).
- **Screenshots:** the browser pane can get stuck at device pixel ratio 3 and capture only a corner. Use `python couch-remote/dev/shoot.py <steps.json> <out_dir>` (headless Edge, true 1920x1080; example steps in `dev/shots-example.json`). Its steps call page functions (`focus`, `pickAudio`, `showStarting`), never anything that launches.
- **Audio:** SteelSeries Sonar, Voicemeeter and VB-Cable are installed but not running; something occasionally sets the calls role back to Sonar Chat, which `keep_audio` undoes. The picker hides virtual devices (`VIRTUAL_AUDIO`).
- **The Bash tool turns a double backslash into one, even in quoted heredocs** (Python escapes like a PNG signature came out as raw bytes). For strings with backslashes, use the Edit tool.
- **The preview is live:** Enter/✕ or `.onactivate()` on a tile in `/launcher?preview` really launches games/apps on this PC (happened twice on 2026-11-21: Silent Hill 2, YouTube). When testing, never activate tiles; check by reading DOM state. `api` is a `const`, so you can't fake `/api/info` from the console.
- **Controller speaker over Bluetooth (verified by the user 2026-11-21):** Windows has no sound device for it, so `padspeaker.py` does what a PS5 does: report 0x31 turns the speaker on (volume 100, preamp 7 = max; Linux uses 2 = +6 dB), and report 0x39 carries two 200-byte CBR Opus frames every 21.333 ms. That stream is labelled 48 kHz but plays at 45 kHz. Both reports end in a CRC-32 over `0xA2` + the report. The encoder is pygame's bundled `libopus-0.dll`; the device is opened and written with plain `CreateFileW`/`WriteFile` (shared with SDL and Steam). The page taps its own output with an AudioWorklet (`padTapWorklet`), which resamples to 45 kHz, applies a 4x lift through a limiter, and posts 2048-byte blocks to `POST /api/padaudio` (local only, one request at a time). Each block is 960 16-bit speaker samples plus 128 haptic bytes (64 frames x 2 grips at 3 kHz). The haptics come from the menu sounds only (the `sfx` bus, not music), through the worklet's second input. Their low end (below 400 Hz) sets the strength of a 150 Hz buzz: drive x120, instant attack, 25 ms fade, so a clop is about 60 ms at full strength. The user found the plain low-passed waveform too weak. The 0x31 control report also asks for full motor power and turns off the controller's own haptic low-pass; those flag bits come from nondebug's DualSense notes. The TV still plays everything; launch music is controller-only (`music(..., padOnly)`). Protocol source: github.com/Jindantesparda/dualsense_BT_audio (from KytyPS5 / DS5Dongle). `python padspeaker.py` plays a test chime.
- **Light bar:** pygame has no LED call, so `_controller_loop` loads pygame's own `SDL2.dll` with ctypes and calls `SDL_GameControllerSetLED(SDL_GameControllerFromInstanceID(id), r, g, b)` on the controllers pygame opened. `POST /api/light {"rgb": [r,g,b]}` (local only) sets `LIGHT`, and the loop applies it, including to a controller that connects later. The page picks the colour (`artColor`: saturated pixels of a 16x16 sample of the cover, grey partly removed, full brightness; gold for grey covers or cross-origin art). Not looked at on the controller by me: the user saw the demo cycle only if they were watching.
- **Turn off controller (verified by the user 2026-11-21):** `padspeaker.turn_off()` reads each Bluetooth DualSense's MAC (`HidD_GetSerialNumberString` gives it, e.g. `0c27566ea39d`) and sends `IOCTL_BTH_DISCONNECT_DEVICE` (0x41000C) to the Bluetooth radio. It stays paired, PS turns it back on, no admin needed. `POST /api/padoff` (local); with `{"idle": true}` it does nothing unless the launcher is in front, because the page's idle timer also runs behind games. The launcher sends that when its 10-min idle screen starts, and has a "Turn off controller" item in the PC row / Options.
- **Games order:** everything is sorted by last played across stores. Steam has its own `LastPlayed`; `launch_app` saves the time a non-Steam game (apps.json `games`) was launched in `choices.json` `played`. GTA shows "Not played yet" until it's started once from the launcher.
- Phone remote's Power tab shows "Playing X" with Resume / Close game (`info.running` now goes to phones too). Game details show free space on the game's library drive (`free` per Steam game).
- `rows` is a global in `launcher.html` (used inside `focus()`); don't declare a local `rows` there (TDZ crash).
- The `<use>` SVG bug: outer `viewBox` must be `0 0 2 2` for symbols defined as `-1 -1 2 2`.
- Fonts/QR lib load non-blocking (no waiting on the internet at boot) — keep it that way.
- Don't change Windows system/security settings (Claude can't); give the user commands instead.
- Don't install third-party plugins for the user (Taste Skill runs its own scripts + a Stop hook); give them the commands.
- Steam is not started at boot by anything; it only opens when picked in the launcher.
- Don't reintroduce: PIN, keyboard/mouse mapping of the controller for desktop apps (user rejected), launcher minimizing on launch (caused black flash), opening with a tile pre-selected, streaming apps like YouTube/Netflix (user wants games only).
