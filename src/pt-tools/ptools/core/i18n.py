# -*- coding: utf-8 -*-
"""i18n 词条表与语言状态（W1 三层拆分 · core/i18n）。

GUI 只调 T(key) 取词；语言状态 _cur_lang 是本模块私有，
外部读当前语言请用 get_lang()（原先 GUI 直读 _cur_lang 的习惯已收敛）。
"""
from .settings import APP_VERSION, build_date, LANG_ZH, LANG_EN

# ---------------------------------------------------------------------------
# i18n 词条表（单语 UI：中文 / English）
# ---------------------------------------------------------------------------

TEXTS = {
    LANG_ZH: {
        "app_title": "pt-tools v%s (%s) — Pro Tools 自动化工具" % (APP_VERSION, build_date()),

        "menu_file": "文件",
        "menu_settings": "设置",
        "menu_tools": "工具",
        "menu_help": "帮助",

        "file_open_outdir": "打开输出目录",
        "file_open_cfgdir": "打开配置与日志目录",
        "file_exit": "退出",

        "sett_lang": "语言",
        "sett_lang_zh": "中文",
        "sett_lang_en": "English",
        "sett_skills": "技能目录（Skills Root）…",
        "sett_outdir": "默认输出目录…",

        "tools_open_skills": "打开技能目录（资源管理器）",
        "tools_open_outdir": "打开输出目录",
        "tools_open_cfgdir": "打开配置与日志目录",
        "tools_clear_log": "清空日志",
        "tools_export_diag": "导出诊断包（zip：日志+配置+版本）",
        "msg_diag_exported": "诊断包已导出：%s",
        "msg_diag_failed": "诊断包导出失败：%s",

        # —— P1 PT 离线黄条 ——
        "pt_warn_bar": ("⚠  Pro Tools 未连接（PTSL 127.0.0.1:31416 不通）——扫描/导出暂不可用。"
                        "自查：PT 是否启动？启动中则可能仍在加载或 PTSL 被占用，详见 docs/ptsl-boot-plan.md"),
        "pt_warn_bar_ok": "",   # 在线时黄条隐藏，无文案

        # —— P4 PT 版本适配说明常驻条（v1.5.2 / B批）——
        "pt_info_bar": ("已验证：Pro Tools 25.6.1 · PTSL v6 · py-ptsl 602.0.0 · 端口 127.0.0.1:31416 ｜ "
                        "其他 PT 版本未经完整验证（PTSL 协议版本与命令集随版本可能不同）；"
                        "换设备/账号不受影响（PTSL 为本机服务）"),

        # —— P2 导出质检 ——
        "qc_running": "质检中…",
        "qc_none": "质检：输出目录里没有本次导出的 wav。",
        "qc_ok": "质检通过：%d 个文件，声道/采样率/位深/时长全部符合。",
        "qc_bad": "质检发现 %d 个异常（共 %d 个文件）：",
        "qc_note": "质检只读文件头，不动产物；此报告同时写入日志文件。",

        # —— P3 档案库页 / P4 导出历史 ——
        "tab_library": " 3 · 档案库 ",
        "lib_what_title": "本页功能",
        "lib_what_body": ("管理档案目录（profile_dir）里平铺的 pt-profile.json：搜索 / 加载到导出页 / "
                          "在资源管理器打开 / 删除（走回收站）。下方「导出历史」按修改时间列出输出根"
                          "（last_out_dir）里的工程文件夹，双击可直接打开。"),
        "lib_dir": "档案目录:",
        "lib_search": "搜索:",
        "lib_col_file": "档案文件",
        "lib_col_project": "工程名",
        "lib_col_mtime": "修改时间",
        "lib_col_size": "大小",
        "lib_refresh": "刷新",
        "lib_load": "加载到导出页",
        "lib_open_dir": "打开所在目录",
        "lib_delete": "删除（回收站）",
        "lib_delete_confirm": "确定把 %d 个档案移入回收站？\n（可在回收站恢复）",
        "lib_deleted": "[library] 已移入回收站 %d 个档案",
        "lib_delete_failed": "[library] 删除失败: %s",
        "lib_empty": "（档案目录为空或不存在）",
        "lib_hist_title": "导出历史（输出根，按修改时间）",
        "lib_open_outroot": "打开输出根",
        "lib_hist_empty": "（输出根为空或不存在）",
        "lib_bad_json": "[library] 档案读取失败（跳过）: %s",

        # —— W8 批量 CLI ——
        "b_save_jobs": "保存任务清单（jobs.json）…",
        "b_jobs_saved": "任务清单已保存（可交给 pt-tools --batch 夜间执行）：\n%s",
        "b_jobs_save_failed": "任务清单保存失败: %s",

        "help_howto": "使用说明",
        "help_about": "关于 pt-tools",

        "tab_scan": " 1 · 扫描建档 ",
        "tab_export": " 2 · 导出 ",
        "tab_clean": " 4 · 清理 ",

        # —— 扫描页 ——
        "s_what_title": "本页功能",
        "s_what_body": ("扫描当前 Pro Tools 工程，生成「工程档案」（pt-profile.json）。"
                        "档案记录轨道、总线、主输出的清单与时长——导出页（页签 2）"
                        "直接从档案取源，不会猜错名字，扫描一次即可反复使用。"),
        "s_req_title": "扫描前提",
        "s_req_ptsl_on": "●  Pro Tools 运行中（PTSL 在线）",
        "s_req_ptsl_off": "○  Pro Tools 未运行（PTSL 离线）",
        "s_req_line2": "请在 Pro Tools 中打开要导出的工程（如「Demo24.ptx」）。",
        "s_steps_title": "操作步骤",
        "s_step1": "1)  启动 Pro Tools 并打开工程",
        "s_step2": "2)  点下方「扫描并生成档案」（只读，安全）",
        "s_step3": "3)  成功后档案自动应用，直接去「导出」页",
        "s_out": "输出目录（档案放这里）:",
        "s_name": "档案文件名:",
        "s_scan_btn": "扫描并生成档案",
        "s_summary": "扫描摘要",
        "s_browse": "浏览…",
        "s_auto_applied": "[scan] 档案已自动应用：%s\n",
        "s_missing_out": "请先选择输出目录。",
        "s_bad_name": "档案文件名必须以 .json 结尾。",

        # —— 导出页 ——
        "e_profile": "档案（pt-profile.json）:",
        "e_browse": "浏览…",
        "e_mode": "导出模式（可多选）:",
        "e_mode_mix": "MIX 整段并轨",
        "e_mode_mix_tip": "主输出并成 1 个文件",
        "e_mode_stem": "STEM 全部分轨",
        "e_mode_stem_tip": "全部音源轨逐轨导出",
        "e_mode_stem_aux": "含效果辅助轨(aux)",
        "e_mode_bus": "BUS 总线分轨",
        "e_mode_bus_tip": "每条总线 1 个文件",
        "e_mode_track": "按轨道名称",
        "e_mode_track_tip": "从下方列表挑选轨道",
        "e_session": "工程:",
        "e_sess_current": "当前打开的",
        "e_sess_file": "指定文件",
        "e_track_frame": "轨道列表 —— 勾「按轨道名称」后可多选",
        "e_type_col": "类型",
        "e_search": "搜索:",
        "e_selected": "已选 %d 个",
        "e_name_col": "名称",
        "e_params": "参数",
        "e_start": "开始:",
        "e_end": "结束:",
        "e_fill_video": "按视频填入…",
        "e_tc_hint": "格式 HH:MM:SS:FF",
        "e_sr": "采样率:",
        "e_bd": "位深:",
        "e_fmt": "格式:",
        "e_out": "输出目录:",
        "e_preview": "预览导出计划",
        "e_export": "执行导出",
        "e_verify": "校验：时长×采样率×位深≈WAV 字节数",
        "e_video_title": "选择工程对应的视频文件",
        "e_video_running": "[video] 正在读取视频时长：%s\n",
        "e_video_ok": "[video] 已按视频填入时间范围：开始 00:00:00:00 → 结束 %s\n",
        "e_video_fail": "[video] 视频时长读取失败：%s\n"
                        "        支持 MP4/MOV 族（mvhd box）；也可手动填结束时间。\n",
        "e_video_margin_note": "结束 = 视频时长 + 余量",

        # —— v1.2.0 轨道选择 / 视频自动 / 批量 ——
        "e_sel_col": "选",
        "e_clips_col": "音频",
        "e_clips_yes": "有",
        "e_clips_no": "空",
        "e_excluded_mark": "（排除）",
        "e_select_all": "全选",
        "e_deselect_all": "全不选",
        "msg_fmt_bad": "无法识别的导出格式：%s\n（请在下拉里重新选一项，工具不会擅自替你猜一个）",
        "e_exclude": "排除名单:",
        "e_exclude_tip": "逗号分隔，支持 * ? 通配（如 BG 1, DX BUS, Master）；命中的轨道默认不勾选",
        "e_track_frame_v2": "轨道列表（勾选 = 导出；空轨与排除名单默认不勾）",
        "e_video_auto": "自动检测视频",
        "e_video_searching": "[video] 正在检索工程目录视频：%s\n",
        "e_video_found1": "[video] 找到 1 条视频：%s\n",
        "e_video_found_n": "[video] 找到 %d 条视频，请在弹窗中选择\n",
        "e_video_none": "[video] 未在工程目录检索到视频（可手动「按视频填入…」，"
                        "或按兜底时长导出）\n",
        "e_video_pick_title": "检索到多条视频，请选择用于锁定时长的视频",
        "e_video_applied": "[video] 已按「%s」填入：结束 %s（含余量 %ss）\n",
        "e_margin": "视频余量(秒):",
        "e_fallback": "兜底时长(秒):",
        "e_by_session": "输出按工程名建夹",
        "e_batch": "批量导出…",

        # —— v1.2.0 批量导出对话框 ——
        "b_title": "批量导出（多工程）",
        "b_ptx_frame": "工程列表（.ptx）——加入后自动预检索视频",
        "b_add": "添加工程…",
        "b_remove": "移除选中",
        "b_rescan": "重新检索",
        "b_col_session": "工程",
        "b_col_video": "选中视频",
        "b_col_status": "状态",
        "b_video_pick": "选择…",
        "b_video_multi": "%d 条，待选择",
        "b_video_none": "未检出（按下方策略处理）",
        "b_video_ok": "%s（%.0fs）",
        "b_policy_frame": "未检出视频时",
        "b_policy_fallback": "按兜底时长导出",
        "b_policy_skip": "跳过并记录",
        "b_multi_frame": "检出多条视频时",
        "b_multi_pick": "弹窗让我选",
        "b_multi_skip": "跳过并记录（含视频命名清单）",
        "b_rule_note": "批量沿用本页导出模式 / 格式 / 轨道规则；排除名单与空轨规则对每个工程生效；"
                       "输出自动按各工程名建文件夹。",
        "b_start": "开始批量导出",
        "b_need_ptsl": "批量导出需要 Pro Tools 正在运行（PTSL 在线）。",
        "b_need_ptx": "请先添加至少一个 .ptx 工程。",
        "b_generating": "[batch] 已生成批量计划：%s\n",
        "b_started": "[batch] 批量导出已启动（%d 个工程），请留意下方日志…\n",
        "b_searching": "[batch] 检索 %s …\n",
        "b_search_fail": "[batch] 检索失败：%s\n",
        "b_pick_title": "「%s」检出 %d 条视频，选择用于锁定时长的一条",

        # —— 清理页 ——
        "c_warn": ("⚠ 需 Pro Tools 2025.10+（CId 146/147）。当前 PT 25.6.1 实测支持不了"
                   "（ErrType 133），升级前此页不可操作。"),
        "c_cap": "能力边界",
        "c_cap1": "✅ 批量改轨道主输出（SetTrackMainOutputAssignments）",
        "c_cap2": "✅ 新建输出路径（CreateSignalPath）",
        "c_cap3": "❌ 删发送 / 删插件 / 删 IO 路径 —— PTSL 不支持",
        "c_params": "参数（骨架，待 PT 升级后启用）",
        "c_track_mode": "选轨方式: 按名字 / 按前缀",
        "c_track_col": "轨道列表（从档案读取，待启用）",
        "c_target_out": "目标输出: （下拉，待启用）",
        "c_backup": "备份/保存: （复选框，待启用）",
        "c_note": "预览 / 执行按钮将在 PT 升级且扫描建档后启用。",

        # —— 日志 / 状态栏 ——
        "log_frame": "日志",
        "log_clear": "清空日志",
        "log_hint": "耗时操作在后台执行，请留意底部状态。",
        "status_ptsl_on": "●  PTSL 在线（Pro Tools 运行中）",
        "status_ptsl_off": "○  PTSL 离线（请先启动 Pro Tools）",
        "status_session": "工程：%s",
        "status_profile": "档案：%s",
        "status_skills_ok": "技能 OK",
        "status_skills_bad": "⚠ 技能目录不可用",
        "lang_changed": "[i18n] 语言已切换。\n",
        "preview_start": "[preview] 预览开始（dry-run）……\n",
        "preview_pass": "[preview] 预览通过。参数未再改动前，可执行导出。\n",
        "cmd_done": "— 命令结束，退出码 %d —\n",
        "err_cmd_start": "[error] 无法启动命令：%s\n",
        "err_cmd_stop": "[error] 第 %d 条命令失败，剩余 %d 条已跳过。\n",
        "toast_title": "pt-tools",
        "toast_done": "任务已完成（退出码 %d）",
        "toast_aborted": "任务已中止",

        # —— v1.3.0 卡死专项（Q12）：中止 / 看门狗 / 关窗 ——
        "log_abort": "■ 中止",
        "abort_title": "中止当前任务",
        "abort_confirm": "确定中止正在运行的命令吗？\n"
                         "（已导出的文件会保留，未完成的部分不再生成；"
                         "只会终止本工具启动的子进程，不会动 Pro Tools 本体）",
        "log_aborting": "[abort] 已请求中止，正在终止子进程…\n",
        "cmd_aborted": "— 命令已被中止 —\n",
        "log_stalled": "[warn] 已 %d 秒没有任何输出，任务可能卡住（常见原因：Pro Tools 弹出了"
                       "待确认对话框）。可点「中止」停止。\n",
        "log_running": "运行中 %dm%02ds",
        "log_no_output": "距上次输出 %ds",
        "quit_title": "退出",
        "quit_confirm": "有任务正在运行，确定退出吗？\n"
                        "（会先终止本工具自己启动的子进程，不会影响 Pro Tools 本体）",

        # —— v1.3.0 导出格式语义（Q5）——
        # v2.6.5（P2）：「单声道（会下混）」文案有理解障碍，改写为动作描述
        "e_fmt_col": "声道",
        "e_fmt_follow": "跟随全局",
        "e_fmt_interleaved": "立体声/多声道 · 保留原宽度（每轨 1 个文件）",
        "e_fmt_mono": "单声道文件 · 立体声轨会被合并降混",
        "e_fmt_multimono": "多单声道 · 立体声拆成 L/R 两个文件",
        "e_fmt_hint": "「声道」不是声道数，而是 bounce 产物的文件组织方式；"
                      "实际宽度由 PT 工程里该轨/该输出的宽度决定。",

        # —— v1.3.0 路径锁定 / 输出预览 / 剔除空轨（Q3 Q6 Q7）——
        "e_lock": "🔒 锁定",
        "e_locked": "🔓 已锁定",
        "e_out_preview": "查看输出路径",
        "e_out_preview_title": "本次导出的落盘预览（只读）",
        "e_exclude_empty": "剔除空轨道（无音频块的轨不导出）",
        "e_excluded_view": "查看被剔除的 %d 条 ▸",
        "e_excluded_title": "被剔除的轨道 —— 可加回（撤回）",
        "e_restore": "加回",
        "e_close": "关闭",
        "e_restored": "[track] 已加回「%s」（本次不再按空轨剔除）\n",
        "e_out_preview_none": "  （当前勾选下没有任何产物 —— 检查导出模式与轨道勾选）",
        "e_out_preview_total": "  共 %d 个文件",
        "e_out_preview_dropped": "  另有 %d 条空轨被剔除（可在「查看被剔除」里加回）",
        "e_video_root_note": "检索范围：.ptx 同级 → 其父目录",
        "e_video_root_empty": "[video]   %s —— 没检索到，换下一个候选目录\n",
        "e_video_root_hit": "[video] 命中检索根：%s\n",
        "e_fallback_warn": "[warn] 未检出视频，已按兜底时长 %ss 导出 —— "
                           "这是**猜**的：工程若长于它会截断、短于它会多出静音尾巴。"
                           "建议补上视频或手工填结束时间。\n",

        # —— 设置/技能目录 ——
        "skills_ok": "技能目录 OK：%s",
        "err_root_missing": "技能目录不存在：%s",
        "err_venv_missing": "未找到 venv 解释器：%s\n（在 pt-exporter/env 下重建 venv 并 pip install py-ptsl）",
        "err_venv_missing_builtin": "技能脚本已内置，仅缺运行解释器的 venv：%s\n"
                                    "（venv 含 py-ptsl、体积大，不随 exe 打包；"
                                    "请在 设置 > 技能目录 指向含 venv 的技能目录，如 %s）",
        "err_scripts_missing": "缺少脚本：%s",
        "skills_broken_title": "技能目录不可用",
        "skills_broken_hint": "请通过 设置 > 技能目录 选择 protools-skills 文件夹（需含 venv 与三个技能脚本）。",
        "choose_skills_title": "选择 protools-skills 技能目录",
        "choose_outdir_title": "选择输出目录",
        "choose_profile_title": "选择 pt-profile.json",
        "choose_ptx_title": "选择 Pro Tools 工程（.ptx）",
        "no_outdir": "还没有设置过输出目录，请先在导出页选择。",

        # —— 弹窗 / 校验 ——
        "msg_profile_invalid": "档案无效",
        "msg_missing": "缺参数",
        "msg_invalid": "参数错误",
        "msg_no_profile": "尚未加载档案，请先扫描或浏览选择 pt-profile.json。",
        "msg_no_source": "请至少选择一个导出源。",
        "msg_no_mode": "请至少勾选一种导出模式（MIX / BUS / STEM / 按轨道名称）。",
        "msg_no_track_sel": "已勾选「按轨道名称」，请在下方轨道列表中选择要导出的轨道。",
        "msg_no_output_src": "已勾选 MIX 整段并轨，但档案中没有输出路径（output）——请重新扫描。",
        "msg_no_bus_src": "已勾选 BUS 总线分轨，但档案中没有总线（bus）——请重新扫描。",
        "msg_no_srctype": "档案中无 %s 类型源。",
        "msg_src_unknown": "源「%s」不在档案的 %s 列表内，请重新扫描。",
        "msg_tc_bad": "时间格式须为 HH:MM:SS:FF，如 00:00:00:00。",
        "msg_end_le": "End 必须晚于 Start。",
        "msg_out_missing": "请选择输出目录。",
        "msg_sr_bad": "采样率无效。",
        "msg_sess_missing": "已选「指定文件」，请提供 .ptx 路径。",
        "msg_warn_profile_start": "[warn] 启动时档案不可用：%s\n",
        "msg_preview_first_title": "请先预览",
        "msg_preview_first_body": "参数可能已变化，请先点「预览导出计划」确认后再执行。",
        "msg_confirm_title": "确认执行",
        "msg_confirm_body": "将按预览计划执行导出并落盘。\n确定执行吗？",
        "msg_ptsl_off_export": "执行导出需要 Pro Tools 正在运行（PTSL 在线）。",
        "msg_len_summary": "校验公式：时长×采样率×位深≈WAV 字节数",

        # —— 摘要字段 ——
        "sum_session": "工程",
        "sum_path": "路径",
        "sum_rate": "采样率 %s Hz  ·  位深 %s  ·  时码率 %s fps",
        "sum_range": "起始 %s  ·  长度 %s",
        "sum_tracks": "轨道数",
        "sum_bus": "总线",
        "sum_output": "主输出",
        "sum_phys": "物理输出",
        "sum_err": "[error] %s",

        # —— 帮助 / 关于 ——
        "help_text": (
            "pt-tools 三步工作流\n"
            "═" * 30 + "\n"
            "1. 扫描建档（页签 1）\n"
            "   启动 Pro Tools 并打开工程，确认 PTSL 在线后，点「扫描并生成档案」。\n"
            "   扫描只读、安全；成功后档案自动应用，无需再做其他操作。\n\n"
            "2. 导出（页签 2）\n"
            "   勾选导出模式（可多选）：MIX 整段并轨 / BUS 总线分轨 /\n"
            "   STEM 全部分轨 / 按轨道名称（从列表挑轨）。\n"
            "   结束时间可点「按视频填入…」自动对齐视频长度。\n"
            "   点「预览导出计划」核对，再点「执行导出」。\n\n"
            "3. 校验\n"
            "   底部公式：时长 × 采样率 × 位深 ≈ WAV 字节数。\n\n"
            "常见问题\n"
            "═" * 30 + "\n"
            "· PTSL 离线：请先启动 Pro Tools（PTSL 服务随 Pro Tools 一起启动）。\n"
            "· 导出卡住：通常是 Pro Tools 弹了模态框（如「缺少文件」），\n"
            "  人工处理后重试。\n"
            "· 技能目录不可用：设置 > 技能目录，指向 protools-skills 文件夹\n"
            "  （内含三个技能 + pt-exporter\\env\\venv）。\n"),
        "about_text": (
            "pt-tools — Pro Tools 自动化桌面工具\n"
            "版本：v%s（%s）\n" % (APP_VERSION, build_date()) +
            "定位：Pro Tools 自动化技能族的人类直用通道\n\n"
            "技术：tkinter GUI → 调用技能脚本 → PTSL（gRPC 127.0.0.1:31416）\n"
            "依赖：protools-skills 技能目录（内置 py-ptsl venv）\n"
            "配置与日志：%APPDATA%\\pt-tools\\\n"),
    },

    LANG_EN: {
        "app_title": "pt-tools v%s (%s) — Pro Tools Automation" % (APP_VERSION, build_date()),

        "menu_file": "File",
        "menu_settings": "Settings",
        "menu_tools": "Tools",
        "menu_help": "Help",

        "file_open_outdir": "Open Output Folder",
        "file_open_cfgdir": "Open Config & Log Folder",
        "file_exit": "Exit",

        "sett_lang": "Language",
        "sett_lang_zh": "中文",
        "sett_lang_en": "English",
        "sett_skills": "Skills Root…",
        "sett_outdir": "Default Output Folder…",

        "tools_open_skills": "Open Skills Root (Explorer)",
        "tools_open_outdir": "Open Output Folder",
        "tools_open_cfgdir": "Open Config & Log Folder",
        "tools_clear_log": "Clear Log",
        "tools_export_diag": "Export Diagnostic Bundle (zip: log+config+version)",
        "msg_diag_exported": "Diagnostic bundle exported: %s",
        "msg_diag_failed": "Failed to export diagnostic bundle: %s",

        # —— P1 offline banner ——
        "pt_warn_bar": ("⚠  Pro Tools not connected (PTSL 127.0.0.1:31416 unreachable) — "
                        "Scan/Export disabled. Check: is PT running? If starting, wait or see "
                        "docs/ptsl-boot-plan.md"),
        "pt_warn_bar_ok": "",

        # —— P4 PT version banner (v1.5.2 / B batch) ——
        "pt_info_bar": ("Verified: Pro Tools 25.6.1 · PTSL v6 · py-ptsl 602.0.0 · port 127.0.0.1:31416 ｜ "
                        "Other PT versions are NOT fully verified (PTSL protocol/commands vary); "
                        "changing machine/account is fine (PTSL is a local service)"),

        # —— P2 export QC ——
        "qc_running": "QC running…",
        "qc_none": "QC: no wav from this export found in the output folder.",
        "qc_ok": "QC passed: %d files; channels / sample rate / bit depth / duration all OK.",
        "qc_bad": "QC found %d issue(s) out of %d file(s):",
        "qc_note": "QC only reads headers, never touches products; this report also goes to the log file.",

        # —— P3 library tab / P4 export history ——
        "tab_library": " 3 · Library ",
        "lib_what_title": "What this tab does",
        "lib_what_body": ("Manage flat pt-profile.json files in the profile folder: search / load into "
                          "Export tab / reveal in Explorer / delete (to Recycle Bin). The \"Export "
                          "history\" below lists session folders in the output root by modified time; "
                          "double-click to open."),
        "lib_dir": "Profile folder:",
        "lib_search": "Search:",
        "lib_col_file": "Profile file",
        "lib_col_project": "Session",
        "lib_col_mtime": "Modified",
        "lib_col_size": "Size",
        "lib_refresh": "Refresh",
        "lib_load": "Load into Export tab",
        "lib_open_dir": "Reveal in Explorer",
        "lib_delete": "Delete (Recycle Bin)",
        "lib_delete_confirm": "Move %d profile(s) to the Recycle Bin?\n(recoverable)",
        "lib_deleted": "[library] %d profile(s) moved to Recycle Bin",
        "lib_delete_failed": "[library] delete failed: %s",
        "lib_empty": "(profile folder empty or missing)",
        "lib_hist_title": "Export history (output root, by modified time)",
        "lib_open_outroot": "Open output root",
        "lib_hist_empty": "(output root empty or missing)",
        "lib_bad_json": "[library] failed to read profile (skipped): %s",

        # —— W8 batch CLI ——
        "b_save_jobs": "Save job list (jobs.json)…",
        "b_jobs_saved": "Job list saved (run with pt-tools --batch overnight):\n%s",
        "b_jobs_save_failed": "Failed to save job list: %s",

        "help_howto": "How to Use",
        "help_about": "About pt-tools",

        "tab_scan": " 1 · Scan ",
        "tab_export": " 2 · Export ",
        "tab_clean": " 4 · Clean ",

        "s_what_title": "What this tab does",
        "s_what_body": ("Scans the currently open Pro Tools session and builds a "
                        "\"session profile\" (pt-profile.json): track / bus / output "
                        "lists with duration. The Export tab reads sources straight "
                        "from this profile — nothing to guess, scan once, reuse."),
        "s_req_title": "Requirements",
        "s_req_ptsl_on": "●  Pro Tools running (PTSL online)",
        "s_req_ptsl_off": "○  Pro Tools not running (PTSL offline)",
        "s_req_line2": "Open the session you want to export in Pro Tools (e.g. \"Demo24.ptx\").",
        "s_steps_title": "Steps",
        "s_step1": "1)  Start Pro Tools and open the session",
        "s_step2": "2)  Click \"Scan & Save Profile\" below (read-only, safe)",
        "s_step3": "3)  Profile is applied automatically — go to the Export tab",
        "s_out": "Output folder (profile goes here):",
        "s_name": "Profile name:",
        "s_scan_btn": "Scan & Save Profile",
        "s_summary": "Scan Summary",
        "s_browse": "Browse…",
        "s_auto_applied": "[scan] Profile applied automatically: %s\n",
        "s_missing_out": "Please choose an output folder first.",
        "s_bad_name": "Profile name must end with .json.",

        "e_profile": "Profile (pt-profile.json):",
        "e_browse": "Browse…",
        "e_mode": "Export mode (multi-select):",
        "e_mode_mix": "MIX (merged)",
        "e_mode_mix_tip": "one merged file of the main output",
        "e_mode_stem": "STEM (all tracks)",
        "e_mode_stem_tip": "one WAV per source track",
        "e_mode_stem_aux": "include aux",
        "e_mode_bus": "BUS (per bus)",
        "e_mode_bus_tip": "one WAV per bus",
        "e_mode_track": "By track name",
        "e_mode_track_tip": "pick tracks from the list below",
        "e_session": "Session:",
        "e_sess_current": "Current",
        "e_sess_file": "File…",
        "e_track_frame": "Track list — selectable when \"By track name\" is on",
        "e_type_col": "Type",
        "e_search": "Search:",
        "e_selected": "%d selected",
        "e_name_col": "Name",
        "e_params": "Parameters",
        "e_start": "Start:",
        "e_end": "End:",
        "e_fill_video": "Fill from video…",
        "e_tc_hint": "Format HH:MM:SS:FF",
        "e_sr": "Sample rate:",
        "e_bd": "Bit depth:",
        "e_fmt": "Format:",
        "e_out": "Output:",
        "e_preview": "Preview Plan",
        "e_export": "Export",
        "e_verify": "Check: duration × rate × depth ≈ WAV bytes",
        "e_video_title": "Choose the session's video file",
        "e_video_running": "[video] Reading video duration: %s\n",
        "e_video_ok": "[video] Range filled from video: start 00:00:00:00 -> end %s\n",
        "e_video_fail": "[video] Failed to read video duration: %s\n"
                        "        MP4/MOV family (mvhd box) is supported; "
                        "or type the end time manually.\n",
        "e_video_margin_note": "end = video duration + margin",

        # —— v1.2.0 track selection / video auto / batch ——
        "msg_fmt_bad": "Unrecognised export format: %s\n(pick one from the dropdown — the tool will not silently guess)",
        "e_sel_col": "Sel",
        "e_clips_col": "Clips",
        "e_clips_yes": "yes",
        "e_clips_no": "empty",
        "e_excluded_mark": " (excluded)",
        "e_select_all": "Select all",
        "e_deselect_all": "Deselect all",
        "e_exclude": "Exclude list:",
        "e_exclude_tip": "Comma-separated, * and ? wildcards supported "
                         "(e.g. BG 1, DX BUS, Master); matched tracks unchecked by default",
        "e_track_frame_v2": "Track list (checked = export; empty/excluded unchecked by default)",
        "e_video_auto": "Auto-detect video",
        "e_video_searching": "[video] Searching session tree for videos: %s\n",
        "e_video_found1": "[video] Found 1 video: %s\n",
        "e_video_found_n": "[video] Found %d videos, please pick one in the dialog\n",
        "e_video_none": "[video] No video found in session tree (use \"Fill from video…\" "
                        "manually, or export with the fallback duration)\n",
        "e_video_pick_title": "Multiple videos found — pick one for the export duration",
        "e_video_applied": "[video] Applied \"%s\": end %s (margin %ss)\n",
        "e_margin": "Video margin (s):",
        "e_fallback": "Fallback duration (s):",
        "e_by_session": "Create output subfolder per session name",
        "e_batch": "Batch export…",

        # —— v1.2.0 batch dialog ——
        "b_title": "Batch export (multiple sessions)",
        "b_ptx_frame": "Sessions (.ptx) — videos are pre-scanned on add",
        "b_add": "Add sessions…",
        "b_remove": "Remove selected",
        "b_rescan": "Re-scan videos",
        "b_col_session": "Session",
        "b_col_video": "Selected video",
        "b_col_status": "Status",
        "b_video_pick": "Pick…",
        "b_video_multi": "%d found, pick one",
        "b_video_none": "None (see policy below)",
        "b_video_ok": "%s (%.0fs)",
        "b_policy_frame": "When no video found",
        "b_policy_fallback": "Export with fallback duration",
        "b_policy_skip": "Skip and record",
        "b_multi_frame": "When multiple videos found",
        "b_multi_pick": "Let me pick",
        "b_multi_skip": "Skip and record (with video name list)",
        "b_rule_note": "Batch reuses this tab's modes / format / track rules; the exclude "
                       "list and empty-track rule apply per session; outputs go into "
                       "per-session subfolders.",
        "b_start": "Start batch export",
        "b_need_ptsl": "Batch export requires Pro Tools running (PTSL online).",
        "b_need_ptx": "Add at least one .ptx session first.",
        "b_generating": "[batch] Batch plan written: %s\n",
        "b_started": "[batch] Batch export started (%d sessions), watch the log…\n",
        "b_searching": "[batch] Scanning %s …\n",
        "b_search_fail": "[batch] Scan failed: %s\n",
        "b_pick_title": "\"%s\": %d videos found — pick one for the export duration",

        "c_warn": ("⚠ Requires Pro Tools 2025.10+ (CId 146/147). Tested on "
                   "PT 25.6.1 it raises ErrType 133 — disabled until you upgrade."),
        "c_cap": "Capability",
        "c_cap1": "✅ Reassign track main outputs (SetTrackMainOutputAssignments)",
        "c_cap2": "✅ Create signal path (CreateSignalPath)",
        "c_cap3": "❌ Delete sends / inserts / IO paths — not supported by PTSL",
        "c_params": "Parameters (skeleton, awaits PT upgrade)",
        "c_track_mode": "Track mode: by name / by prefix",
        "c_track_col": "Track list (from profile, to be enabled)",
        "c_target_out": "Target output: (dropdown, to be enabled)",
        "c_backup": "Backup/Save: (checkbox, to be enabled)",
        "c_note": "Preview / Apply enabled after PT upgrade + scan.",

        "log_frame": "Log",
        "log_clear": "Clear Log",
        "log_hint": "Long tasks run in the background. Watch the status bar.",
        "status_ptsl_on": "●  PTSL online (Pro Tools running)",
        "status_ptsl_off": "○  PTSL offline (start Pro Tools)",
        "status_session": "Session: %s",
        "status_profile": "Profile: %s",
        "status_skills_ok": "Skills OK",
        "status_skills_bad": "⚠ Skills root unavailable",
        "lang_changed": "[i18n] Language switched.\n",
        "preview_start": "[preview] Dry-run started……\n",
        "preview_pass": "[preview] Preview passed. Export is enabled until parameters change.\n",
        "cmd_done": "— Command finished, exit code %d —\n",
        "err_cmd_start": "[error] Cannot start command: %s\n",
        "err_cmd_stop": "[error] Command %d failed — remaining %d skipped.\n",
        "toast_title": "pt-tools",
        "toast_done": "Task finished (exit code %d)",
        "toast_aborted": "Task aborted",

        # v1.3.0 freeze fix (Q12): abort / watchdog / close
        "log_abort": "■ Abort",
        "abort_title": "Abort current task",
        "abort_confirm": "Abort the running command?\n"
                         "(Files already exported are kept; the rest will not be produced. "
                         "Only child processes started by this tool are killed — Pro Tools is untouched.)",
        "log_aborting": "[abort] Abort requested — terminating child process…\n",
        "cmd_aborted": "— Command aborted —\n",
        "log_stalled": "[warn] No output for %d s — the task may be stuck (Pro Tools is often "
                       "waiting on a dialog). Use Abort to stop it.\n",
        "log_running": "Running %dm%02ds",
        "log_no_output": "no output for %ds",
        "quit_title": "Quit",
        "quit_confirm": "A task is running. Quit anyway?\n"
                        "(Child processes started by this tool are terminated; Pro Tools is not affected.)",

        # v1.3.0 export format semantics (Q5) — v2.6.5 (P2): clearer wording
        "e_fmt_col": "Channels",
        "e_fmt_follow": "Follow global",
        "e_fmt_interleaved": "Interleaved · keep width (1 file per track)",
        "e_fmt_mono": "Mono files · stereo tracks get downmixed",
        "e_fmt_multimono": "Multi-mono · stereo split into L/R files",
        "e_fmt_hint": "This is not a channel count but how the bounce is laid out into files; "
                      "the real width comes from the track/output in the Pro Tools session.",

        # v1.3.0 path lock / output preview / drop empty tracks (Q3 Q6 Q7)
        "e_lock": "🔒 Lock",
        "e_locked": "🔓 Locked",
        "e_out_preview": "Preview output paths",
        "e_out_preview_title": "Where files will land (read-only)",
        "e_exclude_empty": "Drop empty tracks (no clips = not exported)",
        "e_excluded_view": "Show %d dropped ▸",
        "e_excluded_title": "Dropped tracks — restore",
        "e_restore": "Restore",
        "e_close": "Close",
        "e_restored": "[track] Restored \"%s\" (no longer dropped as empty)\n",
        "e_out_preview_none": "  (nothing will be produced — check modes and track selection)",
        "e_out_preview_total": "  %d file(s) in total",
        "e_out_preview_dropped": "  %d empty track(s) dropped (restore them via \"Show dropped\")",
        "e_video_root_note": "Search scope: .ptx folder → its parent",
        "e_video_root_empty": "[video]   %s — nothing found, trying next candidate\n",
        "e_video_root_hit": "[video] Hit search root: %s\n",
        "e_fallback_warn": "[warn] No video found — exporting with the fallback duration "
                           "of %s s. This is a GUESS: a longer session gets truncated, "
                           "a shorter one gets a silent tail. Add the video or set the "
                           "end time manually.\n",

        "skills_ok": "Skills root OK: %s",
        "err_root_missing": "Skills root does not exist: %s",
        "err_venv_missing": "venv interpreter not found: %s\n(recreate venv under pt-exporter/env and pip install py-ptsl)",
        "err_venv_missing_builtin": "Scripts are bundled; only the runtime venv is missing: %s\n"
                                    "(the venv carries py-ptsl and is too large to bundle; "
                                    "point Settings > Skills Root at a skills folder that has one, e.g. %s)",
        "err_scripts_missing": "Missing script(s): %s",
        "skills_broken_title": "Skills root unavailable",
        "skills_broken_hint": "Use Settings > Skills Root to select the protools-skills folder (needs venv + three skills).",
        "choose_skills_title": "Select protools-skills root",
        "choose_outdir_title": "Choose output folder",
        "choose_profile_title": "Choose pt-profile.json",
        "choose_ptx_title": "Choose Pro Tools session (.ptx)",
        "no_outdir": "No output folder set yet — choose one on the Export tab.",

        "msg_profile_invalid": "Invalid profile",
        "msg_missing": "Missing",
        "msg_invalid": "Invalid parameters",
        "msg_no_profile": "No profile loaded. Scan first or browse for pt-profile.json.",
        "msg_no_source": "Select at least one source.",
        "msg_no_mode": "Select at least one export mode (MIX / BUS / STEM / By track name).",
        "msg_no_track_sel": "\"By track name\" is on — pick tracks in the list below.",
        "msg_no_output_src": "MIX is on but the profile has no output paths — re-scan first.",
        "msg_no_bus_src": "BUS is on but the profile has no buses — re-scan first.",
        "msg_no_srctype": "Profile has no %s sources.",
        "msg_src_unknown": "Source \"%s\" is not in the profile's %s list. Re-scan.",
        "msg_tc_bad": "Time must be HH:MM:SS:FF, e.g. 00:00:00:00.",
        "msg_end_le": "End must be later than Start.",
        "msg_out_missing": "Choose an output folder.",
        "msg_sr_bad": "Invalid sample rate.",
        "msg_sess_missing": "\"File\" was selected — provide a .ptx path.",
        "msg_warn_profile_start": "[warn] Profile unavailable at startup: %s\n",
        "msg_preview_first_title": "Preview first",
        "msg_preview_first_body": "Parameters may have changed. Click \"Preview Plan\" to confirm, then export.",
        "msg_confirm_title": "Confirm",
        "msg_confirm_body": "Export will run and write files. Continue?",
        "msg_ptsl_off_export": "Export needs Pro Tools running (PTSL online).",
        "msg_len_summary": "Check: duration × rate × depth ≈ WAV bytes",

        "sum_session": "Session",
        "sum_path": "Path",
        "sum_rate": "Rate %s Hz  ·  Depth %s  ·  TC rate %s fps",
        "sum_range": "Start %s  ·  Length %s",
        "sum_tracks": "Tracks",
        "sum_bus": "Bus",
        "sum_output": "Output",
        "sum_phys": "PhysicalOut",
        "sum_err": "[error] %s",

        "help_text": (
            "pt-tools in three steps\n"
            "═" * 30 + "\n"
            "1. Scan (tab 1)\n"
            "   Start Pro Tools, open the session, check PTSL online, click \"Scan & Save Profile\".\n"
            "   Read-only and safe; the profile is applied automatically.\n\n"
            "2. Export (tab 2)\n"
            "   Tick export modes (multi-select): MIX merged / BUS per bus /\n"
            "   STEM all tracks / By track name (pick from the list).\n"
            "   Use \"Fill from video…\" to align the end time with the video.\n"
            "   Click \"Preview Plan\", then \"Export\".\n\n"
            "3. Verify\n"
            "   duration × rate × depth ≈ WAV bytes.\n\n"
            "FAQ\n"
            "═" * 30 + "\n"
            "· PTSL offline: start Pro Tools (its PTSL service starts with it).\n"
            "· Export hangs: Pro Tools usually has a modal dialog open (e.g. \"missing files\");\n"
            "   handle it manually and retry.\n"
            "· Skills root unavailable: Settings > Skills Root, point to protools-skills\n"
            "  (three skills + pt-exporter\\env\\venv).\n"),
        "about_text": (
            "pt-tools — Pro Tools Automation desktop tool\n"
            "Version: v%s (%s)\n" % (APP_VERSION, build_date()) +
            "Role: human-facing channel for the Pro Tools automation skill family\n\n"
            "Tech: tkinter GUI → skill scripts → PTSL (gRPC 127.0.0.1:31416)\n"
            "Depends on: protools-skills folder (bundles py-ptsl venv)\n"
            "Config & logs: %APPDATA%\\pt-tools\\\n"),
    },
}

_cur_lang = LANG_ZH


def set_lang(lang):
    global _cur_lang
    _cur_lang = lang if lang in (LANG_ZH, LANG_EN) else LANG_ZH


def T(key):
    """按当前语言取词条；缺词回退中文；再缺回 key 本身"""
    d = TEXTS.get(_cur_lang) or TEXTS[LANG_ZH]
    if key in d:
        return d[key]
    return TEXTS[LANG_ZH].get(key, key)


def detect_system_lang():
    try:
        import locale
        lc, _ = locale.getdefaultlocale()
        if lc and lc.lower().startswith("zh"):
            return LANG_ZH
    except Exception:
        pass
    return LANG_EN



def get_lang():
    """当前语言（zh / en）；供 GUI 菜单勾选态读取。"""
    return _cur_lang
