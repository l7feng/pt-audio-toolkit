# scripts/ — 历史脚本归档（2026-09-21 从 `D:\My-Temporary` 迁入）

这里放的是**当时与 rename-unify 相关、后来能力已并入工具本体**的历史脚本。
保留原样，作为行为对照与回溯依据；**日常不要再单独跑**，直接用 exe 里的对应页签。

## 1. `FinalMix按集归位.ps1` —— 能力已并入工具

- **原路径**：`D:\My-Temporary\FinalMix按集归位.ps1`
- **原用途**：把 `FinalMix/{MIX,BUS,Stem}/` 三个平铺类别文件夹，重组为「每集一个文件夹」
  （MIX / MIX-MASTER 放集根，BUS-*→集目录\BUS，STEM-*→集目录\STEM）。
- **现状**：已移植为纯 Python 并**并入主流程**。
  - 引擎：`code/core_rules.py` 的 `build_regroup_plan()` / `apply_regroup()` / `regroup_target()`
  - 界面：工具「3 · 预览与执行」页的 **「按集归位」** 选项组
  - 触发：勾选「重命名完成后，自动按集归位」，与改名**串成一步**，共用一份可撤销日志
- **与原脚本的差异**：
  | 维度 | 原 ps1 | 工具内实现 |
  |---|---|---|
  | 集前缀解析 | 只认字面分隔标记 ` 7F_` | 优先走完整识别引擎（能处理 `-DX Folder`、裸集数等历史写法），识别不出才回退字面切分 |
  | 归位时机 | 独立跑，需手动 | 可与改名串成一步 |
  | 撤销 | 无 | 与改名共用 `rename_log_*.csv`，一键反做 |
  | 安全语义 | 只移动不覆盖、解析失败跳过、清理空目录 | **完全一致**（逐条对齐实现） |

## 2. `fix_kimidata_paths.py` —— 一次性修路径，已完成

- **原路径**：`D:\My-Temporary\fix_kimidata_paths.py`
- **原用途**：把 `daimon-share` 里残留的旧路径 `D:\KimiData\` 批量改写为
  `D:\Ai-Files\Agent-Work\KimiData\`（含 JSON 双反斜杠形态与 `file:///` 正斜杠形态），
  改前自动 `.bak` 备份，改后全文复核残留。
- **现状**：**属一次性数据修复，已跑完，无并入价值**，仅作归档。
  如需重跑，改文件头部的 `ROOT` 常量后再执行。

## 迁移说明

- 两个脚本均为**复制迁移**（已校验 sha256 一致），原位置副本的清理见项目 notes。
- 本目录**不参与打包**：`packaging/build.ps1` 只把 `code/` 编进 exe。
