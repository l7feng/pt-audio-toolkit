# -*- coding: utf-8 -*-
"""技能目录解析（W1 三层拆分 · core/paths）。

内置脚本（打包进 exe 内 _internal\\skills）与外部技能树并存的
探测顺序维持 v1.x 语义：配置值 → 环境变量 → 默认路径。
"""
import os
import sys
from .config import save_config
from .i18n import T
from .settings import DEFAULT_SKILLS_ROOT, ENV_SKILLS_ROOT, SCRIPTS

# ---------------------------------------------------------------------------
# 路径解析：venv python（来自技能树）+ 脚本（优先 exe 内置 _internal\\skills）
# ---------------------------------------------------------------------------

class PathResolver:
    def __init__(self, skills_root):
        self.skills_root = skills_root

    # ---- 内置脚本（打包时复制进 dist\\_internal\\skills\\）----
    @staticmethod
    def _builtin_scripts_root():
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(sys.argv[0]))
        cand = os.path.join(base, "_internal", "skills")
        return cand if os.path.isdir(cand) else None

    @property
    def venv_python(self):
        return os.path.join(self.skills_root, "pt-exporter", "env", "venv",
                            "Scripts", "python.exe")

    def script(self, skill_name):
        builtin = self._builtin_scripts_root()
        if builtin:
            p = os.path.join(builtin, skill_name, "scripts", SCRIPTS[skill_name])
            if os.path.isfile(p):
                return p
        return os.path.join(self.skills_root, skill_name, "scripts",
                            SCRIPTS[skill_name])

    def status(self):
        """返回 (ok, msg)：技能目录可用性。

        判定顺序按「到底缺哪一环」排，而不是按目录是否存在 —— 打包后脚本已内置到
        `<exe目录>/_internal/skills/`，此时技能目录不存在并不等于脚本缺失。
        venv 因体积不随 exe 打包，是唯一**必须外置**的依赖，缺它时应给出可操作指引。
        """
        builtin = self._builtin_scripts_root()
        missing = [s for s in SCRIPTS if not os.path.isfile(self.script(s))]
        if missing:
            if not os.path.isdir(self.skills_root) and not builtin:
                return False, T("err_root_missing") % self.skills_root
            return False, T("err_scripts_missing") % ", ".join(missing)
        if not os.path.isfile(self.venv_python):
            if builtin:
                return False, T("err_venv_missing_builtin") % (self.venv_python,
                                                               DEFAULT_SKILLS_ROOT)
            return False, T("err_venv_missing") % self.venv_python
        return True, T("skills_ok") % self.skills_root

    @classmethod
    def detect(cls, cfg):
        """自动探测技能目录：配置值（用户显式设过）→ 环境变量 → 默认路径。
        返回 (resolver, ok, msg)，并把命中的目录回写配置。"""
        candidates = []
        if cfg.get("skills_root"):
            candidates.append(cfg["skills_root"])
        env = os.environ.get(ENV_SKILLS_ROOT)
        if env:
            candidates.append(env)
        candidates.append(DEFAULT_SKILLS_ROOT)

        for c in candidates:
            r = cls(c)
            ok, msg = r.status()
            if ok:
                if cfg.get("skills_root") != c:
                    cfg["skills_root"] = c
                    save_config(cfg)
                return r, True, msg
        r = cls(cfg.get("skills_root") or DEFAULT_SKILLS_ROOT)
        ok, msg = r.status()
        return r, ok, msg
