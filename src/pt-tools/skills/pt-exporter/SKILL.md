---
name: pt-exporter
description: 通过 PTSL（Pro Tools Scripting Library）无 GUI 导出 Pro Tools 工程——支持整段并轨混音（Bounce to Disk，实时渲染插件与自动化）、按 bus/output 的分轨导出（Stems），以及**按单根轨道导出**（BounceTrack，等价 Studio One 的 Export Stems Tracks / PT 右键轨道 Bounce）。读取 pt-scanner 生成的 pt-profile.json（工程档案）做校验与环境探测，支持 dry-run 预览。当用户要求"导出分轨/并轨/批量 bounce/导出 stems/导出 DX/MX 人声轨/按轨道导出/导出所有带音频块的轨道"且 Pro Tools 已在运行时使用，不操控屏幕。两个子命令 mix（并轨）/ stems（分轨）。
---

# pt-exporter — Pro Tools 无界面导出

## 适用场景

- 把某个工程的**整段并轨**导成一个 WAV（保留全部插件/自动化，实时 bounce）
- 把指定几条 bus（人声 DX/MX、DME 分轨等）**分别**导成独立 WAV
- **把单根轨道**（audio / aux / folder / master）导成 WAV —— 如「导出这条人声轨」「把所有带音频块的轨各导一个」
- 多集工程批量重复上述导出，无人值守

**不适用**：AAF/OMF 互导（用 Obsidian 库内 [[01-Pro Tools与Premiere的AAF_OMF交互指南]] 对应流程）；需要点插件 UI 的操作。

## 工作流（5 步，先问后做，不许猜）

```
第 0 步 环境探测  → 读 pt-profile.json（没有就先跑 pt-scanner 扫，只读安全）
第 1 步 需求确认  → 逐个问：导出哪个工程/哪些 source/时间范围/输出目录/格式
第 2 步 dry-run   → 跑 --dry-run 打印导出计划，给用户看，确认后再干活
第 3 步 执行      → 去掉 --dry-run 真正导出
第 4 步 校验汇报  → 逐个文件 [ok] 字节数；对照预期检查（时长×采样率×位深≈字节数）
```

### 第 0 步 · 环境探测（每次先做）

1. 检查 `pt-profile.json` 是否存在（默认在工作目录 `profiles/` 下，或用户指定路径）。
2. 没有 → 调用 `pt-scanner` 技能生成（它只读，安全）。拿到 profile 后才有：工程名、采样率/位深/时码率、长度、可用 source 列表。
3. 检查 venv 解释器（脚本必须用它跑，不要用系统 python）：

   ```
   D:\Ai-Files\Agent-Preset\Skills\protools-skills\pt-exporter\env\venv\Scripts\python.exe
   ```
   （venv 内已 `pip install py-ptsl`。换机器/换 Python 后重建 venv。）

### 第 1 步 · 需求确认（必须问清，不许猜）

| 要问的 | 说明 |
|---|---|
| 工程 | 当前打开的就是？还是要 `--session` 打开别的 .ptx？ |
| 导出粒度 | **先问清楚要「总线（bus）」还是「单根轨道（track）」**——这是两条不同命令线，见下 |
| source | **不能用轨道列表里的名字猜**。用 profile 的 `sources` 节（bus/output/physicalout 三类）核对。例：`DX-BUS-Master`（Bus）、`Master Hole`（Output）。若走 `--source-type track`，则名字用 **profile 的 `tracks` 节**（或 `track_list()`）核对 |
| 时间范围 | `--start` / `--end`，timecode 格式 `HH:MM:SS:FF`。工程默认长度 06:00:00:00 不是真实视频长度——**用 `scripts/video_duration.py` 读视频实际秒数再换算**（见下） |
| 输出目录 | `--out`；会自动创建 |
| 格式 | `--sample-rate 48000` `--bit-depth 24` `--format mono/interleaved` |

时间范围换算：`video_duration.py <视频路径> --profile <profile路径>` 直接给秒数 + 按 profile 时码率算好的 `HH:MM:SS:FF`（不用手动换算，帧率从 profile 自动取）。

### 两条导出线（选错就导不出来）

| | 路径制 | 轨道制 |
|---|---|---|
| 命令 | `ExportMix`（CId 28） | `BounceTrack`（CId 134） |
| PT 对应入口 | 菜单 **File > Bounce Mix** | **右键轨道 > Bounce**（Shift+Opt+Cmd+B） |
| 参数 | `--source-type bus\|output\|physicalout` | `--source-type track` |
| source 取值 | `sources` 节里的 bus/输出名 | `tracks` 节里的轨道名 |
| 能否按轨导 | ❌ | ✅ |

### 第 2~3 步 · dry-run 预览与执行

```powershell
$py = "D:\Ai-Files\Agent-Preset\Skills\protools-skills\pt-exporter\env\venv\Scripts\python.exe"
$script = "D:\Ai-Files\Agent-Preset\Skills\protools-skills\pt-exporter\scripts\pt_export.py"

# 1) 预览（不导）——注意 --profile 是全局参数，必须放在子命令（mix/stems）之前
& $py $script --profile pt-profile.json mix `
  --source "Master Hole" --source-type Output `
  --out "D:\out" --start 00:00:00:00 --end 00:01:38:01 `
  --sample-rate 48000 --bit-depth 24 --format interleaved `
  --realtime --dry-run

# 2) 用户确认后执行（同一命令去掉 --dry-run）
& $py $script --profile pt-profile.json mix `
  --source "Master Hole" --source-type Output `
  --out "D:\out" --start 00:00:00:00 --end 00:01:38:01 `
  --sample-rate 48000 --bit-depth 24 --format interleaved `
  --realtime
```

分轨 stems：`--source "DX-BUS-Master" --source "MX-BUS-Master" --source-type Bus`，每个 source 一个 WAV。

**按轨道导出（BounceTrack）**：

```powershell
# 指定几根轨
& $py $script --profile pt-profile.json stems `
  --source "DX 1" --source "Audio FX ST.dup1" --source-type track `
  --out "D:\out" --start 00:00:00:00 --end 00:01:58:13 --format interleaved

# 批量：全部「含音频块」的非总线轨（给剪辑用，排除 aux/master/folder/vca）
& $py $script --profile pt-profile.json stems `
  --source-type track --all-tracks --skip-buses --exclude-empty `
  --out "D:\out" --start 00:00:00:00 --end 00:01:34:07 --format interleaved

# 只要某类轨
& $py $script --profile pt-profile.json stems `
  --source-type track --all-tracks --track-type audio `
  --out "D:\out" --start 00:00:00:00 --end 00:01:34:07
```

轨道模式专用开关：

| 开关 | 作用 |
|---|---|
| `--all-tracks` | 导出工程内全部轨（自动跳过 video） |
| `--skip-buses` | 配合 `--all-tracks`：排除 aux/master/folder/vca |
| `--exclude-empty` | 配合 `--all-tracks`：依据 profile 的 `contains_clips` 排除无音频块的轨 |
| `--track-type TYPE` | 只要这些类型，可重复（audio/aux/master/vca/routing-folder/instrument/midi） |
| `--bounce-timeout` | 单次导出超时秒数（默认 600；实时导长素材要 ≥ 素材时长 + 余量） |

**离线 vs 实时**：默认离线（快，几秒出）。**实测 118 秒素材实时 bounce 会超过默认超时**，长素材优先用离线；确需实时（如要真实插件尾音）时把 `--bounce-timeout` 放大到素材时长以上。

### 第 4 步 · 输出校验

脚本对每个导出文件打印 `[ok] <name>.wav <bytes>`。校验：
- mono 24-bit 48kHz：`时长秒 × 48000 × 3 ≈ 文件字节数`
- 0 字节或缺失 → 看 stderr 的 PTSL 错误（source 名错 / 时间范围内无内容 / 工程未加载）

## 已识别的坑（实测，均已在脚本/流程中规避）

1. **source 名写错**报 `Required mix source was not found`——必须用 profile 的 `sources` 节核对，或先跑 pt-scanner。**不能照轨道列表猜**（bus 名可能带 `-Master` 后缀、物理输出是 I/O 层名字）。
2. **不设时间选区**直接 bounce 报"时间轴上没有内容"——脚本已强制先 `set_timeline_selection`。
3. **`get_monitor_output_path` 在 Windows 下 JSON 解析崩**（路径反斜杠转义 bug）——别调它；物理输出名含中文时的 `\xNN` 编码 bug 由 pt-scanner 修正（json_cleanup）。
4. **实时 bounce 是阻塞的**——导多久等多久（1 分钟内容约 1 分钟）。
5. 导出路径在 `EM_LocationInfo.directory` 要带尾反斜杠（脚本已补）。
6. `Engine` 对象**不能用 `with` 语句**（该版本不支持 context manager），手动 `pt.close()`。
7. 帧率**从 profile 读**（如 25fps），不要写死 30fps——用的 `--profile` 时 `video_duration.py` 会自动换算。
8. **模态弹窗防御（2026-09-15 实测）**：PT 打开工程时遇"媒体丢失"等弹窗会阻塞 PTSL，导致 `open_session` / 命令调用无限挂起。**三个脚本已内置守卫**：`open_session` 线程化 + 超时（10 秒），会话名轮询自检（5 秒），超时明确提示「疑似模态弹窗，请人工处理」并退出。若仍卡死，手动处理弹窗即可恢复。
9. **【track 模式专属】track id 的花括号不能少**——`track_list()` 返回的 `id` 直接传（已带花括号），**不要自己做 strip/格式化**，去括号必报 `Could not parse Sys_TrackUID`。
10. **【track 模式专属】不要给 `BounceTrack` 传 `in_location`/`out_location`**——传了会报「由于时间轴上没有内容」，哪怕区间真的有音频。区间只能靠 `set_timeline_selection`。
11. **【track 模式专属】VCA 轨会「成功但零文件」**——不是 bug，VCA 不是信号路径。脚本会提前提示。
12. **实时 bounce 超时阈值**：默认 600s 对 118 秒素材的实时导出仍可能不够（实测 120s 阈值时被截断）→ 长素材优先**离线**；确需实时就把 `--bounce-timeout` 放大到素材时长 + 余量。
13. **系统代理会拦 py-ptsl 的 gRPC**：Clash 等把 `127.0.0.1:31416` 也代理了会报 `HTTP proxy returned response code 502`。跑之前设 `$env:NO_PROXY="127.0.0.1,localhost"`。

## 能力边界（2026-09-17 修正；2026-09-18 已全部实现，勿再误判）

**两条导出线均已支持**。不要再对外宣称「PTSL 不能按轨道导出」——那是错的（曾犯过此错，已勘误）。

| 需求 | 命令 | 本技能是否已支持 |
|---|---|---|
| 导某条**总线**（组） | `ExportMix`（CId 28） | ✅ `--source-type bus` |
| 导某条**主输出/物理输出** | `ExportMix` | ✅ `--source-type output` / `physicalout` |
| 导**单根轨道**（如 `DX 1`、`Audio FX ST.dup1`） | **`BounceTrack`（CId 134）** | ✅ `--source-type track`（2026-09-18 实现并实测） |
| 导**片段裸素材**（给剪辑用，不带轨道级效果） | `ExportClipsAsFiles`（CId 10） | ❌ 未实现（语义不同：导的是**片段原始素材**，不渲染轨道级 inserts/自动化） |

**`BounceTrack` 关键用法（已实测跑通，2026-09-17/18）**——py-ptsl 602.0.0 **未封装**，需自定义 `class CId_BounceTrack(Operation): pass`（类名即自动绑定 RequestBody/ResponseBody；脚本已内置）：

1. `src_track_id` 用 `track_list()` 返回的 id，**必须保留花括号** `{00000000-2a000000-…}`；去掉花括号报 `Could not parse Sys_TrackUID`
2. 导出区间**唯一来源是 `pt.set_timeline_selection(in, out)`**；**传 `in_location`/`out_location` 会报「由于时间轴上没有内容」**（哪怕区间真有音频）——脚本已强制不传
3. 选区为空同样报错 → 调用前必先设选区（脚本已做，并在选区为空时提前 fail-fast）
4. 实测可用轨道类型：audio ✅ / aux ✅ / routing-folder ✅ / master ✅；**vca 返回成功但零文件**（VCA 不是信号路径）
5. 自动化渲染由 `RenderAutomationOptions(render_volume_automation, render_pan_automation)` 控制（＝ PT 右键 Bounce 对话框的 Volume/Pan 勾选）
6. 产出命名用 `file_name_prefix`（与 `ExportMix` 的 `file_name` 不同），结果在响应的 `file_paths`；PT 会自行追加 `-St` 之类后缀
7. **单轨导出命令的语义是「渲染该轨的完整信号链」**，所以导 aux / folder 也等于导它们汇入的总和——**这与 24 号工程「排除总线避免音量双倍」的需求直接相关**：要只给剪辑用裸素材就 `--skip-buses --exclude-empty`

> 语义提醒：`BounceTrack` 对应 PT 的「右键轨道 > Bounce」；`ExportMix` 对应 File 菜单的 `Bounce Mix`。**两者不是同一个功能**，所以源类型不同——轨道制 vs 路径制。实测同素材两条命令输出**未做逐字节 A/B 对照**（待办）。

## 相关

- 扫描建档：`pt-scanner`（生成本技能依赖的 pt-profile.json）
- 结构清理：`pt-cleaner`（批量改 IO 输出）
- 集数工程创建：`ptx-episode-folders`
- 理论背景：Obsidian 库内 `07-AI连接ProTools自动化路线.md`、`30-ProTools无GUI导出实操路线-本任务API级方案.md`