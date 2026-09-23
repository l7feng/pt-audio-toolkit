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

## v2.5.0 要点（视频名提取 + 按视频分包）

- **从视频名提取字段**：新增 `core/videoname.py`，把视频素材名解析成
  **项目 / 集数 / 编号 / AiFX**，命名模板可用新占位符
  `{视频项目}` `{集数}` `{编号}` `{AiFX}` `{视频名}`。
  此前 `{项目名}` 只取**草稿文件夹名**，视频名里的集数信息全被丢掉。
- **判断不出的交给人，工具不猜**：两类情况弹窗请你补项目名 ——
  ① **纯数字**（`17.mp4`，通常就是集数，缺的是项目名）；
  ② **项目名超过 4 个字**（`法老的禁忌神谕 第10集 待混音.mp4` → 建议缩写「法老」）。
  补过的答案存在 `video_project_answers`，**下次不再问**。
- **按视频分包**：勾选「按视频分包」后，视频轨上每个片段 = 一个交付文件夹，
  各音频轨按该片段的时间窗切出（空白补真静音，各轨等长对齐）。
  例：一个草稿里有 `法老2`、`法老3` 两个视频 → 产出 `法老2/`、`法老3/`，
  各含本集的全部音频轨。同名片段自动加 `-2` 后缀。
  分包模式下跳过 AAF（AAF 描述整条时间线，与分包语义冲突）。
- 实测（2026-09-23，草稿「9月22日」8 个视频片段 / 6 条音频轨，632s）：
  产出 `法老4`(42.57s)、`法老4-2`(57.80s)、`法老6`(77.33s)、`法老7`(97.70s)…
  每段时长与对应视频片段**逐一对齐**。

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
