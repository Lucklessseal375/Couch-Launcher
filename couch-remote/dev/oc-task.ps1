<#
  Runs one Claude Code task through opencode.ai and prints its report. Used to hand off side work (reviews, research,
  test runs) from a main Claude session. The key is read from your own OPENCODE_KEY user variable; it is never stored
  here or printed. Save it once, in PowerShell:
      [Environment]::SetEnvironmentVariable('OPENCODE_KEY', '<your key>', 'User')

  powershell -File dev\oc-task.ps1 "Review couch-remote\update.py for bugs"              (read-only: can't change files)
  powershell -File dev\oc-task.ps1 "Fix the failing test in tests\test_gate.py" -AllowEdits
#>
param([Parameter(Mandatory)][string]$Task, [string]$Model = 'claude-sonnet-5-5', [switch]$AllowEdits)
$key = [Environment]::GetEnvironmentVariable('OPENCODE_KEY', 'User')
if (-not $key) { throw "No OPENCODE_KEY yet. Save it once: [Environment]::SetEnvironmentVariable('OPENCODE_KEY', '<your key>', 'User')" }
$env:ANTHROPIC_BASE_URL = 'https://opencode.ai/inference/anthropic'
$env:ANTHROPIC_AUTH_TOKEN = $key
$tools = if ($AllowEdits) { 'Read Grep Glob Edit Write Bash' } else { 'Read Grep Glob' }
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))  # the CouchSetup folder
& claude -p $Task --model $Model --allowedTools $tools
