# pt-tools 三层拆分 · 切分坐标与进展记录（W1-D2）

> 用途：W1「三层拆分 + 入口薄壳」的知识沉淀物。供后续会话 / miyo 检索恢复上下文，
> 不要再从头推导 line 偏移。**状态：D2 拆分片已产出（9 模块 + 3 包），W1 尚未完成**
> （最后一步：`pt_tools_gui.py` 由 monolith 换成薄壳 shim + 测试接线）。

## 一、切片坐标（monolith: `src\pt-tools\pt_tools_gui.py`，3449 行）

| 目标模块 | 行区间 `sl(start, end)` ｜ end=开区间 | 内容 |
|---|---|---|
| `core/settings.py` | `sl(33,88) + sl(156,188)` | 常量/路径/版本 块（33–88）+ 版本+语言常量 块（156–188） |
| `core/notify.py` | `sl(90,154)` | toast 托盘通知（ctypes 局部导入） |
| `core/i18n.py` | `sl(190,835) + I18N_FOOT` | TEXTS 词条 + `_cur_lang`/set_lang/T/detect；FOOT 补 `get_lang()` |
| `core/config.py` | `sl(837,905)` | 配置读写/迁移 |
| `core/paths.py` | `sl(908,982)` | `class PathResolver`（脚本/venv 路径解析 + detect） |
| `worker/runner.py` | `sl(985,1155)` | `class CmdWorker` + `ptsl_online` 端口探测 |
| `core/naming.py` | `sl(1158,1400)` | 标题/集数命名、`build_export_cmds` |
| `core/logs.py` | `sl(1403,1429)` | 日志 |
| `gui/app.py` | `sl(1432,3445)` | `class App` + 页签 + main |

**关键切片陷阱**（踩过的坑）：
1. 单文件 GUI 从外部读语言态 `_cur_lang`，三层拆分后 `_cur_lang` 是 `core/i18n` 私有，
   GUI 只能走 `get_lang()`。替换要**双向**：`_cur_lang ==` → `get_lang() ==` **并且**
   `== _cur_lang` → `== get_lang()`（GUI 里有 `if lang == _cur_lang:`，会漏）。
2. `assert "_cur_lang =" not in gui` 会**误伤** `_cur_lang ==` 正常比较——先替换、再断言，
   且断言 needle 不要带尾随空格。
3. `sl(start,end)` 的 `end` 是**开区间**（+1）。检查边长对其最重要的是**不要用 .pyc**——
   那是二进制的 null bytes，`py_compile` 会误报；只看 `.py`。

## 二、薄壳 shim 的公共面（test 契约）

tests 用 `import pt_tools_gui as pt`，只需 re-export 以下名字即可过接线测试：

```python
# src\pt-tools\pt_tools_gui.py  ← 替换 monolith
from core.settings import ...                    # 版本等若被 GUI 引用
from core.i18n import T, get_lang, set_lang, detect_system_lang
from core.config import load_config, save_config
from core.paths import PathResolver              # pt.PathResolver（含 .detect）
from core.naming import build_export_cmds, parse_video_duration_output
from worker.runner import CmdWorker, ptsl_online # pt.CmdWorker、pt.ptsl_online
from gui.app import App                          # pt.App
```

测试引用的确切名字（已扫全 tests\test_*.py）：
- `test_wiring.py` → `pt.App`、`pt.CmdWorker`、`pt.PathResolver`
- `test_pt_modes.py` → `pt.App`、`pt.CmdWorker`、`pt.PathResolver`、
  `pt.build_export_cmds`、`pt.parse_video_duration_output`、`pt.ptsl_online`

## 三、待办（W1 剩余）
- [ ] `pt_tools_gui.py` → 薄壳 shim（上），保留 `if __name__ == "__main__": main()`
- [ ] `import pt_tools_gui as pt` → `(SRC\pt-tools).App()` 无 PTSL 环境应可构造（防炸）
- [ ] 跑 `tests\test_wiring.py` + `tests\test_pt_modes.py`（无 PT 环境部分）
- [ ] 补 W2（诊断包导出）前先 commit W1

## 四、沉淀优先级（miyo 待服务起来）
- miyo CLI 当前仅 search（服务未起）。索引恢复后：上面的「切片坐标表」+「双向替换坑」优先沉淀。
