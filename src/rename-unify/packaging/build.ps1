# build.ps1 -- rename-unify packaging script (PyInstaller, --windowed --onedir)
#
# Usage: run  .\build.ps1  in PowerShell
# Output: <project root>\rename-unify.exe   (flat, house convention)
#
# Layout after build (project root, no dist\ layer):
#   rename-unify\
#     rename-unify.exe
#     _internal\
#     README.md
#     code\                (source, kept)
#     packaging\           (this script, kept)
#     config.json          (optional, seeded from defaults on first run)
#
# NOTE: this file must stay PURE ASCII. PowerShell 5.1 reads .ps1 as ANSI/GBK;
# non-ASCII in the script body corrupts output and can turn '<' inside a string
# into a redirection operator, breaking parsing.

$ErrorActionPreference = "Stop"

$here      = Split-Path -Parent $MyInvocation.MyCommand.Path
$projRoot  = Split-Path -Parent $here
$codeDir   = Join-Path $projRoot "code"
$entry     = Join-Path $codeDir "main.py"
# Build into a scratch dir, then flatten into the project root.
# Reason: when --distpath already holds a <name>.exe from a previous install,
# PyInstaller nests the new output under <distpath>\<name>\ and the old exe
# silently stays put (looks like "nothing was rebuilt").
$staging   = Join-Path $env:TEMP "rename-unify-staging"
$distDir   = $staging
$buildDir  = Join-Path $env:TEMP "rename-unify-build"
$specDir   = Join-Path $env:TEMP "rename-unify-spec"

Write-Host "[info] project root: $projRoot"

if (-not (Test-Path -LiteralPath $entry)) {
    Write-Host "[error] entry script not found: $entry" -ForegroundColor Red
    exit 1
}

# 1) locate python + PyInstaller
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "[error] python not found on PATH" -ForegroundColor Red
    exit 1
}

python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[info] PyInstaller missing, installing ..."
    python -m pip install --quiet pyinstaller
}

# 2) build (onedir: fast start, fewer AV false positives, easy to inspect)
#
# IMPORTANT: PyInstaller writes its progress ("NNN INFO: ...") to STDERR.
# This script runs with $ErrorActionPreference="Stop", and Windows PowerShell
# turns native-command stderr into NativeCommandError -> the build aborts
# right after "[build] building ..." even though PyInstaller is fine.
# So: relax to Continue for this call and judge by $LASTEXITCODE only.
Write-Host "[build] building rename-unify ..."
$ErrorActionPreference = "Continue"
& python -m PyInstaller --noconfirm --clean `
    --windowed `
    --onedir `
    --name "rename-unify" `
    --paths $codeDir `
    --distpath $distDir `
    --workpath $buildDir `
    --specpath $specDir `
    $entry 2>&1 | ForEach-Object { "$_" }
$buildExit = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($buildExit -ne 0) {
    Write-Host "[error] PyInstaller build failed (exit $buildExit)" -ForegroundColor Red
    exit 1
}

# PyInstaller always nests onedir output one level: <distpath>\<name>\
$builtDir = Join-Path $distDir "rename-unify"
$outExe   = Join-Path $builtDir "rename-unify.exe"
$outInt   = Join-Path $builtDir "_internal"
if (-not (Test-Path -LiteralPath $outExe)) {
    Write-Host "[error] exe not found after build: $outExe" -ForegroundColor Red
    exit 1
}

# 3) install: archive the previous build, then flatten the new one into root
$rootExe = Join-Path $projRoot "rename-unify.exe"
$rootInt = Join-Path $projRoot "_internal"

if (Test-Path -LiteralPath $rootExe) {
    # History folder name is the CJK "_history" used across Agent-Out-exe.
    # This file must stay PURE ASCII, so build those chars from code points.
    $histName = "_" + [char]0x5386 + [char]0x53F2
    $histRoot = Join-Path (Split-Path -Parent $projRoot) $histName
    $histDir  = Join-Path $histRoot ("rename-unify_prev_" + (Get-Date -Format "yyyyMMdd_HHmm"))
    New-Item -ItemType Directory -Path $histDir -Force | Out-Null
    Move-Item -LiteralPath $rootExe -Destination (Join-Path $histDir "rename-unify.exe") -Force
    if (Test-Path -LiteralPath $rootInt) {
        Move-Item -LiteralPath $rootInt -Destination (Join-Path $histDir "_internal") -Force
    }
    Write-Host "[info] previous build archived to: $histDir"
}

Move-Item -LiteralPath $outExe -Destination $rootExe -Force
Move-Item -LiteralPath $outInt -Destination $rootInt -Force

# README lives in the project root already; nothing to copy.

Write-Host ""
Write-Host "[ok] build complete: $rootExe" -ForegroundColor Green
Write-Host "[note] distribute the whole folder: rename-unify\"
Write-Host "[note] first run writes config.json next to the exe"

# 4) clean temp artifacts
Remove-Item -Recurse -Force $buildDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $specDir  -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $staging   -ErrorAction SilentlyContinue
