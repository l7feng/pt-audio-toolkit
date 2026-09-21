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
$distDir   = $projRoot
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
Write-Host "[build] building rename-unify ..."
& python -m PyInstaller --noconfirm --clean `
    --windowed `
    --onedir `
    --name "rename-unify" `
    --paths $codeDir `
    --distpath $distDir `
    --workpath $buildDir `
    --specpath $specDir `
    $entry

if ($LASTEXITCODE -ne 0) {
    Write-Host "[error] PyInstaller build failed" -ForegroundColor Red
    exit 1
}

$outExe = Join-Path $distDir "rename-unify.exe"
if (-not (Test-Path -LiteralPath $outExe)) {
    Write-Host "[error] exe not found after build: $outExe" -ForegroundColor Red
    exit 1
}

# 3) ship the reader-facing doc next to the exe
$readmeSrc = Join-Path $projRoot "README.md"
$readmeDst = Join-Path $distDir "README.md"
if (Test-Path -LiteralPath $readmeSrc) {
    Copy-Item -LiteralPath $readmeSrc -Destination $readmeDst -Force
}

Write-Host ""
Write-Host "[ok] build complete: $outExe" -ForegroundColor Green
Write-Host "[note] distribute the whole folder: rename-unify\"
Write-Host "[note] first run writes config.json next to the exe"

# 4) clean temp artifacts
Remove-Item -Recurse -Force $buildDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $specDir  -ErrorAction SilentlyContinue
