# Couch setup – manual checklist

Do these after running `couch-setup.ps1` and rebooting.

## TV connection
The HDMI port the PC uses now reports **60 Hz max and no VRR** (checked 2026-11-20).
- [ ] Check whether your TV supports 120 Hz (its spec sheet, or a port labelled **4K 120Hz**).
  - **120 Hz TV:** move the cable to that port, use an **Ultra High Speed (48 Gbps)** HDMI cable, then do the "120 Hz TV only" steps below.
  - **60 Hz TV:** skip the "120 Hz TV only" steps and do the "60 Hz TV only" step instead.
- [ ] Samsung TV: **Settings > Connection > Game Mode = On** (or Auto). Turn on **Input Signal Plus** for the PC's HDMI port.

## Windows display, driver & sound
- [ ] NVIDIA App > Drivers: install the latest driver (the current one is from May 2026).
- [ ] Settings > System > Display: **Use HDR = On** (already on). Run the **Windows HDR Calibration** app (Microsoft Store).
- [ ] 120 Hz TV only: Settings > System > Display > Advanced display: pick **120 Hz**.
- [ ] 120 Hz TV only: NVIDIA Control Panel > Display > Set up G-SYNC: **Enable G-SYNC Compatible**, full screen and windowed. If the TV has a **VRR / FreeSync Premium** option, turn it on.
- [ ] 60 Hz TV only: NVIDIA Control Panel > Manage 3D settings > **Vertical sync = On**. In demanding games, use **DLSS** so they hold a steady 60 fps at 4K.
- [x] Sound output is already the **SAMSUNG (NVIDIA High Definition Audio)** device.

## Steam
- [x] Leave **Run Steam when my computer starts** and **Start Steam in Big Picture Mode** OFF (Settings > Interface).
      The Couch Launcher starts at sign-in instead and opens Steam only when you pick it. (The old `Steam Big Picture`
      startup shortcut was moved to `couch-remote\old-startup`.)
- [ ] Settings > Controller: **Enable Steam Input for PlayStation controllers** ✔.
- [x] Two DualSense controllers are already paired. To pair another: hold **PS + Create** until the light flashes → Windows Bluetooth > Add device.

## Storage
- [ ] D: (Steam library) has only **32 GB free**. Steam > Settings > Storage: move some games to C: (163 GB free).
- [ ] Longer term: both M.2 slots are in use, so replace the 500 GB drive on D: with a 2 TB NVMe drive.

## Other launchers → Steam (BoilR)
- [x] BoilR 1.11.0 installed to `%LOCALAPPDATA%\Programs\BoilR\BoilR.exe` (Start menu: **BoilR**).
- [ ] For cover art: make a free SteamGridDB account, get an API key at steamgriddb.com/profile/preferences/api, and paste it into BoilR's settings.
- [ ] Close Steam, run BoilR, enable **Epic**, **Origin/EA** and **Ubisoft Connect** (may be called Uplay), click **Synchronize**.
- [ ] BoilR doesn't support Rockstar: in Steam, use **Games > Add a Non-Steam Game to My Library** for those games.
- [ ] Re-run BoilR whenever you install a new game from those launchers.
- [ ] Epic Launcher > Settings: **Minimize to System Tray** ✔.

## Peripherals
- [x] iCUE stays on at startup (it runs the liquid cooler).
- [ ] If SteelSeries GG re-enables itself at startup, turn off "launch on startup" inside GG.
- [ ] Your default microphone is **SteelSeries Sonar's virtual mic**, which is silent while GG isn't running. If you voice chat from the couch, re-enable GG in Task Manager > Startup apps.

## Couch controls (cheat sheet)
| Action | Button |
|---|---|
| Steam menu / quit game / power | **PS** button |
| On-screen keyboard | **PS + Square** (exact chords: Steam > Settings > Controller > Guide Button Chord Layout) |
| Screenshot | **PS + R1** |
| Mouse mode on desktop | Steam's desktop layout (right stick/touchpad = mouse, R2 = click) |
| Sleep | PS → Power → **Sleep**, or press the PC's power button |
| Wake | Press the PC's power button |

## Undo
Start → "Create a restore point" → **System Restore** → choose **"Before couch setup"**.

To turn back on just one of the background apps, run in an admin Terminal:
- OneDrive at sign-in: `Get-ScheduledTask -TaskName 'OneDrive Startup Task*' | Enable-ScheduledTask`
- D3DGear: `Enable-ScheduledTask -TaskName 'D3DGearRawFrameCaptureTask'`
- AMD User Experience Program: `Set-Service AUEPLauncher -StartupType Automatic; Enable-ScheduledTask -TaskName 'StartAUEP'`

## More to do yourself
- [ ] Update the **RZ608 Bluetooth** driver (current one is from Aug 2022): MSI support page for MAG B550 TOMAHAWK MAX WIFI, or Windows Update > Advanced options > Optional updates.
- [ ] Install the latest **AMD Ryzen chipset driver** from amd.com.
- [ ] Disconnect the **AirPods** while gaming; they share the Bluetooth radio with the controllers.
- [x] The script stops **Radmin VPN** starting with Windows (open it from the Start menu when you need it; undo in Task Manager > Startup apps).
