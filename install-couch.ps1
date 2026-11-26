<#
  Set up Couch on this PC. Run it from the folder you downloaded Couch into, as your normal user (not admin):
      powershell -ExecutionPolicy Bypass -File .\install-couch.ps1

  It does only this, and is safe to run again:
    1. Installs Python 3.13 (through winget) if Python isn't there yet, pygame for the controller, and Windows'
       Bluetooth bindings (pywinrt) for pairing from the TV.
    2. Creates the "Couch Launcher" task: Couch starts full screen when you sign in to Windows.
    3. Asks for admin once, then: lets the phone remote reach this PC (one firewall rule), installs Vibepollo (a
       Sunshine fork, with its own controller driver) for streaming to another TV, and adds the "Couch" app to it.
    4. Puts a "Couch" shortcut on the desktop.
  From then on Couch updates itself from GitHub (couch-remote\update.py): at sign-in, and every 6 hours while idle.
  Then it starts Couch. Left for you: Vibepollo's login and pairing Moonlight (docs\streaming-setup.md).
#>
param([switch]$Admin, [string]$Py)  # -Admin: the part step 3 runs elevated
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Windows PowerShell's progress bar makes downloads crawl
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$server = Join-Path $repo 'couch-remote\server.py'
if (-not (Test-Path $server)) { throw "Can't find couch-remote\server.py next to this script ($repo)." }
function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
$adminLog = Join-Path $repo 'couch-remote\install-admin.log'

if ($Admin) {
    function Say($m) { Add-Content $adminLog "  $m" }
    Set-Content $adminLog $null
    try {
        Remove-NetFirewallRule -DisplayName 'Couch (phone remote)' -ErrorAction SilentlyContinue
        New-NetFirewallRule -DisplayName 'Couch (phone remote)' -Direction Inbound -Action Allow -Program $Py -Profile Private,Public | Out-Null
        Say 'Firewall rule for the phone remote added.'
        if (Get-Service ApolloService -ErrorAction SilentlyContinue) {  # Vibepollo's service name
            Say 'Vibepollo is already installed.'
        } else {  # one pinned release, checked before it runs; it replaces Sunshine if that is there
            $setup = Join-Path $env:TEMP 'VibepolloSetup-v2.18.9.exe'
            Invoke-WebRequest -UseBasicParsing 'https://github.com/Nonary/Vibepollo/releases/download/2.18.9/VibepolloSetup-v2.18.9.exe' -OutFile $setup
            if ((Get-FileHash $setup -Algorithm SHA256).Hash -ne 'cc840f867ed4b4462f10d12a5572e8a17748e75aefd495b5af54951a81278bed') { throw 'The Vibepollo download is not the expected file; not running it.' }
            $run = Start-Process $setup -Wait -PassThru -ArgumentList '/qn', '/norestart'
            if ($run.ExitCode -notin 0, 3010) { throw "Vibepollo's installer failed (exit code $($run.ExitCode))." }
            if ($run.ExitCode -eq 3010) { Say 'Restart the PC to finish installing Vibepollo.' }
            Say 'Vibepollo installed.'
        }
        $service = Get-CimInstance Win32_Service -Filter "Name='ApolloService'"
        if (-not $service) { throw 'Vibepollo did not install.' }
        # the service runs <install folder>\tools\sunshinesvc.exe; the settings are in <install folder>\config
        $svcExe = [regex]::Match($service.PathName, '^"?(.+?\.exe)').Groups[1].Value
        $cfg = Join-Path (Split-Path -Parent (Split-Path -Parent $svcExe)) 'config'
        New-Item -ItemType Directory -Force $cfg | Out-Null
        $appsFile = Join-Path $cfg 'apps.json'
        $j = if (Test-Path $appsFile) { Get-Content $appsFile -Raw | ConvertFrom-Json } else { [pscustomobject]@{ apps = @(@{ name = 'Desktop'; 'image-path' = 'desktop.png' }); env = @{} } }
        if (@($j.apps | Where-Object { $_.name -eq 'Couch' }).Count) {
            Say 'Vibepollo already has the Couch app.'
        } else {
            $cmd = '"' + (Join-Path $repo 'couch-remote\stream.cmd') + '"'
            $j.apps = @($j.apps) + [pscustomobject]@{ name = 'Couch'; cmd = ''; 'auto-detach' = $true; 'wait-all' = $true
                'prep-cmd' = @(@{ do = "$cmd on `"Apple TV`""; undo = "$cmd off"; elevated = $false }) }
            $j | ConvertTo-Json -Depth 6 | Set-Content $appsFile -Encoding UTF8
            Say 'Added the Couch app to Vibepollo.'; $restart = $true
        }
        # Couch is a window on the TV's own screen. Vibepollo's default streams a new virtual screen: just an empty desktop
        $conf = Join-Path $cfg 'sunshine.conf'
        $lines = @(if (Test-Path $conf) { Get-Content $conf })
        if (-not ($lines -match '^\s*virtual_display_mode\s*=\s*disabled\s*$')) {
            Set-Content $conf (@($lines | Where-Object { $_ -notmatch '^\s*virtual_display_mode\s*=' }) + 'virtual_display_mode = disabled')
            Say "Vibepollo set to stream the TV's own screen."; $restart = $true
        }
        # A virtual PS5 controller from Vibepollo's own driver: PlayStation buttons in games, and the only kind that can send
        # adaptive triggers back (the Moonlight app on the other end has to support them; Apple TV's doesn't)
        $lines = @(if (Test-Path $conf) { Get-Content $conf })
        if (-not ($lines -match '^\s*gamepad\s*=\s*vhf_ds5\s*$')) {
            Set-Content $conf (@($lines | Where-Object { $_ -notmatch '^\s*gamepad\s*=' }) + 'gamepad = vhf_ds5')
            Say 'Vibepollo set to a PS5 controller.'; $restart = $true
        }
        if ($restart) { Restart-Service ApolloService }  # never interrupts a stream when nothing changed
    } catch {
        Say "FAILED: $_"
    }
    exit
}

Step '1. Python and pygame'
$py = (Get-Command python.exe -ErrorAction SilentlyContinue | Where-Object { $_.Source -notmatch 'WindowsApps' } | Select-Object -First 1).Source
if (-not $py) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements
    } else {  # a brand-new Windows may not have winget yet
        $setup = Join-Path $env:TEMP 'python-3.13.17-amd64.exe'
        Write-Host '  winget not found; downloading Python from python.org'
        Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.13.17/python-3.13.17-amd64.exe' -OutFile $setup
        Start-Process $setup -Wait -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_test=0', 'Include_launcher=0', 'Include_doc=0', 'Include_tcltk=0', 'Include_dev=0'
    }
    $py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    if (-not (Test-Path $py)) { throw 'Python was installed, but python.exe was not found. Open a new PowerShell window and run this script again.' }
}
Write-Host "  Python: $py"
& $py -m pip install --upgrade pygame winrt-runtime winrt-Windows.Devices.Enumeration winrt-Windows.Devices.Bluetooth winrt-Windows.Foundation winrt-Windows.Foundation.Collections  # controller; Bluetooth pairing from the TV
if ($LASTEXITCODE -ne 0) { throw 'pip could not install pygame.' }

Step '2. Start Couch at sign-in (task "Couch Launcher")'
# conhost --headless: no console window; python.exe (not pythonw) so the firewall rule below matches
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\conhost.exe" -Argument "--headless `"$py`" `"$server`" --open" -WorkingDirectory (Split-Path $server)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'Couch Launcher' -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host '  Task created (replaced if it was there).'

Step '3. Phone remote and streaming (asks for admin once)'
try {
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Admin', '-Py', "`"$py`""
    Get-Content $adminLog
} catch {
    Write-Warning '  Skipped (admin not given). Couch works on the TV; the phone remote and streaming need this step: run the script again and allow it.'
}

Step '4. Desktop shortcut'
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Couch.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
# same command as the task: starts Couch, or brings it to the front if it's already running; no terminal window
$s.TargetPath = "$env:SystemRoot\System32\conhost.exe"
$s.Arguments = "--headless `"$py`" `"$server`" --open"
$s.WorkingDirectory = Split-Path $server
$icon = Join-Path $repo 'couch-remote\icon.ico'
if (Test-Path $icon) { $s.IconLocation = $icon }
$s.Save()
Write-Host "  $lnk"

Remove-Item (Join-Path $repo 'couch-remote\cache\installer-changed') -ErrorAction SilentlyContinue  # an update asked for this run
Step 'Starting Couch'
Start-ScheduledTask -TaskName 'Couch Launcher'
Write-Host "`nDone. Couch opens full screen in a few seconds, and from now on whenever you sign in." -ForegroundColor Green
Write-Host 'Your games: Steam games appear by themselves. Other apps and games come from couch-remote\apps.json; tiles for programs this PC does not have are hidden.'
Write-Host 'Streaming to another TV, left for you: open https://localhost:47990 and create a Vibepollo login, then pair Moonlight (docs\streaming-setup.md, step 3).'
