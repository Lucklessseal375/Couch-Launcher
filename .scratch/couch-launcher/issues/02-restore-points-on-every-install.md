# Windows makes a restore point on every install

Status: resolved

`couch-setup.ps1` turned off Windows' "one restore point per day" limit so it could make its own, and never turned it back on. Every driver/game/app install now creates a restore point, using disk space on C:.

In an admin PowerShell:

```powershell
Remove-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore' SystemRestorePointCreationFrequency
```

## Comments

2026-11-25: done at the user's request ("Do 2"): the SystemRestorePointCreationFrequency override (0) was removed with an admin prompt, so Windows is back to its default of one restore point per day.
