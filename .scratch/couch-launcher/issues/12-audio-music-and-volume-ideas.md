# Ideas: background music, per-app volume, and PC volume while playing

Status: ready-for-agent

Saved 2026-11-25 for later, at the user's request ("save it for ideas for music in the back ground with something to adjust audio per app volume also for volume for full pc in games and apps like YouTube"). Per-game audio output was built the same day (issue-free, in `server.py`); these are the follow-ups.

## What the user wants
1. **Music in the background.** Couch already plays an intro clip and optional menu music from `couch-remote/web/audio` (Sound settings). The idea goes further: music that keeps going while you browse, and maybe quietly under a game or app.
2. **Per-app volume.** A mixer on the TV: each running app or game (YouTube, Stremio, a game, Discord) with its own level, like Windows' Volume mixer but driven by the controller.
3. **Whole-PC volume from anywhere.** Change the PC's volume while a game or YouTube is in front, not only from Couch's PC row. (Issue 07 asked this for L2/R2 and was set aside then; this request reopens the need.)

## What's true now
- `audio.py` switches the default output device (Audio output tile) and Couch keeps it (`keep_audio`).
- The PC row has a Volume tile (whole-PC master volume) and Sound settings (Couch's own sounds and music).
- In games and apps, the controller's buttons go to the app; only the PS button and Create/mute are Couch's everywhere.

## Open questions
- **Which button changes volume in a game or YouTube without stealing one the game uses?** Options: hold PS + up/down (like a PS5's quick menu), or the PS-button quick menu with a volume slider over the game.
- **Per-app levels:** Windows' per-app volume (`ISimpleAudioVolume` on each audio session, via pycaw-style COM calls, no new install needed with ctypes/comtypes) vs. only Couch's own apps.
- **Background music:** your own files (like the intro clips) vs. a streaming service; under games or only in the menus.
