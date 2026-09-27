# -*- coding: utf-8 -*-
"""S8 · 8.3：pt-tools 日志区默认折叠（v3.8.0）

验收点：
  ① 默认折叠（日志正文不占高度，主区归 Notebook）
  ② 折叠期间来日志 → 标题计数 +1 且挂「● 新」角标
  ③ 点标题展开 → 正文可见、角标清除
  ④ 展开高度写进 cfg（log_height / log_open），默认不落盘脏配置

跑法：python tests/test_pt_log_collapse.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                     # noqa: E402

SRC = str(C.SRC)
sys.path.insert(0, os.path.join(SRC, "pt-tools"))

import tkinter as tk                                    # noqa: E402
import pt_tools_gui as m                                # noqa: E402

# 不污染真实 config.json：load 时清掉折叠相关键，save 走空实现
_orig_load = m.load_config
m.load_config = lambda: dict((k, v) for k, v in _orig_load().items()
                             if k not in ("log_open", "log_height"))
m.save_config = lambda cfg: None

CHECKS = []


def ck(name, cond, extra=""):
    CHECKS.append((name, bool(cond), extra))
    print("%s %s%s" % ("[OK]" if cond else "[FAIL]", name,
                       ("  <- " + str(extra)) if (extra and not cond) else ""))


app = m.App()
app.update_idletasks()


def mapped():
    app.update_idletasks()
    return bool(app.log_body.winfo_ismapped())


# ① 默认折叠
ck("默认折叠：日志正文不占高度", not mapped(), app.log_toggle_var.get())
ck("标题行显示折叠箭头", app.log_toggle_var.get().startswith("▸"), app.log_toggle_var.get())

# ② 折叠态计数 + 角标
app.log("第一条日志\n")
app.log("第二条日志\n")
ck("折叠态计数累加", app.log_count == 2, app.log_count)
ck("折叠态挂 ● 新 角标", app._log_unread and "新" in app.log_toggle_var.get(),
   app.log_toggle_var.get())
ck("日志确实写进了 Text",
   app.log_text.get("1.0", "end").count("第一条日志") == 1)

# ③ 展开
app.toggle_log(True)
ck("展开后正文可见", mapped())
ck("展开后箭头变 ▾", app.log_toggle_var.get().startswith("▾"), app.log_toggle_var.get())
ck("展开后角标清除", not app._log_unread and "新" not in app.log_toggle_var.get(),
   app.log_toggle_var.get())
h0 = app.winfo_height()
app.toggle_log(False)
ck("再折叠回单行", not mapped())
ck("折叠态窗口不高于展开态", app.winfo_height() <= h0, "%s vs %s" % (app.winfo_height(), h0))

# ④ 高度与展开态进 cfg
app.log_height_var.set(20)
app._on_log_height()
ck("高度改动生效", int(app.log_text.cget("height")) == 20,
   app.log_text.cget("height"))
ck("高度写入 cfg", app.cfg.get("log_height") == 20, app.cfg.get("log_height"))
app._on_log_height()
app.log_height_var.set(999)
app._on_log_height()
ck("高度钳位 4~40", app.cfg.get("log_height") == 40, app.cfg.get("log_height"))
app.toggle_log(True)
ck("展开态写入 cfg", app.cfg.get("log_open") is True, app.cfg.get("log_open"))

# ⑤ 清空归零
app.toggle_log(False)
app.log("再来一条\n")
app._clear_log()
ck("清空后计数归零", app.log_count == 0, app.log_count)
ck("清空后角标清除", not app._log_unread)
ck("清空后角标不残留于标题", "新" not in app.log_toggle_var.get(),
   app.log_toggle_var.get())

app.destroy()

bad = [n for n, ok_, _ in CHECKS if not ok_]
print("\n%d/%d 通过" % (len(CHECKS) - len(bad), len(CHECKS)))
sys.exit(1 if bad else 0)
