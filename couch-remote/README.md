# Couch Remote

A full-screen launcher for the TV that you drive with a controller, plus a remote you open in your phone's browser.

## Start it
It starts by itself when you sign in to Windows (a **Couch Launcher** task in Task Scheduler, which skips the delay Windows adds to Startup-folder apps), and opens the launcher full screen. Double-click **Couch Launcher** on the desktop to bring it back at any time.

To stop it starting at sign-in:
```powershell
Unregister-ScheduledTask -TaskName 'Couch Launcher' -Confirm:$false
```

Needs Python 3 with `pygame` for the controller (already installed). After a fresh Python install, run:
```powershell
python -m pip install pygame
```

## Launcher (TV)
- **D-pad / left stick:** move · **✕:** select · **○:** back · **△:** phone QR code
- The server reads the controller itself, so it works with or without Steam running. Steam only starts when you pick Big Picture or a Steam game.
- **PS button:** brings the launcher back when Steam isn't running (Steam keeps it for itself when it is).
- Arrow keys / Enter / Esc and the mouse work too.
- Rows: **Stage I** apps, **Stage II** games (GTA V Enhanced + installed Steam games, most recently played first), **Stage III** camp (phone remote, sound, sleep, restart, shut down, desktop).
- When you start something, the launcher stays on screen until the new window appears (no black flash), then that window gets focus so the controller works there right away. Quit it and you're back on the launcher.
- Sounds: hoofbeats, spur jingles and a steel-ball whir. Turn them off in **Camp → Sound**.

## Phone remote
On the launcher, press △ (or open **Phone remote**) and scan the QR code. The phone has to be on the same Wi-Fi.
- **Remote:** D-pad, OK/Back, volume, play/pause
- **Touchpad:** drag to move the mouse, tap to click, two-finger tap to right-click, two-finger drag to scroll, and a text box for typing on the PC
- **Apps:** start apps and games
- **Power:** show the launcher, close the app in front, sleep, restart, shut down

## Settings
- `apps.json`: the app tiles (`apps`) and non-Steam games (`games`, with cover/hero image links). Edits show the next time the launcher comes to the front.
- `config.json`: the port (8765) and the Edge path.
- `web/poster.webp`: the launcher's background picture. `make_icon.py` redraws `icon.ico` / `web/icon.png`.
- `server.log`: errors and launches (capped at about 1 MB).
- `profiles\`: separate Edge profiles for the launcher, YouTube and Netflix, with your sign-ins. Don't share this folder.

## Restart / stop the server
```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess }
```
Then double-click **Couch Launcher** to start it again.

## Tests
```powershell
python -m unittest discover tests
```
They check the network rules (home network only, other websites blocked) and the Steam library file reader.

## Security
- No PIN, by choice: anyone on your home Wi-Fi who opens the remote page can control the PC.
- Only devices on your home network (192.168.x.x etc.) are accepted. Radmin VPN and internet addresses are refused.
- It can only start the things listed in `apps.json` and your installed Steam games. It never runs arbitrary commands.
- Websites open on the PC can't call it, because every request needs a custom header that browsers block across sites.

## Limits
- A phone can't wake the PC from sleep (the server is asleep too). Press the PC's power button.
- GTA V Enhanced's pictures come from the internet; without a connection its tile shows just the name.
