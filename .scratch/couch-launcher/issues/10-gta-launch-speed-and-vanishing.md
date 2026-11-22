# GTA V: slow launch, and the game vanished after a reboot

Status: needs-info

Parked on 2026-11-22 at the user's request ("create a stop for this task, save everything for another time"). Everything below is committed; nothing is half-done in the code.

## Where it stands

- GTA V (Epic + Rockstar) launches from Couch, including with both launchers closed (verified 15:30).
- Couch's own part of a launch is ~0.1 s. Measured with everything warm (15:58): Epic → Rockstar 5.5 s, Rockstar ready 8 s, BattlEye 14 s, **GTA window 41 s**, then GTA's own loading.
- PC side: Windows was limited to 16 of the Ryzen 9 5900XT's 32 threads (msconfig "Number of processors" ticked). The user unticked it and rebooted at 16:10; Windows now uses 32. Effect on load time **not measured yet** (the first launch after the reboot was disrupted, see below).
- Other PC checks were fine: High performance power plan, Game Mode and HAGS on, 32 GB RAM @ 3600, GTA on a healthy NVMe (D:, 31 GB free of 466). Defender real-time is on; a GTA-folder exclusion was mentioned but not recommended.

## Open problem (needs-info)

After the 16:10 reboot: press 16:11:11 → Couch started Epic (4 s) → Rockstar started GTA at 16:11:32 → **GTA's process ended at 16:12:28 by itself** (the user didn't close it). No Windows error event, no crash dump in `D:\GTAVEnhanced` or `%LOCALAPPDATA%\Rockstar Games`. Epic logged "Dead foreground process … GTA5_Enhanced.exe"; Rockstar logged "Launcher pipe still open, notifying other instance of external title shutdown".

During that launch Couch had a bug: the Claude app (auto-starts at login) opened its window at 16:11:50 and Couch took it for GTA and focused it. Fixed in `3d5c181` (windows of programs that started before the press are ignored for games). Whether that focus change made GTA quit is unknown.

Next time: launch GTA from Couch after a reboot again, with `3d5c181` live, and see if it stays up. If it vanishes again, look at `Documents\Rockstar Games\Launcher\launcher.log` and `Documents\Rockstar Games\GTAV Enhanced` around that time.

## Still unverified

- `warm_rockstar` (Rockstar started at login, `79a4443`): evidence at 15:58 suggests Epic starts its own Rockstar launcher anyway, so the warm-up may be useless. If a post-reboot launch isn't faster than ~41 s to the window, delete it.
- Covering launchers behind Couch (`121f64e`, `1873803`) and the steadier Starting screen (`02d4513`) with "Last time it took about N seconds" (`9841626`): unit-tested and checked in a test copy, not yet watched on the TV from start to finish.
- The saved "took" for GTA (40 s) came from the Claude-window bug; the next real launch overwrites it.
- Epic's own start-at-login hadn't started Epic within a minute of boot; Couch's start-Epic-first path covered it (4 s).

## Comments
