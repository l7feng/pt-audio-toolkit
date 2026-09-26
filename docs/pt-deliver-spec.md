# PT-Deliver 交付格式规范

> **状态**：正式化于 2026-09-27（D 档决策 3 后半）
> **版本字段**：`schema_version`，当前 `1.1`
> **校验器**：`src/pt-tools/ptools/core/deliver.py`（纯逻辑，可独立测试）
> **回归**：`tests/test_pt_deliver.py`

## 一、它是什么

**PT-Deliver** ＝ Pro Tools → 剪映 的**内部流水线交付格式**：一个 json 清单 + 一个 `audio/` 素材目录。

- **不做二进制**（不做自定义容器），因为素材本身就是 WAV，包一层只会增加解析成本；
- 与 **AAF** 不冲突：AAF 是**对外交换**格式（给别的 DAW / 剪辑系统），PT-Deliver 是**内部流水线**格式（PT → 剪映），可并存；
- 既有产物**无需迁移**：C 批（`b736fb3`）产出的 `pt-clips.json` 已带 `schema_version: "1.1"`，本身就是合法的 PT-Deliver 1.1 包（实测法老35 / 18 素材 / 31 轨 直接通过校验）。

## 二、包结构

```
<工程名>-导入包/
├── pt-clips.json          # 清单（本规范描述的对象）
└── audio/
    ├── 35.1.L.wav
    └── ...
```

## 三、字段说明（`schema_version = "1.1"`）

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `schema_version` | str | ✅ | 版本号字符串（`"1.1"`）。缺失按 `1.0` 处理并告警 |
| `session` | dict | ✅ | `name` / `sample_rate` / `fps` / `raw_summary`（工程元信息） |
| `online_files` | list | ✅ | 包内素材清单，每项 `{name, location}`，`location` 为包内相对目录（通常 `audio/`） |
| `tracks` | list | ✅ | 按轨组织的片段，每项含 `name` / `format` / `clips[]` / `fades[]` / `index` / `format_code` / `type_code` |
| `track_meta` | list | ✅（1.1 起） | `GetTrackList` 的全类型轨元信息 `{name, index, format, type}` |
| `clip_file_map` | dict | 1.1 起 | 片段名 → **包内实际文件名**（合成件如 `X.L.stereo.wav` 必须在这里体现） |
| `track_count` | int | 可选 | 导出文本里的音频轨数 |
| `source` / `scanned_at` | str | 可选 | 产出来源与扫描时间（排障用） |

> ⚠️ **两条实践经验写进了校验器**：
> 1. `online_files` 必须列**包内实际存在的文件名**（照抄原始名会让导入端的「在线文件清单校验」把所有素材挡掉）；
> 2. `clip_file_map` 的值必须能在 `online_files` 里找到，否则导入端按旧名寻址必然失败 —— 校验器把这条判为 **error**。

## 四、校验器用法

```python
from ptools.core import deliver as DL

# 1) 只校验 json（不碰盘）
errors, warnings = DL.validate_structure(doc)

# 2) 校验整个包目录（素材存在性 + md5 + 可选时长对齐）
errors, warnings, stats = DL.validate_package(doc, pkg_dir,
                                              check_md5=True,
                                              check_duration=False)

# 3) 兼容读取：旧版 doc 补齐成当前版本可读形态
doc, warns = DL.upgrade(doc)

# 4) 一行摘要（日志 / UI）
DL.describe(doc)     # -> "PT-Deliver v1.1 · 法老35 · 18 素材 / 31 轨"
```

**判定口径**：`errors` 非空 ＝ 这个包**不该**被导入；`warnings` 只提示（如空轨、`session.name` 为空）。

## 五、兼容规则

| 场景 | 规则 |
|---|---|
| 缺 `schema_version` | 按 `1.0` 处理 + warning |
| `1.0` → `1.1` | 补 `track_meta=[]`、`clip_file_map={}`、`source=""`、`scanned_at=""` |
| 未来 `1.2` | **只加可选字段**时旧版仍可读（校验器不因缺新字段报错）；若改语义则提升 `SUPPORTED_VERSIONS` 并写明迁移 |
| 高于支持范围的版本 | 原样读取 + warning（**不阻断**，避免新版本包被旧工具卡死） |

> 升级一律遵循「**只补缺失、不改既有值**」——与 config 的合并式落盘同源。

## 六、谁产出 / 谁消费

| 角色 | 位置 |
|---|---|
| 产出 | `skills/pt-clips/scripts/pt-clips.py`（总控）→ `pt_clip_scan` + `make_delivery_package` |
| 消费 | 剪映工具箱导入端（`_delivery_package` 离线识别） |
| 校验 | `ptools/core/deliver.py`（导入端应在导入前调用 `validate_package`） |

## 七、未做的事（有意不做）

- **不做二进制容器**：收益低于成本；
- **不替代 AAF**：AAF 继续作为对外交换通道保留；
- **不做跨版本自动迁移写回**：只读补齐，不改用户的包文件。
