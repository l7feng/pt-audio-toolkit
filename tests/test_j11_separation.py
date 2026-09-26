# -*- coding: utf-8 -*-
"""J11 人声分离页签（v2.9.0）+ 启动崩溃回溯钩子 回归。

纯逻辑层：命令拼装用 stub 替换 subprocess，不真跑 demucs、不需要 GPU/torch。

覆盖两个 09-26 交付：
  ① J11 人声分离页（Demucs 两轨/四轨，模型外置不打进 exe）；
  ② gui.py 的 sys.excepthook 崩溃回溯（--windowed 下 stderr 被丢弃，
     启动崩框只报「Failed to execute script」不带 traceback）。
"""
import io
import os
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

C.ensure_tk()

SRC = str(C.SRC)
JY_CODE = os.path.join(SRC, "jianying-draft-toolkit", "code")
SEP = os.path.join(JY_CODE, "tabs", "separation_tab.py")
case = C.case

sys.path.insert(0, JY_CODE)
import gui as jygui                                     # noqa: E402
from tabs import separation_tab as sep                 # noqa: E402


class _Var:
    """tk.StringVar 的最小替身（只需 .get/.set）。"""

    def __init__(self, v=""):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


def _fake_self(inp, out, stems, cmd=("demucs",)):
    """构造只带 _run_demucs 所需成员的假 self（不建任何 tk 控件）。"""
    return types.SimpleNamespace(
        var_in=_Var(str(inp)), var_out=_Var(str(out)),
        var_stems=_Var(stems), demucs_cmd=list(cmd))


def _run_capture(fake_self):
    """跑 _run_demucs，捕获 stdout 并记录被调用的命令（不真执行 demucs）。"""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    orig = sep.subprocess.run
    sep.subprocess.run = fake_run
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            sep.SeparationTab._run_demucs(fake_self)
    finally:
        sep.subprocess.run = orig
    return calls, buf.getvalue()


# ───────── 页签接线 ─────────
@case("J11 接线：gui.py 三页签含 SeparationTab，④号页标题正确")
def j11_registered():
    assert os.path.isfile(SEP), SEP
    src = Path(JY_CODE, "gui.py").read_text(encoding="utf-8")
    assert "SeparationTab" in src, "gui.py 应注册人声分离页签"
    assert sep.SeparationTab.title == "④ 人声分离", sep.SeparationTab.title
    assert "separation_tab import" in src or "SeparationTab" in src


@case("J11 配置：三键声明 + collect/apply_config 对称")
def j11_config_keys():
    assert set(sep.SeparationTab.config_keys) == {"sep_input", "sep_output",
                                                   "sep_stems"}
    obj = types.SimpleNamespace(cfg={}, var_in=_Var("a"), var_out=_Var("b"),
                                var_stems=_Var("all"))
    sep.SeparationTab.collect(obj)
    assert obj.cfg == {"sep_input": "a", "sep_output": "b", "sep_stems": "all"}
    obj2 = types.SimpleNamespace(cfg={"sep_input": "z", "sep_output": "",
                                      "sep_stems": "vocals"},
                                 var_in=_Var(), var_out=_Var(), var_stems=_Var())
    sep.SeparationTab.apply_config(obj2)
    assert (obj2.var_in.get(), obj2.var_out.get(),
            obj2.var_stems.get()) == ("z", "", "vocals")


# ───────── 命令拼装（真跑 demucs 的替身）─────────
@case("J11 两轨模式：命令含 -o 输出 与 --two-stems=vocals")
def j11_two_stems():
    d = C.fresh("j11_two")
    f = Path(d) / "a.wav"
    f.write_bytes(b"RIFF")
    calls, log = _run_capture(_fake_self(f, Path(d) / "out", "vocals"))
    assert len(calls) == 1, calls
    cmd = calls[0]
    assert cmd[0] == "demucs" and "-o" in cmd and "--two-stems=vocals" in cmd
    assert cmd[-1] == str(f), cmd
    assert str(Path(d) / "out") in cmd, cmd
    assert "[完成]" in log, log


@case("J11 四轨模式：命令不带 --two-stems（出 4 轨）")
def j11_four_stems():
    d = C.fresh("j11_four")
    f = Path(d) / "b.wav"
    f.write_bytes(b"RIFF")
    calls, _ = _run_capture(_fake_self(f, Path(d) / "out", "all"))
    assert len(calls) == 1, calls
    assert not any("two-stems" in a for a in calls[0]), calls[0]
    assert "-o" in calls[0], calls[0]


@case("J11 目录模式：只收音频扩展名，按序逐个处理")
def j11_dir_mode():
    d = C.fresh("j11_dir")
    for n in ("1.wav", "2.mp3", "3.m4a", "4.flac"):
        (Path(d) / n).write_bytes(b"x")
    (Path(d) / "note.txt").write_text("忽略我", encoding="utf-8")
    (Path(d) / "cover.jpg").write_bytes(b"x")
    calls, log = _run_capture(_fake_self(d, Path(d) / "out", "vocals"))
    assert len(calls) == 4, calls
    assert all(c[-1].lower().endswith((".wav", ".mp3", ".m4a", ".flac"))
               for c in calls), calls
    assert "共 4 个文件" in log, log


@case("J11 空目录：报错早退，不调 demucs")
def j11_empty_dir():
    d = C.fresh("j11_empty")
    (Path(d) / "readme.md").write_text("没有音频", encoding="utf-8")
    calls, log = _run_capture(_fake_self(d, Path(d) / "out", "vocals"))
    assert calls == [], calls
    assert "没找到音频文件" in log, log


@case("J11 非零返回码：记 [失败] 而不中断后续文件")
def j11_rc_nonzero():
    d = C.fresh("j11_rc")
    f1, f2 = Path(d) / "a.wav", Path(d) / "b.wav"
    f1.write_bytes(b"x")
    f2.write_bytes(b"x")
    seen = []

    def fake_run(cmd, **kw):
        seen.append(list(cmd))
        rc = 1 if cmd[-1].endswith("a.wav") else 0
        return types.SimpleNamespace(returncode=rc, stdout="", stderr="")

    orig = sep.subprocess.run
    sep.subprocess.run = fake_run
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            sep.SeparationTab._run_demucs(_fake_self(d, Path(d) / "out", "vocals"))
    finally:
        sep.subprocess.run = orig
    log = buf.getvalue()
    assert len(seen) == 2, "失败后仍应继续处理下一个文件"
    assert "[失败] 返回码 1" in log, log
    assert "[全部完成]" in log, log


# ───────── 启动阻塞防线（本轮真 bug 的回归守卫）─────────
@case("J11 启动不阻塞：检测走后台线程 + root.after 回主线程刷 UI")
def j11_non_blocking():
    src = Path(SEP).read_text(encoding="utf-8")
    assert "threading.Thread" in src, "检测必须在后台线程跑"
    assert "root.after(0, apply)" in src, "UI 刷新必须回主线程"
    # apply 的定义要在线程启动之前；线程要在文件末尾启动（后台跑完再回主线程）
    i_def = src.index("def apply():")
    i_call = src.index("self.app.root.after(0, apply)")
    i_thr = src.index("threading.Thread(target=job")
    assert i_def < i_call < i_thr, (i_def, i_call, i_thr)
    # 主线程不得直接调 subprocess 探 demucs（那会卡住 mainloop）
    body = src[src.index("def _check_demucs"):i_thr]
    assert body.count("subprocess.run") == 1, "探测只允许在 job 闭包里跑一次"


@case("J11 冻结环境守卫：exe 模式绝不拿 sys.executable 去 import demucs")
def j11_frozen_guard():
    src = Path(SEP).read_text(encoding="utf-8")
    guard = 'not getattr(sys, "frozen", False)'
    assert guard in src, "必须显式排除冻结环境"
    # 用 sys.executable 探 import demucs 的调用必须落在守卫之后
    probe = src.index('"import demucs; print(')
    assert guard in src[:probe], "冻结守卫必须出现在 import demucs 探测之前"
    # 守卫分支里不得回落到 sys.executable（否则等于把 GUI 自己当子进程重跑）
    guarded = src[probe:src.index("def apply():")]
    assert "sys.executable" in guarded and "frozen" not in guarded.split("if ")[0]


# ───────── 启动崩溃回溯钩子 ─────────
@case("钩子：main() 装上 sys.excepthook，异常路径也写回溯")
def hook_installed():
    src = Path(JY_CODE, "gui.py").read_text(encoding="utf-8")
    assert "sys.excepthook = _dump_crash" in src
    assert src.count("_dump_crash(*sys.exc_info())") == 1, "except 分支应再兜一层"


@case("钩子：_dump_crash 把回溯写到 exe 旁 + TEMP 两份")
def hook_writes_two_places(tmp=None):
    import tempfile
    d1 = C.fresh("j11_crash_a")
    d2 = Path(tempfile.mkdtemp(prefix="pt_crash_"))
    os.environ["TEMP"] = str(d2)
    try:
        try:
            raise ValueError("排障自测：这一行应该出现在回溯里")
        except ValueError:
            jygui._dump_crash(*sys.exc_info())
    finally:
        os.environ.pop("TEMP", None)
    # _dump_crash 写 exe 旁（=当前解释器目录，测试环境不一定可写）+ TEMP
    hit = list(d2.glob("jianying_crash.log"))
    assert hit, "TEMP 侧必须落 jianying_crash.log"
    body = hit[0].read_text(encoding="utf-8")
    assert "排障自测" in body and "ValueError" in body, body[:400]


if __name__ == "__main__":
    sys.exit(C.report("J11 人声分离 + 崩溃回溯钩子 回归（v2.9.0）"))
