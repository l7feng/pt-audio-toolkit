# pt-tools GUI 三层拆分（W1）· 拆分坐标与公共面

> 状态：**W1 已切片完成（10 个模块已写出并各自 import 通过）**
> 日期：2026-09-24 · 版本基线：`pt_tools_gui.py` v1.x（单文件 3449 行）
> 目标：monolith 按「core / worker / gui」三层拆包，`src\pt-tools\pt_tools_gui.py`
> 收敛为**薄壳 shim**（只 re-export），新逻辑各自落到新包，测试表面不变。

---

## 一、拆分产出（src\pt-tools 下）

| 包 | 模块 | 内容（来自 monolith 行区间） |
|---|---|---|
| `core/` | `settings.py` | 常量/路径常量 + 版本/构建日期（33–88 + 156–188） |
| `core/` | `notify.py` | Windows 托盘气泡 toast（90–154，ctypes 局部导入） |
| `core/` | `i18n.py` | TEXTS 词条 + `_cur_lang` 私有态 + `T/set_lang/get_lang/detect_system_lang`（190–835） |
| `core/` | `config.py` | 配置读写/迁移/默认值（837–905） |
| `core/` | `paths.py` | `PathResolver` + 技能目录解析（908–982） |
| `core/` | `naming.py` | 命名/导出命令生成（1158–1400） |
| `core/` | `logs.py` | 日志（1403–1429） |
| `worker/` | `runner.py` | `CmdWorker` / `ptsl_online` 探测（985–1155） |
| `gui/` | `app.py` | `App` + 页签 + main（1432–3445） |

切片方式：整段 `lines[start:end]` 搬运，仅做两处改写 —
1. GUI 读语言态：`_cur_lang ==` → `get_lang() ==`（左右两侧都换，见 i18n.py 推理）。
2. 逐模块头补最小 import + 包 docstring。

> 边界要点：`_cur_lang` 是 **i18n 私有**，GUI 只经 `get_lang()` 读、`set_lang()` 写；
> 其余模块（App/CmdWorker/PathResolver）的跨层引用全部 `from core/worker/gui import ...`。

## 二、薄壳 shim 必须 re-export 的公共面（由 tests 决定）

测试用 `import pt_tools_gui as pt`（tests\test_pt_modes.py、test_wiring.py），
只触及以下 5 个名字——shim 只需保证这 5 个即可过接线测试：

```python
# src\pt-tools\pt_tools_gui.py（薄壳）
from core.i18n import T, set_lang, get_lang
from core.config import load_config, save_config
from core.paths import PathResolver
from core.naming import build_export_cmds, parse_video_duration_output
from core.logs import setup_logging
from core.notify import toast
from worker.runner import CmdWorker, ptsl_online
from gui.app import App
if __name__ == "__main__":
    App().mainloop()
```

- `pt.App` / `pt.CmdWorker` / `pt.PathResolver`（含 `.detect`）—— test_wiring.py
- `pt.build_export_cmds` / `pt.parse_video_duration_output` —— test_pt_modes.py

尚未验证：App 在**无 Pro Tools / 无 PTSL**环境下实例化是否抛异常 → 下一步为
`App` 加「无 GUI / 无 PTSL 可离线构造」守卫或做 smoke 测试。

## 三、下一步（待办）

1. 💥 **先把 monolith 备份**再改：`copy src\pt-tools\pt_tools_gui.py pt_tools_gui.mono.bak`
2. 写薄壳 shim（上节代码）替换 `pt_tools_gui.py`，确认 `python -m py_compile` + import。
3. 跑 `tests\test_pt_modes.py`、`tests\test_wiring.py` —— 现有测试应原样通过（表面不变）。
4. 若 App 离线构造抛错 → 包一层「检测 PTSL 在线才建 App」或先做 gui smoke。
5. 提交。

## 四、沉淀记录

- **隐性知识**：PTSL 探测 = socket 直连 `127.0.0.1:31416`（1s timeout）→ 通才算在线；
  PT 进程在但端口不通 = C/D 态（看 `docs\ptsl-boot-plan.md` 三态矩阵）。盲杀 Pro Tools 是红线，
  默认绝不杀，必须 `--force-restart` + 二次确认。
- **本次教训**：用 `sl(start,end)` 切片时 `end` 必须是**开区间+1**；断言 `"_cur_lang =" not in
  gui` 会误伤正常读 `_cur_lang ==`，正确写法是**先 replace 再断言剩余为 0**。
- **miyo 未能接入**：`miyo` CLI 仅 search（service 未运行/仅只读），本会话知识沉淀落在
  repo `docs\`；后续 miyo 服务起来后再补索引。
