<#
  Publishes the latest commit on GitHub's main as a Couch update. Home PCs install a version only when it carries a
  signature from a key in couch-remote\update-signers (update.py), so run this after every push you want to ship:
      powershell -File couch-remote\dev\sign-release.ps1
  The private key stays on this PC (%USERPROFILE%\.ssh\couch_update). The signature goes to the "signatures" branch as
  <commit>.sig; nothing here switches branches or touches your working copy.
#>
$ErrorActionPreference = 'Stop'
$key = Join-Path $env:USERPROFILE '.ssh\couch_update'
$keygen = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh-keygen.exe'
if (-not (Test-Path $key)) { throw "No signing key at ${key}: only the PC that made it can sign updates." }
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
git fetch -q origin
$sha = (git rev-parse origin/main).Trim()
$tmp = Join-Path ([IO.Path]::GetTempPath()) "couch-sign-$sha-$(Get-Random)"  # fresh each run: ssh-keygen asks before overwriting a .sig
New-Item -ItemType Directory -Force $tmp | Out-Null
$msg = Join-Path $tmp 'msg'
[IO.File]::WriteAllText($msg, $sha)  # exactly the commit id, no newline: what update.py verifies
cmd /c "`"$keygen`" -Y sign -n couch-update -f `"$key`" `"$msg`" 2>nul"  # its progress text on stderr would stop this script
if (-not (Test-Path "$msg.sig")) { throw 'Signing failed.' }
function Invoke-Git { $out = & git.exe @args; if ($LASTEXITCODE) { throw "git $args failed" }; $out }
$blob = (Invoke-Git hash-object -w --no-filters "$msg.sig").Trim()
$parent = git rev-parse --verify -q origin/signatures
$env:GIT_INDEX_FILE = Join-Path $tmp 'index'  # a scratch index: this copy's own staging area is left alone
if ($parent) { Invoke-Git read-tree $parent }
Invoke-Git update-index --add --cacheinfo "100644,$blob,$sha.sig"
$tree = (Invoke-Git write-tree).Trim()
Remove-Item Env:GIT_INDEX_FILE
$commit = if ($parent) { Invoke-Git commit-tree $tree -p $parent -m "Sign $sha" } else { Invoke-Git commit-tree $tree -m "Sign $sha" }
Invoke-Git push -q origin "$($commit.Trim()):refs/heads/signatures"
Write-Host "Signed and published $($sha.Substring(0, 7)): home PCs install it at their next check."
