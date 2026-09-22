<#
.ARCHIVED
    2026-09-21 归档于此（原 D:\My-Temporary\FinalMix按集归位.ps1）。

    本脚本的能力已移植为纯 Python 并**并入 rename-unify 主流程**：
      · 引擎 code/core_rules.py: build_regroup_plan() / apply_regroup()
      · 界面 「3 · 预览与执行」页 →「按集归位」选项组
    日常请直接用 exe，不要再单独跑本脚本；保留它是为了行为对照与回溯。
    详见同目录 README.md。

.SYNOPSIS
    FinalMix 按集归位脚本：把 MIX / BUS / Stem 三个平铺类别文件夹里的文件，
    重组为「每集一个文件夹」结构。

    目标结构：
    FinalMix/
    ├── 前夫 01集 0920 V01/
    │   ├── 前夫 01集 0920 V01 7F_MIX.wav          (MIX / MIX-MASTER 放集根目录)
    │   ├── BUS/
    │   │   ├── 前夫 01集 0920 V01 7F_BUS-DX.wav
    │   │   └── ...
    │   └── STEM/
    │       └── ...                                 (哪集有 stem 就放哪集)

    安全规则：只移动，绝不覆盖；解析不了的文件跳过并报告；最后清理搬空的类别文件夹。

.EXAMPLE
    # 默认处理「前夫D」项目
    .\FinalMix按集归位.ps1

    # 其他剧复用（文件名需含相同分隔标记）
    .\FinalMix按集归位.ps1 -Root 'D:\DAW-Project\XX-某剧_日期_规格\FinalMix'
#>
param(
    [string]$Root = 'D:\DAW-Project\11-前夫D_20260920_7F\FinalMix',
    [string]$SplitMark = ' 7F_'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Root)) {
    Write-Host "[错误] 目录不存在：$Root" -ForegroundColor Red
    exit 1
}

$moved = 0
$skipped = 0

foreach ($cat in @('MIX', 'BUS', 'Stem')) {
    $catDir = Join-Path $Root $cat
    if (-not (Test-Path -LiteralPath $catDir)) { continue }

    Get-ChildItem -LiteralPath $catDir -File | ForEach-Object {
        $name = $_.BaseName
        $idx = $name.IndexOf($SplitMark)
        if ($idx -lt 1) {
            Write-Host ("[跳过·无法解析集前缀] {0}\{1}" -f $cat, $_.Name) -ForegroundColor Yellow
            $script:skipped++
            return
        }
        $epPrefix = $name.Substring(0, $idx)
        $type = $name.Substring($idx + $SplitMark.Length)   # MIX / MIX-MASTER / BUS-DX / STEM-DX-01 ...

        if ($type -like 'BUS-*')      { $sub = 'BUS' }
        elseif ($type -like 'STEM-*') { $sub = 'STEM' }
        else                          { $sub = '' }         # MIX / MIX-MASTER 放集根目录

        $epDir  = Join-Path $Root $epPrefix
        $target = if ($sub) { Join-Path $epDir $sub } else { $epDir }

        if (-not (Test-Path -LiteralPath $target)) {
            New-Item -ItemType Directory -Path $target -Force | Out-Null
        }

        $dest = Join-Path $target $_.Name
        if (Test-Path -LiteralPath $dest) {
            Write-Host ("[跳过·目标已存在] {0}" -f $dest) -ForegroundColor Yellow
            $script:skipped++
            return
        }

        Move-Item -LiteralPath $_.FullName -Destination $dest
        $rel = if ($sub) { "$epPrefix\$sub" } else { $epPrefix }
        Write-Host ("[移动] {0}\{1} -> {2}\" -f $cat, $_.Name, $rel)
        $script:moved++
    }
}

# 清理搬空后的类别文件夹
foreach ($cat in @('MIX', 'BUS', 'Stem')) {
    $catDir = Join-Path $Root $cat
    if ((Test-Path -LiteralPath $catDir) -and -not (Get-ChildItem -LiteralPath $catDir -Force)) {
        Remove-Item -LiteralPath $catDir -Force
        Write-Host ("[清理空文件夹] {0}" -f $catDir) -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host ("完成：移动 {0} 个文件，跳过 {1} 个。" -f $moved, $skipped) -ForegroundColor Green
