# pt-tools build entry (thin wrapper around tools/build.py).
#
# Real build logic: <repo>\tools\build.py
# Why not run PyInstaller directly from PowerShell: it writes progress to STDERR,
# and with $ErrorActionPreference="Stop" Windows PowerShell turns native stderr
# into NativeCommandError, aborting the build right after the first "INFO:" line
# (looks like "nothing was built"). See tools/build.py for details.
#
# NOTE: keep this file PURE ASCII. PowerShell 5.1 reads .ps1 as ANSI/GBK and
# non-ASCII bytes can corrupt parsing.
#
# Behavior note (2026-09-23): output now goes to the unified exe root
# (<out-root>\pt-audio-toolkit-v<version>-<date>\pt-tools\) instead of a local
# dist\. Pass --out-root to override, or use tools/build.py directly.
$ErrorActionPreference = "Stop"

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = $dir
while ($repo -and -not (Test-Path (Join-Path $repo "tools\build.py"))) {
    $parent = Split-Path -Parent $repo
    if (-not $parent -or $parent -eq $repo) { break }
    $repo = $parent
}
$builder = Join-Path $repo "tools\build.py"
if (-not (Test-Path -LiteralPath $builder)) {
    Write-Host "[error] tools\build.py not found (searched upward from $dir)" -ForegroundColor Red
    exit 1
}

Write-Host "[info] delegating to $builder"
python $builder pt-tools @args
exit $LASTEXITCODE
