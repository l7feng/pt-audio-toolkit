# 更新日志

按**仓库级版本**记录整体发布；每个工具的细粒度版本史见其 `README.md` 或源码顶部注释。

> 仓库级版本（`VERSION` 文件）= 发布出的这一整套 exe 的版本；
> 工具级 `APP_VERSION` 各自独立演进。两者的对应关系见下表。

| 仓库版本 | 日期 | 工具版本（pt-tools / folder-builder / jianying / rename-unify） | 要点 |
|---|---|---|---|
| **1.1.0** | 2026-09-23 | 1.0.0 / 1.0.0 / 2.4.0 / 1.1.0 | 工程配套：测试入库、构建统一、版本口径统一 |
| 1.0.1 | 2026-09-23 | （当时工具级版本未定义） | 修 3 处缺陷 |
| 1.0.0 | 2026-09-21 | — | 首次聚合发布（四工具） |

---

## 1.1.0 — 2026-09-23

**工程配套改进。四个工具的功能行为未变。**

测试与质量
- **测试入库**：新增 `tests/`（15 模块导入自检 / 24 项核心逻辑 / 5 项接线 / 4 个 GUI 冒烟 /
  剪映端到端），此前这批脚本只在临时目录里，随时会丢
- **全部跨机化**：不再写死用户名与盘符（解释器走 `PT_TEST_PY` → 当前解释器 → 自动探测；
  草稿根走 `%LOCALAPPDATA%`；仓库根从文件位置反推）
- **结果分级**：`PASS / SKIP / FAIL / ERROR` 四态 + 退出码 `0/1/2`，
  区分「功能坏了」与「测试脚本跟不上接口变动」；缺可选依赖（如 py-ptsl）记 SKIP 而非 FAIL

构建与发布
- **新增 `tools/build.py`**：一条命令构建四工具，直调 `python -m PyInstaller` 并逐工具判返回码，
  失败时打印工具名 + 返回码 + 关键 stderr，**绝不静默**
- **四个 `build.ps1` 降级为转发薄壳**：原 325 行重复逻辑收敛（其中三份都在绕过
  「PowerShell 把 PyInstaller 的 stderr 当错误流」这个坑）
- 新增 `tools/verify_exe.py`：exe 产物核验（清单 + 真启动 + 顶层窗口枚举，查 `tk` 残留空窗）

版本
- **四工具统一口径**：`APP_VERSION = "X.Y.Z"`（不带 `v` 前缀）+ `build_date()`；
  窗口标题统一 `名称 vX.Y.Z (YYYY-MM-DD)`
- pt-tools 与 pt-project-folder-builder **补上版本号**（此前完全没有，界面无法辨别新旧）
- 新增仓库根 `VERSION` 文件，供 `tools/build.py` 命名出口目录

依赖提示
- pt-tools 在「技能脚本已内置、仅缺 venv」时报出**可操作指引**（此前含糊报「技能目录不存在」，
  指向了并非真正缺失的一环）

文档
- 新增三个工具级 `README.md` 与本 `CHANGELOG.md`
- 订正根 README 中已失效的「存在开发机硬编码路径」提示

---

## 1.0.1 — 2026-09-23

修复三处缺陷：

- **`jianying-draft-toolkit`：`init_config()` 静默丢配置**（真 bug）
  配置向导重建整个字典覆盖写盘，导致重跑 `--init`（或首次向导）会清空
  `name_templates` / `name_templates_active` / `export_mode` / `track_name_template` /
  `track_spec` / `export_aaf` / `aaf_media_mode`。改为三层合并落盘；
  顺带修了输出目录为空时的 `while` 死循环（连续回车会卡住）。
- **`pt-project-folder-builder`：复制步骤顺序**（数据丢失风险）
  原为「先 `os.remove` 旧文件、后判源是否存在」，模板 `.ptx` 被移走时会「删了不补」。
  改为先确认源可复制再动目标文件。
- **`pt-project-folder-builder/build.ps1`：写死用户名**
  解释器路径写死 `C:\Users\Administrator\...`，家用机直接失败。改为 `$env:USERNAME` 自适应。

---

## 1.0.0 — 2026-09-21

首次聚合发布，包含四个工具：

- **pt-tools** —— Pro Tools 自动化工具箱 GUI（扫描 / 导出 / 清理）
- **pt-project-folder-builder** —— PT 工程文件夹批量生成
- **jianying-draft-toolkit** —— 剪映草稿工具箱（导出 / 导入多轨 / 交付包）
- **rename-unify** —— 素材批量命名统一
