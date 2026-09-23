# tests/ —— pt-audio-toolkit 回归测试

四个工具（pt-tools / pt-project-folder-builder / jianying-draft-toolkit / rename-unify）的回归测试。

> 这批脚本原在临时目录 `D:\My-Temporary\pt-toolkit-test\`，临时目录随时会被清理，
> 而它是当时唯一的测试资产 —— 2026-09-23 收编入库（改进方案 A1），并顺手做了跨机化（A2）。

---

## 前提

| 项 | 要求 |
|---|---|
| 解释器 | 机器上需装有**带 tkinter 的 Python**（GUI 用例必需；托管版通常没有）。入口用哪个 python 起无所谓，脚本会自行切换 |
| Pro Tools | `pt-scan` / `pt-export` / `pt-clean` 的端到端需要 PT 在线（PTSL `127.0.0.1:31416`）；未开则相关项记 **SKIP**，不算失败 |
| 剪映 | `test_jy_multitpl.py` 需要本机装有剪映、且有草稿（默认读「前夫」，**只读**，产物落临时区） |
| 磁盘 | 测试产物落在 `D:\My-Temporary\pt-toolkit-test\`（可用 `PT_TEST_TMP` 改） |

---

## 跑法

```bash
python tests/run_import_tests.py     # 15 个模块逐个 import
python tests/test_core_logic.py      # 24 项核心逻辑（与 GUI 解耦的纯函数）
python tests/test_wiring.py          # 5 项 GUI↔核心接线 + CmdWorker
python tests/run_gui_smoke.py        # 4 个界面建窗即销毁
python tests/test_jy_multitpl.py     # 剪映片段模式 + 多命名模板端到端（真实草稿）
```

**用哪个 python 起都可以。** `test_core_logic.py` / `test_wiring.py` 会在**本进程内**
import 工具 GUI 模块（需要 tkinter）；入口解释器若没有 tkinter，它们会先经
`_common.ensure_tk()` 用探测到的解释器**原样重启自己**，再继续跑。所以拿托管版
Python 直接起也不会崩 —— 历史上这会以 `ModuleNotFoundError: tkinter` 报错，
极易被误判成产品缺陷。

**解释器解析顺序**：`PT_TEST_PY` 环境变量 → 当前解释器 → `%LOCALAPPDATA%\Programs\Python\*` → PATH 上的 `python`。
候选会逐个探活 `import tkinter`；**全都不可用时明确报错**（不静默回落到无 tkinter 的解释器 —— 否则失败现象会变成莫名其妙的 ImportError）。

---

## 退出码

| 码 | 含义 |
|---|---|
| `0` | 全通过（含 SKIP） |
| `1` | 有 **FAIL** —— 断言不成立，产品行为可能有问题 |
| `2` | 有 **ERROR** —— 用例自身抛异常，多半是测试脚本跟不上接口变动 |

## 四态含义

| 态 | 含义 | 处置方向 |
|---|---|---|
| `PASS` | 通过 | — |
| `SKIP` | 环境不满足（PT 未开 / 缺可选依赖如 py-ptsl / 草稿不存在） | 补齐环境后重跑 |
| `FAIL` | 断言不成立 | 查**产品代码** |
| `ERROR` | 用例自身异常 | 查**测试脚本** |

区分 `FAIL` 与 `ERROR` 的意义：接口一变，满屏 FAIL 会掩盖真实缺陷；分开后可一眼看出是「功能坏了」还是「测试没跟上」。

---

## 环境变量

| 变量 | 用途 | 默认 |
|---|---|---|
| `PT_TEST_PY` | 指定带 tkinter 的解释器 | 自动探测 |
| `PT_TEST_TMP` | 测试临时根（沙箱） | `D:\My-Temporary\pt-toolkit-test`（无 D 盘则用系统临时目录） |
| `PT_EXE_ROOT` | exe 出口根（供 exe 核验用） | `D:\Ai-Files\Agent-Preset\exe` |
| `PT_JY_DRAFT` | 剪映草稿根 | `%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft` |
| `PT_JY_DRAFT_NAME` | 端到端用的草稿名 | `前夫` |

> 全部路径都不写死用户名 —— 家用机（用户名 `32112`）与公司机（`Administrator`）都能直接跑。

---

## 文件

| 文件 | 作用 |
|---|---|
| `_common.py` | 公共模块：跨机路径解析 + `PASS/SKIP/FAIL/ERROR` 分级与汇总 + `ensure_tk()` 无 tkinter 时自愈重启 |
| `run_import_tests.py` | 15 个模块逐个 import（缺可选依赖记 SKIP） |
| `test_core_logic.py` | 24 项与 GUI 解耦的纯函数逻辑 |
| `test_wiring.py` | GUI↔核心接线 + `CmdWorker` 真跑 subprocess（历史 bug 高发区） |
| `run_gui_smoke.py` / `gui_smoke_one.py` | 4 个界面真实建窗 → 600ms 自动销毁（独立子进程 + 超时） |
| `test_jy_multitpl.py` | 剪映片段模式 + 多命名模板端到端（真实草稿，只读） |

> **沙箱安全**：所有落盘动作都被限制在 `PT_TEST_TMP` 内；`_common.fresh()` 对越界路径直接拒绝，不会误删仓库或其他目录。
