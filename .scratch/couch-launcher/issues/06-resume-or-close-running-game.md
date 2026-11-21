# Idea: "Resume" and "Close game" when the launcher comes back during a game

Status: resolved

Pressing the PS button mid-game brings the launcher up, but it doesn't know a game is running: picking it again starts a second launch, and quitting means using the game's own menu. PS5 and Apple TV both put the running app first with a Close option.

Server: remember the window `focus_what_opens` found after a launch; while it exists, `/api/info` returns it as `running: {name, hwnd}`. Launcher: a first tile "Resume <game>" (focuses that window) and a "Close <game>" choice behind a confirm dialog (unsaved progress = irreversible). Roughly 40 lines.

## Comments

- 2026-11-21: Done. `/api/launch` resets `RUNNING`; `focus_what_opens` records every window that opens for it. `running_window()` picks the newest one that's still open and isn't a store/launcher program (`LAUNCHER_EXES`), falling back to the newest (so Big Picture counts). `/api/info` adds `running: {name}` for the local page; `POST /api/window` takes `resume` (focus it) and `close-game` (WM_CLOSE, like the game's own close button). Launcher: a "Now playing" row on top with Resume and Close (Close asks first, Cancel focused). Coming back to the launcher while it runs lands on Resume. Tests: `PickRunningTest`.
- Checked: a real Silent Hill 2 launch was detected as running and the row went away when it quit; a minimized Notepad was found and closed via WM_CLOSE. 2026-11-21: user tested Resume and Close with the controller on the TV (YouTube): works.
- Limit: a game window that appears more than 10 s after the last launcher window isn't tracked (comment in `focus_what_opens`). Some games answer WM_CLOSE with their own "Quit?" prompt; pick Resume to answer it.
