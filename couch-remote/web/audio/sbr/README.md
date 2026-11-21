# Steel Ball Run sound clips

Drop your own clips here (`.mp3`, `.ogg`, `.wav`, `.m4a` or `.opus`). The launcher loads them when it starts,
so restart it (or press PS to bring it back after a reload) after adding files. Any slot without a file keeps
its built-in synthesized sound, so a missing or broken file never breaks anything.

| File | Plays when | Ideal length | Loudness |
|---|---|---|---|
| `nav-move.mp3` | D-pad / left stick moves | 0.1 to 0.3 s | quiet: it plays on every move |
| `tab-switch.mp3` | L1 / R1 changes category | 0.2 to 0.5 s | quiet |
| `launch-1.mp3`, `launch-2.mp3`, ... (or `confirm-launch.mp3`) | ✕ starts a game; one variant at random | 1 to 2 s | medium |
| `back.mp3` | ○ closes something | 0.2 to 0.4 s | quiet |
| `control-center.mp3` | Options opens the menu | 1 to 2 s | medium |
| `bgm-loop.mp3` | menu music, looping, low; fades out when a game starts | 1 to 3 min, loops cleanly | the launcher plays it at 35% by default |

**Voice lines:** put `-voice` in the name (`launch-voice-1.mp3`, `control-center-voice.mp3`). Menu > Sound > Voice lines
turns those off and keeps the rest.

Aim for clips normalized to about -14 LUFS (or simply: peaks around -3 dB) so they sit level with each other.
Effects and music volume are set in Menu > Sound, and Menu > Sound > Test sounds plays each slot.

Use clips you have the rights to use, for example from your own copies.

Where they play: the DualSense speaker when the controller is on a USB cable (Windows only offers its speaker
over USB), otherwise Windows' default output (the TV).
