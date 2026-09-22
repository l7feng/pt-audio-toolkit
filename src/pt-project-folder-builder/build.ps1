$ErrorActionPreference = "Stop"

$AppName   = "PT工程文件夹生成器"
$Script    = "folder_builder_gui.py"
$DistName  = "pt-project-folder-builder"
$ToolDir   = $PSScriptRoot
$PySys     = "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\python.exe"
if (Test-Path -LiteralPath $PySys) { $Py = $PySys } else { $Py = (Get-Command python).Source }
$ScriptAbs = Join-Path $ToolDir $Script

Write-Host "Building $AppName (PyInstaller windowed onedir) ..."

& $Py -m PyInstaller --noconfirm --windowed --onedir `
    --name $DistName `
    --distpath (Join-Path $ToolDir "dist") `
    --workpath (Join-Path $ToolDir "build") `
    $ScriptAbs 2>&1 | Tee-Object -FilePath (Join-Path $ToolDir "build.log")

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed (exit $LASTEXITCODE). See build.log"
    exit 1
}

$Exe = Join-Path $ToolDir "dist\$DistName\$DistName.exe"
if (Test-Path $Exe) {
    Write-Host "Done -> $Exe"
} else {
    Write-Error "EXE not found after build: $Exe"
    exit 1
}
