"""Native OS Window Inspection and Manipulation (Win32 API via ctypes) for AVRORA.

Features:
- DWM Cloaked window filtering (DwmGetWindowAttribute) to ignore hidden/suspended UWP apps.
- Per-Monitor DPI-Awareness v2 for pixel-accurate geometry on 4K and scaled multi-monitor displays.
- Window management: focus, minimize, maximize, restore, snap/dock (left/right half), and graceful close via WM_CLOSE.
- Native keyboard input simulation (type_text, press_key, hotkey) via user32.
"""
from __future__ import annotations

import ctypes
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)



class WindowOps:
    """Safe, native OS window inspection."""

    def __init__(self) -> None:
        self._is_windows = os.name == "nt"
        if self._is_windows:
            try:
                # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
                ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            except Exception as _exc:
                logger.debug("Operacion no fatal suprimida: %s", _exc)

    def get_monitors(self) -> list[dict[str, Any]]:
        """Enumerate all connected display monitors and their pixel coordinates."""
        if not self._is_windows:
            return []
        monitors: list[dict[str, Any]] = []

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        def _cb(hMonitor: Any, hdcMonitor: Any, lprcMonitor: Any, dwData: Any) -> bool:
            r = lprcMonitor.contents
            w = r.right - r.left
            h = r.bottom - r.top
            monitors.append({
                "monitor": len(monitors) + 1,
                "left": r.left,
                "top": r.top,
                "right": r.right,
                "bottom": r.bottom,
                "width": w,
                "height": h,
                "primary": (r.left == 0 and r.top == 0),
            })
            return True

        user32 = ctypes.windll.user32
        MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_long)
        user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_cb), 0)
        return monitors

    def _is_cloaked(self, hwnd: int) -> bool:
        """Check if window is cloaked (hidden/suspended UWP app) via DWM API."""
        if not self._is_windows:
            return False
        try:
            cloaked = ctypes.c_int(0)
            dwm = getattr(ctypes.windll, "dwmapi", None)
            if dwm and hasattr(dwm, "DwmGetWindowAttribute"):
                # DWMWA_CLOAKED = 14
                res = dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
                return res == 0 and cloaked.value != 0
        except Exception as _exc:
            logger.debug("Operacion no fatal suprimida: %s", _exc)
        return False

    def list_windows(self) -> list[dict[str, Any]]:
        """List visible top-level windows with their titles, process IDs, and monitor locations."""
        if not self._is_windows:
            return [{"title": "Window inspection is only supported on Windows OS", "pid": 0}]

        windows: list[dict[str, Any]] = []
        user32 = ctypes.windll.user32
        monitors = self.get_monitors()

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        def enum_windows_callback(hwnd: int, lparam: int) -> bool:
            if user32.IsWindowVisible(hwnd) and not self._is_cloaked(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.strip()

                    pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

                    # Filter out tiny system popups or empty titles
                    if title and title not in ("Default IME", "MSCTFIME UI", "Program Manager", "Windows Input Experience"):
                        r = RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(r))
                        w_width = r.right - r.left
                        w_height = r.bottom - r.top

                        mon_idx = 1
                        if monitors:
                            cx = (r.left + r.right) // 2
                            cy = (r.top + r.bottom) // 2
                            for idx, m in enumerate(monitors, 1):
                                if m["left"] <= cx < m["right"] and m["top"] <= cy < m["bottom"]:
                                    mon_idx = idx
                                    break

                        windows.append({
                            "hwnd": hwnd,
                            "title": title,
                            "pid": pid.value,
                            "monitor": mon_idx,
                            "width": w_width,
                            "height": w_height,
                        })
            return True

        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(enum_windows_callback)
        user32.EnumWindows(enum_proc, 0)

        # Sort by monitor, then by title
        windows.sort(key=lambda w: (w.get("monitor", 1), w["title"].lower()))
        return windows

    def get_active_window(self) -> dict[str, Any]:
        """Return title, handle, PID, and monitor of the currently active foreground window."""
        if not self._is_windows:
            return {"title": "Window inspection is only supported on Windows OS", "pid": 0}

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"title": "(no active window)", "pid": 0, "monitor": 1}

        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value.strip()

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        monitors = self.get_monitors()
        mon_idx = 1
        if monitors:
            cx = (r.left + r.right) // 2
            cy = (r.top + r.bottom) // 2
            for idx, m in enumerate(monitors, 1):
                if m["left"] <= cx < m["right"] and m["top"] <= cy < m["bottom"]:
                    mon_idx = idx
                    break

        return {
            "hwnd": hwnd,
            "title": title or "(untitled window)",
            "pid": pid.value,
            "monitor": mon_idx,
            "width": r.right - r.left,
            "height": r.bottom - r.top,
        }

    def find_window(self, target: str | int) -> dict[str, Any] | None:
        """Find an open window by HWND, PID, title substring, or multi-keyword matching."""
        if not self._is_windows:
            return None

        wins = self.list_windows()
        if not wins:
            return None

        if isinstance(target, int):
            for w in wins:
                if w.get("hwnd") == target:
                    return w
            return None

        search_str = str(target).strip()
        if not search_str:
            return None

        # Check if target is a digit (could be PID or HWND)
        if search_str.isdigit():
            val = int(search_str)
            for w in wins:
                if w.get("hwnd") == val or w.get("pid") == val:
                    return w

        low_search = search_str.lower()

        # 1. Exact substring match
        for w in wins:
            if low_search in str(w.get("title", "")).lower():
                return w

        # 2. Multi-keyword match with noise word stripping
        import re
        stop_words = {
            "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas",
            "con", "en", "por", "para", "sobre", "que", "tiene", "proyecto",
            "ventana", "app", "aplicacion", "aplicación", "pestana", "pestaña",
            "the", "a", "an", "of", "with", "in", "on", "window", "project",
        }
        raw_words = re.findall(r"[\w\-]+", search_str.lower())
        keywords = [w for w in raw_words if w not in stop_words and len(w) > 1]

        if keywords:
            # Check for windows matching ALL keywords
            matched_all = []
            for w in wins:
                t_low = str(w.get("title", "")).lower()
                if all(kw in t_low for kw in keywords):
                    matched_all.append(w)
            if matched_all:
                return matched_all[0]

            # Check for best partial match
            scored = []
            for w in wins:
                t_low = str(w.get("title", "")).lower()
                score = sum(1 for kw in keywords if kw in t_low)
                if score > 0:
                    scored.append((score, w))
            if scored:
                scored.sort(key=lambda item: item[0], reverse=True)
                return scored[0][1]

        return None

    def minimize_window(self, hwnd: int) -> dict[str, Any]:
        """Minimize a window by HWND."""
        if not self._is_windows:
            return {"success": False, "error": "Only supported on Windows OS"}
        SW_MINIMIZE = 6
        ok = bool(ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE))
        return {"success": ok, "hwnd": hwnd, "action": "minimized"}

    def snap_window(self, hwnd: int, position: str = "maximize") -> dict[str, Any]:
        """Snap or dock window to left half, right half, maximize, minimize, or restore."""
        if not self._is_windows:
            return {"success": False, "error": "Only supported on Windows OS"}

        user32 = ctypes.windll.user32
        pos = position.lower().strip()

        if pos in ("maximize", "max"):
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            return {"success": True, "hwnd": hwnd, "action": "maximize"}
        if pos in ("minimize", "min"):
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            return {"success": True, "hwnd": hwnd, "action": "minimize"}
        if pos in ("restore", "normal"):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            return {"success": True, "hwnd": hwnd, "action": "restore"}

        # Find monitor where window currently resides
        monitors = self.get_monitors()
        primary_mon = next((m for m in monitors if m.get("primary")), monitors[0] if monitors else None)
        if not primary_mon:
            return {"success": False, "error": "No monitor detected"}

        m_left = primary_mon["left"]
        m_top = primary_mon["top"]
        m_width = primary_mon["width"]
        m_height = primary_mon["height"]

        # Restore from maximized first so MoveWindow takes effect
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE

        if pos in ("left", "left_half", "izquierda"):
            user32.MoveWindow(hwnd, m_left, m_top, m_width // 2, m_height, True)
            return {"success": True, "hwnd": hwnd, "action": "snapped_left"}
        if pos in ("right", "right_half", "derecha"):
            user32.MoveWindow(hwnd, m_left + (m_width // 2), m_top, m_width // 2, m_height, True)
            return {"success": True, "hwnd": hwnd, "action": "snapped_right"}

        return {"success": False, "error": f"Unknown snap position '{position}'"}

    def focus_window(self, target: str | int) -> str:
        """Bring a target window to foreground by title substring, PID, or HWND."""
        if not self._is_windows:
            return "[window] window focus is only supported on Windows OS"

        user32 = ctypes.windll.user32
        target_win = self.find_window(target)

        if not target_win:
            return f"[window] window matching «{target}» not found"

        target_hwnd = target_win["hwnd"]
        target_title = target_win.get("title", f"HWND {target_hwnd}")

        user32.ShowWindow(target_hwnd, 9)  # SW_RESTORE = 9
        res = user32.SetForegroundWindow(target_hwnd)
        return f"[window] focused window «{target_title}»" if res else f"[window] brought «{target_title}» to front"

    def close_window(self, target: str | int) -> dict[str, Any]:
        """Gracefully close a specific target window by sending WM_CLOSE to its HWND without killing other windows/processes."""
        if not self._is_windows:
            return {"success": False, "message": "[window] window operations are only supported on Windows OS"}

        target_win = self.find_window(target)
        if not target_win:
            return {"success": False, "message": f"[window] window matching «{target}» not found"}

        hwnd = target_win["hwnd"]
        title = target_win.get("title", f"HWND {hwnd}")

        # Send WM_CLOSE (0x0010) directly to the specific HWND
        user32 = ctypes.windll.user32
        WM_CLOSE = 0x0010
        res = user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        if res != 0:
            return {
                "success": True,
                "hwnd": hwnd,
                "title": title,
                "pid": target_win.get("pid"),
                "message": f"[window] closed window «{title}» (HWND: {hwnd})",
            }
        return {
            "success": False,
            "hwnd": hwnd,
            "title": title,
            "message": f"[window] failed to send WM_CLOSE to «{title}»",
        }

    def close_tab(self, target: str | int | None = None) -> dict[str, Any]:
        """Close ONLY the active browser tab (Ctrl+W) without closing the entire browser window/process."""
        if not self._is_windows:
            return {"success": False, "message": "[window] window operations are only supported on Windows OS"}

        target_win = self.find_window(target) if target else self.get_active_window()
        if not target_win or not target_win.get("hwnd"):
            return {"success": False, "message": f"[window] no matching window found for «{target}»"}

        hwnd = target_win["hwnd"]
        title = target_win.get("title", f"HWND {hwnd}")

        user32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32

        # Bring window to front
        try:
            fg = user32.GetForegroundWindow()
            if fg != hwnd:
                fg_tid = user32.GetWindowThreadProcessId(fg, None)
                cur_tid = k32.GetCurrentThreadId()
                user32.AttachThreadInput(cur_tid, fg_tid, True)
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
                user32.AttachThreadInput(cur_tid, fg_tid, False)
            else:
                user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
        except Exception as _exc:
            logger.debug("Operacion no fatal suprimida: %s", _exc)

        import time
        time.sleep(0.15)

        # Send Ctrl+W with discrete keydown/keyup delays so Chromium/CEF/Gecko processes the frame
        VK_CONTROL = 0x11
        VK_W = 0x57
        KEYEVENTF_KEYUP = 0x0002

        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_W, 0, 0, 0)
        time.sleep(0.06)
        user32.keybd_event(VK_W, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

        return {
            "success": True,
            "hwnd": hwnd,
            "title": title,
            "action": "closed_tab",
            "message": f"[window] cerrada la pestaña activa de «{title}» mediante Ctrl+W.",
        }

    def click_at(self, x: int, y: int, button: str = "left", double: bool = False) -> str:
        """Send native Win32 mouse click at absolute screen coordinates (x, y)."""
        if not self._is_windows:
            return "[window] mouse click is only supported on Windows OS"

        user32 = ctypes.windll.user32
        user32.SetCursorPos(x, y)

        btn = button.lower().strip()
        if btn == "right":
            down_flag, up_flag = 0x0008, 0x0010  # MOUSEEVENTF_RIGHTDOWN / RIGHTUP
        else:
            down_flag, up_flag = 0x0002, 0x0004  # MOUSEEVENTF_LEFTDOWN / LEFTUP

        user32.mouse_event(down_flag, 0, 0, 0, 0)
        user32.mouse_event(up_flag, 0, 0, 0, 0)

        if double:
            import time
            time.sleep(0.05)
            user32.mouse_event(down_flag, 0, 0, 0, 0)
            user32.mouse_event(up_flag, 0, 0, 0, 0)

        mode = "double-clicked" if double else "clicked"
        return f"[window] {mode} {btn} button at ({x}, {y})"

    def type_text(self, text: str) -> str:
        """Send native Unicode keystrokes to the focused window."""
        if not self._is_windows:
            return "[window] keyboard typing is only supported on Windows OS"
        if not text:
            return "[window] empty text"

        user32 = ctypes.windll.user32

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]

        KEYEVENTF_KEYUP = 0x0002
        KEYEVENTF_UNICODE = 0x0004
        INPUT_KEYBOARD = 1

        for char in text:
            code = ord(char)
            # Key down
            inp_down = INPUT(type=INPUT_KEYBOARD)
            inp_down.union.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=None)
            user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))

            # Key up
            inp_up = INPUT(type=INPUT_KEYBOARD)
            inp_up.union.ki = KEYBDINPUT(
                wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=None
            )
            user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))

        return f"[window] typed {len(text)} character(s)"

    def press_key(self, key: str) -> str:
        """Send native keypress for special keys or combinations (e.g. 'enter', 'ctrl+w', 'alt+f4')."""
        if not self._is_windows:
            return "[window] keypress is only supported on Windows OS"

        clean = key.lower().strip()
        if "+" in clean:
            parts = [p.strip() for p in clean.split("+") if p.strip()]
            return self.hotkey(*parts)

        key_map = {
            "enter": 0x0D,
            "return": 0x0D,
            "tab": 0x09,
            "escape": 0x1B,
            "esc": 0x1B,
            "backspace": 0x08,
            "space": 0x20,
            "up": 0x26,
            "down": 0x28,
            "left": 0x25,
            "right": 0x27,
            "delete": 0x2E,
        }
        vk = key_map.get(clean)
        if vk is None:
            if len(clean) == 1:
                vk = ord(clean.upper())
            else:
                return f"[window] unsupported key «{key}» (supported: {', '.join(sorted(key_map.keys()))})"

        user32 = ctypes.windll.user32
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return f"[window] pressed key '{key}'"

    def hotkey(self, *keys: str) -> str:
        """Send a native key combination (e.g. hotkey('ctrl', 'l'))."""
        if not self._is_windows:
            return "[window] hotkey is only supported on Windows OS"
        key_map = {
            "ctrl": 0x11,
            "control": 0x11,
            "shift": 0x10,
            "alt": 0x12,
            "win": 0x5B,
            "enter": 0x0D,
            "tab": 0x09,
            "esc": 0x1B,
            "escape": 0x1B,
            "space": 0x20,
            "l": 0x4C,
            "v": 0x56,
            "c": 0x43,
            "a": 0x41,
            "t": 0x54,
            "w": 0x57,
        }
        vks = []
        for k in keys:
            vk = key_map.get(k.lower().strip())
            if vk is None and len(k) == 1:
                vk = ord(k.upper())
            if vk is not None:
                vks.append(vk)

        user32 = ctypes.windll.user32
        KEYEVENTF_KEYUP = 0x0002
        for vk in vks:
            user32.keybd_event(vk, 0, 0, 0)
        for vk in reversed(vks):
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return f"[window] sent hotkey {'+'.join(keys)}"

