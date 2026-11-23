#Requires -RunAsAdministrator
<#
  MAIN PC ONLY: old one-off Windows tuning from before Couch (restore point, startup apps, auto sign-in).
  To set up Couch on another PC, use install-couch.ps1 instead (see README.md).
  Couch gaming setup for this PC (Steam Big Picture + Epic via BoilR, PS5 controller).
  Run ONCE from an *administrator* PowerShell:
      powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\Documents\CouchSetup\couch-setup.ps1"
  Then reboot. To undo everything: Start > "Create a restore point" > System Restore >
  pick "Before couch setup".
  A full log is written next to this script (couch-setup.log).
#>

# ============================ SETTINGS =====================================
# Set to $false if Corsair iCUE controls your liquid cooler pump / fan curves.
$DisableICUEStartup      = $false   # iCUE controls the liquid cooler - keep it at startup
$DisableSteelSeriesStartup = $true
$RemoveNvidiaApp         = $false   # keep the NVIDIA App installed
$SetupAutologon          = $false   # auto sign-in already works
# ===========================================================================

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Start-Transcript -Path (Join-Path $here 'couch-setup.log') -Append | Out-Null

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Set-Reg($path, $name, $value, $type = 'DWord') {
    if (-not (Test-Path $path)) { New-Item -Path $path -Force | Out-Null }
    New-ItemProperty -Path $path -Name $name -Value $value -PropertyType $type -Force | Out-Null
    Write-Host "  set $path\$name = $value"
}

# --------------------------------------------------------------------------
Step '1. System Restore point'
# --------------------------------------------------------------------------
try {
    Enable-ComputerRestore -Drive "$env:SystemDrive\" -ErrorAction Stop
    # Windows normally refuses more than one restore point per 24h; lift that for this run.
    Set-Reg 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore' 'SystemRestorePointCreationFrequency' 0
    Checkpoint-Computer -Description 'Before couch setup' -RestorePointType MODIFY_SETTINGS -ErrorAction Stop
    Write-Host '  Restore point created.' -ForegroundColor Green
} catch {
    Write-Warning "Could not create a restore point: $($_.Exception.Message)"
    if ((Read-Host 'Continue WITHOUT a restore point? (y/N)') -ne 'y') { Stop-Transcript; exit 1 }
}

# --------------------------------------------------------------------------
Step '2. Remove NVIDIA App (driver and Control Panel stay)'
# --------------------------------------------------------------------------
$uninstallKeys = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
                 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
$nvApp = Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue |
         Where-Object { $_.DisplayName -like 'NVIDIA App*' } | Select-Object -First 1
if (-not $RemoveNvidiaApp) {
    Write-Host '  Skipped: keeping NVIDIA App.'
} elseif ($nvApp -and $nvApp.UninstallString) {
    Write-Host "  Launching uninstaller for $($nvApp.DisplayName) - follow its prompts."
    # /s + outer quotes: cmd strips only the outer pair, so the uninstall string's own quotes survive.
    Start-Process -FilePath 'cmd.exe' -ArgumentList "/s /c `"$($nvApp.UninstallString)`"" -Wait
} else { Write-Host '  NVIDIA App not found (already removed).' }

# --------------------------------------------------------------------------
Step '3. Startup apps'
# --------------------------------------------------------------------------
# Disables a startup entry the same way Task Manager does (StartupApproved, byte 0 = 0x03).
function Disable-StartupEntry($pattern) {
    $disabled = [byte[]](3,0,0,0,0,0,0,0,0,0,0,0)
    $runs = @(
        @{ Run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run';             Approved = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run' },
        @{ Run = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run';             Approved = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run' },
        @{ Run = 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'; Approved = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32' }
    )
    $found = $false
    foreach ($r in $runs) {
        if (-not (Test-Path $r.Run)) { continue }
        $props = Get-ItemProperty $r.Run
        foreach ($p in $props.PSObject.Properties) {
            if ($p.Name -like 'PS*') { continue }
            if ($p.Name -match $pattern -or "$($p.Value)" -match $pattern) {
                Set-Reg $r.Approved $p.Name $disabled 'Binary'; $found = $true
            }
        }
    }
    $folders = @(
        @{ Dir = [Environment]::GetFolderPath('Startup');       Approved = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder' },
        @{ Dir = [Environment]::GetFolderPath('CommonStartup'); Approved = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder' }
    )
    foreach ($f in $folders) {
        Get-ChildItem $f.Dir -ErrorAction SilentlyContinue | Where-Object Name -match $pattern | ForEach-Object {
            Set-Reg $f.Approved $_.Name $disabled 'Binary'; $found = $true
        }
    }
    if (-not $found) { Write-Host "  No startup entry matched '$pattern'." }
}
if ($DisableSteelSeriesStartup) { Disable-StartupEntry 'SteelSeries' }
Disable-StartupEntry 'Radmin'   # Radmin VPN: open it from the Start menu when you need it
if ($DisableICUEStartup)        { Disable-StartupEntry 'iCUE|Corsair' } else { Write-Host '  Keeping iCUE at startup (cooler control).' }

# Epic: start silently in the tray at login so it never pops over Big Picture.
$epic = "${env:ProgramFiles(x86)}\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"
if (Test-Path $epic) {
    Set-Reg 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' 'EpicGamesLauncher' "`"$epic`" -silent" 'String'
}

# --------------------------------------------------------------------------
Step '4. Remove Store apps'
# --------------------------------------------------------------------------
$remove = @(
    'Microsoft.MixedReality.Portal','Microsoft.People','Microsoft.WindowsMaps',
    'Microsoft.BingNews','Microsoft.BingWeather','Microsoft.BingSearch',
    'Microsoft.MicrosoftSolitaireCollection','Microsoft.McLarenSennaTrackDay',
    'Microsoft.WindowsFeedbackHub','Microsoft.GetHelp','Microsoft.Todos',
    'Microsoft.PowerAutomateDesktop','Microsoft.Windows.DevHome',
    'MicrosoftWindows.Client.WebExperience',           # Widgets
    'Microsoft.YourPhone','MicrosoftWindows.CrossDevice', # Phone Link
    'Microsoft.XboxApp','Microsoft.GamingApp',          # Xbox app
    'Microsoft.XboxGamingOverlay','Microsoft.XboxGameOverlay','Microsoft.XboxSpeechToTextOverlay', # Game Bar
    'Microsoft.StartExperiencesApp',
    'Microsoft.Copilot','Microsoft.Windows.Ai.Copilot.Provider',
    '4DF9E0F8.Netflix','Disney.37853FC22B2CE','AmazonVideo.PrimeVideo','2BDFC20A.CBS'
)
foreach ($name in $remove) {
    $pkgs = Get-AppxPackage -AllUsers -Name $name -ErrorAction SilentlyContinue
    foreach ($pkg in $pkgs) {
        try { Remove-AppxPackage -Package $pkg.PackageFullName -AllUsers -ErrorAction Stop; Write-Host "  removed $name" }
        catch { Write-Warning "  could not remove ${name}: $($_.Exception.Message)" }
    }
    Get-AppxProvisionedPackage -Online | Where-Object DisplayName -eq $name | ForEach-Object {
        Remove-AppxProvisionedPackage -Online -PackageName $_.PackageName -ErrorAction SilentlyContinue | Out-Null
    }
}

# --------------------------------------------------------------------------
Step '5. Telemetry, widgets, Copilot, ads, suggestions'
# --------------------------------------------------------------------------
Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection' 'AllowTelemetry' 0   # Enterprise honours 0
Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Dsh' 'AllowNewsAndInterests' 0               # Widgets
Set-Reg 'HKCU:\Software\Policies\Microsoft\Windows\WindowsCopilot' 'TurnOffWindowsCopilot' 1
Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsCopilot' 'TurnOffWindowsCopilot' 1
Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\CloudContent' 'DisableWindowsConsumerFeatures' 1
Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\CloudContent' 'DisableSoftLanding' 1
Set-Reg 'HKCU:\Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo' 'Enabled' 0
$cdm = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'
foreach ($v in 'SilentInstalledAppsEnabled','SystemPaneSuggestionsEnabled','SoftLandingEnabled',
               'SubscribedContent-338388Enabled','SubscribedContent-338389Enabled',
               'SubscribedContent-353694Enabled','SubscribedContent-353696Enabled',
               'SubscribedContent-310093Enabled','RotatingLockScreenOverlayEnabled') { Set-Reg $cdm $v 0 }
Set-Reg 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced' 'TaskbarDa' 0   # widgets button

# --------------------------------------------------------------------------
Step '6. Gaming: Game Bar off, Game Mode on, GPU scheduling on'
# --------------------------------------------------------------------------
Set-Reg 'HKCU:\System\GameConfigStore' 'GameDVR_Enabled' 0
Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\GameDVR' 'AllowGameDVR' 0
Set-Reg 'HKCU:\Software\Microsoft\Windows\CurrentVersion\GameDVR' 'AppCaptureEnabled' 0
Set-Reg 'HKCU:\Software\Microsoft\GameBar' 'UseNexusForGameBarEnabled' 0   # controller button won't open Game Bar
Set-Reg 'HKCU:\Software\Microsoft\GameBar' 'AutoGameModeEnabled' 1
Set-Reg 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers' 'HwSchMode' 2

# --------------------------------------------------------------------------
Step '7. Quiet Windows: notifications off, updates overnight only'
# --------------------------------------------------------------------------
Set-Reg 'HKCU:\Software\Microsoft\Windows\CurrentVersion\PushNotifications' 'ToastEnabled' 0
$wu = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate'
Set-Reg "$wu\AU" 'NoAutoUpdate' 0
Set-Reg "$wu\AU" 'AUOptions' 4                    # auto download + scheduled install
Set-Reg "$wu\AU" 'ScheduledInstallDay' 0          # every day
Set-Reg "$wu\AU" 'ScheduledInstallTime' 3         # 3 am
Set-Reg "$wu\AU" 'NoAutoRebootWithLoggedOnUsers' 1
Set-Reg "$wu\AU" 'AUPowerManagement' 0            # don't wake the PC from sleep for updates
Set-Reg $wu 'SetActiveHours' 1
Set-Reg $wu 'ActiveHoursStart' 6                  # 6 am ...
Set-Reg $wu 'ActiveHoursEnd' 0                    # ... to midnight = no restarts in that window

# --------------------------------------------------------------------------
Step '8. Power: High performance, power button sleeps, no night wakes, no lock screen on wake'
# --------------------------------------------------------------------------
powercfg /setactive SCHEME_MIN                                  # High performance
powercfg /change monitor-timeout-ac 30
powercfg /change standby-timeout-ac 60                          # idle safety net
# USB selective suspend off (keeps Bluetooth controller connection stable)
powercfg /setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
# Don't require sign-in when waking from sleep
powercfg /setacvalueindex SCHEME_CURRENT SUB_NONE CONSOLELOCK 0
# Power button = Sleep: one press sleeps, the next press wakes (was: shut down)
powercfg /setacvalueindex SCHEME_CURRENT 4f971e89-eebd-4455-a8de-9e59040e7347 7648efa3-dd9c-4e3e-b566-50f929386280 1
# Wake timers off: scheduled tasks can't wake the PC in the night
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 0
powercfg /setactive SCHEME_CURRENT
Set-Reg 'HKCU:\Control Panel\Desktop' 'ScreenSaveActive' '0' 'String'
Set-Reg 'HKCU:\Control Panel\Desktop' 'ScreenSaverIsSecure' '0' 'String'

# --------------------------------------------------------------------------
Step '9. Background cleanup: AMD usage uploader, D3DGear, OneDrive at sign-in'
# --------------------------------------------------------------------------
# AMD User Experience Program (usage-data uploader): service + sign-in task
$auep = Get-Service -Name 'AUEPLauncher' -ErrorAction SilentlyContinue
if ($auep) {
    Stop-Service -Name 'AUEPLauncher' -Force -ErrorAction SilentlyContinue
    Set-Service  -Name 'AUEPLauncher' -StartupType Disabled
    Write-Host '  AMD User Experience Program service disabled.'
} else { Write-Host '  AMD User Experience Program service not found.' }
# Scheduled tasks that start things at sign-in (disabled, not deleted - easy to turn back on)
foreach ($taskName in 'StartAUEP', 'D3DGearRawFrameCaptureTask', 'OneDrive Startup Task*') {
    $tasks = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $tasks) { Write-Host "  Task '$taskName' not found."; continue }
    foreach ($t in $tasks) {
        $t | Disable-ScheduledTask -ErrorAction Continue | Out-Null
        Write-Host "  Disabled task $($t.TaskPath)$($t.TaskName)"
    }
}

# --------------------------------------------------------------------------
Step '10. Auto sign-in (Sysinternals Autologon - stores password encrypted)'
# --------------------------------------------------------------------------
if (-not $SetupAutologon) {
    Write-Host '  Skipped: auto sign-in already works.'
} else {
# Lets password sign-in be used even if Windows Hello / PIN is set up.
Set-Reg 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device' 'DevicePasswordLessBuildVersion' 0
winget install --id Microsoft.Sysinternals.Autologon -e --accept-source-agreements --accept-package-agreements
# winget adds its Links folder to PATH, but this already-running window doesn't see the new PATH.
$wingetLinks = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'
$autologon = @(
    (Join-Path $wingetLinks 'Autologon64.exe'), (Join-Path $wingetLinks 'Autologon.exe')
    (Get-Command Autologon64.exe, Autologon.exe -ErrorAction SilentlyContinue).Source
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $autologon) {
    $autologon = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') -Recurse -Include 'Autologon64.exe','Autologon.exe' -ErrorAction SilentlyContinue |
                 Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if ($autologon) {
    Write-Host '  Opening Autologon: enter your Windows password and click Enable.' -ForegroundColor Yellow
    Start-Process $autologon -Wait
} else {
    Write-Warning '  Autologon not found on PATH. Open a new terminal and run: Autologon64  (or see CHECKLIST.md)'
}
}

Step 'Done. Reboot now, then work through CHECKLIST.md.'
Stop-Transcript | Out-Null
