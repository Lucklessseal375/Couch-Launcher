# Session handoff (2026-11-21)

Read this first, then the gotchas in `PICKUP.md` §6 (they matter before you touch anything), then `CLAUDE.md`.

## Where things stand

- **Everything is committed and the working tree is clean.** The last commit is the one that adds this file, on `main`. Nothing is pushed.
- **Running now:** the server (`python server.py`, started hidden, not by the logon task) and the TV launcher (Edge `--app`), both on the latest code. The phone remote is a static page; reload it on the phone to get the new icons.
- **Tests:** `cd couch-remote && python -m unittest discover tests`. Result: 17 tests, OK.

## What this session did

Earlier in the session (details in `PICKUP.md` §1):

| Commit | Work |
|---|---|
| `2fcf0d6` | Launcher UI cleanup and row scroll fix |
| `784604d` | Games-only launcher: resume/close, battery, idle screen |
| `b4797cb` | Hide/pin games with Square; audio output tool |
| `5166807` | Audio output that holds the TV as default; real app icons; polish |
| `6decd0c` | PS5-style launcher with SBR key art, search, details, menu, sound slots |

Then:

| Commit | Work | Confirmed by the user? |
|---|---|---|
| `5bf0e41` | No more "unsupported command-line flag" banner. The `--use-fake-ui-for-media-stream` flag is gone; `allow_audio_names()` writes the media permission into the launcher's own Edge profile instead. | Yes: "banner is gone" |
| `9f939cf` | Launcher sounds on a wireless DualSense's speaker, plus the TV. `padspeaker.py` sends HID report 0x31 (speaker on, volume 100, preamp 7 = max) and 0x39 (Opus audio). Opus comes from pygame's `libopus-0.dll`. Music started with a game is controller-only. USB is unchanged. | Yes: "works", "louder", no delay |
| `19bf408` | Menu sounds felt in the grips. The haptic bytes in 0x39 are driven by the menu sounds' low end (a 150 Hz buzz, drive x120, 25 ms fade). Music is never felt. | Yes: "taps feel good" |
| `fddfed9` | The ui-sound-design skill (`.claude/skills/ui-sound-design`, MIT, every file read first) and a sound redesign: its rule fixes, a hoof knock + thump, FM bells for metal, and a measured loudness order (move -40 … launch -30 dB). | Yes: "sounds good" |
| `d88eac8` | **Light bar:** gold in the menu, the game's cover colour (or a store app's brand colour) when it starts, restored on Resume; `POST /api/light`, set through SDL. **Steam updates (issue 09):** "Updating 45%" / waiting / paused on the tile with an "Open Steam" pill, refreshed every 20 s. Also fixes updating games vanishing from the shelf. | Not yet |
| `d4c77c6` | Phone remote: drawn PlayStation buttons and icons instead of text symbols. Screenshot-checked at 390x844 and sent to the user. | Not yet |

Answered, no code: a Godot rewrite isn't worth it (the server would keep all the real work); the launcher's Edge uses ~600 MB of the PC's 32 GB.

## How the sound and light paths work (one-minute map)

- `launcher.html` `Sound` holds one AudioContext. Its nodes:
  - `out`: synth sounds, through a 9 kHz low-pass.
  - `sfx`: menu sounds, felt in the grips.
  - `bus`: everything.
- `Out.detect()` picks one of three outputs:
  - A USB DualSense device id, via `setSinkId`.
  - `"bt"`: `GET /api/padspeaker` says a wireless one is connected.
  - `""`, the TV.
- In `"bt"` mode an AudioWorklet (`padTapWorklet`) taps two inputs:
  - The bus, through a 4x lift and a limiter, becomes the speaker.
  - `sfx` becomes the grips.
- `PadLink` posts 2048-byte blocks (960 16-bit samples at 45 kHz, then 128 haptic bytes) to `POST /api/padaudio`, one request at a time.
- `padspeaker.Speaker` paces one 0x39 report every 21.333 ms to every Bluetooth DualSense, and rests after ~1 s of quiet. `python padspeaker.py` plays a test chime plus a tap.
- **Light bar:** `padLight(rgb)` posts to `POST /api/light`. The controller loop calls `SDL_GameControllerSetLED` (ctypes on pygame's `SDL2.dll`). `artColor(img)` picks the colour from a 16x16 sample of the cover.
- Protocol details: `PICKUP.md` §6 (the "Controller speaker over Bluetooth" and "Light bar" bullets).

## Ground rules from the user (keep following them)

- **Ponytail mode (full).** Smallest complete change; end replies with what was skipped and any risk.
- **Working style.** Work without asking for permission and verify things yourself. Commit only when the user asks ("fix all" from the handoff list counted).
- **No copyrighted audio downloads.** The user asked several times for "SPIN" by Kroi (YouTube, majdata.net); it was declined each time. They can drop their own file into `couch-remote/web/audio/` (intro) or `web/audio/sbr/` (slots).
- **Don't change Windows system or security settings.** Issues 01 and 02 hold the exact commands for the user to run.
- **Never activate a tile** (Enter / ✕ / `.onactivate()`) in `/launcher?preview`: it launches real games.
- **Close every preview tab when done.** The newest launcher page takes the controller's presses away from the TV. Then reload the TV launcher.

## Restart recipe (what was used all session)

```powershell
cd C:\Users\eli\Documents\CouchSetup\couch-remote
# stop the server and the launcher's Edge
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'server\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'msedge.exe' -and $_.CommandLine -match 'profiles.launcher' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Process python -ArgumentList 'server.py' -WindowStyle Hidden
# then open the launcher on the TV
Invoke-WebRequest http://127.0.0.1:8765/api/window -Method Post -Headers @{'X-Couch'='1'} -ContentType 'application/json' -Body '{"action":"launcher"}' -UseBasicParsing
```

- **A page-only change:** `{"action":"close-launcher"}`, then `{"action":"launcher"}`.
- **Safe test keys:** `POST /api/key` with arrows or escape, and `POST /api/text {"text":"m"}` for the menu. Never send `enter`.
- **Light bar test:** `POST /api/light {"rgb":[98,171,255]}`.

## Next

1. **For the user to do or confirm:**
   - Watch the light bar change when a game starts, and reload the phone remote to see the new buttons.
   - Issue 01: never sleep, so the phone remote always works. Issue 02: one restore point per day again. Each issue has the admin command.
   - Add their own intro song file.
2. **Not verified (needs the hardware or a real situation):**
   - A real Steam update on a tile. No game was updating, so it was only tested with a faked one.
   - Steam Input or a running game taking over the light bar or the speaker stream.
   - Two DualSenses on at once. Both get the sound and the colour; never tried.
   - The 0x31 haptic flags (full motor power, built-in haptic low-pass off). They come from community notes (nondebug's DualSense docs); the taps feel good either way.
3. **No open feature work is left from the list.** All issues are resolved, wontfix (07), or the user's own (01, 02).
