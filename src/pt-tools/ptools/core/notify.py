# -*- coding: utf-8 -*-
"""Windows 托盘气泡通知（W1 三层拆分 · core/notify）。

ctypes 直调 Shell_NotifyIcon，零第三方依赖；任何失败都静默，
通知绝不影响主流程。调用方传 root 用于延迟删除托盘图标。
"""
import os

# ---------------------------------------------------------------------------
# Windows 托盘气泡通知（W7 · ctypes 直调 Shell_NotifyIcon，零第三方依赖）
# ---------------------------------------------------------------------------

def toast(root, title, message, timeout_ms=6000):
    """任务完成弹 Windows 通知（托盘气泡）。任何失败都静默吞掉，
    通知绝不影响主流程。非 Windows / 无 root 直接返回。
    """
    if os.name != "nt" or root is None:
        return
    try:
        import ctypes
        from ctypes import wintypes

        NIM_ADD = 0x00000000
        NIM_DELETE = 0x00000002
        NIF_ICON = 0x00000002
        NIF_INFO = 0x00000010
        NIIF_INFO = 0x00000001
        IDI_INFORMATION = 32516

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON),
            ]

        user32 = ctypes.windll.user32
        user32.Shell_NotifyIconW.argtypes = [
            wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        user32.Shell_NotifyIconW.restype = wintypes.BOOL
        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        user32.LoadIconW.restype = wintypes.HICON

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = int(root.winfo_id())
        nid.uID = 1
        nid.uFlags = NIF_INFO | NIF_ICON
        nid.hIcon = user32.LoadIconW(None, IDI_INFORMATION)
        nid.dwInfoFlags = NIIF_INFO
        nid.szInfoTitle = (title or "")[:63]
        nid.szInfo = (message or "")[:255]
        user32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        try:
            root.after(timeout_ms + 1000,
                       lambda: user32.Shell_NotifyIconW(NIM_DELETE,
                                                        ctypes.byref(nid)))
        except Exception:
            pass
    except Exception:
        pass
