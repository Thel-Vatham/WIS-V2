"""AVRORA — Advanced GUI Interaction Driver.

Provides 3 native interaction channels for controlling complex desktop applications:
1. UIAutomation (UIA): Native control inspection (buttons, inputs, menus) without pixel guesswork.
2. Keystroke & Hotkey Injector: High-speed native keystroke sequences and modifier keys.
3. Domain Scripting Backdoors: AutoCAD (.scr / .lsp), Photoshop (.jsx ExtendScript), LTspice (.asc / .net batch).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)



class GUIDriver:
    """Advanced GUI and application control driver."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()

    # ------------------------------------------------------------------
    # Channel 1: Keystrokes & Hotkey Sequences
    # ------------------------------------------------------------------
    def send_keys(self, keys: str, window_title: str = "", delay: float = 0.05) -> dict[str, Any]:
        """Send keystrokes or shortcut sequences (e.g. 'ctrl+s', 'alt+f4', 'f2', 'text')."""
        try:
            # If target window is specified, bring it to focus first
            if window_title:
                self.focus_window_by_title(window_title)
                time.sleep(0.15)

            if delay > 0:
                time.sleep(delay)

            # 1. High-speed native Win32 SendInput / keybd_event (<0.01ms)
            if os.name == "nt":
                try:
                    from .window_tools import WindowOps
                    wops = WindowOps()
                    win_res = wops.press_key(keys)
                    if "unsupported" not in win_res.lower() and "only supported" not in win_res.lower():
                        return {"status": "ok", "keys": keys, "target_window": window_title or "active", "method": "win32_native"}
                except Exception as _exc:
                    logger.debug("Operacion no fatal suprimida: %s", _exc)

            # 2. Universal PowerShell SendKeys fallback
            ps_keys = self._convert_to_sendkeys(keys)
            ps_script = f"""
            Add-Type -AssemblyName System.Windows.Forms
            Start-Sleep -Milliseconds {int(delay * 1000)}
            [System.Windows.Forms.SendKeys]::SendWait('{ps_keys}')
            """
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode != 0:
                return {"status": "error", "message": res.stderr.strip() or "SendKeys failed"}
            return {"status": "ok", "keys": keys, "target_window": window_title or "active", "method": "powershell_sendkeys"}
        except Exception as exc:
            return {"status": "error", "message": f"send_keys failed: {exc}"}

    def send_scancode_key(self, key: str, duration: float = 0.05) -> dict[str, Any]:
        """Send DirectInput hardware scancode keypress for 3D/CAD/Game viewports."""
        if os.name != "nt":
            return {"status": "error", "message": "Only supported on Windows"}
        try:
            import ctypes
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

            clean = key.strip().upper()
            vk = ord(clean[0]) if len(clean) == 1 else 0
            vk_map = {
                "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
                "SPACE": 0x20, "ENTER": 0x0D, "TAB": 0x09, "ESC": 0x1B,
                "SHIFT": 0x10, "CTRL": 0x11, "ALT": 0x12,
            }
            if clean in vk_map:
                vk = vk_map[clean]

            vsc = user32.MapVirtualKeyW(vk, 0)
            if not vsc:
                return {"status": "error", "message": f"Could not map scancode for '{key}'"}

            KEYEVENTF_SCANCODE = 0x0008
            KEYEVENTF_KEYUP = 0x0002

            # Key Down
            inp_down = INPUT(type=1)
            inp_down.union.ki = KEYBDINPUT(wVk=0, wScan=vsc, dwFlags=KEYEVENTF_SCANCODE, time=0, dwExtraInfo=None)
            user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))

            if duration > 0:
                time.sleep(duration)

            # Key Up
            inp_up = INPUT(type=1)
            inp_up.union.ki = KEYBDINPUT(wVk=0, wScan=vsc, dwFlags=KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
            user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))

            return {"status": "ok", "key": key, "scancode": hex(vsc), "method": "directinput_scancode"}
        except Exception as exc:
            return {"status": "error", "message": f"Scancode send failed: {exc}"}

    def _convert_to_sendkeys(self, shortcut: str) -> str:
        """Convert standard shortcut syntax (e.g. 'ctrl+s', 'alt+f4', 'enter') to Windows Forms SendKeys format."""
        s = shortcut.strip().lower()
        parts = [p.strip() for p in s.split("+")]

        key_map = {
            "enter": "{ENTER}",
            "tab": "{TAB}",
            "esc": "{ESC}",
            "escape": "{ESC}",
            "backspace": "{BACKSPACE}",
            "delete": "{DELETE}",
            "del": "{DELETE}",
            "up": "{UP}",
            "down": "{DOWN}",
            "left": "{LEFT}",
            "right": "{RIGHT}",
            "home": "{HOME}",
            "end": "{END}",
            "space": " ",
            "f1": "{F1}",
            "f2": "{F2}",
            "f3": "{F3}",
            "f4": "{F4}",
            "f5": "{F5}",
            "f6": "{F6}",
            "f7": "{F7}",
            "f8": "{F8}",
            "f9": "{F9}",
            "f10": "{F10}",
            "f11": "{F11}",
            "f12": "{F12}",
        }

        modifiers = ""
        main_key = ""

        for p in parts:
            if p in ("ctrl", "control"):
                modifiers += "^"
            elif p == "alt":
                modifiers += "%"
            elif p == "shift":
                modifiers += "+"
            else:
                main_key = key_map.get(p, p)

        result = f"{modifiers}{main_key}" if modifiers or main_key else shortcut
        return result.replace("'", "''")

    def focus_window_by_title(self, title_query: str) -> bool:
        """Find and focus a window matching title_query via PowerShell Win32 API."""
        if sys.platform != "win32":
            return False
        safe_title = title_query.replace("'", "''").replace("`", "``")
        ps_code = f"""
        Add-Type @"
        using System;
        using System.Runtime.InteropServices;
        public class Win32 {{
            [DllImport("user32.dll")]
            public static extern bool SetForegroundWindow(IntPtr hWnd);
            [DllImport("user32.dll")]
            public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
        }}
"@
        $proc = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*{safe_title}*' }} | Select-Object -First 1
        if ($proc -and $proc.MainWindowHandle -ne 0) {{
            [Win32]::ShowWindow($proc.MainWindowHandle, 9) # RESTORE
            [Win32]::SetForegroundWindow($proc.MainWindowHandle)
            exit 0
        }}
        exit 1
        """
        try:
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_code], capture_output=True, timeout=3)
            return res.returncode == 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Channel 2: UIAutomation (UIA) Control Tree Inspection
    # ------------------------------------------------------------------
    def inspect_controls(self, window_title: str = "", max_controls: int = 40) -> dict[str, Any]:
        """Inspect native UI elements (buttons, inputs, menus, checkboxes) in a window."""
        if sys.platform != "win32":
            return {"status": "error", "message": "UIAutomation is only available on Windows"}

        ps_script = f"""
        Add-Type -AssemblyName UIAutomationClient
        Add-Type -AssemblyName UIAutomationTypes

        $root = [System.Windows.Automation.AutomationElement]::RootElement
        $cond = [System.Windows.Automation.Condition]::TrueCondition

        if ('{window_title}') {{
            $nameCond = New-Object System.Windows.Automation.PropertyCondition(
                [System.Windows.Automation.AutomationElement]::NameProperty,
                '{window_title}'
            )
            # Partial search fallback
            $allWins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
            $targetWin = $null
            foreach ($w in $allWins) {{
                if ($w.Current.Name -like '*{window_title}*') {{
                    $targetWin = $w
                    break
                }}
            }}
            if ($targetWin) {{ $root = $targetWin }}
        }}

        $elements = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
        $out = @()
        $count = 0

        foreach ($el in $elements) {{
            if ($count -ge {max_controls}) {{ break }}
            $name = $el.Current.Name
            $type = $el.Current.ControlType.ProgrammaticName.Replace('ControlType.', '')
            $id = $el.Current.AutomationId
            $rect = $el.Current.BoundingRectangle

            if ($name -or $id) {{
                $out += [PSCustomObject]@{{
                    name = $name
                    control_type = $type
                    automation_id = $id
                    is_enabled = $el.Current.IsEnabled
                    bounds = "$($rect.X),$($rect.Y),$($rect.Width),$($rect.Height)"
                }}
                $count++
            }}
        }}

        $out | ConvertTo-Json -Compress
        """
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if res.returncode != 0 or not res.stdout.strip():
                return {"status": "ok", "controls": [], "count": 0, "window": window_title}

            import json
            raw = res.stdout.strip()
            data = json.loads(raw) if raw.startswith("[") or raw.startswith("{") else []
            if isinstance(data, dict):
                data = [data]
            return {"status": "ok", "controls": data, "count": len(data), "window": window_title}
        except Exception as exc:
            return {"status": "error", "message": f"inspect_controls failed: {exc}"}

    def click_control(self, window_title: str, control_name: str = "", control_type: str = "Button") -> dict[str, Any]:
        """Find a control by name/type and invoke its default click pattern or click its center."""
        if sys.platform != "win32":
            return {"status": "error", "message": "UIAutomation is only available on Windows"}

        ps_script = f"""
        Add-Type -AssemblyName UIAutomationClient
        Add-Type -AssemblyName UIAutomationTypes
        Add-Type -AssemblyName System.Windows.Forms

        $root = [System.Windows.Automation.AutomationElement]::RootElement
        $cond = [System.Windows.Automation.Condition]::TrueCondition

        $allWins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
        $targetWin = $null
        foreach ($w in $allWins) {{
            if ($w.Current.Name -like '*{window_title}*') {{
                $targetWin = $w
                break
            }}
        }}

        if (-not $targetWin) {{
            Write-Error "Window not found matching '{window_title}'"
            exit 1
        }}

        $nameCond = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty,
            '{control_name}'
        )
        $ctrl = $targetWin.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $nameCond)

        if (-not $ctrl) {{
            # Partial search fallback
            $elements = $targetWin.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
            foreach ($el in $elements) {{
                if ($el.Current.Name -like '*{control_name}*') {{
                    $ctrl = $el
                    break
                }}
            }}
        }}

        if (-not $ctrl) {{
            Write-Error "Control '{control_name}' not found in window"
            exit 2
        }}

        # Try InvokePattern first
        try {{
            $invPattern = $ctrl.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
            $invPattern.Invoke()
            Write-Output "invoked"
            exit 0
        }} catch {{
            # Fallback: Click center of bounding rectangle
            $rect = $ctrl.Current.BoundingRectangle
            $cx = [int]($rect.X + ($rect.Width / 2))
            $cy = [int]($rect.Y + ($rect.Height / 2))
            [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($cx, $cy)

            Add-Type @"
            using System;
            using System.Runtime.InteropServices;
            public class Mouse {{
                [DllImport("user32.dll")]
                public static extern void mouse_event(int dwFlags, int dx, int dy, int cButtons, int dwExtraInfo);
            }}
"@
            [Mouse]::mouse_event(0x02, 0, 0, 0, 0) # MOUSEEVENTF_LEFTDOWN
            Start-Sleep -Milliseconds 50
            [Mouse]::mouse_event(0x04, 0, 0, 0, 0) # MOUSEEVENTF_LEFTUP
            Write-Output "clicked"
            exit 0
        }}
        """
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if res.returncode != 0:
                return {"status": "error", "message": res.stderr.strip() or "Control click failed"}
            return {"status": "ok", "control": control_name, "window": window_title, "action": res.stdout.strip()}
        except Exception as exc:
            return {"status": "error", "message": f"click_control failed: {exc}"}

    # ------------------------------------------------------------------
    # Channel 3: Domain Scripting Backdoors (AutoCAD, Photoshop, LTspice)
    # ------------------------------------------------------------------
    def execute_script(
        self,
        app_name: str,
        script_content: str,
        script_type: str = "autodetect",
    ) -> dict[str, Any]:
        """Execute specialized scripts inside complex desktop applications."""
        app_low = app_name.lower().strip()

        # 1. AutoCAD Scripting (.scr / .lsp)
        if "autocad" in app_low or script_type in ("scr", "lsp", "lisp"):
            return self._execute_autocad_script(script_content, script_type)

        # 2. Adobe Photoshop / Illustrator ExtendScript (.jsx)
        if "photoshop" in app_low or "illustrator" in app_low or script_type in ("jsx", "extendscript"):
            return self._execute_photoshop_jsx(script_content)

        # 3. LTspice SPICE Netlist / Batch Simulation (.asc / .net)
        if "ltspice" in app_low or "spice" in app_low or script_type in ("spice", "netlist"):
            return self._execute_ltspice_simulation(script_content)

        # 4. Universal PowerShell Scripting fallback
        return self._execute_powershell_script(script_content)

    def _execute_autocad_script(self, script_content: str, script_type: str) -> dict[str, Any]:
        """Save and execute AutoCAD command script (.scr) or AutoLISP (.lsp)."""
        suffix = ".lsp" if script_type in ("lsp", "lisp") else ".scr"
        with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as f:
            f.write(script_content)
            temp_path = f.name

        return {
            "status": "ok",
            "engine": "AutoCAD",
            "script_type": suffix[1:],
            "script_file": temp_path,
            "instruction": f"Script saved to {temp_path}. In AutoCAD, type SCRIPT or APPLOAD and select this file, or pass via CLI.",
        }

    def _execute_photoshop_jsx(self, jsx_content: str) -> dict[str, Any]:
        """Execute ExtendScript inside Adobe Photoshop via COM or file dispatch."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsx", delete=False, encoding="utf-8") as f:
            f.write(jsx_content)
            temp_path = f.name

        # Attempt to run via PowerShell / COM if Photoshop is installed
        ps_code = f"""
        try {{
            $ps = New-Object -ComObject "Photoshop.Application"
            $ps.DoJavaScriptFile('{temp_path.replace(chr(92), "/")}')
            Write-Output "executed"
            exit 0
        }} catch {{
            Write-Error $_.Exception.Message
            exit 1
        }}
        """
        try:
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_code], capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                return {"status": "ok", "engine": "Photoshop", "action": "executed_via_com", "script_file": temp_path}
            return {
                "status": "ok",
                "engine": "Photoshop",
                "action": "saved_file",
                "script_file": temp_path,
                "note": "Photoshop COM not currently attached. Script saved ready for File -> Scripts -> Browse.",
            }
        except Exception as e:
            return {"status": "error", "message": f"JSX dispatch error: {e}"}

    def _execute_ltspice_simulation(self, netlist_or_directive: str) -> dict[str, Any]:
        """Save SPICE netlist and run batch simulation if LTspice CLI is available."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".net", delete=False, encoding="utf-8") as f:
            f.write(netlist_or_directive)
            temp_path = f.name

        # Search for LTspice executable in standard paths
        ltspice_paths = [
            r"C:\Program Files\ADI\LTspice\LTspice.exe",
            r"C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe",
            r"C:\Program Files (x86)\LTC\LTspiceIV\scad3.exe",
        ]
        found_exe = None
        for p in ltspice_paths:
            if os.path.exists(p):
                found_exe = p
                break

        if found_exe:
            try:
                cmd = [found_exe, "-b", temp_path]
                subprocess.run(cmd, capture_output=True, timeout=15)
                raw_file = temp_path.replace(".net", ".raw")
                return {
                    "status": "ok",
                    "engine": "LTspice",
                    "action": "batch_simulation_completed",
                    "netlist_file": temp_path,
                    "raw_output": raw_file if os.path.exists(raw_file) else None,
                }
            except Exception as e:
                return {"status": "error", "message": f"LTspice batch simulation error: {e}"}

        return {
            "status": "ok",
            "engine": "LTspice",
            "action": "netlist_created",
            "file": temp_path,
            "instruction": f"Netlist saved to {temp_path}. Open directly in LTspice with 'pc_open(target=\"{temp_path}\")'.",
        }

    def _execute_powershell_script(self, script_content: str) -> dict[str, Any]:
        """Execute generic PowerShell automation script."""
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script_content],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return {
                "status": "ok" if res.returncode == 0 else "error",
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "exit_code": res.returncode,
            }
        except Exception as e:
            return {"status": "error", "message": f"Script execution error: {e}"}
