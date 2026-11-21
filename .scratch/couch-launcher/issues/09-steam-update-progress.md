# Idea: show when a Steam game is updating

Status: needs-triage

Launching a game that's mid-update opens Steam's download page instead of the game. The server already reads each game's appmanifest; its `StateFlags` says when an update is pending or downloading. The tile meta could read "Update in progress" (and the pill "Open Steam") instead of "Last played …". About 20 lines; refresh happens on the existing focus reload.
