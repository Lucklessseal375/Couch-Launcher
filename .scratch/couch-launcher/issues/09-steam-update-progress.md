# Idea: show when a Steam game is updating

Status: resolved

Launching a game that's mid-update opens Steam's download page instead of the game. The server already reads each game's appmanifest; its `StateFlags` says when an update is pending or downloading. The tile meta could read "Update in progress" (and the pill "Open Steam") instead of "Last played …". About 20 lines; refresh happens on the existing focus reload.

## Comments

- 2026-11-21: Done.
  - **Server:** `update_status(st)` turns `StateFlags` into the tile text: "Update waiting in Steam" (2), "Updating 45%" (running, downloading, staging or committing, with `BytesDownloaded+BytesStaged` over `BytesToDownload+BytesToStage`), or "Update paused in Steam" (512). Games now carry it as `update`.
  - **Bug found on the way:** Steam drops "fully installed" (4) while an update runs, so such a game used to vanish from the launcher. `steam_games` now keeps a game that has an update and `InstalledDepots`, while a first install (no depots) stays hidden.
  - **Launcher:** the tile's line reads the update text and its pill says "Open Steam". While any game updates, the page re-reads `/api/info` every 20 s so the % moves.
  - **Tests:** `SteamUpdateTest`.
  - **Checked:** with a faked update the tile read "Updating 45%" with "Open Steam" and the 20 s refresh armed. No game was updating on this PC, so it hasn't been seen with a real update.
