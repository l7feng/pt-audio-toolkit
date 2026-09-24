# W6 · onefile vs onedir 打包形态说明（2026-09-24）

> 结论先行：**维持 onefile，暂不切 onedir**。本页记录两种形态的取舍与
> 将来切换时要动哪些地方，避免下次重新推导。

## 现状

- 四工具均以 PyInstaller **onefile** 打包（26–32 MB），双击启动需自解压，
  首启偏慢（约 1–3 秒，冷缓存更久）。
- `启动.bat` 会**动态解析**出口里最新的 `pt-audio-toolkit-v<版本>-<日期>`
  目录，不依赖固定路径（2026-09-23 出口收敛时改的）。

## 两种形态对比

| 维度 | onefile（现状） | onedir |
|---|---|---|
| 启动速度 | 慢（每次自解压到 %TEMP%） | 快（免解压） |
| 目录观感 | 单个 exe，干净 | 一坨 `_internal/`，误删即坏 |
| 分发/备份 | 复制一个文件 | 复制整个目录 |
| 与「配置 exe 旁」的配合 | 配置/日志在 exe 旁，随版本目录走 | 同左，但 exe 与 _internal 并列 |
| 诊断 | `-y` 可解包；warn 文件在 build 目录 | 直接看 _internal |

## 若将来要切 onedir

1. `tools/build.py` 给 PyInstaller 加 `--onedir`（四工具 TARGETS 各一份 spec
   或参数），staging → 移动出口的流程不变；
2. `verify_exe.py` 的清单核对逻辑按目录形态调整（exe 在根、依赖在 `_internal/`）；
3. `PathResolver._builtin_scripts_root()` 已按「exe 同目录 `_internal/skills`」
   探测，onedir 下天然成立，无需改；
4. `启动.bat` 的动态解析不用动（它认的是出口顶层目录与其中 exe）。

## 决策记录

- 2026-09-24（07 清单 W6）：现状能忍就不动 —— 启动慢的痛点已被
  「任务完成托盘通知（W7）」部分对冲，而 onedir 的"目录散"会放大误删风险
  （用户环境里 `My-Temporary` 已有误清理前科，见 J3）。
