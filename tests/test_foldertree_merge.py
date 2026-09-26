# -*- coding: utf-8 -*-
"""D 档合并（F7+R2 · 甲案）回归：foldertree 建树核心 + rename-unify 第 5 页签接线

覆盖：
  1. 纯函数迁移一致性（命名拼装 / 集数解析 / 根名反解）
  2. **F5**：集数文件夹固定建在 Project 子目录（「项目根」选项已删）
  3. 端到端：造假模板根 → 规划 → 执行 → 断言目录与 .ptx 落盘
  4. copy 铁律：**先确认源可复制再动目标**（源缺失时跳过，绝不删已有目标）
  5. 配置：foldertree 段逐键合并（缺键补默认，不 KeyError）
  6. 分层：foldertree 零 tkinter；main.py 第 5 页签已注册
"""
import os
import sys
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import SRC, TMP, case, fresh, report  # noqa: E402

RENAME_CODE = str(SRC / "rename-unify" / "code")
if RENAME_CODE not in sys.path:
    sys.path.insert(0, RENAME_CODE)

import foldertree as FT  # noqa: E402


def _make_template(root):
    """造一个假模板根：文件夹模板/{Audio,Video} + Project模板/tpl.ptx。"""
    tpl_root = os.path.join(root, "00文件夹模板")
    for sub in ("Audio", "Video", "Audio/Sub"):
        os.makedirs(os.path.join(tpl_root, "文件夹模板", sub), exist_ok=True)
    ptx_dir = os.path.join(tpl_root, "Project模板")
    os.makedirs(ptx_dir, exist_ok=True)
    ptx = os.path.join(ptx_dir, "template.ptx")
    with open(ptx, "w", encoding="utf-8") as fh:
        fh.write("fake ptx")
    return tpl_root, ptx


@case("1 · 命名拼装：项目根名与三种集数命名")
def _():
    assert FT.build_project_name("15", "测试", "D", "20260925", "7F") == \
        "15-测试D_20260925_7F", "项目根名形态不符"
    assert FT.build_project_name("", "测试", "D", "20260925", "7F") == \
        "测试D_20260925_7F", "序号为空应退化、不留前导连字符"
    assert FT.build_episode_name("睡父亲", "D", 3, "num") == "3"
    assert FT.build_episode_name("睡父亲", "D", 3, "name_num") == "睡父亲3"
    assert FT.build_episode_name("睡父亲", "D", 3, "name_level_num") == "睡父亲D3"
    return "项目根名 / 集数三模式 全部符合"


@case("2 · 集数解析：区间 + 去重 + 非法片段")
def _():
    eps, errs = FT.parse_episodes("1-3, 5, 5, 8")
    assert eps == [1, 2, 3, 5, 8], eps
    assert not errs, errs
    eps2, errs2 = FT.parse_episodes("abc, 7")
    assert eps2 == [7] and errs2, "非法片段应进 errors 且不抛异常"
    eps3, errs3 = FT.parse_episodes("")
    assert eps3 == [] and errs3, "空输入应报「集数输入为空」"
    return "区间/去重/非法/空 四类均正确"


@case("3 · F6 根名反解（15-测试D_20260925_7F）")
def _():
    info = FT.parse_project_root_name("15-测试D_20260925_7F")
    assert info == {"name": "测试", "level": "D", "date": "20260925", "user": "7F"}, info
    assert FT.parse_project_root_name("随手建的文件夹") is None
    # 无等级（结尾非 ABCD）时整体算项目名
    info2 = FT.parse_project_root_name("15-前夫_20260920_7F")
    assert info2["name"] == "前夫" and info2["level"] == "", info2
    return "带等级 / 无等级 / 非法 三类均正确"


@case("4 · F5：集数固定建在 Project 子目录（无「项目根」选项）")
def _():
    sb = fresh("foldertree_f5")
    tpl_root, _ptx = _make_template(sb)
    out_root = os.path.join(sb, "DAW-Project")
    os.makedirs(out_root, exist_ok=True)
    root, steps, _w, ep_names = FT.plan_creation(
        [1, 2], "测试", "1", "D", "20260927", "7F",
        out_root, tpl_root, ptx_mode="none", ep_naming="name_num")
    ep_dirs = [p for a, p in steps if a == "mkdir" and os.path.basename(p) in ep_names]
    assert len(ep_dirs) == 2, ep_dirs
    for p in ep_dirs:
        rel = os.path.relpath(p, root)
        assert rel.startswith("Project" + os.sep), \
            "F5 之后集数必须在 Project 子目录下，实际: %s" % rel
    # 默认常量即 Project 子目录
    assert FT.EP_PLACEMENT_DEFAULT == "Project子目录"
    # UI 不再暴露 placement：确认 PTX/命名模式常量里没有「项目根」
    assert all("项目根" not in v for _k, v in FT.PTX_MODES)
    return "集数落在 Project/<集名>，且无「项目根」选项残留"


@case("5 · 端到端：规划 → 执行 → 目录与 .ptx 落盘")
def _():
    sb = fresh("foldertree_e2e")
    tpl_root, src_ptx = _make_template(sb)
    out_root = os.path.join(sb, "DAW-Project")
    os.makedirs(out_root, exist_ok=True)
    eps, _errs = FT.parse_episodes("1-2")
    root, steps, warns, ep_names = FT.plan_creation(
        eps, "测试", "1", "D", "20260927", "7F",
        out_root, tpl_root, ptx_mode="原样复制", ep_naming="name_num")
    assert os.path.basename(root) == "1-测试D_20260927_7F", root
    assert not warns, warns
    created, skipped, failed = FT.apply_plan(
        root, steps, src_ptx=src_ptx, skip_existing=True)
    assert failed == 0, "有失败项: %s" % failed
    assert created > 0
    # 分类目录
    assert os.path.isdir(os.path.join(root, "Audio")), "分类目录未建立"
    assert os.path.isdir(os.path.join(root, "Audio", "Sub")), "子目录未递归建立"
    # 集数 + ptx
    for ep in ("测试1", "测试2"):
        ep_dir = os.path.join(root, "Project", ep)
        assert os.path.isdir(ep_dir), "集数目录缺失: %s" % ep_dir
        assert os.path.isfile(os.path.join(ep_dir, "template.ptx")), \
            "集数 .ptx 未复制: %s" % ep
    # 重跑：已存在项应跳过，不重复创建
    c2, s2, f2 = FT.apply_plan(root, steps, src_ptx=src_ptx, skip_existing=True)
    assert c2 == 0 and s2 == len(steps) and f2 == 0, (c2, s2, f2)
    return "新建 %d / 跳过 %d / 失败 %d；重跑全跳过（幂等）" % (created, skipped, failed)


@case("6 · copy 铁律：源缺失时跳过，绝不删已有目标文件")
def _():
    sb = fresh("foldertree_copyguard")
    dst_dir = os.path.join(sb, "ep")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "keep.ptx")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write("original")
    # 源不存在 —— 目标必须原样保留
    created, skipped, failed = FT.apply_plan(
        sb, [("copy", dst)], src_ptx=None, skip_existing=False)
    assert created == 0 and skipped == 1 and failed == 0, (created, skipped, failed)
    assert os.path.isfile(dst), "目标文件被删了！这是早期不可逆丢失 bug"
    assert open(dst, encoding="utf-8").read() == "original"
    # 源存在 + skip_existing=False → 覆盖
    src = os.path.join(sb, "src.ptx")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write("new")
    c2, _s2, _f2 = FT.apply_plan(sb, [("copy", dst)], src_ptx=src, skip_existing=False)
    assert c2 == 1 and open(dst, encoding="utf-8").read() == "new"
    return "源缺失→跳过保目标；源存在→覆盖；旧 bug 未复发"


@case("7 · 预检：模板缺失 / 输出盘不可写 一次列全")
def _():
    sb = fresh("foldertree_precheck")
    tpl_root, _ptx = _make_template(sb)
    problems = FT.precheck_build(tpl_root, sb, os.path.join(sb, "proj"), "none")
    assert problems == [], problems
    bad = FT.precheck_build(os.path.join(sb, "不存在"), sb,
                            os.path.join(sb, "proj"), "none")
    assert bad and "模板路径不存在" in bad[0], bad
    assert len(bad) == 1, "模板不存在时应立即返回，不再往下探测"
    return "正常 / 缺失 两类均符合"


@case("8 · 配置：foldertree 段逐键合并（缺键补默认）")
def _():
    import config as CFG
    assert "foldertree" in CFG.DEFAULTS
    # 模拟「用户只写了两个键」的旧配置
    import json
    p = CFG.CONFIG_PATH
    bak = None
    if os.path.exists(p):
        bak = p + ".bak-foldertree-test"
        shutil.copy2(p, bak)
    try:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"foldertree": {"name": "睡父亲"},
                       "last_root": r"D:\DAW-Project"}, fh, ensure_ascii=False)
        cfg = CFG.load_config()
        ft = cfg["foldertree"]
        assert ft["name"] == "睡父亲", "用户值应保留"
        assert ft["output_root"] == CFG.DEFAULTS["foldertree"]["output_root"], \
            "缺键应补默认，不能 KeyError"
        assert "placement" not in ft, "F5 之后不应有 placement 键"
    finally:
        if bak:
            shutil.copy2(bak, p)
            os.remove(bak)
        elif os.path.exists(p):
            os.remove(p)
    return "缺键补默认 + 用户值保留 + 无 placement 残留"


@case("9 · 分层：foldertree 零 tkinter；main.py 第 5 页签已注册")
def _():
    src = open(os.path.join(RENAME_CODE, "foldertree.py"), encoding="utf-8").read()
    assert "import tkinter" not in src and "from tkinter" not in src, \
        "foldertree 是纯逻辑层，不得 import tkinter"
    m = open(os.path.join(RENAME_CODE, "main.py"), encoding="utf-8").read()
    assert "import foldertree as FT" in m
    assert "self.tab_folder = ttk.Frame(nb)" in m
    assert 'nb.add(self.tab_folder' in m
    assert "工程文件夹" in m
    assert "项目根（1/" not in m, "F5：「项目根」单选按钮不应存在"
    return "分层干净 + 页签已接线 + 旧选项已删"


if __name__ == "__main__":
    sys.exit(report("D 档合并（F7+R2 甲案）：foldertree 建树 + rename-unify 第 5 页签"))
