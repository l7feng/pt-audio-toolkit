# Jianying toolkit - one-click build script (ASCII only, PS 5.1 safe)
#
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
# Output: packaging\dist\daorugongju\
#           daorugongju.exe + _internal\ + tools\jy-draftc\
#
# Notes:
#   * onedir (NOT onefile): tools\ must be a real directory next to the exe,
#     because jy-draftc writes the JianYing install path into .env at runtime.
#     A onefile build would unpack to a temp dir that gets wiped.
#   * Requires a Python with tkinter (the official Windows installer has it).
#   * py-ptsl is OPTIONAL: with it, "parse .ptx" works; without it, the tool
#     still imports delivery-package JSON fully offline. We deliberately do NOT
#     bundle py-ptsl - the editor's machine does not need it.
#   * This file is kept ASCII-only on purpose: PS 5.1 reads .ps1 as ANSI/GBK,
#     so non-ASCII Chinese text here would be garbled or break parsing.

param(
    [string]$Python = "",
    [string]$AppName = "jianying-draft-toolkit",
    [string]$ExeLabel = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Pack = Join-Path $Root "packaging"

if (-not $ExeLabel) { $ExeLabel = $AppName }

# -- Pick a Python: explicit param, then official 3.12, then PATH python --
if (-not $Python) {
    $sys312 = "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\python.exe"
    if (Test-Path $sys312) { $Python = $sys312 }
    else { $Python = (Get-Command python).Source }
}
Write-Host "==> Python: $Python"
& $Python -c "import tkinter, PyInstaller" 2>$null
if (-not $?) {
    throw "This Python lacks tkinter or PyInstaller. Install official Python 3.12 and run: pip install pyinstaller tkinterdnd2"
}

Write-Host "==> 1/4 Clean old artifacts"
$distDir = Join-Path $Pack "dist"
$buildDir = Join-Path $Pack "build"
if (Test-Path $distDir) { Remove-Item -Recurse -Force $distDir }
if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }

Write-Host "==> 2/4 PyInstaller build (onedir + windowed)"
$pyArgs = @(
    "-m", "PyInstaller",
    "--name", $AppName,
    "--windowed",
    "--onedir",
    "--clean",
    "--noconfirm",
    "--hidden-import", "tkinterdnd2",
    "--collect-data", "tkinterdnd2",
    "--distpath", $distDir,
    "--workpath", $buildDir,
    "--specpath", $Pack,
    (Join-Path $Root "code\gui.py")
)
& $Python @pyArgs
if (-not $?) { throw "PyInstaller build failed" }

Write-Host "==> 3/4 Copy tools\ (jy-draftc decryptor)"
$appDir = Join-Path $distDir $AppName
$toolDest = Join-Path $appDir "tools"
Copy-Item -Recurse -Force (Join-Path $Root "tools") $toolDest

Write-Host "==> 4/4 Verify artifacts"
$exe = Join-Path $appDir "$AppName.exe"
$dc = Join-Path $appDir "tools\jy-draftc\jy-draftc-amd64-windows\jy-draftc.exe"
foreach ($f in @($exe, $dc)) {
    if (Test-Path $f) { Write-Host "    [OK] $f" }
    else { Write-Host "    [MISSING] $f" }
}

$sum = (Get-ChildItem -Recurse $appDir | Measure-Object -Property Length -Sum).Sum / 1MB

Write-Host ""
Write-Host "Done: $appDir   (about $([math]::Round($sum,1)) MB)"
Write-Host "    $AppName.exe        -- double-click to run the GUI (3 tabs)"
Write-Host "    tools\jy-draftc\    -- decryptor (.env written on first run)"
Write-Host ""
Write-Host "IMPORTANT: move the whole folder together (_internal\ and tools\ sit next to the exe)."
Write-Host "NOTE: py-ptsl is not bundled, so 'parse .ptx' is unavailable in the exe;"
Write-Host "      offline JSON import still works."
