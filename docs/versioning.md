# W5 · 版本号双轨规则（2026-09-24 定稿）

> 本规则不写代码，是仓库维护纪律。背景：仓库 VERSION 与工具内 APP_VERSION
> 是**两套版本轨**，历史上发生过「剪映版本带飞仓库版本」的断档
> （1.5.0–2.6.1 期间仓库 VERSION 跟着 jianying 走，CHANGELOG 未登记）。

## 规则

1. **工具版本（APP_VERSION）**：`pt-tools` /
   `jianying-draft-toolkit` / `rename-unify` 各自独立演进，谁改谁升
   （修 bug 升 patch，加功能升 minor，破坏性升 major）。
2. **仓库版本（VERSION 文件）**：只在**发版日**由打包发起人统一改一次，
   当轮三个工具的版本以 CHANGELOG 的对照行为准，不强求与 VERSION 相等。
3. **CHANGELOG 每轮必登记**「仓库版本 | 日期 | 三工具版本对照 | 要点」一行，
   这是两轨之间唯一的权威对照表。
4. exe 出口：`Agent-Preset\exe\` 下按家族分目录——PT/剪映共用 `音频工具箱-v<仓库版本>-<日期>\`，统一命名工具独立 `统一命名工具-v<工具版本>-<日期>\`。

## 判定口径速查

- 窗口标题/关于里的版本 = 各工具 APP_VERSION（校验 exe 是否新版看它）；
- `启动.bat` / 出口目录名 / git tag = 仓库 VERSION；
- 两者不一致是**常态**，一致与否不作为发布障碍，CHANGELOG 对照行不缺即合规。
