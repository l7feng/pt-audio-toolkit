# -*- coding: utf-8 -*-
"""pt-tools `--batch` CLI（W8 · v1.5.0）——夜间批量导出入口。

复用既有批量链路：GUI「批量导出」对话框产出的 jobs.json（open/close 守卫、
逐工程扫描、产物核对都在 pt_batch_export.py 脚本侧，壳不动芯），
CLI 只做三件事：校验 jobs.json → 调 venv python 跑编排脚本 → 输出落日志。

为什么输出进日志而不是控制台：四工具 exe 是 `--windowed` 打包（无控制台），
print 出不来。全部输出同步写 `pt-batch-<时间戳>.log`（exe 旁），跑完首行
回写 `EXIT rc=...`，配 Windows 任务计划程序夜间跑也能事后查证。

用法：
    pt-tools.exe --batch D:\\path\\jobs.json
    （jobs.json 由 GUI 批量对话框的「保存任务清单…」生成，格式见
      BatchExportDialog._build_spec；也可手写，结构 = {defaults, paths, jobs}）
"""
import json
import os
import subprocess
import sys
import time

from ptools.core.settings import CREATE_NO_WINDOW


def validate_jobs(spec):
    """jobs.json 结构校验，返回错误消息列表（空 = 通过）。"""
    errs = []
    if not isinstance(spec, dict):
        return ["顶层必须是 JSON 对象"]
    jobs = spec.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        errs.append("jobs 必须是非空数组")
        return errs
    paths = spec.get("paths") or {}
    for key in ("venv_python", "export_script", "out_root"):
        if not str(paths.get(key) or "").strip():
            errs.append("paths.%s 缺失" % key)
    for i, job in enumerate(jobs, 1):
        if not isinstance(job, dict):
            errs.append("job[%d] 必须是对象" % i)
            continue
        if not str(job.get("ptx") or "").strip():
            errs.append("job[%d].ptx 缺失" % i)
        if not isinstance(job.get("exports"), list) or not job.get("exports"):
            errs.append("job[%d].exports 必须是非空数组" % i)
    return errs


def run_batch(jobs_path, log):
    """执行批量导出，返回退出码。log = callable(text) 逐行回调。

    venv python / 编排脚本路径优先取 jobs.json 的 paths（GUI 生成时已写好），
    缺失时回落本机配置探测（PathResolver）。
    """
    from ptools.core.config import load_config
    from ptools.core.paths import PathResolver

    jobs_path = os.path.abspath(jobs_path)
    if not os.path.isfile(jobs_path):
        log("[错误] jobs.json 不存在: %s" % jobs_path)
        return 2
    try:
        with open(jobs_path, "r", encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        log("[错误] jobs.json 读取/解析失败: %s" % e)
        return 2
    errs = validate_jobs(spec)
    if errs:
        for e in errs:
            log("[错误] %s" % e)
        return 2

    paths = spec.get("paths") or {}
    venv = str(paths.get("venv_python") or "").strip()
    script = str(paths.get("export_script") or "").strip()
    if not venv or not os.path.isfile(venv):
        cfg = load_config()
        resolver, ok, msg = PathResolver.detect(cfg)
        if not ok:
            log("[错误] venv python 不可用（jobs.json 未提供或路径失效），"
                "技能探测: %s" % msg)
            return 2
        venv = resolver.venv_python
        script = script or os.path.join(
            os.path.dirname(resolver.script("pt-exporter")),
            "pt_batch_export.py")
    if not script or not os.path.isfile(script):
        log("[错误] 批量编排脚本不存在: %s" % script)
        return 2

    out_root = str(paths.get("out_root") or "").strip()
    if out_root:
        try:
            os.makedirs(out_root, exist_ok=True)
        except OSError as e:
            log("[错误] 输出根不可创建: %s (%s)" % (out_root, e))
            return 2

    cmd = [venv, script, "--jobs", jobs_path]
    log("命令: %s" % subprocess.list2cmdline(cmd))
    log("开始执行 %d 个任务…" % len(spec.get("jobs") or []))
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                encoding="utf-8", errors="replace",
                                creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        log("[错误] 启动失败: %s" % e)
        return 1
    for line in proc.stdout:                     # CLI 模式无需可中止，直读即可
        log(line.rstrip("\n"))
    proc.wait()
    rc = proc.returncode or 0
    log("批量导出结束：退出码 %d，用时 %.0f 秒" % (rc, time.time() - t0))
    return rc
