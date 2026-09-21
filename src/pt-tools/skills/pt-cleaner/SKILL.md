---
name: pt-cleaner
description: 通过 PTSL 批量修改 Pro Tools 工程里轨道的 IO 主输出分配（把多轨输出统一改到指定 bus/主输出），支持先 CreateSignalPath 新建输出路径、dry-run 预览与自动备份副本。当用户要求"批量改轨道输出/把 XX 轨道接到 XX 输出/清理 IO 路由"且 Pro Tools 已在运行时使用。注意：删发送（send）、删插件（insert）、删 IO 路径 PTSL 不支持，不要承诺。
---

# pt-cleaner — Pro Tools 批量 IO 输出清理

> ⚠️ **版本要求（已实测）**：本工具依赖 PT 2025.10+ 的 CId 146/147。**本机当前 PT 25.6.1 实测不支持**（ErrType 133），升级前运行会在写入步骤失败。dry-run/预览/备份逻辑均正常，可在旧版上安全预览。

## 能力边界（先读，别越界）

| 用户想做的 | 本工具 | 说明（2026-09-15 E0 实测定案） |
|---|---|---|
| 批量改轨道**主输出** | ✅ 支持 | `SetTrackMainOutputAssignments`（PTSL v6，CId 147） |
| 先**新建输出路径**再指派 | ✅ 支持 | `CreateSignalPath`（含创建，响应返回 SignalPathInfo.id） |
| 批量**删发送（send）** | ❌ 不支持 | PTSL 无任何 Send 命令 |
| 批量**删插件（insert）** | ❌ 不支持 | 插件窗口类深层 UI 不在 PTSL 覆盖 |
| **删 IO 路径** | ❌ 不支持 | 只有创建（CreateSignalPath），无删除 |
| 撤销/多级回退 | ⚠️ 靠备份 | 执行前自动 SaveSessionAs 副本，不要指望 PTSL 撤销链 |

> 结论：**本技能只做 P1（批量改 IO 输出）**。用户提删发送/删插件等需求时，直说 PTSL 不支持，并建议替代方案（手工操作 / UI 自动化兜底，另议）。

## 工作流（先预览，再执行，写操作自动备份）

```
第 0 步 环境探测  → 读 pt-profile.json（没有先跑 pt-scanner）；PT 在线确认
第 1 步 需求确认  → 问清：哪些轨道（名字列表或前缀）、改到什么输出路径
第 2 步 dry-run   → --dry-run 展示计划（轨道清单 + 目标输出），给用户确认
第 3 步 执行      → 自动 SaveSessionAs 备份副本 → 写入 → 汇报
第 4 步 校验      → 建议重跑 pt-scanner 扫一遍，对照 tracks 的输出变化
```

### 第 0 步 · 环境

1. `pt-profile.json`：轨道名字和输出路径名都从它校验（不猜轨道名、不猜输出名）。
2. venv 解释器（同 pt-exporter 家族，复用同一个 venv）：
   ```
   D:\Ai-Files\Agent-Preset\Skills\protools-skills\pt-exporter\env\venv\Scripts\python.exe
   ```
3. Pro Tools 已启动、目标工程已加载。

### 第 1 步 · 需求确认（必须问）

| 要问的 | 说明 |
|---|---|
| 目标轨道 | 逐个列名字（`--tracks "DX 1" "DX VO"`），或给统一前缀（`--track-prefix DX`，匹配所有 DX 开头轨）。**注意 folder/VCA 会匹配到**，选前缀时先 dry-run 核对清单 |
| 目标输出 | 用 profile 的 `sources` 节里的名字（如 `Master Hole`）。输出路径 = 导出源名，同源 |
| 新建路径？ | 需要新 bus 再指派时给 `--create-path <新路径名>`（不常用） |

### 第 2~3 步 · dry-run 与执行

```powershell
$py = "D:\Ai-Files\Agent-Preset\Skills\protools-skills\pt-exporter\env\venv\Scripts\python.exe"
$script = "D:\Ai-Files\Agent-Preset\Skills\protools-skills\pt-cleaner\scripts\pt_clean.py"

# 预览
& $py $script --profile pt-profile.json --track-prefix DX --output "Master Hole" --dry-run

# 确认后执行（默认先备份副本到工程同目录 *_cleaner-backup-时间戳.ptx）
& $py $script --profile pt-profile.json --track-prefix DX --output "Master Hole"
```

执行后默认**不保存原工程**（`--save` 才保存）——改完让用户先听一遍，满意再保存。

### 第 4 步 · 校验

重跑 pt-scanner → 对比 profile 前后差异汇报给用户；或让用户直接在 Pro Tools 里看 Mix 窗口。

## 已知坑（实测/源码确认）

1. **本机（PT 25.6.1 / PTSL 2025）实测不支持 CId 146/147**：`CreateSignalPath`、`SetTrackMainOutputAssignments` 均报 `ErrType 133: PT_UnsupportedCommand`（2026-09-15 实测）。**需 Pro Tools 2025.10+ 才能用本技能**。升级前跑本脚本会在此步失败——这是版本限制，不是脚本 bug。
2. **PTSL 没有"读 signal path 列表"的命令**——只有 `GetExportMixSourceList`（给名字）和 `Create/Set`（无 Get）。所以目标路径用**名字**传参；新建路径时 CreateSignalPath 响应里的 `SignalPathInfo.id` 也可直接用于指派。
3. **`SetTrackMainOutputAssignments` 是 v6 命令（CId 147）**：py-ptsl 未封装（源码仅 TODO），本工具用自定义 Operation。
4. **请求体字段**：`track_names`（字符串列表）+ `signalpath_ids`（目标路径名字符串列表）——不要给 Track 对象，只要名字。
5. **备份是最后防线**：`pt.save_session_as()` 在写操作前自动调；万一命令已执行但用户不满意，用副本恢复（或回退 Pro Tools 未保存的撤销）。

## 相关

- 扫描建档：`pt-scanner`（本技能依赖的 profile）
- 导出验证：`pt-exporter`（改完输出后用全家桶导出验证路由正确）
- 集数工程创建：`ptx-episode-folders`
- 理论背景：Obsidian 库内 `07-AI连接ProTools自动化路线.md`（批量改 IO 专项节）