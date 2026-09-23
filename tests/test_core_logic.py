# -*- coding: utf-8 -*-
"""pt-audio-toolkit 核心功能测试（沙箱执行，不修改仓库源码/数据）

测试原则：
- 每个用例独立 try/except，失败记录后继续下一条（用户要求）
- 所有落盘动作都在 D:\\My-Temporary\\pt-toolkit-test\\sandbox\\ 下
- 不删除任何既有文件
"""
import importlib
import os
import shutil
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

# 本脚本会在本进程内 import 工具的 GUI 模块（它们 import tkinter）。
# 入口解释器若没有 tkinter（如托管版），先自愈重启 —— 否则会以
# ModuleNotFoundError 崩掉，看着像产品缺陷。
C.ensure_tk()

SRC = str(C.SRC)
SANDBOX = str(C.SANDBOX)

# 用例登记与沙箱目录一律走公共模块：
#   case  —— 区分 FAIL（断言不成立）/ ERROR（用例自身异常）/ SKIP（环境不满足）
#   fresh —— 只在测试临时区内建目录（越界拒绝）
case = C.case
fresh = C.fresh


# ===========================================================================
# 1. pt-project-folder-builder
# ===========================================================================
sys.path.insert(0, os.path.join(SRC, "pt-project-folder-builder"))
fb = importlib.import_module("folder_builder_gui")


@case("fb.parse_episodes 区间+去重+排序")
def _():
    eps, errs = fb.parse_episodes("1-10, 23, 38, 46-49")
    assert eps == list(range(1, 11)) + [23, 38, 46, 47, 48, 49], eps
    assert errs == [], errs
    assert fb.parse_episodes("")[0] == []
    assert fb.parse_episodes("")[1] == ["集数输入为空"]
    eps2, errs2 = fb.parse_episodes("5-3, x, 7")
    assert eps2 == [3, 4, 5, 7], eps2
    assert len(errs2) == 1, errs2
    return "eps=%s" % (eps[:5],)


@case("fb.build_project_name 命名规则")
def _():
    got = fb.build_project_name("10", "誓言", "D", "20260920", "7F")
    assert got == "10-誓言D_20260920_7F", got
    got2 = fb.build_project_name("", "誓言", "D", "20260920", "7F")
    assert got2 == "誓言D_20260920_7F", got2
    return got


@case("fb.build_episode_name 三种模式")
def _():
    assert fb.build_episode_name("睡父亲", "D", 1, "num") == "1"
    assert fb.build_episode_name("睡父亲", "D", 1, "name_num") == "睡父亲1"
    assert fb.build_episode_name("睡父亲", "D", 1, "name_level_num") == "睡父亲D1"
    return "ok"


@case("fb.detect_next_seq 目录扫描顺延")
def _():
    root = fresh("fb_seq")
    for n in ("1-a", "10-b", "3-c", "abc"):
        os.makedirs(os.path.join(root, n), exist_ok=True)
    got = fb.detect_next_seq(root)
    assert got == 11, got
    assert fb.detect_next_seq(os.path.join(root, "__not_exist__")) == 1
    return "next=%d" % got


@case("fb.plan_creation 完整规划（含模板目录）")
def _():
    tpl = fresh("fb_tpl")
    os.makedirs(os.path.join(tpl, "文件夹模板", "Audio"), exist_ok=True)
    os.makedirs(os.path.join(tpl, "文件夹模板", "Video", "Sub"), exist_ok=True)
    os.makedirs(os.path.join(tpl, "Project模板"), exist_ok=True)
    open(os.path.join(tpl, "Project模板", "TEMPlate.ptx"), "w").write("x")
    out = fresh("fb_out")
    proj, steps, warns, ep_names = fb.plan_creation(
        [1, 2], "誓言", "10", "D", "20260920", "7F", out, tpl, "项目根", "重命名", "name_num")
    assert proj.endswith("10-誓言D_20260920_7F"), proj
    assert ep_names == ["誓言1", "誓言2"], ep_names
    mk = [p for a, p in steps if a == "mkdir"]
    cp = [p for a, p in steps if a == "copy"]
    assert any(p.endswith("Audio") for p in mk), mk
    assert any(p.endswith(os.path.join("Video", "Sub")) for p in mk), mk
    assert len(cp) == 2 and cp[0].endswith("誓言1.ptx"), cp
    return "mkdir=%d copy=%d warns=%s" % (len(mk), len(cp), warns)


@case("fb.plan_creation 返回元组个数与调用处一致（回归 commit 145796f）")
def _():
    tpl = fresh("fb_tpl2")
    os.makedirs(os.path.join(tpl, "文件夹模板"), exist_ok=True)
    out = fresh("fb_out2")
    r = fb.plan_creation([], "x", "1", "D", "20260920", "7F", out, tpl,
                         "项目根", "none", "num")
    assert isinstance(r, tuple) and len(r) == 4, "plan_creation 元组长度 = %d" % len(r)
    return "4 元组 ok"


@case("fb.plan_creation ptx_mode=none 不复制")
def _():
    tpl = fresh("fb_tpl3")
    os.makedirs(os.path.join(tpl, "文件夹模板"), exist_ok=True)
    os.makedirs(os.path.join(tpl, "Project模板"), exist_ok=True)
    open(os.path.join(tpl, "Project模板", "T.ptx"), "w").write("x")
    out = fresh("fb_out3")
    _, steps, _, _ = fb.plan_creation([1], "x", "1", "D", "20260920", "7F", out, tpl,
                                      "项目根", "none", "num")
    assert not [p for a, p in steps if a == "copy"], steps
    return "ok"


# ===========================================================================
# 2. rename-unify
# ===========================================================================
sys.path.insert(0, os.path.join(SRC, "rename-unify", "code"))
cr = importlib.import_module("core_rules")

SHORT_TPL = "{片名} {集数}_{轨道信息}"


def _tg(mix=None, bus=None, stem=None, aifx=None, **over):
    """构造目标表：模板传 None = 不单独配（回落全局模板）。

    over 用大写目标名传附加键，如 _tg(**{"BUS": {"enabled": False}})。
    """
    def one(name, d, tpl):
        e = {"name": name, "dir": d, "templates": [tpl] if tpl else []}
        e.update(over.get(name, {}))
        return e
    return cr.normalize_targets([one("MIX", "", mix), one("BUS", "BUS", bus),
                                 one("STEM", "STEM", stem), one("AIFX", "STEM", aifx)])


@case("ru.identify 目标 + 轨道信息两段式（含自由轨道信息）")
def _():
    R = cr.DEFAULT_RULES
    cases = [
        # 用户已交付的 17 集成品（全格式）—— 曾经 20/28 识别失败，现在必须全中
        ("法老 17集 0922 V01 7F_Master", ("MIX", "17", "Master")),
        ("法老 17集 0922 V01 7F_DX BUS", ("BUS", "17", "DX BUS")),
        ("法老 17集 0922 V01 7F_Ai FX 1", ("AIFX", "17", "Ai FX 1")),
        ("法老 17集 0922 V01 7F_MX Verb ST", ("STEM", "17", "MX Verb ST")),
        ("法老 17集 0922 V01 7F_DX UI", ("STEM", "17", "DX UI")),
        # 20 集源名（裸集数 + 自由轨道信息）
        ("法老20_DX BUS", ("BUS", "20", "DX BUS")),
        ("法老20_Master BUS", ("MIX", "20", "Master")),
        ("法老20_DX 1", ("STEM", "20", "DX 1")),
        ("法老20_Ai FX 3", ("AIFX", "20", "Ai FX 3")),
        ("法老13_FX 1 MON", ("STEM", "13", "FX 1 MON")),
        ("法老13_FX 2.dup1", ("STEM", "13", "FX 2.dup1")),
        # 早期前夫集（含 " Folder" 结尾旧写法）
        ("前夫 10集 0920 V01 7F_DX BUS", ("BUS", "10", "DX BUS")),
        ("前夫 01集 0920 V01 7F_BUS-DX", ("BUS", "01", "BUS-DX")),
        ("前夫1_DX Folder", ("BUS", "1", "BUS-DX")),
        ("前夫2_BUS DX Folder", ("BUS", "2", "BUS-DX")),
        ("前夫 1集 0920 V01 7F", ("MIX", "1", "Master")),
        ("前夫 10集 0920 V01 7F_MX 2", ("STEM", "10", "MX 2")),
    ]
    bad = []
    for stem, want in cases:
        h = cr.identify(stem, R)
        got = None if h is None else (h.target, h.ep, h.info)
        if got != want:
            bad.append("%s -> %s (want %s)" % (stem, got, want))
    assert not bad, bad
    assert cr.identify("完全乱写的东西", R) is None
    return "%d 条识别全部命中" % len(cases)


@case("ru.render 轨道信息原样保留（不补零）+ 双扩展名防护 + {档位} 兼容")
def _():
    F = cr.DEFAULT_FIELDS
    assert cr.render(cr.DEFAULT_TEMPLATE, "10", "DX BUS", F) == \
        "前夫 10集 0920 V01 7F_DX BUS"
    # ⚠️ 回归护栏：此处曾把窄序号补零（`MX 2` -> `MX 02`），会把用户已交付的
    #    17 集成品（..._Ai FX 1.wav）改名 —— 已永久取消，见 core.normalize_info。
    assert cr.render(cr.DEFAULT_TEMPLATE, "1", "MX 2", F) == \
        "前夫 01集 0920 V01 7F_MX 2"
    assert cr.render(cr.DEFAULT_TEMPLATE + ".wav", "1", "Master", F) == \
        "前夫 01集 0920 V01 7F_Master"
    # 旧占位符 {档位} 仍可用（归一化为 {用户}）
    assert cr.render("{片名} {集数}集 {档位}", "1", "x", F) == "前夫 01集 7F"
    try:
        cr.render("{不存在的字段}", "1", "Master", F)
        raise AssertionError("未知占位符未报 RuleError")
    except cr.RuleError:
        pass
    return "ok"


@case("ru.build_item 扩展名沿用源文件")
def _():
    r = cr.build_item(r"D:\x\法老20_DX BUS.wav", cr.DEFAULT_TEMPLATE,
                      cr.DEFAULT_RULES, cr.DEFAULT_FIELDS)
    # v1.3.0：BUS 出厂默认挂「短格式」（不再是全局全格式回落）
    assert r and r[0].endswith("20_DX BUS.wav"), r
    assert not r[0].endswith(".wav.wav"), r
    return r[0]


@case("ru.模板与目标拆开：MIX 全格式 / BUS·STEM 短格式")
def _():
    F = cr.DEFAULT_FIELDS
    tg = _tg(mix=cr.DEFAULT_TEMPLATE, bus=SHORT_TPL, stem=SHORT_TPL, aifx=SHORT_TPL)
    r1 = cr.build_item(r"D:\x\20\法老20_Master BUS.wav", cr.DEFAULT_TEMPLATE,
                       cr.DEFAULT_RULES, F, root=r"D:\x", targets=tg)
    # 注意：源名里的「法老」会被捕获并**优先于**全局字段「前夫」，所以是法老
    assert r1 and os.path.basename(r1[0]) == "法老 20集 0920 V01 7F_Master.wav", r1
    r2 = cr.build_item(r"D:\x\20\法老20_DX BUS.wav", cr.DEFAULT_TEMPLATE,
                       cr.DEFAULT_RULES, F, root=r"D:\x", targets=tg)
    assert r2 and os.path.basename(r2[0]) == "法老 20_DX BUS.wav", r2
    assert os.path.basename(os.path.dirname(r2[0])) == "BUS", r2
    r3 = cr.build_item(r"D:\x\20\法老20_Ai FX 1.wav", cr.DEFAULT_TEMPLATE,
                       cr.DEFAULT_RULES, F, root=r"D:\x", targets=tg)
    assert r3 and os.path.basename(os.path.dirname(r3[0])) == "STEM", r3
    return "Master 全格式 / BUS·AIFX 短格式 均生效"


@case("ru.保持原名（只归类、不改名）")
def _():
    F = cr.DEFAULT_FIELDS
    tg = _tg(mix=cr.DEFAULT_TEMPLATE, bus=cr.KEEP_NAME, stem=cr.KEEP_NAME)
    r = cr.build_item(r"D:\x\20\法老20_DX BUS.wav", cr.DEFAULT_TEMPLATE,
                      cr.DEFAULT_RULES, F, root=r"D:\x", targets=tg)
    assert r and os.path.basename(r[0]) == "法老20_DX BUS.wav", r
    assert os.path.basename(os.path.dirname(r[0])) == "BUS", r
    return "只挪不改名"


@case("ru.目录级字段继承（同一集不出现两个日期）")
def _():
    root = fresh("ru_dirdefault")
    for f in ("法老 12集 0922 V01 7F_Master.wav", "法老12_DX BUS.wav"):
        open(os.path.join(root, f), "wb").write(b"RIFF")
    items, _st = cr.make_plan(cr.scan_dir(root), cr.DEFAULT_TEMPLATE,
                              cr.DEFAULT_RULES, cr.DEFAULT_FIELDS, root=root,
                              date_from_mtime=False)
    dsts = [i.dst for i in items if i.status == ""]
    assert dsts, "应至少规划出 1 条改名"
    # Master（全格式）名里必须继承 0922，不许混进全局 0920；
    # BUS（v1.3.0 短格式）名里没有日期段 → 改断言「落点仍在 0922 集目录下」
    by_bus = [d for d in dsts if "BUS" in d]
    assert any(os.path.basename(d) == "法老 12集 0922 V01 7F_Master.wav" for d in dsts), dsts
    assert all("法老 12集 0922 V01 7F" in d for d in by_bus), dsts
    return str([os.path.basename(d) for d in dsts])


@case("ru.make_plan 冲突/跳过/错误三类状态")
def _():
    root = fresh("ru_plan")
    files = ["法老20_DX BUS.wav", "法老20_MX BUS.wav",
             "乱写.wav", "法老20_FX BUS.wav"]
    paths = []
    for f in files:
        p = os.path.join(root, f)
        open(p, "wb").write(b"RIFF")
        paths.append(p)
    # 让 FX 的目标名已被占用 → conflict（平铺布局下目标会新建集目录）
    # v1.3.0：BUS 出厂默认短格式 → 占用名要按短格式写
    conf_dir = os.path.join(root, "法老 20集 0920 V01 7F", "BUS")
    os.makedirs(conf_dir, exist_ok=True)
    open(os.path.join(conf_dir, "法老 20_FX BUS.wav"), "wb").write(b"RIFF")
    items, stats = cr.make_plan(paths, cr.DEFAULT_TEMPLATE, cr.DEFAULT_RULES,
                                cr.DEFAULT_FIELDS, root=root,
                                date_from_mtime=False)
    assert stats["total"] == 4, stats
    assert stats["error"] == 1, stats
    assert stats["conflict"] == 1, stats
    assert stats["rename"] == 2, stats
    return str(stats)


@case("ru.make_plan + apply_plan + undo_from_log 端到端")
def _():
    root = fresh("ru_e2e")
    for f in ("法老20_DX BUS.wav", "法老20_MX 2.wav"):
        open(os.path.join(root, f), "wb").write(b"RIFF")
    paths = cr.scan_dir(root)
    items, stats = cr.make_plan(paths, cr.DEFAULT_TEMPLATE, cr.DEFAULT_RULES,
                                cr.DEFAULT_FIELDS, root=root,
                                date_from_mtime=False)
    assert stats["rename"] == 2, stats
    log = os.path.join(root, "log.csv")
    done, failed, lp = cr.apply_plan(items, write_log=True, log_path=log)
    assert len(done) == 2 and not failed, (done, failed)
    ep_dir = os.path.join(root, "法老 20集 0920 V01 7F")
    after = (sorted(os.listdir(os.path.join(ep_dir, "BUS"))) +
             sorted(os.listdir(os.path.join(ep_dir, "STEM"))))
    # v1.3.0：BUS/STEM 出厂默认短格式
    assert "法老 20_DX BUS.wav" in after, after
    assert "法老 20_MX 2.wav" in after, after
    # 撤销（倒序：先归位回原处，再改回原名）
    n = cr.undo_from_log(lp, dry_run=False)
    back = sorted(os.listdir(root))
    assert "法老20_DX BUS.wav" in back, back
    assert "法老20_MX 2.wav" in back, back
    return "renamed=2 undone=%s files=%s" % (n, back)


@case("ru.target_state 目标启停 / 限定集数（原命名清单能力）")
def _():
    tg = _tg(**{"BUS": {"enabled": False}, "STEM": {"eps": "20"}})
    ok, why = cr.target_state(tg, "BUS", "20")
    assert not ok and "取消勾选" in why, (ok, why)
    ok2, why2 = cr.target_state(tg, "STEM", "12")
    assert not ok2 and "限定集数" in why2, (ok2, why2)
    ok3, _ = cr.target_state(tg, "STEM", "20")
    assert ok3, "20 集在限定范围内应放行"
    return "ok"


@case("ru.parse_eps / normalize_ep 集数解析")
def _():
    assert cr.parse_eps("1,3-5") == {1, 3, 4, 5}
    assert cr.parse_eps("1，3、5;7") == {1, 3, 5, 7}
    assert cr.parse_eps("") == set()
    assert cr.normalize_ep("9") == "09" and cr.normalize_ep("10") == "10"
    return "ok"


@case("ru.平铺分类目录自动重组为集目录（原 build_regroup_plan 已内联）")
def _():
    root = fresh("ru_regroup")
    os.makedirs(os.path.join(root, "BUS"), exist_ok=True)
    os.makedirs(os.path.join(root, "10"), exist_ok=True)
    open(os.path.join(root, "BUS", "前夫 10集 0920 V01 7F_DX BUS.wav"),
         "wb").write(b"RIFF")
    items, stats = cr.make_plan(cr.scan_dir(root), cr.DEFAULT_TEMPLATE,
                                cr.DEFAULT_RULES, cr.DEFAULT_FIELDS, root=root)
    assert stats["rename"] == 1, stats
    d = items[0].dst
    assert os.path.basename(os.path.dirname(d)) == "BUS", d
    assert "10集" in os.path.basename(os.path.dirname(os.path.dirname(d))), d
    return os.path.relpath(d, root)


@case("ru.v1.3.0 mtime 日期兜底 + 集目录改名 + 空目录清点")
def _():
    import datetime
    root = fresh("ru_v13")
    os.makedirs(os.path.join(root, "13"), exist_ok=True)
    open(os.path.join(root, "13", "法老13_Master BUS.wav"), "wb").write(b"RIFF")
    items, stats = cr.make_plan(cr.scan_dir(root), cr.DEFAULT_TEMPLATE,
                                cr.DEFAULT_RULES, cr.DEFAULT_FIELDS, root=root,
                                date_from_mtime=True, rename_ep_dirs=True)
    assert stats["rename"] == 1, stats
    it = items[0]
    # 沙箱文件是刚建的 → mtime = 今天；目录与文件名都按今天日期渲染
    today = datetime.datetime.now().strftime("%m%d")
    ep_name = os.path.basename(os.path.dirname(it.dst))
    assert ep_name == "法老 13集 %s V01 7F" % today, ep_name
    assert os.path.basename(it.dst) == "法老 13集 %s V01 7F_Master.wav" % today, it.dst
    # 关掉 mtime → 回落全局字段 0920
    items2, _ = cr.make_plan(cr.scan_dir(root), cr.DEFAULT_TEMPLATE,
                             cr.DEFAULT_RULES, cr.DEFAULT_FIELDS, root=root,
                             date_from_mtime=False, rename_ep_dirs=True)
    ep_name2 = os.path.basename(os.path.dirname(items2[0].dst))
    assert ep_name2 == "法老 13集 0920 V01 7F", ep_name2
    # 关掉集目录改名 → 就地沿用 13/
    items3, _ = cr.make_plan(cr.scan_dir(root), cr.DEFAULT_TEMPLATE,
                             cr.DEFAULT_RULES, cr.DEFAULT_FIELDS, root=root,
                             date_from_mtime=False, rename_ep_dirs=False)
    assert os.path.basename(os.path.dirname(items3[0].dst)) == "13", items3[0].dst
    # 执行「改名模式」的 items2 → 文件搬进新名集目录，旧目录 13/ 空壳
    # list_emptied_dirs 只报告、不代删
    done, failed, _lp = cr.apply_plan(items2, write_log=False)
    assert len(done) == 1 and not failed, (done, failed)
    emptied = cr.list_emptied_dirs(items2)
    assert any(os.path.basename(d) == "13" for d in emptied), emptied
    return "mtime=%s / 改名=%s / 空壳=%d" % (today, ep_name, len(emptied))


@case("ru.manual_plan_item 人工分类走同一套落点/渲染")
def _():
    F = cr.DEFAULT_FIELDS
    assert cr.guess_info_from_name("法老20_DX BUS.wav") == "DX BUS"
    assert cr.guess_info_from_name("杂项.wav") == "杂项"
    mi = cr.manual_plan_item(r"D:\x\20\乱七八糟.wav", "20", "BUS", "DX BUS",
                             cr.DEFAULT_TEMPLATE, F, root=r"D:\x")
    # v1.3.0：BUS 出厂默认短格式；人工分类与自动识别同一套落点
    assert os.path.basename(mi.dst) == "前夫 20_DX BUS.wav", mi.dst
    assert os.path.basename(os.path.dirname(mi.dst)) == "BUS", mi.dst
    return os.path.relpath(mi.dst, r"D:\x")


@case("ru.v1.3.1 Demo 无集数工程（识别/日期归一/折叠渲染/目录改名）")
def _():
    # 识别：全格式（PT 导出原态）与短格式（已归位态）都要认
    h = cr.identify("出轨Demo 20260923 V02 7F_Master", cr.DEFAULT_RULES)
    assert h and h.target == "MIX" and h.ep == "" and h.info == "Master", h
    # 日期归一化：8 位 → 4 位（用户手工标准答案 `出轨Demo 0923 V02 7F`）
    assert h.captured["日期"] == "0923" and h.captured["片名"] == "出轨Demo", h.captured
    h2 = cr.identify("出轨Demo DX BUS", cr.DEFAULT_RULES)
    assert h2 and h2.target == "BUS" and h2.info == "DX BUS", h2
    h3 = cr.identify("出轨Demo Ai FX 1", cr.DEFAULT_RULES)
    assert h3 and h3.target == "AIFX", h3
    h4 = cr.identify("出轨Demo MX Verb ST", cr.DEFAULT_RULES)
    assert h4 and h4.target == "STEM", h4
    # 渲染折叠：全格式去集数段、短格式连下划线一起折叠（空格分隔、无下划线）
    F = {"片名": "出轨", "日期": "0923", "版本": "V01", "用户": "7F"}
    assert cr.render(cr.DEFAULT_TEMPLATE, "", "Master", h.captured) == \
        "出轨Demo 0923 V02 7F_Master", \
        cr.render(cr.DEFAULT_TEMPLATE, "", "Master", h.captured)
    assert cr.render("{片名} {集数}_{轨道信息}", "", "DX BUS", h2.captured) == \
        "出轨Demo DX BUS", \
        cr.render("{片名} {集数}_{轨道信息}", "", "DX BUS", h2.captured)
    # 沙箱端到端：平铺旧名 → 目录改名 + Master 改名（8 位日期归一 4 位）
    root = fresh("ru_demo")
    open(os.path.join(root, "出轨Demo 20260923 V02 7F_Master.wav"), "wb").write(b"RIFF")
    items, stats = cr.make_plan(cr.scan_dir(root), cr.DEFAULT_TEMPLATE,
                                cr.DEFAULT_RULES, F, root=root,
                                date_from_mtime=True, rename_ep_dirs=True)
    assert stats["rename"] == 1 and stats["error"] == 0, stats
    rel = os.path.relpath(items[0].dst, root)
    assert rel == os.path.join("出轨Demo 0923 V02 7F", "出轨Demo 0923 V02 7F_Master.wav"), rel
    return rel


@case("ru.config 默认值/读写/清洗 + v1.2.0 新键与 {用户} 迁移")
def _():
    sys.path.insert(0, os.path.join(SRC, "rename-unify", "code"))
    cfgmod = importlib.import_module("config")
    d = cfgmod.load_config()
    assert "last_root" in d and isinstance(d["fields"], dict)
    assert "用户" in d["fields"] and "档位" not in d["fields"], d["fields"]
    assert isinstance(d.get("targets"), list) and isinstance(d.get("templates"), list)
    assert cfgmod.APP_VERSION >= "1.2.0", cfgmod.APP_VERSION
    cleaned = cfgmod._clean_enabled_types([{"type": "A"}, {"x": 1}, "bad", {"type": ""}])
    assert len(cleaned) == 1 and cleaned[0]["type"] == "A", cleaned
    # 旧配置 {档位} → {用户}：读旧文件必须搬值，不能静默丢
    import json as _json
    import tempfile as _tf
    fd, tmp = _tf.mkstemp(suffix=".json")
    os.close(fd)
    with open(tmp, "w", encoding="utf-8") as fh:
        _json.dump({"fields": {"片名": "誓言", "档位": "5F"}}, fh, ensure_ascii=False)
    old_path = cfgmod.CONFIG_PATH
    cfgmod.CONFIG_PATH = tmp
    try:
        c2 = cfgmod.load_config()
        assert c2["fields"].get("用户") == "5F", c2["fields"]
        assert "档位" not in c2["fields"], c2["fields"]
    finally:
        cfgmod.CONFIG_PATH = old_path
        os.remove(tmp)
    return "ok"


# ===========================================================================
# 3. jianying-draft-toolkit
# ===========================================================================
JY = os.path.join(SRC, "jianying-draft-toolkit", "code")
sys.path.insert(0, JY)
jycfg = importlib.import_module("core.config")
jymain = importlib.import_module("main")


@case("jy.core.config 默认配置字段完整性与新字段")
def _():
    d = jycfg.DEFAULT_CONFIG
    for k in ("name_templates", "name_templates_active", "export_mode",
              "track_name_template", "export_aaf", "aaf_media_mode"):
        assert k in d, "DEFAULT_CONFIG 缺字段: %s" % k
    assert isinstance(d["name_templates"], list) and d["name_templates_active"]
    return "字段数=%d" % len(d)


@case("jy.core.config init_config 是否保留新字段（BUG 探针）")
def _():
    import json as _json
    p = os.path.join(fresh("jy_init"), "config.json")
    p = __import__("pathlib").Path(p)
    old = {"output_dir": "D:/tmp/o", "name_templates": ["A", "B"],
           "name_templates_active": ["B"], "export_mode": ["tracks", "clips"],
           "track_name_template": "{项目名}_{轨道名}", "export_aaf": True,
           "aaf_media_mode": "embed"}
    p.write_text(_json.dumps(old, ensure_ascii=False), encoding="utf-8")
    # 直接调核心：写回应基于 DEFAULT_CONFIG 合并，而不是整体替换
    sys.stdin = open(os.devnull)
    try:
        jycfg.init_config(p)
    finally:
        sys.stdin = sys.__stdin__
    now = _json.loads(p.read_text(encoding="utf-8"))
    lost = [k for k in ("name_templates", "name_templates_active", "export_mode",
                        "export_aaf", "aaf_media_mode") if k not in now]
    assert not lost, "init_config 丢字段: %s -> 现有键 %s" % (lost, sorted(now))
    return "保留 ok"


@case("jy.apply_cli_overrides 参数覆盖与消费")
def _():
    cfg = {}
    args = ["--output-dir", "D:/o", "--format", "wav", "--bitrate", "320",
            "--mode", "clips", "--aaf", "--refresh", "D:/draft"]
    cfg = jymain.apply_cli_overrides(cfg, args)
    assert cfg["output_dir"] == "D:/o", cfg
    assert cfg["audio_format"] == "wav"
    assert cfg["bitrate_kbps"] == 320
    assert cfg["export_mode"] == "clips"
    assert cfg["export_aaf"] is True
    assert cfg["skip_existing"] is False
    assert args == ["D:/draft"], args
    return "剩余位置参数=%s" % args


@case("jy.check_environment 环境自检可运行")
def _():
    r = jymain.check_environment()
    assert isinstance(r, dict) and "Python" in r and "ffmpeg" in r, r
    return {k: (v[0], v[1]) for k, v in r.items()}


@case("jy.find_jy_draftc 定位解密工具")
def _():
    p = jymain.find_jy_draftc()
    assert p is not None
    return "%s (exists=%s)" % (p, p.exists())


@case("jy.execute_export 模式归一化（mode 字符串兼容）")
def _():
    cfg = {"output_dir": os.path.join(fresh("jy_exec"), "o"), "export_mode": "clips",
           "skip_existing": False}
    root = os.path.join(SANDBOX, "jy_exec", "empty_drafts")
    os.makedirs(root, exist_ok=True)
    stats = jymain.execute_export(cfg, __import__("pathlib").Path(root), draft_dirs=[])
    assert stats == {"success": 0, "failed": 0, "skipped": 0}, stats
    return str(stats)


# ===========================================================================
# 4. pt-tools
# ===========================================================================
sys.path.insert(0, os.path.join(SRC, "pt-tools"))
pt = importlib.import_module("pt_tools_gui")


@case("pt.PathResolver 技能脚本路径拼装")
def _():
    r = pt.PathResolver(os.path.join(SRC, "pt-tools", "skills"))
    p = r.script("pt-scanner")
    assert p.endswith(os.path.join("pt-scanner", "scripts", "pt_scan.py")), p
    ok, msg = r.status()
    return "script=%s status=%s" % (p, (ok, msg))


@case("pt 技能脚本文件齐全（3 技能 × scripts）")
def _():
    base = os.path.join(SRC, "pt-tools", "skills")
    missing = []
    for sk, fn in (("pt-scanner", "pt_scan.py"), ("pt-exporter", "pt_export.py"),
                   ("pt-cleaner", "pt_clean.py")):
        p = os.path.join(base, sk, "scripts", fn)
        if not os.path.isfile(p):
            missing.append(p)
    assert not missing, missing
    return "3/3 齐全"


# ===========================================================================
# 汇总
# ===========================================================================
sys.exit(C.report("核心功能测试结果", tail_lines=14))
