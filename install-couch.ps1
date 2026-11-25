<#
  Set up Couch on this PC. Run it from the folder you downloaded Couch into, as your normal user (not admin):
      powershell -ExecutionPolicy Bypass -File .\install-couch.ps1

  It does only this, and is safe to run again:
    1. Installs Python 3.13 (through winget) if Python isn't there yet, pygame for the controller, and Windows'
       Bluetooth bindings (pywinrt) for pairing from the TV.
    2. Creates the "Couch Launcher" task: Couch starts full screen when you sign in to Windows.
    3. Asks for admin once, then: lets the phone remote reach this PC (one firewall rule), installs Sunshine for
       streaming to another TV with the controller driver it needs (ViGEmBus, as a PS4 controller), and adds the "Couch" app to Sunshine.
    4. Puts a "Couch" shortcut on the desktop.
  From then on Couch updates itself from GitHub (couch-remote\update.py): at sign-in, and every 6 hours while idle.
  Then it starts Couch. Left for you: Sunshine's login and pairing Moonlight (docs\streaming-setup.md).
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
        if (Get-Service SunshineService -ErrorAction SilentlyContinue) {
            Say 'Sunshine is already installed.'
        } elseif (Get-Command winget -ErrorAction SilentlyContinue) {
            winget install --id LizardByte.Sunshine --exact --scope machine --silent --accept-package-agreements --accept-source-agreements | Out-Null
            Say 'Sunshine installed.'
        } else {
            $msi = Join-Path $env:TEMP 'Sunshine-Windows-AMD64-installer.msi'
            Invoke-WebRequest -UseBasicParsing 'https://github.com/LizardByte/Sunshine/releases/latest/download/Sunshine-Windows-AMD64-installer.msi' -OutFile $msi
            Start-Process msiexec.exe -Wait -ArgumentList '/i', "`"$msi`"", '/qn'
            Say 'Sunshine installed (from its GitHub releases).'
        }
        if (-not (Get-Service SunshineService -ErrorAction SilentlyContinue)) { throw 'Sunshine did not install.' }
        $cfg = Join-Path $env:ProgramFiles 'Sunshine\config'
        New-Item -ItemType Directory -Force $cfg | Out-Null
        $appsFile = Join-Path $cfg 'apps.json'
        $j = if (Test-Path $appsFile) { Get-Content $appsFile -Raw | ConvertFrom-Json } else { [pscustomobject]@{ apps = @(@{ name = 'Desktop'; 'image-path' = 'desktop.png' }); env = @{} } }
        if (@($j.apps | Where-Object { $_.name -eq 'Couch' }).Count) {
            Say 'Sunshine already has the Couch app.'
        } else {
            $cmd = '"' + (Join-Path $repo 'couch-remote\stream.cmd') + '"'
            $j.apps = @($j.apps) + [pscustomobject]@{ name = 'Couch'; cmd = ''; 'auto-detach' = $true; 'wait-all' = $true
                'prep-cmd' = @(@{ do = "$cmd on `"Apple TV`""; undo = "$cmd off"; elevated = $false }) }
            $j | ConvertTo-Json -Depth 6 | Set-Content $appsFile -Encoding UTF8
            Say 'Added the Couch app to Sunshine.'; $restart = $true
        }
        # Without ViGEmBus, Moonlight's controller never reaches Windows ("No gamepad input is available" in Sunshine's log)
        if (Get-Service ViGEmBus -ErrorAction SilentlyContinue) {
            Say 'Controller driver for streaming (ViGEmBus) is already installed.'
        } else {
            if (Get-Command winget -ErrorAction SilentlyContinue) {
                winget install --id ViGEm.ViGEmBus --exact --silent --accept-package-agreements --accept-source-agreements | Out-Null
            } else {
                $vig = Join-Path $env:TEMP 'ViGEmBus_1.22.0_x64_x86_arm64.exe'
                Invoke-WebRequest -UseBasicParsing 'https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe' -OutFile $vig
                Start-Process $vig -Wait -ArgumentList '/exenoui', '/qn', '/norestart'
            }
            if (-not (Get-Service ViGEmBus -ErrorAction SilentlyContinue)) { throw 'The controller driver for streaming (ViGEmBus) did not install.' }
            Say 'Controller driver for streaming (ViGEmBus) installed.'; $restart = $true
        }
        # A PS4 controller: the closest ViGEmBus can make (PS5 needs Sunshine's paid driver; without this it's Xbox)
        $conf = Join-Path $cfg 'sunshine.conf'
        $lines = @(if (Test-Path $conf) { Get-Content $conf })
        if (-not ($lines -match '^\s*gamepad\s*=\s*ds4\s*$')) {
            Set-Content $conf (@($lines | Where-Object { $_ -notmatch '^\s*gamepad\s*=' }) + 'gamepad = ds4')
            Say 'Sunshine set to a PS4 controller (PlayStation buttons in games).'; $restart = $true
        }
        if ($restart) { Restart-Service SunshineService }  # never interrupts a stream when nothing changed
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
Write-Host 'Streaming to another TV, left for you: open https://localhost:47990 and create a Sunshine login, then pair Moonlight (docs\streaming-setup.md, step 3).'
