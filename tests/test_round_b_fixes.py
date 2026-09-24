# -*- coding: utf-8 -*-
"""方案B（v2.6.6）体验包回归：J4 默认值迁移 / J6 布局拆行 / G1 拖拽解析 / G2 滚动容器 / P4 版本条。

纯逻辑层 + 最小 GUI 冒烟（ScrollableFrame 可实例化）；无 PT/剪映真机依赖。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

C.ensure_tk()          # ScrollableFrame / App 基类都需要 tkinter

SRC = str(C.SRC)
case = C.case

# ───────── J4：剪映默认值与一次性迁移 ─────────
JY_CODE = os.path.join(SRC, "jianying-draft-toolkit", "code")
sys.path.insert(0, JY_CODE)

from core.config import DEFAULT_CONFIG, load_config    # noqa: E402


@case("J4 出厂默认：audio_format=wav / bitrate_kbps=320")
def j4_defaults():
    assert DEFAULT_CONFIG.get("audio_format") == "wav", DEFAULT_CONFIG.get("audio_format")
    assert DEFAULT_CONFIG.get("bitrate_kbps") == 320, DEFAULT_CONFIG.get("bitrate_kbps")


@case("J4 一次性迁移：旧默认 mp3/192 → wav/320，且写入标记")
def j4_migrate_once(tmp=None):
    d = C.fresh("j4_mig")
    p = Path(d) / "config.json"
    p.write_text(json.dumps({"audio_format": "mp3", "bitrate_kbps": 192}),
                 encoding="utf-8")
    cfg = load_config(p)
    assert cfg["audio_format"] == "wav" and cfg["bitrate_kbps"] == 320, cfg
    assert cfg.get("_migrated_266") is True, cfg
    disk = json.loads(p.read_text(encoding="utf-8"))
    assert disk["_migrated_266"] is True, disk          # 已写回盘


@case("J4 迁移只跑一次：用户特意改回 mp3/192 不会被反复覆盖")
def j4_migrate_idempotent():
    d = C.fresh("j4_idem")
    p = Path(d) / "config.json"
    p.write_text(json.dumps({"audio_format": "mp3", "bitrate_kbps": 192}),
                 encoding="utf-8")
    cfg1 = load_config(p)                               # 第一次：迁移
    assert cfg1["audio_format"] == "wav", cfg1
    cfg2 = dict(cfg1)
    cfg2.update({"audio_format": "mp3", "bitrate_kbps": 192})   # 用户特意改回
    p.write_text(json.dumps(cfg2), encoding="utf-8")
    cfg3 = load_config(p)                               # 有标记 → 不再覆盖
    assert cfg3["audio_format"] == "mp3" and cfg3["bitrate_kbps"] == 192, cfg3


@case("J4 UI：wav 下码率置灰逻辑（_sync_mode 分支存在且读 var_format）")
def j4_ui_gate():
    src = open(os.path.join(JY_CODE, "tabs", "export_tab.py"),
               encoding="utf-8").read()
    assert 'self.var_format.get() == "wav"' in src, "缺少 wav 置灰判断"
    assert 'var_format.trace_add' in src, "格式变化未联动 _sync_mode"


# ───────── J6：导出配置区拆行 ─────────
@case("J6 拆行：码率标签独立列、重名策略独占一行（不再同格相挤）")
def j6_layout():
    src = open(os.path.join(JY_CODE, "tabs", "export_tab.py"),
               encoding="utf-8").read()
    assert "码率 kbps（仅 mp3）" in src, "码率标签应带「仅 mp3」说明"
    assert "音频格式（片段模式）" in src, "格式标签应注明作用范围"
    # 重名策略独占 row=3（旧版与格式/码率挤 row=2）
    assert 'text="重名策略").grid(\n            row=3' in src.replace(
        "\r\n", "\n"), "重名策略应独占 row=3"


# ───────── G2：ScrollableFrame ─────────
@case("G2 滚动容器：可实例化、inner 宽度联动注册、滚轮让位逻辑存在")
def g2_scrollable():
    from tabs.base import ScrollableFrame
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    sf = ScrollableFrame(root)
    sf.pack()
    inner = sf.inner
    assert inner.winfo_exists(), "inner 应可用"
    src = open(os.path.join(JY_CODE, "tabs", "base.py"), encoding="utf-8").read()
    assert "ttk.Treeview" in src and "_on_wheel" in src, "滚轮让位应覆盖 Treeview"
    src2 = open(os.path.join(JY_CODE, "tabs", "export_tab.py"),
                encoding="utf-8").read()
    assert "ScrollableFrame(self)" in src2, "导出页应已套用滚动容器"
    root.destroy()


# ───────── G1：拖拽 ─────────
@case("G1 drop 解析：花括号路径 / 多路径 / 纯路径")
def g1_split():
    sys.path.insert(0, os.path.join(SRC, "pt-tools"))
    from ptools.gui.app import split_dnd_data
    assert split_dnd_data("{C:/a b/c.txt}") == ["C:/a b/c.txt"]
    assert split_dnd_data("C:/a/b D:/c/d") == ["C:/a/b", "D:/c/d"]
    assert split_dnd_data("{C:/x y} {D:/z w}") == ["C:/x y", "D:/z w"]
    assert split_dnd_data("") == []
    sys.path.insert(0, os.path.join(SRC, "rename-unify", "code"))
    sys.modules.pop("main", None)   # 剪映的 main 已在模块缓存，弹出以免同名冲突
    import main as ru
    assert ru.split_dnd_data("{D:/目标 目录}") == ["D:/目标 目录"]


@case("G1 拖拽注册：ptools 档案/输出框 + rename-unify 目标目录框已接线")
def g1_wired():
    pt = open(os.path.join(SRC, "pt-tools", "ptools", "gui", "app.py"),
              encoding="utf-8").read()
    assert "enable_path_drop(self.entry_profile, self._drop_profile)" in pt
    assert "enable_path_drop(self.out_entry, self._drop_out)" in pt
    ru = open(os.path.join(SRC, "rename-unify", "code", "main.py"),
              encoding="utf-8").read()
    assert "enable_path_drop(entry_root, self._drop_root)" in ru


# ───────── P4：版本条 ─────────
@case("P4 版本条：pt_info_bar 词条存在且声明已验证版本")
def p4_banner():
    sys.path.insert(0, os.path.join(SRC, "pt-tools"))
    from ptools.core import i18n
    for lang, table in i18n.TEXTS.items():
        v = table.get("pt_info_bar", "")
        assert "25.6.1" in v and "602.0.0" in v, (lang, v)
    app_src = open(os.path.join(SRC, "pt-tools", "ptools", "gui", "app.py"),
                   encoding="utf-8").read()
    assert "self.pt_info" in app_src and "before=self.nb" in app_src


# ───────── F3 尾巴：出厂提示不再带个人项目名 ─────────
@case("F3 尾巴：folder-builder/ptools 出厂提示无「誓言」")
def f3_tail():
    fb = open(os.path.join(SRC, "pt-project-folder-builder",
                           "folder_builder_gui.py"), encoding="utf-8").read()
    assert "誓言" not in fb, "folder-builder 提示仍带个人项目名"
    pt = open(os.path.join(SRC, "pt-tools", "ptools", "core", "i18n.py"),
              encoding="utf-8").read()
    assert "誓言24" not in pt and "ShiYan24" not in pt, "ptools 提示仍带个人项目名"


if __name__ == "__main__":
    sys.exit(C.report("方案B（v2.6.6）体验包回归"))
