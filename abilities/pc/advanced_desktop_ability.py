"""
WIS Advanced Desktop Ability — Unified AVRORA PC Engine.
=========================================================
Wraps ALL AVRORA PC motors into a single, coherent WIS Ability block:
  - GUIDriver   : UIA inspection, keystrokes, domain scripting (AutoCAD, Photoshop, LTspice)
  - VisionEngine: CLIP-ViT ONNX deep visual analysis, OCR (RapidOCR), perceptual hash cache
  - WindowOps   : Win32 native window management (focus, resize, snap, DPI-aware)
  - ScreenMarker: AVRORA SOM (Set of Marks) screen annotation
  - AppLauncher : Dynamic app/URL/document launch via registry + Start Menu indexing
  - ProcessMgr  : Process list, kill, wait, PID tracking

This single Ability gives the LLM full desktop AGI capabilities.
"""
from __future__ import annotations

import logging
from typing import Any

from abilities.base import Ability

logger = logging.getLogger("wis.abilities.pc.advanced_desktop")


# ─── Lazy-loaded engine singletons ────────────────────────────────────────────

def _get_gui_driver():
    from .gui_driver import GUIDriver
    return GUIDriver()

def _get_window_ops():
    from .window_tools import WindowOps
    return WindowOps()

def _get_vision_engine():
    from .vision_engine import VisionEngine
    return VisionEngine()

def _get_screen_marker():
    from .som import ScreenMarker
    return ScreenMarker()

def _get_app_launcher():
    from .apps import AppLauncher
    return AppLauncher()

def _get_process_mgr():
    from .process import ProcessManager
    return ProcessManager()


class AdvancedDesktopAbility(Ability):
    """
    Unified AVRORA PC Engine — gives WIS full desktop AGI capabilities.
    Engines are lazily instantiated on first use to avoid import overhead.
    """

    def __init__(self) -> None:
        self._gui: Any = None
        self._wops: Any = None
        self._vision: Any = None
        self._marker: Any = None
        self._apps: Any = None
        self._proc: Any = None

    # ── Lazy accessors ─────────────────────────────────────────────────────────

    @property
    def gui(self):
        if self._gui is None:
            try:
                self._gui = _get_gui_driver()
            except Exception as e:
                logger.warning("GUIDriver init failed: %s", e)
        return self._gui

    @property
    def wops(self):
        if self._wops is None:
            try:
                self._wops = _get_window_ops()
            except Exception as e:
                logger.warning("WindowOps init failed: %s", e)
        return self._wops

    @property
    def vision(self):
        if self._vision is None:
            try:
                self._vision = _get_vision_engine()
            except Exception as e:
                logger.warning("VisionEngine init failed: %s", e)
        return self._vision

    @property
    def marker(self):
        if self._marker is None:
            try:
                self._marker = _get_screen_marker()
            except Exception as e:
                logger.warning("ScreenMarker init failed: %s", e)
        return self._marker

    @property
    def apps(self):
        if self._apps is None:
            try:
                self._apps = _get_app_launcher()
            except Exception as e:
                logger.warning("AppLauncher init failed: %s", e)
        return self._apps

    @property
    def proc(self):
        if self._proc is None:
            try:
                self._proc = _get_process_mgr()
            except Exception as e:
                logger.warning("ProcessManager init failed: %s", e)
        return self._proc

    # ── Ability metadata ───────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "advanced_desktop"

    @property
    def description(self) -> str:
        return (
            "Full AVRORA desktop AGI engine: launch apps/URLs, control windows, "
            "inspect UI elements via UIA, send keystrokes, deep visual analysis (CLIP+OCR), "
            "screen annotation (SOM), and process management."
        )

    @property
    def domain(self) -> str:
        return "pc"

    def get_schema(self) -> list:
        return [
            # ── AppLauncher ───────────────────────────────────────────────────
            {
                "action": "launch_app",
                "description": "Launch an application, file, or URL by name or full path.",
                "params": {
                    "target": "App name, file path, or URL to open",
                    "args": "(optional) list of CLI arguments",
                }
            },
            {
                "action": "launch_url",
                "description": "Open a URL in the default browser.",
                "params": {"url": "Full URL to open"}
            },
            # ── WindowOps ─────────────────────────────────────────────────────
            {
                "action": "list_windows",
                "description": "List all visible windows with titles, PIDs, and geometry.",
                "params": {}
            },
            {
                "action": "focus_window",
                "description": "Bring a window to the foreground by title substring.",
                "params": {"title": "Window title substring to match"}
            },
            {
                "action": "resize_window",
                "description": "Resize and reposition a window.",
                "params": {
                    "title": "Window title substring",
                    "x": "Left position (pixels)",
                    "y": "Top position (pixels)",
                    "width": "Width in pixels",
                    "height": "Height in pixels"
                }
            },
            {
                "action": "snap_window",
                "description": "Snap a window to a screen position.",
                "params": {
                    "title": "Window title substring",
                    "position": "left | right | maximize | minimize | restore"
                }
            },
            {
                "action": "close_window",
                "description": "Close a window gracefully via WM_CLOSE.",
                "params": {"title": "Window title substring"}
            },
            {
                "action": "get_monitors",
                "description": "List all connected monitors with resolution and DPI info.",
                "params": {}
            },
            # ── GUIDriver — Keystrokes & UIA ──────────────────────────────────
            {
                "action": "send_keys",
                "description": "Send keystrokes or hotkeys to the active or specified window (e.g. 'ctrl+s', 'alt+f4', 'Hello World').",
                "params": {
                    "keys": "Key sequence or text to type",
                    "window_title": "(optional) Target window title"
                }
            },
            {
                "action": "click_element",
                "description": "Click a UI element found by name/text using UIA accessibility tree.",
                "params": {
                    "element_name": "Accessible name or text of the UI element",
                    "window_title": "(optional) Window to search in"
                }
            },
            {
                "action": "type_text",
                "description": "Type text into the currently focused input field.",
                "params": {"text": "Text to type"}
            },
            {
                "action": "uia_inspect",
                "description": "Inspect the UIA accessibility tree of a window and return interactive elements.",
                "params": {"window_title": "Target window title"}
            },
            # ── VisionEngine ─────────────────────────────────────────────────
            {
                "action": "analyze_screen",
                "description": "Deep visual analysis of the screen: scene classification (CLIP-ViT), OCR text extraction, color analysis.",
                "params": {
                    "region": "(optional) Crop region as [x, y, w, h] pixels. Omit for full screen."
                }
            },
            {
                "action": "extract_text_ocr",
                "description": "Extract all visible text from the screen or a region using RapidOCR.",
                "params": {
                    "region": "(optional) [x, y, w, h] crop region"
                }
            },
            # ── ScreenMarker / SOM ────────────────────────────────────────────
            {
                "action": "annotate_screen",
                "description": "Capture and annotate the screen with Set-of-Marks (numbered labels on UI elements). Returns annotated image path and element map.",
                "params": {}
            },
            {
                "action": "find_element_on_screen",
                "description": "Find a UI element on screen by visible text using SOM.",
                "params": {"text": "Text or label to search for"}
            },
            # ── ProcessManager ────────────────────────────────────────────────
            {
                "action": "list_processes",
                "description": "List running processes with PID, name, CPU%, and memory.",
                "params": {"filter_name": "(optional) filter by process name substring"}
            },
            {
                "action": "kill_process",
                "description": "Terminate a process by PID or name.",
                "params": {
                    "pid": "(optional) PID to kill",
                    "name": "(optional) Process name substring to kill"
                }
            },
            {
                "action": "wait_for_process",
                "description": "Wait until a process with the given name appears (up to timeout).",
                "params": {
                    "name": "Process name substring",
                    "timeout": "Max seconds to wait (default 10)"
                }
            },
        ]

    # ── Main dispatcher ────────────────────────────────────────────────────────

    async def execute(self, action: str, params: dict) -> dict:
        try:
            # ── AppLauncher ────────────────────────────────────────────────────
            if action == "launch_app":
                target = params.get("target", "")
                args = params.get("args", [])
                if not target:
                    return {"success": False, "message": "No target provided"}
                result = self.apps.open(target, args=args if isinstance(args, list) else [])
                return {"success": result.get("success", False), "data": result, "message": result.get("message", "")}

            elif action == "launch_url":
                import webbrowser
                url = params.get("url", "")
                if not url:
                    return {"success": False, "message": "No URL provided"}
                webbrowser.open(url)
                return {"success": True, "message": f"Opened URL: {url}"}

            # ── WindowOps ──────────────────────────────────────────────────────
            elif action == "list_windows":
                windows = self.wops.list_windows()
                return {"success": True, "data": windows, "message": f"{len(windows)} windows found"}

            elif action == "focus_window":
                title = params.get("title", "")
                result = self.wops.focus_window(title)
                return {"success": bool(result), "message": f"Focused: {title}" if result else f"Window '{title}' not found"}

            elif action == "resize_window":
                title = params.get("title", "")
                x = int(params.get("x", 0))
                y = int(params.get("y", 0))
                w = int(params.get("width", 800))
                h = int(params.get("height", 600))
                result = self.wops.set_window_geometry(title, x, y, w, h)
                return {"success": bool(result), "message": f"Resized '{title}' to {w}x{h}"}

            elif action == "snap_window":
                title = params.get("title", "")
                pos = params.get("position", "maximize")
                result = self.wops.snap_window(title, pos)
                return {"success": bool(result), "message": f"Snapped '{title}' to {pos}"}

            elif action == "close_window":
                title = params.get("title", "")
                result = self.wops.close_window(title)
                return {"success": bool(result), "message": f"Closed '{title}'"}

            elif action == "get_monitors":
                monitors = self.wops.get_monitors()
                return {"success": True, "data": monitors, "message": f"{len(monitors)} monitors detected"}

            # ── GUIDriver ──────────────────────────────────────────────────────
            elif action == "send_keys":
                keys = params.get("keys", "")
                window_title = params.get("window_title", "")
                if not keys:
                    return {"success": False, "message": "No keys provided"}
                result = self.gui.send_keys(keys, window_title=window_title)
                ok = result.get("status") == "ok" if isinstance(result, dict) else bool(result)
                return {"success": ok, "data": result, "message": f"Keys sent: {keys}"}

            elif action == "type_text":
                text = params.get("text", "")
                result = self.gui.send_keys(text)
                ok = result.get("status") == "ok" if isinstance(result, dict) else bool(result)
                return {"success": ok, "message": f"Typed: {text[:50]}"}

            elif action == "click_element":
                name = params.get("element_name", "")
                window_title = params.get("window_title", "")
                result = self.gui.click_element_by_name(name, window_title=window_title)
                ok = result.get("status") == "ok" if isinstance(result, dict) else bool(result)
                return {"success": ok, "data": result, "message": f"Clicked: {name}"}

            elif action == "uia_inspect":
                window_title = params.get("window_title", "")
                result = self.gui.inspect_window(window_title)
                return {"success": True, "data": result, "message": f"Inspected: {window_title}"}

            # ── VisionEngine ───────────────────────────────────────────────────
            elif action == "analyze_screen":
                import asyncio
                region = params.get("region")
                # VisionEngine.analyze() is sync — run in executor
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: self.vision.analyze(region=region)
                )
                return {"success": True, "data": result, "message": "Screen analyzed"}

            elif action == "extract_text_ocr":
                import asyncio
                region = params.get("region")
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: self.vision.extract_text(region=region)
                )
                return {"success": True, "data": result, "message": "OCR completed"}

            # ── SOM / ScreenMarker ─────────────────────────────────────────────
            elif action == "annotate_screen":
                import asyncio
                loop = asyncio.get_event_loop()
                path, marks = await loop.run_in_executor(
                    None, self.marker.annotate_screen
                )
                return {
                    "success": True,
                    "data": {"path": str(path), "marks": marks},
                    "message": f"Annotated screen saved: {path}"
                }

            elif action == "find_element_on_screen":
                text = params.get("text", "")
                from .screen_vision import ScreenVisionOps
                sv = ScreenVisionOps()
                result = sv.find_text(text)
                return {"success": bool(result), "data": result, "message": f"Found '{text}'" if result else f"'{text}' not found"}

            # ── ProcessManager ─────────────────────────────────────────────────
            elif action == "list_processes":
                filter_name = params.get("filter_name", "")
                procs = self.proc.list_processes(filter_name=filter_name)
                return {"success": True, "data": procs, "message": f"{len(procs)} processes"}

            elif action == "kill_process":
                pid = params.get("pid")
                name = params.get("name", "")
                result = self.proc.kill(pid=pid, name=name)
                return {"success": result.get("success", False), "message": result.get("message", "")}

            elif action == "wait_for_process":
                name = params.get("name", "")
                timeout = float(params.get("timeout", 10))
                result = self.proc.wait_for(name=name, timeout=timeout)
                return {"success": result, "message": f"Process '{name}' {'appeared' if result else 'not found within timeout'}"}

            return {"success": False, "message": f"Unknown action: {action}"}

        except Exception as e:
            logger.exception("AdvancedDesktopAbility error: %s", e)
            return {"success": False, "message": str(e)}
