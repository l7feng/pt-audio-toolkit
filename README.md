# pt-audio-toolkit

**Pro Tools / 剪映 音频后期工具包** —— 把日常音频后期工作中反复用到的几套自动化工具聚合成一个开源仓库：源码可读、可本地构建、也可直接下载打包好的 exe 使用。

面向影视混音、游戏音效、短剧后期的实际工作流：Pro Tools 工程扫描与批量导出、素材命名统一、剪映草稿导入导出与交付打包。

---

## 包含的工具

| 工具 | 作用 | 形态 |
|---|---|---|
| [**pt-tools**](src/pt-tools/) | Pro Tools 自动化工具箱 GUI：一个壳带三个技能（扫描 / 导出 / 清理），走 PTSL 连接 Pro Tools | 单 exe（tkinter，零第三方依赖） |
| [**pt-project-folder-builder**](src/pt-project-folder-builder/) | 按视频文件或集数列表批量建 Pro Tools 工程文件夹，从模板复制 .ptx，已存在的自动跳过 | 单 exe |
| [**jianying-draft-toolkit**](src/jianying-draft-toolkit/) | 剪映草稿工具箱：导入音频、导出音频、交付打包、AAF 输出 | 单 exe（多标签页） |
| [**rename-unify**](src/rename-unify/) | 素材批量命名统一：按规则集重命名并生成清单 | 单 exe |

---

## 快速开始

### 方式一：直接下载 exe（推荐给非开发用户）

到 [**Releases**](../../releases) 下载对应版本的四个工具包
（`pt-audio-toolkit-v<版本>-<工具名>.zip`，一工具一包），解压后双击 `.exe` 即可运行，
**无需安装 Python**。

> ⚠️ 每个工具要**整个文件夹一起用**（`_internal\` 必须与 exe 同级），不要只拷 exe。

### 方式二：从源码运行

各工具均只依赖 Python 标准库（`tkinter`、`subprocess`、`json` 等），

```bash
# pt-tools
python src/pt-tools/pt_tools_gui.py

# pt-project-folder-builder
python src/pt-project-folder-builder/folder_builder_gui.py

# jianying-draft-toolkit
python src/jianying-draft-toolkit/code/main.py

# rename-unify
python src/rename-unify/code/main.py
```

部分工具需要额外前置条件，见下方「环境依赖」。

### 方式三：自行打包 exe

统一入口（推荐）：

```bash
python tools/build.py                   # 构建全部四个工具
python tools/build.py pt-tools          # 只构建指定工具
python tools/build.py --version 1.1.0 --date 20260923 --out-root D:\somewhere\exe
```

产物默认落在 `D:\Ai-Files\Agent-Preset\exe\pt-audio-toolkit-v<版本>-<日期>\<工具名>\`，
结构为 `exe` + `_internal\`，**整个文件夹一起分发**。

构建解释器需带 **tkinter**（官方 Windows 安装版自带）与 **PyInstaller**；剪映工具另需
`tkinterdnd2`。`tools/build.py` 会在构建前自检并给出明确报错。

各工具目录下的 `build.ps1` 仍然可用，但已降级为**转发薄壳** ——
原因见 `tools/build.py` 顶部注释：PowerShell 会把 PyInstaller 的 stderr 当作错误流，
配合 `$ErrorActionPreference="Stop"` 会在第一行 `INFO:` 就**静默中断**构建。

---

## 环境依赖

| 工具 | 前置条件 |
|---|---|
| pt-tools | 本机装有 **Pro Tools**（脚本通过 PTSL 连接 `127.0.0.1:31416`）；py-ptsl 相关依赖在首次使用时按提示安装 |
| pt-project-folder-builder | 需有一个 `.ptx` 模板工程文件 |
| jianying-draft-toolkit | 本机装有 **剪映**（依赖 `videoeditor.dll` 解密草稿）；`ffmpeg` 用于切片转码；`tools\jy-draftc\` 为第三方草稿解密工具（自带 exe） |
| rename-unify | 无，纯 Python 标准库 |

---

## 仓库结构

```
pt-audio-toolkit/
├── README.md                 本文件
├── CHANGELOG.md              版本与变更
├── VERSION                   仓库级版本（tools/build.py 用它命名出口目录）
├── LICENSE                   MIT
├── .gitignore
├── tools/                    构建与核验
│   ├── build.py              统一打包入口（四工具，一条命令）
│   └── verify_exe.py         exe 产物核验（清单 + 真启动 + 窗口枚举，查 tk 残留空窗）
├── tests/                    回归测试（跑法见 tests/README.md）
│   ├── _common.py            跨机路径解析 + PASS/SKIP/FAIL/ERROR 分级
│   ├── run_import_tests.py   15 模块导入自检
│   ├── test_core_logic.py    24 项核心逻辑
│   ├── test_wiring.py        5 项 GUI↔核心接线
│   ├── run_gui_smoke.py      4 个 GUI 建窗即销毁
│   └── test_jy_multitpl.py   剪映片段 + 多模板端到端
└── src/
    ├── pt-tools/                 Pro Tools 工具箱 GUI
    │   ├── pt_tools_gui.py
    │   ├── build.ps1             → 转发 tools/build.py
    │   ├── README.md
    │   └── skills/               三个技能脚本（打包时进 _internal\skills\）
    │       ├── pt-cleaner/
    │       ├── pt-exporter/      （scripts/ 为正式脚本，env/ 为调试探针）
    │       └── pt-scanner/
    ├── pt-project-folder-builder/
    │   ├── folder_builder_gui.py
    │   ├── build.ps1             → 转发 tools/build.py
    │   └── README.md
    ├── jianying-draft-toolkit/
    │   ├── code/                 主程序 + core/ + tabs/
    │   ├── config.json
    │   ├── packaging/build.ps1   → 转发 tools/build.py
    │   ├── README.md
    │   └── tools/                第三方依赖 jy-draftc
    └── rename-unify/
        ├── code/
        ├── README.md
        └── packaging/build.ps1   → 转发 tools/build.py
```

---

## 设计原则

这些工具都遵循同一条原则：**壳不动芯**。

GUI 外壳只负责收集用户参数，然后拼成命令行参数，用 `subprocess` 调用底层技能脚本；
真正的业务逻辑（PTSL 连接、编码处理、错误守卫）全部留在技能脚本内部。
好处是：GUI 可以随时替换（命令行、Web、别的壳），而底层脚本始终可独立运行、可脚本化、可被 Agent 调用。

---

## 已知事项

- **构建解释器**：GUI 打包需要**带 tkinter 的 Python**（官方 Windows 安装版自带）与 `PyInstaller`；
  剪映工具另需 `tkinterdnd2`。`tools/build.py` 会自检并给出明确报错。
- **pt-tools 的运行依赖**：打包后 exe **自带技能脚本**，但**不带 venv（py-ptsl）** ——
  首次执行 PT 任务前，需在「设置 > 技能目录」指向一个含 venv 的技能目录
  （默认 `D:\Ai-Files\Agent-Preset\Skills\protools-skills`）。详见 `src/pt-tools/README.md`。
- 各工具的 Python 虚拟环境（`env\` / `venv\`）与构建产物（`build\` / `dist\` / `__pycache__\` / `*.spec`）
  均不进仓库，克隆后按需自建。
- 历史提示「`build.ps1` 与 `code/main.py` 存在硬编码 `C:\Users\Administrator\...`，运行前需手工调整」
  **已失效**：`build.ps1` 系列已改为跨机自适应并转发 `tools/build.py`；
  `code/main.py` 里那一处只是 `os.environ.get("LOCALAPPDATA", <兜底>)` 的兜底值，不影响运行。

---

## License

[MIT](LICENSE)

其中 `src/jianying-draft-toolkit/tools/jy-draftc/` 为第三方工具，遵循其自带 LICENSE。
