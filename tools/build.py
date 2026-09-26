# -*- coding: utf-8 -*-
"""pt-audio-toolkit 统一打包入口（四工具 → PyInstaller onedir + windowed）。

用法
----
    python tools/build.py                       # 构建全部四个工具
    python tools/build.py pt-tools rename-unify # 只构建指定工具
    python tools/build.py --version 1.1.0 --date 20260923
    python tools/build.py --out-root D:\\somewhere\\exe
    python tools/build.py --py C:\\path\\to\\python.exe

输出布局（默认）
----------------
    <out-root>/pt-audio-toolkit-v<版本>-<日期>/<工具名>/
        <工具名>.exe  +  _internal/            （通用）
        pt-tools/_internal/skills/              （内置技能脚本，开箱即用）
        jianying-draft-toolkit/tools/           （jy-draftc 解密器）

    ⚠️ 分发时**整个工具文件夹一起给** —— `_internal/` 必须与 exe 同级。

为什么不用各目录的 build.ps1
----------------------------
PowerShell 把原生程序的 stderr 当错误流，配 `$ErrorActionPreference=Stop` 时，
PyInstaller 打出第一行 `INFO:` 就会触发 NativeCommandError 而**静默中断**
（表现为只输出 "building ..." 就退出）。四个 build.ps1 里有三份都在跟这个坑搏斗
（rename-unify 那份还专门写了一段注释解释它，并单独把 ErrorActionPreference
降级成 Continue 绕过）。

本脚本一律直调 `python -m PyInstaller`，逐工具取 returncode，
失败时打印「工具名 + 返回码 + 关键 stderr 行」，**绝不静默**。

四个旧 build.ps1 已降级为转发本脚本的薄壳，既有调用方式（`.\\build.ps1`）不变。
"""
import argparse
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 控制台默认 GBK，打印 ⚠/✅ 之类字符会 UnicodeEncodeError 把构建中断
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent

# 每个工具：入口 / PyInstaller --name / 额外参数 / 后置动作
TARGETS = [
    {
        "key": "pt-tools",
        "entry": "src/pt-tools/pt_tools_gui.py",
        "name": "pt-tools",
        "args": ["--hidden-import", "tkinterdnd2", "--collect-data", "tkinterdnd2"],
        "post": "pt_tools_skills",
    },
    {
        "key": "pt-project-folder-builder",
        "entry": "src/pt-project-folder-builder/folder_builder_gui.py",
        "name": "pt-project-folder-builder",
        "args": [],
        "post": None,
    },
    {
        "key": "jianying-draft-toolkit",
        "entry": "src/jianying-draft-toolkit/code/gui.py",
        "name": "jianying-draft-toolkit",
        "args": ["--hidden-import", "tkinterdnd2", "--collect-data", "tkinterdnd2"],
        "post": "jianying_tools",
    },
    {
        "key": "rename-unify",
        "entry": "src/rename-unify/code/main.py",
        "name": "rename-unify",
        "args": ["--paths", "src/rename-unify/code",
                 "--hidden-import", "tkinterdnd2", "--collect-data", "tkinterdnd2"],
        "post": None,
    },
]

LOG = []


def say(msg=""):
    print(msg, flush=True)
    LOG.append(msg)


# ── 版本 ─────────────────────────────────────────────────────
def repo_version():
    """仓库级版本：读仓库根 VERSION 文件（纯文本，如 `1.1.0`）。"""
    p = REPO / "VERSION"
    if p.is_file():
        v = p.read_text(encoding="utf-8").strip()
        if v:
            return v
    return "0.0.0"


# ── 构建解释器自检 ───────────────────────────────────────────
def check_builder(py):
    """返回问题列表（空 = 通过）。不静默回落。"""
    problems = []
    if not os.path.isfile(py):
        problems.append("解释器不存在：%s" % py)
        return problems
    r = subprocess.run([py, "-c", "import tkinter"], capture_output=True)
    if r.returncode != 0:
        problems.append("解释器缺少 tkinter（GUI 打包必需）：%s" % py)
    r = subprocess.run([py, "-m", "PyInstaller", "--version"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        problems.append("解释器未安装 PyInstaller：%s\n      安装：%s -m pip install pyinstaller"
                        % (py, py))
    return problems


# ── 后置动作 ─────────────────────────────────────────────────
def post_pt_tools_skills(out_root):
    """把三个技能脚本内置到 _internal/skills/<skill>/scripts/（PathResolver 的查找布局）。

    来源取**仓库内** `src/pt-tools/skills/`（唯一真源）。
    外部 `D:\\Ai-Files\\Agent-Preset\\Skills\\protools-skills\\` 是**技能生效区**，
    2026-09-23 已逐文件核对 MD5，6 个脚本与仓内完全一致 —— 因此从仓内复制不会引入旧版。

    注意：venv（含 py-ptsl）**不打包** —— 体积大且属运行时环境。
    故 exe 自带脚本、但运行仍需一个含 venv 的技能目录（见 pt-tools 的「设置 > 技能目录」）。
    """
    dst_root = out_root / "pt-tools" / "_internal" / "skills"
    src_root = REPO / "src" / "pt-tools" / "skills"
    copied = []
    for sk in ("pt-scanner", "pt-exporter", "pt-cleaner", "pt-clips"):
        s = src_root / sk / "scripts"
        if not s.is_dir():
            continue
        d = dst_root / sk / "scripts"
        d.mkdir(parents=True, exist_ok=True)
        for f in sorted(s.iterdir()):
            if f.suffix == ".py":
                shutil.copy2(f, d / f.name)
                copied.append("%s/%s" % (sk, f.name))
    say("[post] pt-tools 内置技能脚本 %d 个 -> %s" % (len(copied), dst_root))
    for c in copied:
        say("       · %s" % c)
    return len(copied) > 0


def post_jianying_tools(out_root):
    """复制 tools/（jy-draftc 解密器）到 exe 同级。

    onedir 而非 onefile 的原因就在这里：jy-draftc 运行时要把剪映安装路径
    写进 .env，需要 exe 旁有**真实目录**（onefile 会解到临时目录且被清理）。
    """
    src = REPO / "src" / "jianying-draft-toolkit" / "tools"
    dst = out_root / "jianying-draft-toolkit" / "tools"
    if dst.is_dir():
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    exe = dst / "jy-draftc" / "jy-draftc-amd64-windows" / "jy-draftc.exe"
    say("[post] jianying tools/ 已复制，解密器存在=%s" % exe.is_file())
    return exe.is_file()


POST = {
    "pt_tools_skills": post_pt_tools_skills,
    "jianying_tools": post_jianying_tools,
}


# ── 单工具构建 ───────────────────────────────────────────────
def build_one(py, t, out_root, work_root, spec_dir, staging_root):
    name = t["name"]
    entry = REPO / t["entry"]
    say()
    say("=" * 72)
    say("[build] %s  ← %s" % (name, t["entry"]))
    say("=" * 72)

    if not entry.is_file():
        say("[FAIL] 入口不存在：%s" % entry)
        return False

    # ⚠️ --distpath 指向**每次全新的 staging 目录**，而不是最终出口。
    # 原因：PyInstaller 的 --noconfirm 会删除 --distpath 下已有的同名目录；
    # 出口在受保护路径（如 D:\）下、文件数超过批量阈值时会被安全策略拦截并中断构建
    # （实测：「Removing dir …」→ SAFE_DELETE_BULK_CONFIRM_REQUIRED，count=945）。
    # 改为先建到 staging，再把旧产物**改名保留**、新产物**移入** —— 全程无删除。
    cmd = [py, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--windowed", "--onedir", "--name", name,
           "--distpath", str(staging_root),
           "--workpath", str(work_root / name),
           "--specpath", str(spec_dir)]
    cmd += [str(x) if x.startswith("src/") else x for x in t["args"]]
    cmd.append(str(entry))

    t0 = datetime.datetime.now()
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    dt = (datetime.datetime.now() - t0).total_seconds()

    built = staging_root / name
    ok = (p.returncode == 0) and (built / (name + ".exe")).is_file()
    if ok:
        dst = out_root / name
        if dst.exists():
            prev = out_root / ("%s.prev-%s" % (name, staging_root.name))
            dst.rename(prev)
            say("[keep] 旧产物已改名保留（未删除）：%s" % prev.name)
        shutil.move(str(built), str(dst))
    exe = out_root / name / (name + ".exe")
    say("[%s] %s（%.0f 秒）" % ("OK" if ok else "FAIL", exe if ok else "未产出 exe", dt))
    if not ok:
        # 关键：打印工具名 + 返回码 + 末尾 stderr，绝不静默
        say("[FAIL] 工具=%s 返回码=%s" % (name, p.returncode))
        tail = (p.stdout or "").strip().splitlines() + (p.stderr or "").strip().splitlines()
        for line in tail[-18:]:
            say("       | %s" % line)
    return ok


def main():
    ap = argparse.ArgumentParser(
        description="pt-audio-toolkit 四工具统一打包",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tools", nargs="*", help="要构建的工具名（缺省=全部）")
    ap.add_argument("--out-root", default=os.environ.get("PT_EXE_ROOT",
                                                         r"D:\Ai-Files\Agent-Preset\exe"),
                    help="exe 出口根目录")
    ap.add_argument("--version", default=None, help="仓库版本（缺省读仓库根 VERSION 文件）")
    ap.add_argument("--date", default=datetime.date.today().strftime("%Y%m%d"),
                    help="发布日期 YYYYMMDD（缺省今天）")
    ap.add_argument("--py", default=sys.executable,
                    help="构建用解释器（必须带 tkinter 与 PyInstaller）")
    ap.add_argument("--work", default=os.path.join(
        os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp", "pt-toolkit-build"),
        help="PyInstaller 中间产物目录")
    args = ap.parse_args()

    version = args.version or repo_version()
    out_root = Path(args.out_root) / ("pt-audio-toolkit-v%s-%s" % (version, args.date))
    work_root = Path(args.work) / "work"
    spec_dir = Path(args.work) / "spec"

    say("pt-audio-toolkit 统一打包")
    say("  仓库     : %s" % REPO)
    say("  版本     : %s（%s）" % (version, "命令行指定" if args.version else "VERSION 文件"))
    say("  出口     : %s" % out_root)
    say("  解释器   : %s" % args.py)
    say()

    problems = check_builder(args.py)
    if problems:
        say("构建前置检查未通过：")
        for x in problems:
            say("  ✗ %s" % x)
        say()
        say("提示：GUI 打包需要带 tkinter 的解释器（官方 Windows 安装版自带），")
        say("      且需 pip install pyinstaller；剪映工具另需 pip install tkinterdnd2。")
        return 2

    wanted = [t for t in TARGETS if not args.tools or t["key"] in args.tools]
    unknown = [k for k in args.tools if k not in [t["key"] for t in TARGETS]]
    if unknown:
        say("未知工具名：%s" % ", ".join(unknown))
        say("可用：%s" % ", ".join(t["key"] for t in TARGETS))
        return 2
    if not wanted:
        say("没有匹配到任何工具。")
        return 2

    out_root.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    # 每次构建用全新的 staging：PyInstaller 会删除 --distpath 下的同名目录，
    # staging 是唯一且位于系统临时区，既避开批量删除保护，也不会误删已有产物。
    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    staging_root = Path(args.work) / "staging" / run_id
    staging_root.mkdir(parents=True, exist_ok=True)

    results = {}
    for t in wanted:
        try:
            results[t["key"]] = build_one(args.py, t, out_root, work_root,
                                          spec_dir, staging_root)
        except Exception as e:
            say("[FAIL] %s 构建异常：%s" % (t["key"], e))
            results[t["key"]] = False

    # 后置动作（只对构建成功的工具做）
    for t in wanted:
        if results.get(t["key"]) and t.get("post"):
            try:
                results[t["key"] + ":post"] = POST[t["post"]](out_root)
            except Exception as e:
                say("[FAIL] %s 后置异常：%s" % (t["key"], e))
                results[t["key"] + ":post"] = False

    say()
    say("=" * 72)
    say("打包汇总")
    say("=" * 72)
    for k, v in results.items():
        say("  %-32s %s" % (k, "OK" if v else "FAIL"))
    say()
    for t in wanted:
        d = out_root / t["name"]
        if d.is_dir():
            n = sum(len(fs) for _r, _dd, fs in os.walk(d))
            mb = sum(os.path.getsize(os.path.join(r, f))
                     for r, _dd, fs in os.walk(d) for f in fs) / 1048576.0
            say("  %-32s %6.1f MB  %4d 文件" % (t["name"] + "/", mb, n))

    log_path = Path(args.work) / "build.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(LOG), encoding="utf-8")
        say()
        say("日志：%s" % log_path)
    except Exception:
        pass

    # 清理本轮 staging（位于系统临时区，不涉及出口目录）
    shutil.rmtree(staging_root, ignore_errors=True)

    say()
    say("⚠️ 分发时把整个工具文件夹一起给 —— _internal/ 必须与 exe 同级。")
    return 0 if all(v for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
