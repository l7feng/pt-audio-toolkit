# 剪映工程工具包（jianying-draft-toolkit）

一个 GUI，三件独立的事 —— 把 Pro Tools 工程的多轨结构「翻译」进剪映草稿，并支持跨设备离线交付。

## 三个标签页

| 标签页 | 干什么 | 依赖 | 谁用 |
|---|---|---|---|
| **① 导出音频** | 剪映草稿 → 按时间线切片导出音频（命名模板 + 分类归档） | ffmpeg、剪映（解密用） | 任何人 |
| **② 导入多轨** | `.ptx`（需 PT 在线）/ 交付包 json（离线）→ 写入剪映草稿 | jy-draftc；`py-ptsl` 仅解析 `.ptx` 时需要 | 你 / 剪辑 |
| **③ 生成交付包** | json 路径相对化 + 音频随包（含 L/R 预合成立体声） | 无 | 你 |

**三页配置彼此完全独立**：各页只写自己的配置字段，互不覆写。

## 菜单栏

窗口顶部有 4 组菜单，`核心诉求（集中改路径）` 在「设置」里：

| 菜单 | 项 |
|---|---|
| **文件** | 保存全部配置（Ctrl+S）/ 重新载入配置 / 打开配置文件所在文件夹 / 打开配置文件（记事本）/ 退出 |
| **设置** | **默认路径设置…** ← 5 个路径字段集中一处改，改完即存为默认 / 恢复出厂默认（仅路径） |
| **工具** | 刷新状态（PT / 剪映）/ 环境自检 / 清理立体声合成缓存 / 打开临时目录 |
| **帮助** | 使用说明 / 打开程序目录 / 关于（版本 + 构建日期） |

**「默认路径设置…」为什么值得单列**：三页的输入/输出目录分散在各自标签页，
换工作目录要切页逐个改。菜单把它集中到一处，且**能存成默认**——下次开 exe 直接生效。

对话框只管 5 个**路径**字段（`input_dir` / `output_dir` / `temp_dir` /
`import_draft_dir` / `import_pkg_out`）。「恢复出厂默认」**只重置路径**，
不碰你调好的命名模板 / 规格 / 开关。

动作逻辑在 `core/menus.py`（纯标准库、可单测），对话框在 `tabs/paths_dialog.py`。

## 关键设计：为什么「解析」与「写入」分成两步

PTSL（py-ptsl）**不是文件解析器**，它只是向「正在运行的 Pro Tools」发命令、
拿回会话信息。因此：

- **解析 `.ptx` 无法离线** —— 必须 PT 在线；
- **写入草稿可以完全离线** —— 拿到 json 后与 PT 再无关系。

两者的前置条件还是**互斥**的（分时，不是二选一）：

```
① 开 PT  → 解析得 json        （剪映开不开无所谓）
② 关剪映 → 写入草稿            （PT 开不开无所谓）
③ 开剪映 → 检查结果
```

GUI 按这个模型组织：②页的「① 解析 PT 工程」按钮在 PT 离线时置灰，
「② 导入到剪映草稿」按钮在剪映运行时置灰 —— 不满足条件根本点不下去，
不会走到一半才报错。

## 跨设备离线交付怎么走

需要给剪辑（或另一台没有 PT、没有原始工程路径的机器）导入时：

1. 本机：**① 开 PT → ②页「解析 PT 工程」** 得到 `pt-clips.json`
2. 本机：**③页「生成交付包」** → 产出 `<工程名>-导入包/`
   ```
   <工程名>-导入包/
   ├── <工程名>.pt-clips.json   ← 路径已相对化
   ├── audio/                    ← 素材（含预合成的 *.stereo.wav）
   ├── 导入工具.exe              ← 固定资产，一次做好
   └── 01-使用说明.txt           ← 固定资产，一次做好
   ```
3. 剪辑机器：解压 → 双击 `导入工具.exe` → ②页选包里的 json → 导入

打包时会同步改写**三处**（缺一即失败，都是实际踩过的坑）：

| # | 改什么 | 不改的后果 |
|---|---|---|
| a | `online_files[].location` → `audio/` | 找不到素材 |
| b | `clip_file_map` 的值 → 包内实际文件名 | 找不到素材（L/R 合成件改名了） |
| c | `online_files` 清单 → 按包内实况重建 | 导入器的清单校验把素材全挡掉 |

### 固定资产 vs 日常交付

`导入工具.exe` 与 `01-使用说明.txt` 是**一次性做好、长期复用**的两样东西，
不参与日常打包：

- 固定资产位置：`D:\Ai-Files\Agent-Out-exe\_delivery\_交付模板\`
- 日常只要跑 ③页 生成 `json + audio/`，把那两样一起拖进包里压缩发出去即可

③页在生成完会问一句「是否顺手复制固定资产」—— 点一次「是」就补齐了。

## 前置条件

- Windows 10/11
- **带 tkinter 的 Python**（源码模式）；Windows 官方安装包自带
- `ffmpeg`（仅 ①导出页 需要）
- 剪映专业版已安装（`jy-draftc` 解密要靠它的 `videoeditor.dll`）
- **`py-ptsl`（可选）**：只有「解析 .ptx」需要；装不上也不影响离线 json 导入

## 运行（源码模式）

```powershell
cd code
python gui.py
```

## 打包为 exe

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

产物：`packaging/dist/导入工具/`（约 31.6 MB）

```
导入工具/
├── 导入工具.exe        ← 双击运行（GUI，三标签页）
├── _internal/          ← PyInstaller 运行时
└── tools/jy-draftc/    ← 解密器（.env 首次运行时自动写入）
```

要点：

- **onedir，不是 onefile**：`tools/` 必须在 exe 旁的真实目录，因为 `jy-draftc`
  运行时要把剪映路径写进 `.env`；onefile 会解压到临时目录并被清掉
- **必须整个文件夹搬动**（`_internal/` 与 `tools/` 都在 exe 旁）
- **不打包 `py-ptsl`**：剪辑机器不需要它，装了只增加体积与杀软误报；
  代价是 exe 里「解析 .ptx」不可用（离线 json 导入照常）
- `build.ps1` **保持纯 ASCII**：PS 5.1 按 ANSI/GBK 读 `.ps1`，
  文件里写中文会乱码甚至让解析失败

## 配置文件

- 位置：exe 旁（源码模式为包根的 `config.json`）
- 旧版 `code/config.json` 首次运行会自动迁移过来
- 三个标签页各写自己的字段；「保存全部配置」一次写全

## 目录结构

```
jianying-draft-toolkit/
├── code/
│   ├── gui.py                    ← 主窗口（菜单栏 + 三标签页宿主）
│   ├── tabs/
│   │   ├── base.py               ← 标签页底座（配置/日志/异步/apply_config）
│   │   ├── export_tab.py         ← ① 导出音频
│   │   ├── import_tab.py         ← ② 导入多轨
│   │   ├── delivery_tab.py       ← ③ 生成交付包
│   │   └── paths_dialog.py       ← 默认路径设置对话框
│   ├── core/                     ← 领域层（禁止 import tkinter，可单测）
│   │   ├── config.py             ← 配置单一来源（默认值 / 读写 / 向导）
│   │   ├── host.py               ← 进程/端口探测（StatusProbe / CREATE_NO_WINDOW）
│   │   └── menus.py              ← 菜单动作（路径默认值读写/恢复、缓存清理）
│   ├── main.py                   ← 导出核心（+ 版本号、PT 探测、路径常量）
│   ├── import_audio.py           ← 导入核心（PT json / CSV → 草稿）
│   ├── pt_clip_scan.py           ← PTSL 扫描器（PT → pt-clips.json）
│   ├── make_delivery_package.py  ← 交付包生成
│   └── config.json               ← 历史配置（首次运行会迁移）
├── tools/jy-draftc/              ← 草稿解密器（wenshui330, MIT）
└── packaging/
    ├── build.ps1                 ← 一键打包
    └── dist/                     ← 打包产物
```

## M3：音频块时长延长

目标时长超过素材可用长度时（典型：音乐不够长，要延长适配画面），导入器不再拦截，
支持两种模式（CLI：`import_audio.py --extend "素材名=目标毫秒[:模式]"`，可重复）：

| 模式 | 原理 | 适用 |
|---|---|---|
| `loop`（默认） | 多段引用同一素材顺延时间码，相邻段重叠 200ms 交叉淡化，总长精确等于目标 | 音乐/氛围床延长，不变调 |
| `stretch` | 单段变速，写真实 speed 素材（speed = 源/目标）；**可能变调，待实测** | 想让素材「拉长/压短」时 |

也可以把 `target_ms` / `extend_mode` 直接写进 pt-clips.json 的 clip 条目 ——
覆盖随 json（含交付包）走，剪辑机器无需命令行。

```powershell
python import_audio.py --pt-clips 包\工程.pt-clips.json "草稿目录" --extend "107林间小路=86727:loop"
```

## 已知限制

- 「解析 `.ptx`」在打包的 exe 里不可用（未打包 `py-ptsl`）；需要就地解析请用源码模式
- 变速延长（`stretch`）的音调表现（变调/不变调）待剪映内实测确认；循环延长不受影响
- 剪映草稿是「双份 + 多时间线」结构，写入时必须两份同步写；
  只写根目录会导致「导入了但剪映看不到」

## License

- 主脚本：MIT
- jy-draftc：MIT（wenshui330）
