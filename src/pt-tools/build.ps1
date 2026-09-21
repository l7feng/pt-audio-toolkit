# build.ps1 —— pt-tools GUI 打包脚本（PyInstaller, --windowed --onedir）
#
# 用法：PowerShell 里执行  .\build.ps1
# 产物：dist\pt-tools\pt-tools.exe
#
# 结构（v2，2026-09-21 起）：
#   dist\pt-tools\
#   ├─ pt-tools.exe              GUI 壳（tkinter，可独立启动）
#   └─ _internal\
#       └─ skills\               脚本已内置（pt-scanner/pt-exporter/pt-cleaner）
#           ├─ pt-scanner\scripts\pt_scan.py
#           ├─ pt-exporter\scripts\*.py
#           └─ pt-cleaner\scripts\pt_clean.py
#
# 仍依赖（v2 边界，v3 计划自包含）：
#   protools-skills\pt-exporter\env\venv\Scripts\python.exe —— 运行脚本的解释器。
#   exe 启动时自动探测：exe 相对(_internal\skills) -> 环境变量
#   PTOOLS_SKILLS_ROOT -> 默认 D:\Ai-Files\Agent-Preset\Skills\protools-skills。
#   GUI 内已无「技能目录」常驻控件；找不到时经 设置 > 技能目录 指定一次。
#
# 壳不动芯：Pro Tools 交互逻辑永远只在技能脚本里维护，GUI 只拼 CLI。

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$gui = Join-Path $here "pt_tools_gui.py"
$skillsSrc = "D:\Ai-Files\Agent-Preset\Skills\protools-skills"

if (-not (Test-Path -LiteralPath $gui)) {
    Write-Host "[error] 找不到 $gui" -ForegroundColor Red
    exit 1
}

# 1) 找一个 pyinstaller（优先系统 python 的，其次 pipx）
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "[error] 未找到 python，请先安装 Python 3.8+" -ForegroundColor Red
    exit 1
}

python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[info] 未检测到 PyInstaller，正在安装……"
    python -m pip install --quiet pyinstaller
}

# 2) 构建（--onedir 而非 --onefile：启动快、杀软误报低、好排查）
Write-Host "[build] 开始构建 pt-tools……"
Push-Location (Split-Path -Parent $here)
try {
    python -m PyInstaller --noconfirm --clean `
        --windowed `
        --onedir `
        --name "pt-tools" `
        --distpath (Join-Path $here "dist") `
        --workpath (Join-Path $here "build") `
        --specpath (Join-Path $here "build") `
        $gui
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[error] PyInstaller 构建失败" -ForegroundColor Red
        exit 1
    }
}
finally {
    Pop-Location
}

# 3) 把技能脚本内置到 dist\_internal\skills\（exe 相对自身定位，减少外部漂移）
$skillsDst = Join-Path $here "dist\pt-tools\_internal\skills"
foreach ($sk in @("pt-scanner", "pt-exporter", "pt-cleaner")) {
    $dstDir = Join-Path $skillsDst $sk
    New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
    $srcPat = Join-Path $skillsSrc "$sk\scripts\*.py"
    if (Test-Path -LiteralPath (Split-Path -Parent $srcPat)) {
        Copy-Item -Path $srcPat -Destination $dstDir -Force
    }
}
# pt-exporter 额外脚本（batch 编排 / 媒体就位）随技能目录一起复制
Write-Host "[build] 脚本已内置到 $skillsDst"

$exe = Join-Path $here "dist\pt-tools\pt-tools.exe"
Write-Host ""
Write-Host "[ok] 构建完成：$exe" -ForegroundColor Green
Write-Host "[提示] 分发 = dist\pt-tools\ 整个目录"
Write-Host "[提示] 运行仍需技能目录 venv（python 解释器），缺失时经 设置>技能目录 指定"

# 4) 清理临时产物
Remove-Item -Recurse -Force (Join-Path $here "build") -ErrorAction SilentlyContinue