# ptsl-boot —— PTSL 服务启动 / 自愈方案

> 状态：**方案定稿，未实现**（2026-09-24，用户报障 Q2）
> 目标：解决「PTSL 服务未监听，怎么在 PT 里重启」——先给一份可执行的诊断/启动脚本，
> 稳定后打成 exe。实现时以本文档为准。

---

## 〇、三条硬结论

1. **PTSL 不能单独重启**：它是跑在 Pro Tools 进程内的 gRPC server，无用户可见开关，
   生命周期 = Pro Tools 进程。所谓"在 PT 里重启"唯一等价动作是 **重启 Pro Tools**。
2. **"未监听"是四个状态，不是一个**：见 §二。现状工具只输出一句
   「PTSL 离线，请先启动 Pro Tools」，在"PT 明明开着"时是误导。
3. **盲杀 Pro Tools 是红线**：强杀丢未保存工程。脚本默认绝不杀，
   杀必须 `--force-restart` + 二次确认 + 先温柔关闭。

## 一、事实底座（本机实测）

| 项 | 值 |
|---|---|
| PTSL 监听 | `127.0.0.1:31416`（TCP/gRPC），`pt_tools_gui.py:37-38` |
| Pro Tools 主程序 | `C:\Program Files\Avid\Pro Tools\ProTools.exe` |
| 进程名 | `ProTools.exe` |
| py-ptsl | `602.0.0`（grpcio 1.76.0 / protobuf 7.36.1） |
| venv | `<skills_root>\pt-exporter\env\venv\Scripts\python.exe` |
| 现有探测 | `ptsl_online()`（socket，1s timeout），`pt_tools_gui.py:892` |
| 现有轮询 | `_poll_ptsl()` 每 5s，`pt_tools_gui.py:1679` |

⚠️ py-ptsl 版本号（602）= **PTSL API 版本**，必须与 Pro Tools 版本匹配；
不匹配时端口通但握手失败 → "灯亮却导出失败"。必须纳入判定。

## 二、四态判定矩阵

| 态 | 端口 | PT 进程 | 判定 | 处置 |
|---|---|---|---|---|
| **A 在线** | 通 | 在 | 正常 | 无。可选握手验证工程已打开 |
| **B 没开 PT** | 不通 | 不在 | 最好办 | 启动 PT（可带 .ptx），轮询等端口 |
| **C 启动中/被阻塞** | 不通 | 在（< 90s） | 加载插件中或弹了模态框 | 等待重试 + 提示去看 PT 窗口 |
| **D 僵死** | 不通 | 在（≥ 90s） | PTSL 没起来 / PT 卡死 | 需重启 PT；默认只提示 |

亚型：**A1 端口通但没打开工程**（扫描/导出必失败）；
**A2 版本不匹配**（握手报 PTSL 版本错）。

## 三、三层探测（便宜 → 贵）

1. **socket connect** `127.0.0.1:31416`，timeout 1s —— 零依赖，可打进 exe。
2. **`tasklist /FI "IMAGENAME eq ProTools.exe" /V /FO CSV`** —— 零依赖，
   拿 PID + 窗口状态（`Running` / `Not Responding`），后者是判 D 态最便宜的信号。
3. **venv python + py-ptsl 握手** —— 只在第 1 层通过后跑（冷启动 ~2s），
   确认有无工程、版本是否匹配。

GUI 侧 5s 轮询只跑第 1 层；第 3 层仅用户点「诊断」时跑。

## 四、处置动作规格

### B 启动
```
start "" "C:\Program Files\Avid\Pro Tools\ProTools.exe" [--ptx]
```
轮询间隔 2s，上限 `--launch-timeout`（默认 **180s**），每 15s 打一行进度
（否则用户以为又卡死——见 Q12 教训）。命中 → 0；超时 → 1 + 提示看对话框。

### C 等待
不动 PT，轮询上限 `--wait-timeout`（默认 **90s**）。必须打出：
> "Pro Tools 正在运行但 PTSL 未就绪——请检查 PT 窗口是否弹出了对话框
> （缺少插件 / 授权 / 工程恢复），点掉后会自动就绪。"

恢复 → 0；超时 → 2（**不做任何破坏性动作**）。

### D 重启（危险区）
1. 二次确认（CLI 交互 `y`；GUI 弹框含「未保存的工程改动会丢失」）；取消 → 130。
2. **温柔关闭优先**：`taskkill /IM ProTools.exe`（**不带 `/F`**），给 15s 让它弹保存框。
3. 15s 后仍在 → 再问一次，确认才 `taskkill /F /IM ProTools.exe`。
4. 重启 + 走 B 态轮询。结果：在线 → 3；仍离线 → 4 + 人工排查清单。

**红线**（写进代码注释）：
- ❌ 禁止把 `taskkill /F` 当默认路径；❌ 禁止自动执行 D 态；
- ❌ 本脚本**不复用** `kill_process_tree()`——那是杀自己 spawn 的子树，PTSL boot 碰的是 PT。

## 五、脚本规格

**落位**：`src/pt-tools/skills/pt-service/scripts/ptsl_boot.py`（新增第四技能，
可被 `PathResolver` 识别、打进 `_internal\skills\`）。

```
ptsl_boot.py                       # 只探测，无副作用（默认）
  --ensure / --launch / --ptx PATH
  --launch-timeout N   (180)   --wait-timeout N (90)
  --force-restart      (危险，需确认)  --yes (跳过确认，GUI 不用)
  --deep               (跑第 3 层握手)  --json  --quiet
```

退出码：`0` 在线｜`1` 启动后仍离线｜`2` PT 在跑但超时（未处置）｜
`3` 重启后在线｜`4` 重启后仍离线｜`5` 环境问题（venv 缺失等）｜`130` 用户取消

`--json` 字段：`port_open / pt_running / pt_pid / pt_responsive / state /
session_name / ptsl_version_ok / action / exit_code / message`

**GUI 接线**：`pt_tools_gui.py:1549` 指示灯旁加「诊断/修复」按钮；
`:1679 _poll_ptsl()` 保持 5s 轻量轮询，灯不亮时启用按钮，点了跑 `--ensure --deep`；
i18n 双字典补 `s_ptsl_diag` / `s_ptsl_fix` / `s_ptsl_state_c` / `s_ptsl_state_d` /
`s_ptsl_restart_confirm`。

**打包**：先脚本跑通，稳定后 `tools/build.py` 加 `ptsl-boot` 目标，
出口统一 `D:\Ai-Files\Agent-Preset\exe\pt-audio-toolkit-v<版本>-<日期>\`。
纯标准库，无第三方依赖。

## 六、落地顺序

- **D1** 脚本骨架：参数 + 三层探测 + `--json` + 退出码（只读，安全）。
- **D2** B/C 态：启动 PT + 轮询 + 进度打印 + 超时文案。
- **D3** D 态重启：确认 → 温柔 → 强制 → 重启 → 再等待。**用可丢弃测试工程单独测。**
- **D4** GUI 接线 + 打包出 exe。

## 七、待拍板

1. A1（端口通但没工程）要不要自动打开 `--ptx`？建议**只提示不自动开**。
2. D 态超时 90s 是否够（大工程加载时长）？
3. 做成第四技能（集成进 exe）还是独立小 exe？
