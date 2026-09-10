"""Windows Native GDI Screen Vision & Window Capture.

High-performance, non-failing desktop vision utilizing Windows GDI BitBlt
with Per-Monitor DPI awareness and Multi-Monitor Virtual Screen support.
"""
from __future__ import annotations

import ctypes
import datetime
import logging
from ctypes import wintypes
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .vision_engine import VisionEngine

logger = logging.getLogger(__name__)



class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class ScreenVision:
    """Windows native screen and window capture engine."""

    SRCCOPY = 0x00CC0020
    PW_RENDERFULLCONTENT = 0x00000002

    def __init__(self, artifacts_dir: Path | None = None, web_url: str = "http://localhost:8020") -> None:
        self.artifacts_dir = artifacts_dir or (Path.cwd() / ".avrora" / "artifacts")
        self.screenshots_dir = self.artifacts_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.web_url = web_url
        self._engine: VisionEngine | None = None

        self._user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
        self._gdi32 = ctypes.windll.gdi32 if hasattr(ctypes, "windll") else None

        # Enable Per-Monitor DPI awareness so coordinates and bitmaps match 1:1 with hardware pixels
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception as _exc:
            logger.debug("Operacion no fatal suprimida: %s", _exc)

    @property
    def engine(self) -> VisionEngine:
        if self._engine is None:
            self._engine = VisionEngine()
        return self._engine

    def get_monitors(self) -> list[dict[str, Any]]:
        """Enumerate all physical and virtual display monitors connected to the system."""
        if self._user32 is None:
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

        MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_long)
        self._user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_cb), 0)
        return monitors

    # ------------------------------------------------------------------
    # Full Screen Capture (Multi-Monitor Virtual Screen)
    # ------------------------------------------------------------------
    def capture_screen(
        self, path: Path | str | None = None, all_screens: bool = True, monitor_idx: int | None = None
    ) -> dict[str, Any]:
        """Capture full screen via Win32 GDI BitBlt with multi-monitor reporting."""
        if self._user32 is None or self._gdi32 is None:
            raise RuntimeError("Win32 GDI not available on this platform")

        monitors = self.get_monitors()
        if monitor_idx is not None and 1 <= monitor_idx <= len(monitors):
            m = monitors[monitor_idx - 1]
            left, top, width, height = m["left"], m["top"], m["width"], m["height"]
        elif all_screens:
            left = self._user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
            top = self._user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
            width = self._user32.GetSystemMetrics(78) # SM_CXVIRTUALSCREEN
            height = self._user32.GetSystemMetrics(79)# SM_CYVIRTUALSCREEN
        else:
            left, top = 0, 0
            width = self._user32.GetSystemMetrics(0)   # SM_CXSCREEN
            height = self._user32.GetSystemMetrics(1)  # SM_CYSCREEN

        if width <= 0 or height <= 0:
            width, height = 1920, 1080

        img = self._gdi_capture_rect(left, top, width, height)

        # Save to disk
        if path is None:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            target_path = self.screenshots_dir / f"screenshot_{ts}.png"
        else:
            target_path = Path(path)
            target_path.parent.mkdir(parents=True, exist_ok=True)

        img.save(str(target_path), format="PNG")
        web_link = f"{self.web_url}/artifacts/screenshots/{target_path.name}"

        mon_info = ""
        if monitors and len(monitors) > 1:
            parts = [f"Pantalla {m['monitor']} ({m['width']}x{m['height']})" for m in monitors]
            mon_info = f" | {len(monitors)} pantallas: " + ", ".join(parts)

        return {
            "status": "success",
            "path": str(target_path),
            "width": width,
            "height": height,
            "left": left,
            "top": top,
            "monitors": monitors,
            "web_link": web_link,
            "summary": (
                f"[vision] Screen captured ({width}x{height}{mon_info}) -> {target_path.name}\n"
                f"[Web View]: {web_link}"
            ),
        }

    # ------------------------------------------------------------------
    # Window Capture (Active or Targeted Window)
    # ------------------------------------------------------------------
    def capture_window(self, target: str = "active", path: Path | str | None = None) -> dict[str, Any]:
        """Capture a specific window (or the active foreground window)."""
        if self._user32 is None or self._gdi32 is None:
            raise RuntimeError("Win32 GDI not available")

        hwnd = self._resolve_hwnd(target)
        if not hwnd or not self._user32.IsWindow(hwnd):
            raise ValueError(f"Could not find window matching «{target}»")

        rect = wintypes.RECT()
        self._user32.GetWindowRect(hwnd, ctypes.byref(rect))
        left = rect.left
        top = rect.top
        width = rect.right - rect.left
        height = rect.bottom - rect.top

        if width <= 0 or height <= 0:
            raise ValueError(f"Window has invalid dimensions: ({width}x{height})")

        # Get window title
        buf = ctypes.create_unicode_buffer(512)
        self._user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value or "Untitled Window"

        # Capture using PrintWindow with PW_RENDERFULLCONTENT for GPU-composited
        # windows (Brave, Chrome, Edge, Electron). Falls back to GDI BitBlt if it
        # returns a blank frame (all-black), which happens with minimized windows.
        img = self._print_window_capture(hwnd, width, height)
        if img is None or self._is_blank(img):
            img = self._gdi_capture_rect(left, top, width, height)

        if path is None:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            target_path = self.screenshots_dir / f"window_{ts}.png"
        else:
            target_path = Path(path)
            target_path.parent.mkdir(parents=True, exist_ok=True)

        img.save(str(target_path), format="PNG")
        web_link = f"{self.web_url}/artifacts/screenshots/{target_path.name}"

        return {
            "status": "success",
            "title": title,
            "hwnd": hwnd,
            "path": str(target_path),
            "width": width,
            "height": height,
            "left": left,
            "top": top,
            "web_link": web_link,
            "summary": f"[vision] Captured window '{title}' ({width}x{height}) -> {target_path.name}\n[Web View]: {web_link}",
        }

    # ------------------------------------------------------------------
    # High-Performance CPU Multimodal Visual Inspection (< 2s)
    # ------------------------------------------------------------------
    def inspect_screen(
        self, monitor_idx: int | None = None, prompt: str = ""
    ) -> dict[str, Any]:
        """Capture screen and perform full CPU visual inspection in < 2s."""
        cap = self.capture_screen(monitor_idx=monitor_idx)
        img = Image.open(cap["path"])
        analysis = self.engine.analyze_image(img, prompt=prompt)
        analysis["path"] = cap["path"]
        analysis["web_link"] = cap["web_link"]
        analysis["summary"] = f"{cap['summary']}\n\n{analysis['summary']}"
        return analysis

    def inspect_window(
        self, target: str = "active", prompt: str = ""
    ) -> dict[str, Any]:
        """Capture window and perform full CPU visual inspection in < 2s."""
        cap = self.capture_window(target=target)
        img = Image.open(cap["path"])
        analysis = self.engine.analyze_image(img, prompt=prompt)
        analysis["path"] = cap["path"]
        analysis["web_link"] = cap["web_link"]
        analysis["title"] = cap["title"]
        analysis["summary"] = f"{cap['summary']}\n\n{analysis['summary']}"
        return analysis

    # ------------------------------------------------------------------
    # PrintWindow Capture (GPU-composited apps: Brave, Chrome, Electron)
    # ------------------------------------------------------------------
    def _print_window_capture(self, hwnd: int, width: int, height: int) -> Image.Image | None:
        """Use PrintWindow(PW_RENDERFULLCONTENT) to capture GPU-accelerated windows."""
        if self._user32 is None or self._gdi32 is None:
            return None
        hdc_screen = None
        hdc_mem = None
        hbitmap = None
        try:
            hdc_screen = self._user32.GetDC(0)
            hdc_mem = self._gdi32.CreateCompatibleDC(0)
            hbitmap = self._gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
            self._gdi32.SelectObject(hdc_mem, hbitmap)
            # PW_RENDERFULLCONTENT = 0x2 — forces DWM to composite the window including GPU layers
            ret = self._user32.PrintWindow(hwnd, hdc_mem, self.PW_RENDERFULLCONTENT)

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = width
            bmi.biHeight = -height
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0

            buf = ctypes.create_string_buffer(width * height * 4)
            self._gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, buf, ctypes.byref(bmi), 0)

            if ret == 0:
                return None
            return Image.frombuffer("RGBA", (width, height), bytes(buf), "raw", "BGRA", 0, 1).convert("RGB")
        except Exception:
            return None
        finally:
            if hbitmap and self._gdi32:
                self._gdi32.DeleteObject(hbitmap)
            if hdc_mem and self._gdi32:
                self._gdi32.DeleteDC(hdc_mem)
            if hdc_screen and self._user32:
                self._user32.ReleaseDC(0, hdc_screen)

    @staticmethod
    def _is_blank(img: Image.Image, threshold: int = 5) -> bool:
        """Return True if the image is effectively all-black (PrintWindow failed silently)."""
        arr = np.array(img)
        return bool(arr.max() < threshold)

    # ------------------------------------------------------------------
    # Internal GDI BitBlt Core
    # ------------------------------------------------------------------
    def _gdi_capture_rect(self, left: int, top: int, width: int, height: int) -> Image.Image:
        if self._user32 is None or self._gdi32 is None:
            raise RuntimeError("Win32 GDI not available")
        hdc_screen = None
        hdc_mem = None
        hbitmap = None
        try:
            hdc_screen = self._user32.GetDC(0)
            hdc_mem = self._gdi32.CreateCompatibleDC(hdc_screen)
            hbitmap = self._gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
            self._gdi32.SelectObject(hdc_mem, hbitmap)

            self._gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, self.SRCCOPY)

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = width
            bmi.biHeight = -height  # top-down DIB
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0

            buf = ctypes.create_string_buffer(width * height * 4)
            self._gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, buf, ctypes.byref(bmi), 0)

            return Image.frombuffer("RGBA", (width, height), bytes(buf), "raw", "BGRA", 0, 1).convert("RGB")
        finally:
            if hbitmap and self._gdi32:
                self._gdi32.DeleteObject(hbitmap)
            if hdc_mem and self._gdi32:
                self._gdi32.DeleteDC(hdc_mem)
            if hdc_screen and self._user32:
                self._user32.ReleaseDC(0, hdc_screen)

    def _resolve_hwnd(self, target: str) -> int:
        if self._user32 is None:
            raise RuntimeError("Win32 GDI not available")
        if not target or target.lower() in ("active", "foreground", "current"):
            hwnd = self._user32.GetForegroundWindow()
            if hwnd and self._user32.IsWindow(hwnd):
                return hwnd

        if target.isdigit():
            return int(target)

        # Search by window title substring
        found_hwnd = 0
        target_lower = target.lower() if target else ""

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd: int, lparam: int) -> bool:
            nonlocal found_hwnd
            if self._user32 and self._user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(512)
                self._user32.GetWindowTextW(hwnd, buf, 512)
                title = buf.value.strip()
                if title and (not target_lower or target_lower in ("active", "foreground", "current") or target_lower in title.lower()):
                    rect = wintypes.RECT()
                    self._user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    if (rect.right - rect.left) > 100 and (rect.bottom - rect.top) > 100:
                        found_hwnd = hwnd
                        return False  # stop enumeration
            return True

        self._user32.EnumWindows(enum_cb, 0)
        return found_hwnd or self._user32.GetDesktopWindow()


# Alias for backward compatibility
ScreenVisionOps = ScreenVision
