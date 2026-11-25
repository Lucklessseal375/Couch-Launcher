# Engineering brief: status and test matrix

What came of the "Couch Launcher — Engineering Review & Development Brief" (2026-11-24/25), checked against the real code.
The brief assumed an Electron app; Couch is a Python web server (`couch-remote/server.py`) plus Edge windows, so its
Electron sections were mapped to the equivalent part here, or marked as not applying.

## Where each section stands

| Brief section | Status in Couch |
| --- | --- |
| 0. Verify the diff | Done. `355154a..812fa0b` is one commit (the self-update supervisor); both on `main`. |
| 2. Architecture map | Server `server.py`; TV page `web/launcher.html` (Edge `--app` window, own profile); phone remote `web/remote.html`; Stremio driven over WebView2 DevTools (`stremio.js`); updates `update.py`; settings `choices.json`. |
| 3.1 Window security | Not Electron. The equivalent boundary is the HTTP server: loopback and private-LAN clients only, `Host` check, and a custom `X-Couch` header that blocks other websites (`server.py` `client_kind`, `host_ok`, `gate`). No PIN on the phone remote, by the user's choice. |
| 3.2 IPC validation | HTTP API equivalent: bodies capped at 10 kB; every action takes allow-listed values. New endpoints (`/api/apps`) validate kinds, ids, https URLs and Start-menu ids. |
| 3.3 Browser / CDP | Edge and WebView2 DevTools ports are random per launch (YouTube since before; Stremio since `90b477d`) and bind to loopback. Dedicated profiles, never the user's own. No page contents or tokens are logged. Residual risk: any program already running on the PC as you could drive those pages. |
| 3.4 Injection | Checked: every name, title and window title is escaped (`esc`) or set as text. |
| 4.1 Lifecycle / recovery | A supervisor restarts a crashed server (gives up after 3 crashes in 10 minutes). The TV shows "Reconnecting to Couch…". Launch has a 3 s double-press guard. |
| 4.3 Error states | Launch failures, a server that's down and a missing controller each have plain messages. Edge itself missing isn't handled (Couch needs Edge). |
| 4.4 Logging | 1 MB rotating log; no typed text, keys, tokens or URLs with queries. PC row → About Couch shows version, update status, streaming parts, controllers and recent problems; Copy for support puts exactly that text (user folder and name removed) on the clipboard. |
| 5 Controller | Server-side reading (SDL) with held-key repeat; Controls lists every button, the connected controllers and battery, swap ✕/○, and Reduce motion. Not done: adjustable dead zones and a button-test screen (defaults work). |
| 5.4 On-screen keyboard | Letters, capitals, symbols, accents (L1/R1), △ space, □ delete, hidden text for passwords; types into Couch's own prompts. Stremio has its own keyboard (`stremio.js`). |
| 6.1 Home screen | Now playing (Resume/Close), Apps, Games (recent first, pins), PC row; the first press after a reload lands on your last tile. |
| 6.2 Managing apps | Add app (Start-menu program or https website), Move, Hide, Remove, all from the controller; kept per PC in `choices.json`. |
| 6.4 Accessibility | Reduce motion switch; TV-sized text (≥ 2.3vh); light/high-contrast themes not added (the JoJo look is dark by design). |
| 7 Media features | Skipped with Milestone 4, at the user's request. |
| 8 System | Sleep timer, power menu, audio output, volume, controller battery, stay-awake while streaming, Sunshine streaming. |
| 9 Config | Atomic `choices.json` writes; a damaged `choices.json` is kept as `choices.bad.json`; a broken `apps.json` leaves out its tiles instead of failing. |
| 15 Auto-update guardrail | Updates are signed (Ed25519, key only on the main PC), checked against the installed copy's own key, and roll back if the new version crashes within 2 minutes. |

## Performance baseline (main PC, 2026-11-25, 4K TV at 300%, 32 logical cores)

| Measure | Result |
| --- | --- |
| Server idle CPU | 0.7% of one core |
| Server memory | 53 MB (+ 34 MB supervisor) |
| `/api/info` (full library) | 42 ms median |
| `/api/running` (the 3 s poll) | 1 ms median |
| TV page load (headless) | HTML 3 ms, DOM ready 24 ms, load 307 ms |
| Moving focus | 6 ms per move |
| TV page idle (Edge, 10 processes) | 279 MB; 3–12% of one core, varying with the background's 20 s change |
| Self-update after a push | about 2 s from sign-in check to the new version answering |

## Manual test matrix

Automated: `python -m unittest discover -s tests` in `couch-remote` (127 tests). Screens: `dev/shoot.py` specs.
Clean-PC install and signed self-update: Windows Sandbox (`C:\Users\eli\couch-sandbox-test`).

| Scenario | Expected | Last checked |
| --- | --- | --- |
| Fresh install (Install Couch.cmd) | Python, startup task, firewall rule, Sunshine + ViGEmBus, shortcut; Couch opens | Sandbox, 2026-11-24 |
| Signed update at sign-in | New version installed, Couch back in ~2 s | Sandbox, 2026-11-24 |
| Unsigned or wrong-key update | Skipped, logged | Throwaway copy, 2026-11-24 |
| Update that crashes on start | Old files back, version marked bad | Throwaway copy, 2026-11-24 |
| Server killed | Back within ~8 s; TV shows reconnecting, then "Couch is back." | Main PC, 2026-11-24 |
| Broken apps.json / choices.json | Home screen loads; damaged choices kept as a copy | Unit tests |
| Add, move, hide, remove an app | Tile appears/moves/hides; hidden ones return from the PC row | Main PC API + previews |
| Rename a game with spaces/accents | Typed with △ and the accents layer | Preview |
| Stremio on a 4K TV at 300% | Whole page on screen (1280 px wide) | Main PC, 2026-11-24 |
| Stremio with a random DevTools port | Controller, Back, fit all work | Not yet: next time Stremio opens |
| Phone remote Back after a controller was used | Goes back in Couch; Back in Stremio | Unit tests + API |
| Moonlight stream (PS4 controller mode) | Couch and games see a PlayStation controller | Not yet: next stream |
| Controller disconnect / reconnect | Header shows "No controller", then the battery | Main PC (logs) |

## Not done, by choice or for later

- Electron-specific items (contextBridge, WebContentsView cache): Couch has no Electron; skipped at the user's request, 2026-11-25.
- Adjustable dead zones, button remapping and a controller test screen: skipped at the user's request, 2026-11-25 (the defaults work).
- Milestone 4 (universal search across streaming services, profiles, Plex/Jellyfin, voice): skipped at the user's request, 2026-11-25.
- Light/high-contrast themes: skipped, the JoJo / Steel Ball Run look stays (user's standing rule).
