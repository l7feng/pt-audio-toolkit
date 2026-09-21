#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
pt_batch_export.py — Pro Tools 多工程全自动批量导出编排（batch 主控，2026-09-18）

对应项目：05-PT技能通用化改造 · 05-全自动批量导出编排方案（pt-batch）
人类构想：PT 自动打开工程 → 导出 → 关闭 → 自动切下一个，全程无人值守；
          某集失败 → 标记跳过 → 最后汇总人工处理清单。

架构（与 pt-tools-gui 同款决策）：
  batch 主进程只做三件 PTSL 事——open_session / 会话名核对 / close_session，
  全部用「非致命」线程守卫（超时返回，不 sys.exit，主控不停机）；
  扫描与导出交给 pt_scan.py / pt_export.py 子进程（它们自带 fail-fast 守卫，
  子进程挂死由主控 kill，batch 继续下一集）。
  好处：pt_export 的成熟逻辑零复制；主控进程永不因 PT 弹窗卡死。

失败语义（对应方案文档风险③拍板「脚本侧容错 batch 不停机」）：
  FAILED-MODAL        open/会话轮询超时 → 疑似模态弹窗阻塞（如媒体丢失查找框）
  FAILED-NAME-MISMATCH open 后会话名对不上目标工程
  FAILED-SCAN         pt_scan.py 子进程失败
  FAILED-EXPORT       pt_export.py 子进程失败/超时
  FAILED-CLOSE        close_session 超时 → 疑似保存框/弹窗，需人工
  连续 --max-consecutive-modal 个 MODAL 类失败 → 中止整批（弹窗在挡路，继续无意义）

用法：
  python pt_batch_export.py --jobs jobs.json                  # 全量（enabled 的 job）
  python pt_batch_export.py --jobs jobs.json --only 24,23     # 指定集（按 jobs.json 顺序）
  python pt_batch_export.py --jobs jobs.json --dry-run        # 只打印计划，不连 PT
  python pt_batch_export.py --jobs jobs.json --keep-open      # 导完不关（留给人工检查）
  python pt_batch_export.py --jobs jobs.json --no-save-on-close

jobs.json 结构见同目录示例；要点：
  defaults  采样率/位深/格式/save_on_close
  paths     venv_python / export_script / scan_script / profile_dir / out_root
  jobs[]    id / ptx / duration_sec / fps / exports[]（kind: track|bus|output|physicalout|track-all）
  会话名期望默认 = "誓言{id}"，可用 session_name_expect 覆盖。
  fps 优先 job.fps，缺省回退 profile.session.timecode_rate。

导出区间：一律 00:00:00:00 → round(duration_sec × fps) 帧（ffprobe 实测时长）。
产物校验：导出前对输出目录快照，结束后 diff 新增文件，逐个核对 >0 bytes。
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── 通用工具 ─────────────────────────────────────────────────────────


def timed_call(fn, timeout):
    """线程超时包装（batch 版守卫）：返回 (status, err)。
    status: "ok" | "timeout" | "error"。超时后线程留为 daemon 自生自灭，
    主控继续——这是与 pt_export.py 内 sys.exit 版守卫的本质区别。"""
    result = {}

    def _call():
        try:
            fn()
            result["status"] = "ok"
        except Exception as exc:  # noqa: BLE001
            result["status"] = "error"
            result["err"] = exc

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return "timeout", None
    if result.get("status") == "error":
        return "error", result.get("err")
    return "ok", None


def sec_to_tc(seconds, fps):
    """秒 → 时码 HH:MM:SS:FF（round 到帧；小数帧率按比例取帧）。"""
    total_frames = int(round(seconds * fps))
    ff = int(round(fps))
    frames = total_frames % ff
    secs = (total_frames // ff) % 60
    mins = (total_frames // (ff * 60)) % 60
    hours = total_frames // (ff * 3600)
    return "%02d:%02d:%02d:%02d" % (hours, mins, secs, frames)


def snapshot_dir(d):
    """目录文件快照 {path: (size, mtime_ns)}，用于导出后 diff 产物。
    记 mtime 是为了把「覆盖重写同名文件」也算成本次产物（重导场景）。"""
    out = {}
    if os.path.isdir(d):
        for root, _dirs, files in os.walk(d):
            for f in files:
                p = os.path.join(root, f)
                try:
                    st = os.stat(p)
                    out[p] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    out[p] = (-1, 0)
    return out


# ── PTSL 连接与会话守卫 ──────────────────────────────────────────────


class PTSession:
    """batch 主控的 PTSL 连接与会话操作。全部方法非致命（返回状态，不退出）。"""

    def __init__(self, app_name="pt-batch"):
        self.app_name = app_name
        self.pt = None

    def connect(self, timeout=15.0):
        """建立/重建 PTSL 连接。返回 (status, err)。"""
        if self.pt is not None:
            # 已有连接：轻探测，坏了就重建
            status, _err = timed_call(lambda: self.pt.session_name(), 6.0)
            if status == "ok":
                return "ok", None
            try:
                self.pt.close()
            except Exception:
                pass
            self.pt = None

        def _mk():
            from ptsl import Engine
            self.pt = Engine(company_name="local", application_name=self.app_name)

        status, err = timed_call(_mk, timeout)
        return ("ok", None) if status == "ok" else (status, err)

    def close_connection(self):
        if self.pt is not None:
            try:
                self.pt.close()
            except Exception:
                pass
            self.pt = None

    def session_name(self, timeout=8.0):
        """读会话名。返回 (name|None, status)。timeout → 疑似弹窗阻塞。"""
        box = {}

        def _get():
            box["name"] = self.pt.session_name()

        status, _err = timed_call(_get, timeout)
        return box.get("name"), status

    def wait_for_session(self, expect, timeout=45.0, interval=0.5):
        """轮询直到 session_name == expect。返回 (matched, last_name, status)。"""
        deadline = time.time() + timeout
        last, last_status = None, "error"
        while time.time() < deadline:
            last, last_status = self.session_name()
            if last_status == "ok" and last and last.strip() == expect.strip():
                return True, last, last_status
            time.sleep(interval)
        return False, last, last_status

    def open_session(self, path, expect, timeout=90.0, name_timeout=45.0):
        """open + 会话名核对。返回 (status, detail)。
        status: "ok" | "FAILED-MODAL" | "FAILED-NAME-MISMATCH" | "error"
        注意：open 会隐式关闭当前已加载工程——若其有未保存更改，PT 可能弹
        「是否保存」框导致本调用超时（风险①同源，由守卫兜住）。"""
        status, err = timed_call(lambda: self.pt.open_session(path), timeout)
        if status == "timeout":
            return "FAILED-MODAL", "open_session %.0fs 未返回（疑似弹窗阻塞）" % timeout
        if status == "error":
            return "error", "open_session 异常：%r" % (err,)
        matched, last, last_status = self.wait_for_session(
            expect, timeout=name_timeout)
        if last_status == "timeout":
            return "FAILED-MODAL", "open 后会话轮询超时（疑似弹窗阻塞）"
        if not matched:
            return "FAILED-NAME-MISMATCH", "会话名=%r 期望=%r" % (last, expect)
        return "ok", "会话名核对通过：%r" % last

    def close_session(self, save_on_close, timeout=30.0):
        """close 守卫（首次实弹在 batch 内验证，见 05 号文档风险①）。
        返回 (status, detail)：status "ok" | "FAILED-CLOSE" | "error"。"""
        status, err = timed_call(
            lambda: self.pt.close_session(save_on_close=save_on_close), timeout)
        if status == "timeout":
            return "FAILED-CLOSE", "close_session %.0fs 未返回（疑似保存框/弹窗）" % timeout
        if status == "error":
            return "error", "close_session 异常：%r" % (err,)
        return "ok", "closed (save_on_close=%s)" % save_on_close


# ── jobs.json 处理 ───────────────────────────────────────────────────


def load_jobs(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def job_fps(job, profile, defaults):
    """fps 决策：job.fps > profile.session.timecode_rate > 报错。"""
    fps = job.get("fps") or (defaults or {}).get("fps")
    if fps:
        return float(fps)
    s = (profile or {}).get("session") or {}
    raw = s.get("timecode_rate") or s.get("timecode_rate_raw")
    if raw:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    return None


def export_range(job, profile, defaults):
    """计算 start/end 时码。返回 (start_tc, end_tc, fps) 或 (None, err_str, None)。"""
    dur = job.get("duration_sec") or job.get("duration_tc")
    if not dur:
        return None, "job 缺 duration_sec/duration_tc", None
    fps = job_fps(job, profile, defaults)
    if not fps:
        return None, "无法确定 fps（job.fps 与 profile.timecode_rate 均缺）", None
    if job.get("duration_tc"):
        return "00:00:00:00", job["duration_tc"], fps
    return "00:00:00:00", sec_to_tc(float(dur), fps), fps


def build_export_cmd(job, export, paths, defaults, profile_path, out_dir,
                     start_tc, end_tc, bounce_timeout):
    """组装 pt_export.py 子进程命令行（stems 模式通吃 track/bus/output/track-all）。"""
    py = paths["venv_python"]
    script = paths["export_script"]
    cmd = [py, script]
    # ⚠ --profile 是 argparse 全局参数，必须放子命令(stems)之前——
    #   放后面报 unrecognized arguments（§8.3 老坑，2026-09-19 batch 侧再踩再修）
    if profile_path and os.path.exists(profile_path):
        cmd += ["--profile", profile_path]
    cmd += ["stems"]
    kind = (export.get("kind") or "bus").lower()
    if kind == "track-all":
        cmd += ["--source-type", "track", "--all-tracks"]
        if export.get("skip_buses"):
            cmd += ["--skip-buses"]
        if export.get("exclude_empty"):
            cmd += ["--exclude-empty"]
        for t in export.get("track_types", []):
            cmd += ["--track-type", t]
    else:
        st = {"track": "track", "bus": "bus", "output": "output",
              "physicalout": "physicalout"}.get(kind)
        if st is None:
            return None, "未知 export.kind=%r" % kind
        cmd += ["--source-type", st]
        for s in export.get("sources", []):
            cmd += ["--source", s]
        if not export.get("sources"):
            return None, "export.kind=%r 缺 sources" % kind
    cmd += [
        "--out", out_dir,
        "--start", start_tc,
        "--end", end_tc,
        "--sample-rate", str(job.get("sample_rate") or defaults.get("sample_rate", 48000)),
        "--bit-depth", str(job.get("bit_depth") or defaults.get("bit_depth", 24)),
        "--format", job.get("format") or defaults.get("format", "interleaved"),
        "--bounce-timeout", str(bounce_timeout),
    ]
    if export.get("prefix"):
        cmd += ["--prefix", export["prefix"]]
    return cmd, None


# ── 子进程执行 ───────────────────────────────────────────────────────


def run_subprocess(cmd, timeout, what):
    """跑子进程（scan/export），捕获输出。返回 dict(status, stdout, tail)。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, env=env)
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        status = "ok" if proc.returncode == 0 else "error"
        return {"status": status, "output": out, "code": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "output": "", "code": -1}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "output": "%s 启动失败：%r" % (what, exc), "code": -2}


# ── 单 job 流程 ──────────────────────────────────────────────────────


def process_job(job, paths, defaults, args, ptsession, log_lines):
    """执行单个 job。返回结果 dict（含 status / artifacts / detail）。"""
    jid = job.get("id", "?")
    res = {"id": jid, "status": "OK", "steps": [], "artifacts": [], "seconds": 0}
    t0 = time.time()

    def step(msg):
        log_lines.append("[%s] %s" % (jid, msg))
        print("  %s" % msg, flush=True)
        res["steps"].append(msg)

    expect = job.get("session_name_expect") or ("誓言%s" % jid)
    ptx = job["ptx"]
    profile_path = os.path.join(paths["profile_dir"], "profile-%s.json" % jid)
    out_dir = os.path.join(paths["out_root"], "誓言%s" % jid)

    if not os.path.exists(ptx):
        res["status"] = "FAILED-PTX-MISSING"
        step("[fail] 工程不存在：%s" % ptx)
        return res
    os.makedirs(out_dir, exist_ok=True)

    # ── 1) 会话就位：自动检测已打开 → 免 open ────────────────────────
    cur, cur_status = ptsession.session_name()
    if cur_status == "timeout":
        res["status"] = "FAILED-MODAL"
        step("[fail] 会话状态探测超时（疑似弹窗阻塞 PTSL）")
        return res
    if cur and cur.strip() == expect.strip():
        step("[info] 会话已是目标工程 %r，跳过 open（自动检测）" % cur)
    else:
        if cur:
            step("[info] 当前会话=%r，open 切换 → %r" % (cur, expect))
        status, detail = ptsession.open_session(
            ptx, expect, timeout=args.open_timeout)
        step("[open] %s" % detail)
        if status != "ok":
            res["status"] = status
            return res

    # ── 2) profile 就位（缺失自动扫）─────────────────────────────────
    need_profile = any(
        (e.get("kind") == "track-all" and e.get("exclude_empty"))
        or e.get("kind") == "track" for e in job.get("exports", []))
    if not args.no_scan and (need_profile or not os.path.exists(profile_path)):
        step("[scan] profile 缺失或需要 → pt_scan.py")
        scan_cmd = [paths["venv_python"], paths["scan_script"],
                    "--out", paths["profile_dir"],
                    "--name", "profile-%s.json" % jid]
        scan_res = run_subprocess(scan_cmd, 120, "pt_scan")
        if scan_res["status"] != "ok":
            res["status"] = "FAILED-SCAN"
            step("[fail] 扫描失败（code=%s）：%s" % (
                scan_res["code"], scan_res["output"][-400:]))
            return res
        step("[ok] profile-{}.json 已生成/更新".format(jid))

    # ── 3) 计算导出区间 ─────────────────────────────────────────────
    profile = {}
    if os.path.exists(profile_path):
        try:
            with open(profile_path, encoding="utf-8") as f:
                profile = json.load(f)
        except Exception:
            profile = {}
    start_tc, end_tc, fps = export_range(job, profile, defaults)
    if start_tc is None:
        res["status"] = "FAILED-RANGE"
        step("[fail] %s" % end_tc)
        return res
    step("[range] %s → %s（fps=%g，duration_sec=%s）" % (
        start_tc, end_tc, fps, job.get("duration_sec")))

    # ── 4) 逐个 export 跑子进程 ─────────────────────────────────────
    bounce_timeout = args.bounce_timeout
    for i, export in enumerate(job.get("exports", []), 1):
        cmd, err = build_export_cmd(job, export, paths, defaults,
                                    profile_path, out_dir, start_tc, end_tc,
                                    bounce_timeout)
        if err:
            res["status"] = "FAILED-EXPORT"
            step("[fail] %s" % err)
            return res
        before = snapshot_dir(out_dir)
        step("[export %d/%d] %s" % (i, len(job["exports"]), " ".join(cmd[2:])))
        proc_timeout = args.proc_timeout
        r = run_subprocess(cmd, proc_timeout, "pt_export")
        if r["status"] == "timeout":
            res["status"] = "FAILED-EXPORT"
            step("[fail] pt_export 子进程 %ss 超时被终止" % proc_timeout)
            return res
        if r["status"] != "ok":
            res["status"] = "FAILED-EXPORT"
            step("[fail] pt_export 退出码 %s，输出尾部：\n%s" % (
                r["code"], "\n".join(r["output"].splitlines()[-12:])))
            return res

        after = snapshot_dir(out_dir)
        new_files = [p for p in after
                     if p not in before or before[p] != after[p]]
        if not new_files:
            res["status"] = "FAILED-EXPORT"
            step("[fail] 子进程成功但输出目录无新增/变化文件")
            return res
        # pt_export 对个别轨失败只打 [fail] 行、退出码仍为 0（逐轨容错设计）
        # → batch 侧数 [fail] 行，>0 标 PARTIAL（不中断，继续剩余 exports）
        fail_lines = [l.strip() for l in r["output"].splitlines()
                      if l.strip().startswith("[fail]")]
        if fail_lines:
            if res["status"] == "OK":
                res["status"] = "PARTIAL"
            step("[warn] pt_export 报告 %d 条失败：" % len(fail_lines))
            for l in fail_lines[:10]:
                step("    " + l)
        bad = [p for p in new_files if after[p][0] <= 0]
        for p in sorted(new_files):
            step("[artifact] %s  %s bytes%s" % (
                os.path.basename(p), format(after[p][0], ","),
                "  ⚠零字节" if after[p][0] <= 0 else ""))
            res["artifacts"].append({"path": p, "size": after[p][0]})
        if bad:
            res["status"] = "FAILED-EXPORT"
            step("[fail] 存在零字节产物")
            return res
        step("[ok] export %d/%d 完成：%d 个新文件" % (
            i, len(job["exports"]), len(new_files)))

    res["seconds"] = round(time.time() - t0, 1)
    return res


# ── 主流程 ───────────────────────────────────────────────────────────


def main():
    p = argparse.ArgumentParser(
        description="Pro Tools batch export orchestrator (PTSL)")
    p.add_argument("--jobs", required=True, help="jobs.json 路径")
    p.add_argument("--only", default=None,
                   help="只跑这些 job id（逗号分隔，按 jobs.json 顺序）")
    p.add_argument("--dry-run", action="store_true",
                   help="只打印计划，不连 PT、不执行")
    p.add_argument("--keep-open", action="store_true",
                   help="导完不 close（留给人工检查）")
    p.add_argument("--no-save-on-close", action="store_true",
                   help="close 时 save_on_close=False（默认 True，方案拍板）")
    p.add_argument("--no-scan", action="store_true",
                   help="跳过自动 profile 扫描（profile 缺失也不扫）")
    p.add_argument("--open-timeout", type=float, default=90.0,
                   help="open_session 守卫超时秒（默认 90，大工程加载留余量）")
    p.add_argument("--bounce-timeout", type=float, default=600.0,
                   help="传给 pt_export 的单次导出超时（默认 600）")
    p.add_argument("--proc-timeout", type=float, default=1800.0,
                   help="单个 export 子进程整体超时（默认 1800，track-all 留余量）")
    p.add_argument("--max-consecutive-modal", type=int, default=2,
                   help="连续多少个 MODAL 类失败后中止整批（默认 2）")
    p.add_argument("--log-dir", default=None,
                   help="结果 JSON 日志目录（默认 jobs.json 同目录）")
    args = p.parse_args()

    spec = load_jobs(args.jobs)
    defaults = spec.get("defaults", {})
    paths = spec["paths"]
    jobs = [j for j in spec.get("jobs", []) if j.get("enabled", True)]
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        jobs = [j for j in jobs if str(j.get("id")) in want]
    if not jobs:
        print("[error] 过滤后没有可执行的 job", file=sys.stderr)
        sys.exit(2)

    save_on_close = not args.no_save_on_close and \
        defaults.get("save_on_close", True)

    print("=== pt-batch 计划 ===")
    for j in jobs:
        print("  [{id}] {ptx}".format(id=j.get("id"), ptx=j["ptx"]))
        print("        exports: {x}".format(x=json.dumps(
            j.get("exports", []), ensure_ascii=False)))
    if args.dry_run:
        print("\n[dry-run] 计划结束，未连接 PT、未执行。")
        return

    ptsession = PTSession()
    log_lines = []
    results = []
    consecutive_modal = 0
    t_all = time.time()

    status, err = ptsession.connect()
    if status != "ok":
        print("[error] 无法连接 PTSL（localhost:31416）：%r" % (err,),
              file=sys.stderr)
        sys.exit(1)
    log_lines.append("[batch] PTSL 已连接")

    for idx, job in enumerate(jobs, 1):
        jid = job.get("id", "?")
        print("\n════ job %d/%d  [%s] ════" % (idx, len(jobs), jid), flush=True)
        r = process_job(job, paths, defaults, args, ptsession, log_lines)
        results.append(r)
        print("  ── 结果：[%s] %s  用时 %.1fs" % (
            jid, r["status"], r.get("seconds", 0)), flush=True)

        if r["status"] in ("FAILED-MODAL",):
            consecutive_modal += 1
            if consecutive_modal >= args.max_consecutive_modal:
                print("\n[abort] 连续 %d 个 MODAL 类失败 → 中止整批"
                      "（弹窗阻塞 PTSL，请人工处理后再跑剩余集）。"
                      % consecutive_modal)
                break
        else:
            consecutive_modal = 0

        # ── close（本 job 专属收尾）──────────────────────────────────
        if args.keep_open:
            log_lines.append("[%s] --keep-open：跳过 close" % jid)
            continue
        c_status, c_detail = ptsession.close_session(save_on_close)
        r["close"] = {"status": c_status, "detail": c_detail}
        log_lines.append("[%s] close: %s %s" % (jid, c_status, c_detail))
        print("  [close] %s — %s" % (c_status, c_detail), flush=True)
        if c_status != "ok":
            # close 挂了 → PT 可能卡弹窗/保存框。连接作废重建，下个 job 见真章
            ptsession.close_connection()
            st2, _ = ptsession.connect()
            if st2 != "ok":
                log_lines.append("[batch] close 失败后重连失败 → 中止整批")
                print("\n[abort] close 失败且 PTSL 不可用 → 中止整批。")
                break

    ptsession.close_connection()

    # ── 汇总 ────────────────────────────────────────────────────────
    print("\n════ 批量汇总 ════")
    ok_n = 0
    for r in results:
        mark = "✅" if r["status"] == "OK" else ("🟡" if r["status"] == "PARTIAL" else "❌")
        n_art = len(r.get("artifacts", []))
        print("  %s [%s] %-22s 产物 %d 个  close=%s" % (
            mark, r["id"], r["status"], n_art,
            (r.get("close") or {}).get("status", "-")))
        ok_n += 1 if r["status"] == "OK" else 0
    part_n = sum(1 for r in results if r["status"] == "PARTIAL")
    print("  共 %d 集：%d 成功 / %d 部分成功 / %d 失败 / 总用时 %.1fs" % (
        len(results), ok_n, part_n, len(results) - ok_n - part_n,
        time.time() - t_all))

    manual = [r for r in results if r["status"] != "OK"]
    if manual:
        print("\n需人工处理：")
        for r in manual:
            print("  [%s] %s — %s" % (r["id"], r["status"],
                                      "; ".join(r["steps"][-2:])))

    # ── 日志落盘 ────────────────────────────────────────────────────
    log_dir = args.log_dir or os.path.dirname(os.path.abspath(args.jobs))
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(
        log_dir, "batch_log_%s.json" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({"results": results, "log": log_lines,
                   "total_seconds": round(time.time() - t_all, 1)},
                  f, ensure_ascii=False, indent=2)
    print("\n[log] %s" % log_path)

    sys.exit(0 if ok_n == len(results) and results else 1)


if __name__ == "__main__":
    main()
