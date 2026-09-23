# jianying-draft-toolkit

**剪映工程工具包** —— 一个 exe，三件独立的事：

| 标签页 | 作用 | 前置 |
|---|---|---|
| ① 导出音频 | 剪映草稿 → 切片 / 整轨导出 | 剪映（依赖 `videoeditor.dll` 解密草稿）+ ffmpeg |
| ② 导入多轨 | `.ptx`（需 PT 在线）/ 交付包 JSON（离线）→ 写剪映草稿 | PT 在线 **或** 一个 JSON |
| ③ 生成交付包 | JSON 路径相对化 + 音频随包 | 无 |

## 入口

```bash
python code/gui.py      # GUI（三标签页）
python code/main.py     # CLI
python code/main.py --init   # 首次运行配置向导
```

打包：仓库根执行 `python tools/build.py jianying-draft-toolkit`（或 `packaging\build.ps1`）。

## 分层约定

```
ui (tabs/)  →  app (main.py)  →  core/
```

`core/` **不 import tkinter** —— 保证核心逻辑可无界面测试、可被 Agent 调用。

## 配置落点

| 模式 | 路径 |
|---|---|
| frozen（exe） | `<exe目录>\config.json`（可写，与 exe 同级） |
| 源码 | `src\jianying-draft-toolkit\config.json` |

⚠️ 所有可变文件（配置 / 交付包）**一律写 APP_DIR**，不写代码目录 ——
打包后代码在 `_internal\`（只读且会被清理）。

⚠️ 配置向导是**合并式**落盘（`DEFAULT_CONFIG` → 磁盘现值 → 向导结果）：
重跑 `--init` **不会**清空你调好的「命名模板多选 / 导出模式多选 / AAF 开关」。

## v2.4.0 要点

- **导出模式多选**：整轨 / 片段可同时勾（配置 `export_mode` 为 list）
- **命名模板多选**：`name_templates`（库）+ `name_templates_active`（勾选）；
  多模板按 `模板N/` 分目录产出，各模板**独立去重**
- **整轨源文件路径解析修复**：剪映素材 path 是**相对草稿根**的，原实现按 exe 的 CWD 判定
  `exists()` → 误报「源文件找不到」。现改为三级查找：原样 → `draft_dir/path` → 按文件名 walk

版本史见仓库根 [CHANGELOG.md](../../CHANGELOG.md)。

## 已知坑

- **必须是 onedir**：`tools\jy-draftc\`（第三方解密器，遵循其自带 LICENSE）运行时会把剪映安装路径
  写进 `.env`，需要 exe 旁有**真实目录**；onefile 会解到临时目录并被清理。分发时 `tools\` 与 exe 同级。
- **`py-ptsl` 不打包**：装了才能「解析 `.ptx`」；没装仍可**完全离线**导入交付包 JSON。
- **不要用 PowerShell 直接跑 PyInstaller**（见 `tools/build.py` 顶部说明）。
- 打包机需 `pip install tkinterdnd2`（拖拽依赖，`tools/build.py` 已自动带
  `--hidden-import tkinterdnd2 --collect-data tkinterdnd2`）。

## 回归测试

```bash
python tests/test_core_logic.py       # 核心逻辑（含 init_config 丢字段探针）
python tests/test_jy_multitpl.py      # 片段模式 + 多命名模板端到端（真实草稿，只读）
python tests/run_gui_smoke.py         # 三标签页建窗即销毁
```
