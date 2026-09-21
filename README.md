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

到 [**Releases**](../../releases) 下载 `pt-audio-toolkit-v1.0.0.zip`，解压后每个工具一个文件夹，
双击对应的 `.exe` 即可运行，**无需安装 Python**。

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

每个工具目录下都有 `build.ps1`（或 `packaging/build.ps1`），直接运行：

```powershell
cd src/pt-tools
.\build.ps1
```

产物在各自 `dist\` 下，结构为 `exe` + `_internal\`。

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
├── LICENSE                   MIT
├── .gitignore
└── src/
    ├── pt-tools/                 Pro Tools 工具箱 GUI
    │   ├── pt_tools_gui.py
    │   ├── build.ps1
    │   └── skills/               ← 三个内置技能（打包时进 _internal\skills\）
    │       ├── pt-cleaner/
    │       ├── pt-exporter/      （scripts/ 为正式脚本，env/ 为调试探针）
    │       └── pt-scanner/
    ├── pt-project-folder-builder/
    │   ├── folder_builder_gui.py
    │   └── build.ps1
    ├── jianying-draft-toolkit/
    │   ├── code/                 主程序 + core/ + tabs/
    │   ├── config.json
    │   ├── packaging/build.ps1
    │   └── tools/                第三方依赖 jy-draftc
    └── rename-unify/
        ├── code/
        └── packaging/build.ps1
```

---

## 设计原则

这些工具都遵循同一条原则：**壳不动芯**。

GUI 外壳只负责收集用户参数，然后拼成命令行参数，用 `subprocess` 调用底层技能脚本；
真正的业务逻辑（PTSL 连接、编码处理、错误守卫）全部留在技能脚本内部。
好处是：GUI 可以随时替换（命令行、Web、别的壳），而底层脚本始终可独立运行、可脚本化、可被 Agent 调用。

---

## 已知事项

- `src/pt-project-folder-builder/build.ps1` 与 `src/jianying-draft-toolkit/code/main.py` 中存在
  **开发机硬编码路径**（`C:\Users\Administrator\...`），自行构建或运行前请按本机环境调整。
- 各工具的 Python 虚拟环境（`env\` / `venv\`）与构建产物（`build\` / `dist\` / `__pycache__\`）
  均不进仓库，克隆后按需自建。

---

## License

[MIT](LICENSE)

其中 `src/jianying-draft-toolkit/tools/jy-draftc/` 为第三方工具，遵循其自带 LICENSE。
