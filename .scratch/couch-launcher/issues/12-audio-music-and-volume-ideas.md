# Ideas: background music, per-app volume, and PC volume while playing

Status: resolved

Saved 2026-11-25 for later, at the user's request ("save it for ideas for music in the back ground with something to adjust audio per app volume also for volume for full pc in games and apps like YouTube"). Per-game audio output was built the same day (issue-free, in `server.py`); these are the follow-ups.

## What the user wants
1. **Music in the background.** Couch already plays an intro clip and optional menu music from `couch-remote/web/audio` (Sound settings). The idea goes further: music that keeps going while you browse, and maybe quietly under a game or app.
2. **Per-app volume.** A mixer on the TV: each running app or game (YouTube, Stremio, a game, Discord) with its own level, like Windows' Volume mixer but driven by the controller.
3. **Whole-PC volume from anywhere.** Change the PC's volume while a game or YouTube is in front, not only from Couch's PC row. (Issue 07 asked this for L2/R2 and was set aside then; this request reopens the need.)

## What's true now
- `audio.py` switches the default output device (Audio output tile) and Couch keeps it (`keep_audio`).
- The PC row has a Volume tile (whole-PC master volume) and Sound settings (Couch's own sounds and music).
- In games and apps, the controller's buttons go to the app; only the PS button and Create/mute are Couch's everywhere.

## Remaining decision
- **Background music during gameplay or apps:** Decide whether menu music should keep playing quietly when a game or app is in front. The current implementation fades menu music when a game starts.

## Comments

2026-11-25: built.
- Whole-PC volume anywhere: hold PS and press up/down (4% a press, Windows shows its volume bar); PS alone still acts on release.
- Per-app volume: PC row → Volume → Volume for each app, sliders over Windows' own per-app levels (audio.py, no install). YouTube has its own slider, separate from Couch’s sounds and music.
- Background music: Menu music plays your Windows Music folder, shuffled, when no bgm-loop clip is set; fades when a game starts.
