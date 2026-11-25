# PC sleeps after 1 hour idle, so the phone remote isn't 24/7

Status: wontfix

`couch-setup.ps1` set Windows to sleep after 60 idle minutes (still set: 3600 s). While asleep the server is asleep too, and a phone can't wake the PC.

Claude doesn't change Windows system settings, so this one is yours. In an admin PowerShell:

```powershell
powercfg /change standby-timeout-ac 0
```

(`0` = never; or e.g. `180` for 3 hours.) You can still sleep it from the launcher (Camp → Sleep) or the phone.

## Comments

## Comments

2026-11-25: closed at the user's request ("Forget 01"). The PC keeps sleeping after an hour.
