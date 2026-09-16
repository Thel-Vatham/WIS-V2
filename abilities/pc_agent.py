"""
WIS PC Agent — Specialized Desktop Control Ability.
====================================================
Full desktop control: GUI automation, process management,
screen vision, app launching, and fast offline actions.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from abilities.base import Ability

logger = logging.getLogger("wis.abilities.pc_agent")


class PCAgent(Ability):
    """Specialized PC control agent: GUI, processes, screen, apps."""

    @property
    def name(self):
        return "pc_agent"

    @property
    def description(self):
        return (
            "Specialized PC control agent. "
            "Actions: screenshot, open_app, close_app, list_processes, kill_process, "
            "click, type_text, press_key, get_clipboard, set_clipboard, "
            "get_active_window, list_windows, minimize, maximize, move_mouse."
        )

    @property
    def domain(self):
        return "pc"

    def get_schema(self):
        return [
            {"action": "screenshot", "description": "Capture the screen and save to file.", "params": {"path": "save path (optional)"}},
            {"action": "open_app", "description": "Launch an application by name or path.", "params": {"app": "App name or exe path", "args": "list of args (optional)"}},
            {"action": "close_app", "description": "Close an app by process name.", "params": {"process_name": "Process name e.g. notepad.exe"}},
            {"action": "list_processes", "description": "List running processes.", "params": {"filter": "Optional name filter"}},
            {"action": "kill_process", "description": "Kill a process by PID or name.", "params": {"pid": "int PID", "name": "process name alternative"}},
            {"action": "click", "description": "Click at screen coordinates.", "params": {"x": "int x", "y": "int y", "button": "left/right/middle"}},
            {"action": "type_text", "description": "Type text using keyboard.", "params": {"text": "text to type", "delay": "ms between keys (optional)"}},
            {"action": "press_key", "description": "Press a keyboard key or combo.", "params": {"key": "e.g. ctrl+c, enter, escape, alt+f4"}},
            {"action": "get_clipboard", "description": "Get current clipboard text.", "params": {}},
            {"action": "set_clipboard", "description": "Set clipboard text.", "params": {"text": "text to put in clipboard"}},
            {"action": "get_active_window", "description": "Get the title of the currently focused window.", "params": {}},
            {"action": "list_windows", "description": "List all open window titles.", "params": {}},
            {"action": "minimize", "description": "Minimize a window by title.", "params": {"title": "window title or partial match"}},
            {"action": "maximize", "description": "Maximize a window by title.", "params": {"title": "window title or partial match"}},
            {"action": "move_mouse", "description": "Move mouse to coordinates without clicking.", "params": {"x": "int x", "y": "int y"}},
            {"action": "run_command", "description": "Run a shell command and return stdout.", "params": {"command": "command string", "timeout": "seconds"}},
        ]

    async def execute(self, action: str, params: dict) -> dict:
        a = (action or "").lower().strip()
        try:
            if a == "screenshot":
                return await asyncio.to_thread(self._screenshot, params)
            if a == "open_app":
                return await asyncio.to_thread(self._open_app, params)
            if a == "close_app":
                return await asyncio.to_thread(self._close_app, params)
            if a == "list_processes":
                return await asyncio.to_thread(self._list_processes, params)
            if a == "kill_process":
                return await asyncio.to_thread(self._kill_process, params)
            if a == "click":
                return await asyncio.to_thread(self._click, params)
            if a == "type_text":
                return await asyncio.to_thread(self._type_text, params)
            if a == "press_key":
                return await asyncio.to_thread(self._press_key, params)
            if a == "get_clipboard":
                return await asyncio.to_thread(self._get_clipboard, params)
            if a == "set_clipboard":
                return await asyncio.to_thread(self._set_clipboard, params)
            if a == "get_active_window":
                return await asyncio.to_thread(self._get_active_window, params)
            if a == "list_windows":
                return await asyncio.to_thread(self._list_windows, params)
            if a in ("minimize", "maximize"):
                return await asyncio.to_thread(self._window_state, a, params)
            if a == "move_mouse":
                return await asyncio.to_thread(self._move_mouse, params)
            if a == "run_command":
                return await self._run_command(params)
            return {"success": False, "message": f"Unknown action: {action}"}
        except Exception as e:
            logger.error("PCAgent error in %s: %s", action, e)
            return {"success": False, "message": str(e)}

    # ── Screenshot ───────────────────────────────────────────────────────────────

    def _screenshot(self, params: dict) -> dict:
        save_path = params.get("path", "")
        try:
            import pyautogui
            img = pyautogui.screenshot()
            if save_path:
                img.save(save_path)
                return {"success": True, "message": f"Screenshot saved to {save_path}"}
            # Save to temp
            tmp = Path(os.environ.get("TEMP", "/tmp")) / "wis_screenshot.png"
            img.save(str(tmp))
            return {"success": True, "data": str(tmp), "message": f"Screenshot saved to {tmp}"}
        except ImportError:
            return {"success": False, "message": "pyautogui not installed. Run: pip install pyautogui"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ── App management ───────────────────────────────────────────────────────────

    def _open_app(self, params: dict) -> dict:
        app = params.get("app", "")
        args = params.get("args", [])
        if not app:
            return {"success": False, "message": "app required"}
        try:
            cmd = [app] + (args if isinstance(args, list) else [args])
            subprocess.Popen(cmd, shell=False)
            return {"success": True, "message": f"Launched: {app}"}
        except Exception as e:
            try:
                os.startfile(app)
                return {"success": True, "message": f"Opened: {app}"}
            except Exception as e2:
                return {"success": False, "message": str(e2)}

    def _close_app(self, params: dict) -> dict:
        name = params.get("process_name", "")
        if not name:
            return {"success": False, "message": "process_name required"}
        try:
            result = subprocess.run(["taskkill", "/f", "/im", name], capture_output=True, text=True)
            ok = result.returncode == 0
            return {"success": ok, "message": result.stdout + result.stderr}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _list_processes(self, params: dict) -> dict:
        filt = params.get("filter", "").lower()
        try:
            result = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=10)
            lines = result.stdout.strip().split("\n")
            procs = []
            for line in lines:
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2:
                    name = parts[0]
                    pid = parts[1]
                    if not filt or filt in name.lower():
                        procs.append(f"{name} (PID: {pid})")
            msg = "\n".join(procs[:50])
            return {"success": True, "data": procs, "message": msg}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _kill_process(self, params: dict) -> dict:
        pid = params.get("pid")
        name = params.get("name", "")
        try:
            if pid:
                result = subprocess.run(["taskkill", "/f", "/pid", str(pid)], capture_output=True, text=True)
            elif name:
                result = subprocess.run(["taskkill", "/f", "/im", name], capture_output=True, text=True)
            else:
                return {"success": False, "message": "pid or name required"}
            ok = result.returncode == 0
            return {"success": ok, "message": result.stdout + result.stderr}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ── Input ─────────────────────────────────────────────────────────────────────

    def _click(self, params: dict) -> dict:
        x, y = int(params.get("x", 0)), int(params.get("y", 0))
        btn = params.get("button", "left")
        try:
            import pyautogui
            pyautogui.click(x, y, button=btn)
            return {"success": True, "message": f"Clicked {btn} at ({x}, {y})"}
        except ImportError:
            return {"success": False, "message": "pyautogui not installed"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _type_text(self, params: dict) -> dict:
        text = params.get("text", "")
        delay = float(params.get("delay", 0.05))
        try:
            import pyautogui
            pyautogui.typewrite(text, interval=delay)
            return {"success": True, "message": f"Typed: {text[:50]}"}
        except ImportError:
            return {"success": False, "message": "pyautogui not installed"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _press_key(self, params: dict) -> dict:
        key = params.get("key", "")
        try:
            import pyautogui
            keys = [k.strip() for k in key.lower().split("+")]
            if len(keys) > 1:
                pyautogui.hotkey(*keys)
            else:
                pyautogui.press(keys[0])
            return {"success": True, "message": f"Pressed: {key}"}
        except ImportError:
            return {"success": False, "message": "pyautogui not installed"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _move_mouse(self, params: dict) -> dict:
        x, y = int(params.get("x", 0)), int(params.get("y", 0))
        try:
            import pyautogui
            pyautogui.moveTo(x, y, duration=0.3)
            return {"success": True, "message": f"Mouse moved to ({x}, {y})"}
        except ImportError:
            return {"success": False, "message": "pyautogui not installed"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ── Clipboard ─────────────────────────────────────────────────────────────────

    def _get_clipboard(self, params: dict) -> dict:
        try:
            import pyperclip
            text = pyperclip.paste()
            return {"success": True, "data": text, "message": text}
        except ImportError:
            pass
        try:
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5
            )
            return {"success": True, "data": result.stdout.strip(), "message": result.stdout.strip()}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _set_clipboard(self, params: dict) -> dict:
        text = params.get("text", "")
        try:
            import pyperclip
            pyperclip.copy(text)
            return {"success": True, "message": "Clipboard set"}
        except ImportError:
            pass
        try:
            subprocess.run(
                ["powershell", "-Command", f"Set-Clipboard '{text}'"],
                capture_output=True, timeout=5
            )
            return {"success": True, "message": "Clipboard set"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ── Windows ───────────────────────────────────────────────────────────────────

    def _get_active_window(self, params: dict) -> dict:
        try:
            import pygetwindow as gw
            w = gw.getActiveWindow()
            title = w.title if w else "None"
            return {"success": True, "data": title, "message": title}
        except ImportError:
            try:
                result = subprocess.run(
                    ["powershell", "-Command", "(Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | Sort-Object CPU -Descending | Select-Object -First 1).MainWindowTitle"],
                    capture_output=True, text=True, timeout=5
                )
                return {"success": True, "data": result.stdout.strip(), "message": result.stdout.strip()}
            except Exception as e:
                return {"success": False, "message": str(e)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _list_windows(self, params: dict) -> dict:
        try:
            import pygetwindow as gw
            titles = [w.title for w in gw.getAllWindows() if w.title]
            msg = "\n".join(titles)
            return {"success": True, "data": titles, "message": msg}
        except ImportError:
            try:
                result = subprocess.run(
                    ["powershell", "-Command", "Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | Select-Object -ExpandProperty MainWindowTitle"],
                    capture_output=True, text=True, timeout=5
                )
                titles = [t for t in result.stdout.strip().split("\n") if t.strip()]
                return {"success": True, "data": titles, "message": "\n".join(titles)}
            except Exception as e:
                return {"success": False, "message": str(e)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _window_state(self, state: str, params: dict) -> dict:
        title = params.get("title", "")
        try:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(title)
            if not wins:
                return {"success": False, "message": f"No window found with title: {title}"}
            w = wins[0]
            if state == "minimize":
                w.minimize()
            else:
                w.maximize()
            return {"success": True, "message": f"Window '{w.title}' {state}d"}
        except ImportError:
            return {"success": False, "message": "pygetwindow not installed. Run: pip install pygetwindow"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ── Shell ─────────────────────────────────────────────────────────────────────

    async def _run_command(self, params: dict) -> dict:
        command = params.get("command", "")
        timeout = int(params.get("timeout", 60))
        if not command:
            return {"success": False, "message": "command required"}
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            ok = proc.returncode == 0
            return {"success": ok, "data": {"stdout": out, "stderr": err}, "message": out + err}
        except asyncio.TimeoutError:
            return {"success": False, "message": f"Command timed out after {timeout}s"}
