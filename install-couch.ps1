<#
  Set up Couch on this PC. Run it from the folder you downloaded Couch into, as your normal user (not admin):
      powershell -ExecutionPolicy Bypass -File .\install-couch.ps1

  It does only this, and is safe to run again:
    1. Installs Python 3.13 (through winget) if Python isn't there yet, and pygame for the controller.
    2. Creates the "Couch Launcher" task: Couch starts full screen when you sign in to Windows.
    3. Lets the phone remote reach this PC on your home network (one firewall rule; Windows asks for admin).
    4. Puts a "Couch" shortcut on the desktop.
  Then it starts Couch.
#>
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$server = Join-Path $repo 'couch-remote\server.py'
if (-not (Test-Path $server)) { throw "Can't find couch-remote\server.py next to this script ($repo)." }
function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

Step '1. Python and pygame'
$py = (Get-Command python.exe -ErrorAction SilentlyContinue | Where-Object { $_.Source -notmatch 'WindowsApps' } | Select-Object -First 1).Source
if (-not $py) {
    winget install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements
    $py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    if (-not (Test-Path $py)) { throw 'Python was installed, but python.exe was not found. Open a new PowerShell window and run this script again.' }
}
Write-Host "  Python: $py"
& $py -m pip install --user --upgrade pygame
if ($LASTEXITCODE -ne 0) { throw 'pip could not install pygame.' }

Step '2. Start Couch at sign-in (task "Couch Launcher")'
# conhost --headless: no console window; python.exe (not pythonw) so the firewall rule below matches
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\conhost.exe" -Argument "--headless `"$py`" `"$server`" --open" -WorkingDirectory (Split-Path $server)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'Couch Launcher' -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host '  Task created (replaced if it was there).'

Step '3. Phone remote: allow Python through the firewall (asks for admin)'
$rule = "Remove-NetFirewallRule -DisplayName 'Couch (phone remote)' -ErrorAction SilentlyContinue; " +
        "New-NetFirewallRule -DisplayName 'Couch (phone remote)' -Direction Inbound -Action Allow -Program '$py' -Profile Private,Public | Out-Null"
try {
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList '-NoProfile', '-Command', $rule
    Write-Host '  Firewall rule added.'
} catch {
    Write-Warning '  Skipped (admin not given). Couch works on the TV; the phone remote may not connect until you run this script again and allow it.'
}

Step '4. Desktop shortcut'
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Couch.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$s.Arguments = "-NoProfile -WindowStyle Hidden -Command Start-ScheduledTask -TaskName 'Couch Launcher'"
$icon = Join-Path $repo 'couch-remote\icon.ico'
if (Test-Path $icon) { $s.IconLocation = $icon }
$s.Save()
Write-Host "  $lnk"

Step 'Starting Couch'
Start-ScheduledTask -TaskName 'Couch Launcher'
Write-Host "`nDone. Couch opens full screen in a few seconds, and from now on whenever you sign in." -ForegroundColor Green
Write-Host 'Your games: Steam games appear by themselves. Other apps and games come from couch-remote\apps.json; tiles for programs this PC does not have are hidden.'
