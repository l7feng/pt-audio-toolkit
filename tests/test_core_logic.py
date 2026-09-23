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


@case("ru.identify 历史命名识别（4 类总线 + MIX + STEM）")
def _():
    R, F = cr.DEFAULT_RULES, cr.DEFAULT_FIELDS
    cases = [
        ("前夫 10集 0920 V01 7F_DX BUS", ("BUS", "10", "BUS-DX")),
        ("前夫1_DX Folder", ("BUS", "1", "BUS-DX")),
        ("前夫2_BUS DX Folder", ("BUS", "2", "BUS-DX")),
        ("前夫 01集 0920 V01 7F_BUS-DX", ("BUS", "01", "BUS-DX")),
        ("前夫 1集 0920 V01 7F", ("MIX", "1", "MIX")),
        ("前夫 10集 0920 V01 7F_Master", ("MIX", "10", "MIX-MASTER")),
        ("前夫 10集 0920 V01 7F_MX 2", ("Stem", "10", "STEM-MX-2")),
        ("前夫 10集 0920 V01 7F_STEM-DX-01", ("Stem", "10", "STEM-DX-01")),
    ]
    bad = []
    for stem, want in cases:
        got = cr.identify(stem, R, F)
        if got != want:
            bad.append("%s -> %s (want %s)" % (stem, got, want))
    assert not bad, bad
    assert cr.identify("完全乱写的东西", R, F) is None
    return "%d 条识别全部命中" % len(cases)


@case("ru.render 模板渲染 + 序号补零 + 双扩展名防护")
def _():
    assert cr.render(cr.DEFAULT_TEMPLATE, "10", "BUS-DX", cr.DEFAULT_FIELDS) == \
        "前夫 10集 0920 V01 7F_BUS-DX"
    assert cr.render(cr.DEFAULT_TEMPLATE, "1", "STEM-MX-2", cr.DEFAULT_FIELDS) == \
        "前夫 01集 0920 V01 7F_STEM-MX-02"
    assert cr.render(cr.DEFAULT_TEMPLATE + ".wav", "1", "MIX", cr.DEFAULT_FIELDS) == \
        "前夫 01集 0920 V01 7F_MIX"
    try:
        cr.render("{不存在的字段}", "1", "MIX", cr.DEFAULT_FIELDS)
        raise AssertionError("未知占位符未报 RuleError")
    except cr.RuleError:
        pass
    return "ok"


@case("ru.build_item 扩展名沿用源文件")
def _():
    r = cr.build_item(r"D:\x\前夫 10集 0920 V01 7F_DX BUS.wav",
                      cr.DEFAULT_TEMPLATE, cr.DEFAULT_RULES, cr.DEFAULT_FIELDS)
    assert r and r[0].endswith("7F_BUS-DX.wav"), r
    assert not r[0].endswith(".wav.wav"), r
    return r[0]


@case("ru.make_plan 冲突/跳过/错误三类状态")
def _():
    root = fresh("ru_plan")
    files = ["前夫 10集 0920 V01 7F_DX BUS.wav",
             "前夫 11集 0920 V01 7F_DX BUS.wav",
             "乱写.wav",
             "前夫 12集 0920 V01 7F_DX BUS.wav"]
    paths = []
    for f in files:
        p = os.path.join(root, f)
        open(p, "wb").write(b"RIFF")
        paths.append(p)
    # 让 12 集的目标名已被占用 → conflict
    open(os.path.join(root, "前夫 12集 0920 V01 7F_BUS-DX.wav"), "wb").write(b"RIFF")
    items, stats = cr.make_plan(paths, cr.DEFAULT_TEMPLATE, cr.DEFAULT_RULES,
                                cr.DEFAULT_FIELDS)
    assert stats["total"] == 4, stats
    assert stats["error"] == 1, stats
    assert stats["conflict"] == 1, stats
    return str(stats)


@case("ru.make_plan + apply_plan + undo_from_log 端到端")
def _():
    root = fresh("ru_e2e")
    for f in ("前夫 10集 0920 V01 7F_DX BUS.wav", "前夫 10集 0920 V01 7F_MX 2.wav"):
        open(os.path.join(root, f), "wb").write(b"RIFF")
    paths = cr.scan_dir(root)
    items, stats = cr.make_plan(paths, cr.DEFAULT_TEMPLATE, cr.DEFAULT_RULES,
                                cr.DEFAULT_FIELDS)
    assert stats["rename"] == 2, stats
    log = os.path.join(root, "log.csv")
    done, failed, lp = cr.apply_plan(items, write_log=True, log_path=log)
    assert len(done) == 2 and not failed, (done, failed)
    after = sorted(os.listdir(root))
    assert "前夫 10集 0920 V01 7F_BUS-DX.wav" in after, after
    assert "前夫 10集 0920 V01 7F_STEM-MX-02.wav" in after, after
    # 撤销
    n = cr.undo_from_log(lp, dry_run=False)
    back = sorted(os.listdir(root))
    assert "前夫 10集 0920 V01 7F_DX BUS.wav" in back, back
    return "renamed=2 undone=%s files=%s" % (n, back)


@case("ru.enabled_state 清单过滤（含 STEM 尾随 * 坑）")
def _():
    et = cr.DEFAULT_ENABLED_TYPES
    ok, _w = cr.enabled_state(et, "STEM-MX-2", "10")
    assert ok, "STEM-MX-2 应被 STEM-MX-* 覆盖（尾随 * 规则）"
    ok2, why2 = cr.enabled_state(et, "UNKNOWN-TYPE", "10")
    assert not ok2 and why2, (ok2, why2)
    ok3, _ = cr.enabled_state([], "任意", "1")
    assert ok3, "空清单 = 全放行"
    return "ok"


@case("ru.parse_eps / normalize_ep 集数解析")
def _():
    assert cr.parse_eps("1,3-5") == {1, 3, 4, 5}
    assert cr.parse_eps("1，3、5;7") == {1, 3, 5, 7}
    assert cr.parse_eps("") == set()
    assert cr.normalize_ep("9") == "09" and cr.normalize_ep("10") == "10"
    return "ok"


@case("ru.build_regroup_plan 按集归位规划")
def _():
    root = fresh("ru_regroup")
    os.makedirs(os.path.join(root, "BUS"), exist_ok=True)
    os.makedirs(os.path.join(root, "10"), exist_ok=True)
    open(os.path.join(root, "BUS", "前夫 10集 0920 V01 7F_BUS-DX.wav"), "wb").write(b"RIFF")
    items, stats = cr.build_regroup_plan(root, cr.DEFAULT_RULES, cr.DEFAULT_FIELDS)
    assert items, "应规划出至少 1 条归位项"
    it = items[0]
    # 归位目录 = 「集前缀」（如 前夫 10集 0920 V01 7F），其下再按 type 分 BUS/STEM
    ep_dir = os.path.dirname(it.dst)
    assert "10" in ep_dir and os.path.basename(ep_dir).upper() in ("BUS", "STEM"), it.dst
    assert stats["move"] == 1, stats
    return "dst=%s stats=%s" % (it.dst, stats)


@case("ru.config 默认值/读写/清洗")
def _():
    sys.path.insert(0, os.path.join(SRC, "rename-unify", "code"))
    cfgmod = importlib.import_module("config")
    d = cfgmod.load_config()
    assert "last_root" in d and isinstance(d["fields"], dict)
    cleaned = cfgmod._clean_enabled_types([{"type": "A"}, {"x": 1}, "bad", {"type": ""}])
    assert len(cleaned) == 1 and cleaned[0]["type"] == "A", cleaned
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
