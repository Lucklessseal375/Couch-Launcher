# Couch over Sunshine: play on the Apple TV in another room

_Design, 2026-11-22. Status: awaiting approval._

## Intent
The user wants to play their PC games on a second TV, an **Apple TV in another room of the house**, without moving the PC, and with **Couch as the menu** there too. Sunshine (free, open source) on the PC streams picture and sound; Moonlight (free, App Store) on the Apple TV shows it and sends a PS5 controller paired to the Apple TV back to the PC.

## Goals
- From the Apple TV, open Moonlight, pick **Couch**, and land in the normal Couch launcher; pick and play games with the controller in that room.
- Couch knows a stream is on: the header shows **"Streaming to <device>"**.
- Sound follows the stream: Couch's audio-keeper must not pull the default output back to the living-room TV while streaming.

## Non-goals
- Streaming outside the house (internet, VPN). Home network only.
- Pairing Moonlight from Couch's own screen, one Moonlight entry per game, a virtual display sized for the Apple TV, turning the living-room TV off (approach B; later, if A feels good).
- Installing or configuring Sunshine for the user.

## Anti-goals (a failure even if it technically works)
- Anything that changes how Couch behaves when nobody is streaming.
- Couch reachable from the internet, or new open ports beyond what Sunshine itself opens.
- Couch writing into Sunshine's settings or storing the user's Sunshine password.

## Constraints
- Python stdlib server, no new dependencies (SESSION.md §3).
- Installing software and changing Windows settings are the user's to do: Couch gives instructions, never runs installers.
- The PC is on Wi-Fi (Wi-Fi 7 / 6E adapters, no cable). Stream quality depends on it; recommend 1080p60 to start.
- `keep_audio` already forces the default output back to the chosen device and hides virtual devices (`VIRTUAL_AUDIO`).

## Approaches considered
- **A. Couch as the front door** (chosen by the user). User installs Sunshine and Moonlight once; Couch is added as a Sunshine app; Couch detects the stream, shows it, and pauses its audio-keeper. Small; builds on what exists.
- B. Couch runs the whole show: A plus pairing from Couch, per-game Moonlight entries, virtual display. Much bigger (Sunshine settings API with credentials, display driver); deferred.
- C. Steam Link instead of Sunshine: nothing new to install, but Steam's menus instead of Couch, and Epic games (GTA) awkward. Rejected: works against "Couch as the menu".

## Design (A)
1. **One-time setup by the user** (Couch's Controls/help text and SESSION.md carry the steps): install Sunshine from its official GitHub release; in Sunshine's web page, add an app named **Couch** whose command opens the launcher (same command the scheduled task uses, or a `POST /api/window {"action":"launcher"}` call); install Moonlight on the Apple TV, pair it with the PIN Sunshine shows; pair the PS5 controller to the Apple TV.
2. **Stream detection** (server): read whether a Moonlight client is connected from Sunshine's own log file (read-only). Exposed in `/api/info` as `stream: {device} | null` and pushed to the page like controller status.
3. **Header** (page): a small "Streaming to Apple TV" pill next to the controller status while connected.
4. **Audio** (server): while a stream is on, `keep_audio` stands down; when it ends, it resumes and restores the chosen device.
5. **Controller**: the remote controller arrives as Sunshine's virtual gamepad; Couch's SDL reader should already see it. Light bar, controller speaker and haptics only apply to the local Bluetooth DualSense; skip them for the virtual pad without errors.

## Left to the builder (to settle once Sunshine is installed)
- The exact Sunshine log lines (or other read-only signal) for connect/disconnect and the client's name; fall back to "a device" if no name.
- Whether Sunshine switches the default audio device itself during a stream, and which device name `keep_audio` should treat as "stream audio".
- Whether the virtual gamepad needs any change in `_controller_loop` (e.g. it reports no battery: show nothing, not "Battery empty").

## Done when
- With Sunshine + Moonlight set up, the user opens Couch from the Apple TV, starts a game, plays it in the other room with sound there, and the living-room Couch shows "Streaming to …" during it.
- With no stream, Couch behaves exactly as before (all existing tests pass; new tests cover the log parsing and the audio stand-down).
