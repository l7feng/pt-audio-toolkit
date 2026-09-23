# pt-tools

**Pro Tools 自动化工具箱 GUI** —— 一个 tkinter 壳，带三个技能脚本（扫描 / 导出 / 清理），
通过 PTSL（gRPC）连接 Pro Tools。

GUI 本身**零第三方依赖**；真正的 PT 交互逻辑全在技能脚本里（**壳不动芯**：壳负责收集参数、
拼 CLI，脚本负责 PTSL 连接、编码处理与错误守卫）。

## 入口

```bash
python pt_tools_gui.py
```

打包：在仓库根执行 `python tools/build.py pt-tools`（或本目录 `.\build.ps1` —— 转发薄壳）。

## 导出页（v1.1.0 · 四模式多选）

「导出模式」区四个复选框，**勾哪几个就按顺序导哪几路**（每路一条 CLI 命令顺序执行，失败即停）：

| 模式 | 底层 | 产出 |
|---|---|---|
| ☑ **MIX 整段并轨** | ExportMix 主输出（`sources.output`） | 1 个 WAV |
| ☑ **BUS 总线分轨** | ExportMix 全部总线（`sources.bus`） | 每条 bus 1 个 WAV |
| ☑ **STEM 全部分轨** | BounceTrack `--all-tracks`，默认排除总线类轨 + 空轨 | 每根音源轨 1 个 WAV |
| ☐ **按轨道名称** | BounceTrack 指定轨（勾选后从下方列表挑，列表带类型列） | 选中轨每根 1 个 WAV |

- STEM 旁有子选项「**含效果辅助轨 (aux)**」：勾上改走 `--track-type audio/aux/instrument/midi`
  白名单（aux 进、master/vca/folder 仍排除），空 aux 一并按档案 `contains_clips` 排除。
- **按视频填入…**：选择工程对应视频，自动读时长并按工程帧率换算，
  一键填「开始 00:00:00:00 → 结束=视频末帧」（底层 `video_duration.py`，纯标准库读 MP4/MOV）。
- 预览闸门：所有勾选模式的 dry-run 计划全部列出后才解锁「执行导出」；
  任何参数变化（含模式勾选、选轨）都会熄灭执行按钮，需重新预览。

## 前置条件

| 项 | 说明 |
|---|---|
| Pro Tools | 必须正在运行 —— 脚本经 PTSL 连接 `127.0.0.1:31416`（离线时 GUI 会亮红灯） |
| 技能目录 | 需要**含 venv（py-ptsl）**的技能目录，见下 |

## 依赖关系（重要）

打包后 exe **自带技能脚本副本**（`_internal\skills\`），但**不带 venv** ——
venv 含 py-ptsl、体积大，且属运行时环境，不随 exe 打包。

所以 exe 能直接启动，但**首次执行 PT 任务前需要一个含 venv 的技能目录**：

```
<技能目录>/
├── pt-scanner/scripts/pt_scan.py
├── pt-exporter/
│   ├── scripts/*.py
│   └── env/venv/Scripts/python.exe      ← 含 py-ptsl 的 venv（缺这个就跑不了）
└── pt-cleaner/scripts/pt_clean.py
```

- **技能目录探测顺序**（`PathResolver.detect`）：`config.json` 里显式设过 → 环境变量
  `PTOOLS_SKILLS_ROOT` → 默认 `D:\Ai-Files\Agent-Preset\Skills\protools-skills`。
  都不通时用 **设置 > 技能目录…** 指定一次（会写回配置）。
- **脚本查找顺序**（`PathResolver.script`）：`<exe目录>\_internal\skills\<skill>\scripts\` **优先**
  → 回落技能目录。即**脚本以 exe 内置副本为准**，技能目录主要用来提供 venv。
- 若脚本已内置、只缺 venv，GUI 会明确指出「技能脚本已内置，仅缺运行解释器的 venv」并给出默认路径 ——
  不会含糊地说「技能目录不存在」。
- 技能脚本的**唯一真源是本仓库** `src/pt-tools/skills/`；外部技能目录是**生效区**
  （2026-09-23 逐文件核对，6 个脚本 MD5 完全一致）。

## 配置与日志落点

```
%APPDATA%\pt-tools\config.json
```

不写程序目录 —— exe 的 `_internal\` 只读且可能被清理。

## 已知坑

- **不要用 PowerShell 直接跑 PyInstaller**：它把进度写 stderr，配 `$ErrorActionPreference="Stop"`
  会在第一行 `INFO:` 就静默中断（只输出 "building..." 就退出）。统一走 `tools/build.py`。
- **启动闪窗**：靠 `withdraw + overrideredirect + alpha` 三重保险消除（历史痛点：`ttk.Style()`
  早于 `Tk()` 会隐式建一个标题为 `tk` 的空窗）。改动启动流程后请跑 `tests/run_gui_smoke.py` 回归。
- `env/` 目录是**调试探针脚本**（不是虚拟环境），故 `.gitignore` 只忽略 `env/venv`。

## 回归测试

```bash
python tests/run_import_tests.py    # 导入自检
python tests/test_wiring.py         # CmdWorker / 接线
python tests/run_gui_smoke.py       # 建窗即销毁
python tests/test_pt_modes.py       # 导出模式多选专项（25 项）
```
