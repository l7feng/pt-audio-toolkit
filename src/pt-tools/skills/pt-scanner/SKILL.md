---
name: pt-scanner
description: 扫描正在运行的 Pro Tools 工程，生成结构化 JSON 档案（pt-profile.json）：机器环境、工程参数（采样率/位深/时码率/长度）、全部轨道清单（类型/格式/时基/静音/独奏/隐藏/父文件夹）、导出源清单（Bus/Output/PhysicalOut）。供 pt-exporter、pt-cleaner 与 AI 智能体共享，实现跨会话、跨工程的 Pro Tools 自动化。适用于需要"读取当前工程状态"的任何任务（导出前确认、路由检查、工程盘点）。
---

# pt-scanner —— Pro Tools 工程扫描器

扫描正在运行的 Pro Tools 工程，输出统一 JSON 档案，供同家族的 `pt-exporter` / `pt-cleaner` 及 AI 智能体消费。

## 运行前提

| 条件 | 说明 |
| --- | --- |
| Pro Tools | 已启动（本家族面向 PT 25.x，PTSL v6） |
| 工程 | 已加载目标工程（不必保存） |
| PTSL | `PTSL.dll` 位于 PT 安装目录，服务监听 `localhost:31416` |
| Python | venv：`D:\Ai-Files\Agent-Preset\Skills\protools-skills\pt-exporter\env\venv\Scripts\python.exe`（内置 py-ptsl） |

## 使用方法

```powershell
# 输出到当前目录 pt-profile.json
& $venvPython pt_scan.py

# 指定输出目录与文件名
& $venvPython pt_scan.py --out "D:\path\dir" --name pt-profile.json
```

- `--out`：输出目录（默认 `.`，自动创建）
- `--name`：文件名（默认 `pt-profile.json`）

退出码：0 成功；1 失败（PT 未启动 / 未加载工程 / 连接失败），此时 stderr 会给出原因。

## 交互流程

1. **确认环境**：检查 Pro Tools 是否已启动、目标工程是否已加载（`session_name` 与预期不符时先 `pt-exporter` 打开正确工程）。
2. **扫描**：运行 `pt_scan.py`。
3. **展示**：读回 JSON，向用户汇报摘要：工程名、采样率/位深/时码率、长度、轨道总数、可用后缀（`.ptx`）路径、导出源（Bus/Output）清单。
4. **确认**：与用户确认扫描结果是否符合预期（尤其是目标 bus / 主输出是否在列表内）。
5. **保存**：把 `pt-profile.json` 放到 `工作目录/profiles/` 下（如 `<剧名>\profiles\pt-profile.json`），后续导出/清理步骤直接引用。

## pt-profile.json 结构

```jsonc
{
  "schema_version": "1.0",
  "scanned_at": "ISO 8601 UTC",
  "machine": { "hostname", "platform", "python", "ptsl_version" },
  "session": {
    "name": "工程名（不含 .ptx）",
    "path": "完整 .ptx 路径",
    "sample_rate": 48000,            // Hz，真实数值
    "bit_depth": "24-bit",           // 枚举映射：16-bit/24-bit/32-bit float
    "bit_depth_raw": 3,              // 原始枚举值
    "timecode_rate": "25",           // fps 字符串
    "timecode_rate_raw": 3,
    "start_time": "00:00:00:00.00",
    "length": "06:00:00:00"
  },
  "tracks": [                        // 50 条轨道示例（1-based index）
    { "index": 1, "name": "Master Hole", "type": "master",
      "format": "stereo", "timebase": "samples", "color": "#ff47000b",
      "parent_folder": "", "attributes": { "is_muted": false, ... } }
  ],
  "sources": {
    "physicalout": ["链接输出 1-2"],  // 中文名由 GBK 转义还原
    "bus": ["DX-BUS-Master", ...],
    "output": ["Master Hole"],
    "renderer": []                    // 无 Renderer 设备时空数组
  }
}
```

### 枚举映射速查（以安装版 PTSL_pb2 为准）

| 字段 | 值 |
| --- | --- |
| timecode_rate | 1=23.976, 2=24, 3=25, 4=29.97, 5=29.97DF, 6=30, 7=30DF, 8=47.952, 9=48, 10=50, 11=59.94, 12=59.94DF, 13=60, 14=60DF, 15=100, 16=119.88, 17=119.88DF, 18=120, 19=120DF |
| bit_depth | 1=none, 2=16-bit, 3=24-bit, 4=32-bit float |
| track.type | 1=midi, 2=audio, 3=aux, 4=video, 5=vca, 6=tempo, 7=markers, 8=meter, 9=key-signature, 10=chord-symbols, 11=instrument, 12=master, 13=heat, 14=basic-folder, 15=routing-folder, 16=comp-lane |
| track.format | 1=mono, 2=stereo, 3=LCR, 4=LCRS, 5=quad, 6=5.0, 7=5.1, 8=5.0.2, 9=5.1.2, 10=5.0.4, 11=5.1.4, 21=7.1.4, ... |
| track.timebase | 1=samples, 2=ticks, 3=none |
| source type | 1=physicalout, 2=bus, 3=output, 4=renderer |

## 已知问题与规避

1. **PTSL 中文编码 bug**：PhysicalOut 名称中的非 ASCII 字符被转义成 `\xNN`（GBK 双字节），非法 JSON。已在 `json_cleanup` 中按 GBK 整体还原（`json_cleanup → _GBK_RUN_RE`）。若换用新版 PTSL 修复了此问题，可移除该适配。
2. **Renderer 源**：无 Dolby Renderer 设备的工程查询 `EMSType_Renderer` 会报 `PT_InvalidParameter`，已吞掉并记空数组（带 `[warn]` 提示），不影响 profile 其余部分。
3. **`session_bit_depth()` 返回值是枚举不是位深数**：3 是 24-bit（很多文档示例会误以为 32-float），映射表以安装版 proto 为准。
4. **`source_list` 是 `repeated string` 而非 `EM_SourceInfo` 对象**：直接取字符串列表，别用 `.name`。
5. **Windows 控制台乱码**：脚本已强制 stdout UTF-8；PowerShell 直接显示中文正常，若在 GBK code page 下仍乱码，先 `chcp 65001`。

## 与家族其他技能的协作

- `pt-exporter`：消费 profile 的 `session` + `sources`，确认目标 bus/Output 存在后再导出。
- `pt-cleaner`：消费 profile 的 `tracks`，定位输入轨做清理。
- 通用叙事：扫描（了解现状）→ 导出/清理（改变现状）→ 再扫描（验证效果）。

## 支持/反馈

脚本问题→本技能 `log.md`（追加）；PTSL 能力缺口→ `4-项目/05-PT技能通用化改造/` 方案文档；库内知识→ `3-知识库/04-分析/07-AI连接ProTools自动化路线.md`。