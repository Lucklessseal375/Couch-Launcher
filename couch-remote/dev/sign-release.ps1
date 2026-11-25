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
$tmp = Join-Path ([IO.Path]::GetTempPath()) "couch-sign-$sha"
New-Item -ItemType Directory -Force $tmp | Out-Null
$msg = Join-Path $tmp 'msg'
[IO.File]::WriteAllText($msg, $sha)  # exactly the commit id, no newline: what update.py verifies
& $keygen -Y sign -n couch-update -f $key $msg 2>$null | Out-Null
if (-not (Test-Path "$msg.sig")) { throw 'Signing failed.' }
$blob = (git hash-object -w "$msg.sig").Trim()
$parent = git rev-parse --verify -q origin/signatures
$entries = @(if ($parent) { git ls-tree $parent | Where-Object { $_ -notmatch "\t$sha\.sig$" } }) + "100644 blob $blob`t$sha.sig"
$tree = ($entries -join "`n") + "`n" | git mktree
$commit = if ($parent) { git commit-tree $tree -p $parent -m "Sign $sha" } else { git commit-tree $tree -m "Sign $sha" }
git push -q origin "${commit}:refs/heads/signatures"
Write-Host "Signed and published $($sha.Substring(0, 7)): home PCs install it at their next check."
