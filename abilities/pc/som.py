"""AVRORA Universal Desktop Set-of-Mark (SoM) Grounding Engine.

Enables autonomous, precise visual interaction with ANY native closed-source Windows
application (Photoshop, Blender, CAD, ERP, legacy Win32/Qt/MFC, custom canvases)
by extracting UI elements (via hybrid UIA + ONNX/Morphological computer vision)
and stamping numbered pills [1], [2], [3] over the controls in RAM.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger("AVRORA.SoM")


def compute_iou(box1: dict[str, Any], box2: dict[str, Any]) -> float:
    """Calculate Intersection-over-Union (IoU) between two bounding boxes."""
    x1 = max(int(box1.get("x", 0)), int(box2.get("x", 0)))
    y1 = max(int(box1.get("y", 0)), int(box2.get("y", 0)))
    x2 = min(int(box1.get("x", 0)) + int(box1.get("w", 0)), int(box2.get("x", 0)) + int(box2.get("w", 0)))
    y2 = min(int(box1.get("y", 0)) + int(box1.get("h", 0)), int(box2.get("y", 0)) + int(box2.get("h", 0)))

    inter_w = max(0, x2 - x1)
    inter_h = max(0, y2 - y1)
    inter_area = inter_w * inter_h

    if inter_area == 0:
        return 0.0

    area1 = int(box1.get("w", 0)) * int(box1.get("h", 0))
    area2 = int(box2.get("w", 0)) * int(box2.get("h", 0))
    union_area = area1 + area2 - inter_area
    if union_area <= 0:
        return 0.0
    return float(inter_area) / float(union_area)


def apply_nms(boxes: list[dict[str, Any]], iou_threshold: float = 0.35) -> list[dict[str, Any]]:
    """Perform Non-Maximum Suppression (NMS) to eliminate duplicate or nested bounding boxes."""
    if not boxes:
        return []

    # Sort boxes by priority: higher confidence, then moderate area (avoiding extreme noise)
    sorted_boxes = sorted(
        boxes,
        key=lambda b: (
            float(b.get("confidence", 0.7)),
            -abs(int(b.get("w", 0)) * int(b.get("h", 0)) - 3500),
        ),
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    for candidate in sorted_boxes:
        suppress = False
        for chosen in selected:
            if compute_iou(candidate, chosen) > iou_threshold:
                suppress = True
                break
        if not suppress:
            selected.append(candidate)

    return selected


class VisualElementDetector:
    """Hybrid Computer Vision UI element detector.

    Supports local ONNX inference sessions (e.g. YOLOv8-Icon ONNX / OmniParser) when
    weights exist, with zero-dependency, ultra-fast Morphological Contour Analysis
    in pure NumPy + PIL (<25 ms) as default sovereign engine.
    """

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = model_path or (Path.cwd() / "data" / "models" / "vision" / "icon_detect.onnx")
        self._onnx_session = None
        self._init_onnx()

    def _init_onnx(self) -> None:
        """Attempt to initialize ONNX Runtime inference session if weights exist."""
        env_path = os.getenv("AVRORA_SOM_MODEL_PATH")
        if env_path:
            self.model_path = Path(env_path)

        if not self.model_path.exists():
            logger.debug(
                f"SoM ONNX model not found at {self.model_path}. "
                "Using high-speed Morphological Vision engine."
            )
            return

        try:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            som_threads = int(os.getenv("AVRORA_SOM_THREADS", "0")) or max(2, min(8, (os.cpu_count() or 4) // 2))
            opts.intra_op_num_threads = som_threads
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._onnx_session = ort.InferenceSession(
                str(self.model_path),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            logger.info(f"SoM ONNX Visual Detector loaded from {self.model_path}")
        except Exception as e:
            logger.warning(f"Failed to load ONNX model {self.model_path}: {e}. Falling back to Morphological Vision.")
            self._onnx_session = None

    def detect(self, img: Image.Image, max_elements: int = 40) -> list[dict[str, Any]]:
        """Detect interactive UI elements on the given PIL Image."""
        if self._onnx_session is not None:
            try:
                res = self._detect_onnx(img, max_elements=max_elements)
                if res:
                    return res
            except Exception as e:
                logger.debug(f"ONNX inference failed: {e}. Running Morphological detector.")

        return self._detect_morphological(img, max_elements=max_elements)

    def _detect_morphological(self, img: Image.Image, max_elements: int = 40) -> list[dict[str, Any]]:
        """Vectorized Morphological edge and contour clustering for rectangular UI controls.

        Extracts buttons, inputs, icons, and toolbars across any UI canvas in <25 ms.
        """
        orig_w, orig_h = img.size
        if orig_w < 30 or orig_h < 30:
            return []

        # Downsample for sub-25ms analysis
        scale = 0.5 if orig_w > 900 else 1.0
        sw = max(16, int(orig_w * scale))
        sh = max(16, int(orig_h * scale))

        small = img.resize((sw, sh), Image.Resampling.BILINEAR) if scale != 1.0 else img
        gray = small.convert("L")

        # Find high-frequency visual edges
        edges = gray.filter(ImageFilter.FIND_EDGES)
        arr_edges = np.array(edges)
        edge_mask = arr_edges > 22

        # Morphological dilation/closing to consolidate control boundaries
        mask_img = Image.fromarray((edge_mask * 255).astype(np.uint8))
        dilated = mask_img.filter(ImageFilter.MaxFilter(3))
        active_arr = np.array(dilated) > 80

        # Reduce into block grid (4x4 blocks) for fast connected-component grouping
        bh, bw = 4, 4
        gh, gw = sh // bh, sw // bw
        if gh < 2 or gw < 2:
            return []

        blocks_any = active_arr[: gh * bh, : gw * bw].reshape(gh, bh, gw, bw).any(axis=(1, 3))
        blocks = np.asarray(blocks_any, dtype=bool)
        visited = np.zeros_like(blocks, dtype=bool)

        raw_boxes = []
        for r in range(gh):
            for c in range(gw):
                if blocks[r, c] and not visited[r, c]:
                    # BFS component extraction
                    q = [(r, c)]
                    visited[r, c] = True
                    min_r, max_r = r, r
                    min_c, max_c = c, c

                    while q:
                        cr, cc = q.pop()
                        min_r = min(min_r, cr)
                        max_r = max(max_r, cr)
                        min_c = min(min_c, cc)
                        max_c = max(max_c, cc)

                        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                            nr, nc = cr + dr, cc + dc
                            if 0 <= nr < gh and 0 <= nc < gw and blocks[nr, nc] and not visited[nr, nc]:
                                visited[nr, nc] = True
                                q.append((nr, nc))

                    # Map back to original coordinate space
                    bx = int(min_c * bw / scale)
                    by = int(min_r * bh / scale)
                    bw_px = int((max_c - min_c + 1) * bw / scale)
                    bh_px = int((max_r - min_r + 1) * bh / scale)

                    # Filter out full-window canvas border or tiny noise
                    if bw_px >= 0.85 * orig_w and bh_px >= 0.85 * orig_h:
                        continue
                    if bw_px < 16 or bh_px < 12:
                        continue

                    # Filter extreme aspect ratios
                    aspect = bw_px / max(1, bh_px)
                    if aspect < 0.08 or aspect > 20:
                        continue

                    # Classify control archetype based on geometric proportions
                    if aspect > 2.4 and bh_px <= 48:
                        ctype = "Input/Field"
                    elif 0.8 <= aspect <= 1.4 and bw_px <= 52 and bh_px <= 52:
                        ctype = "Icon/ToolButton"
                    elif aspect >= 1.4 and bh_px <= 64:
                        ctype = "Button"
                    elif bh_px > 120 and bw_px > 160:
                        ctype = "Container/Card"
                    else:
                        ctype = "VisualBox"

                    raw_boxes.append({
                        "name": f"{ctype} ({bx + bw_px // 2}, {by + bh_px // 2})",
                        "control_type": ctype,
                        "x": bx,
                        "y": by,
                        "w": bw_px,
                        "h": bh_px,
                        "confidence": 0.75 if ctype != "VisualBox" else 0.65,
                    })

        # Apply Non-Maximum Suppression to deduplicate nested borders
        nms_boxes = apply_nms(raw_boxes, iou_threshold=0.35)
        return nms_boxes[:max_elements]

    def _detect_onnx(self, img: Image.Image, max_elements: int = 40) -> list[dict[str, Any]]:
        """Inference with ONNX icon/UI detector model."""
        if self._onnx_session is None:
            return []

        orig_w, orig_h = img.size
        input_meta = self._onnx_session.get_inputs()[0]
        input_name = input_meta.name
        shape = input_meta.shape

        # Target dimensions (typically 640x640)
        target_h = shape[2] if len(shape) > 2 and isinstance(shape[2], int) else 640
        target_w = shape[3] if len(shape) > 3 and isinstance(shape[3], int) else 640

        resized = img.resize((target_w, target_h), Image.Resampling.BILINEAR)
        arr = np.array(resized).astype(np.float32) / 255.0

        # Channels-first format (1, 3, H, W)
        if arr.ndim == 3 and arr.shape[2] == 3:
            arr = np.transpose(arr, (2, 0, 1))
        tensor = np.expand_dims(arr, axis=0)

        outputs = self._onnx_session.run(None, {input_name: tensor})
        if not outputs:
            return []

        out = np.squeeze(np.asarray(outputs[0]))
        # Expected shape: (N, 5+) or (5+, N)
        if out.shape[0] < out.shape[-1]:
            out = out.T

        boxes = []
        for row in out:
            conf = float(row[4]) if len(row) > 4 else float(np.max(row[4:])) if len(row) > 5 else 0.5
            if conf < 0.25:
                continue

            cx, cy, w, h = row[0], row[1], row[2], row[3]
            bx = int((cx - w / 2.0) * (orig_w / target_w))
            by = int((cy - h / 2.0) * (orig_h / target_h))
            bw_px = int(w * (orig_w / target_w))
            bh_px = int(h * (orig_h / target_h))

            boxes.append({
                "name": f"ONNX Control ({bx + bw_px // 2}, {by + bh_px // 2})",
                "control_type": "Button",
                "x": max(0, bx),
                "y": max(0, by),
                "w": max(10, bw_px),
                "h": max(10, bh_px),
                "confidence": conf,
            })

        return apply_nms(boxes, iou_threshold=0.35)[:max_elements]


class DesktopSoM:
    """Desktop Set-of-Mark (SoM) Visual Grounding and Coordinate Dispatcher."""

    _instance: DesktopSoM | None = None

    def __init__(self, artifacts_dir: Path | None = None) -> None:
        self.artifacts_dir = artifacts_dir or (Path.cwd() / ".avrora" / "artifacts" / "screenshots")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.detector = VisualElementDetector()
        self._active_boxes: dict[int, dict[str, Any]] = {}

    @classmethod
    def get_instance(cls) -> DesktopSoM:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def inspect(self, target: str = "active", max_elements: int = 30) -> dict[str, Any]:
        """Capture screen/window, detect controls (UIA + Vision), stamp visual marks, and build interactive map."""
        from .gui_driver import GUIDriver
        from .screen_vision import ScreenVision

        vision = ScreenVision(artifacts_dir=self.artifacts_dir.parent)
        gui = GUIDriver()

        # 1. Capture target window or full screen
        if target.lower() in ("screen", "desktop", "fullscreen"):
            cap = vision.capture_screen()
            base_x, base_y = 0, 0
            title = "Desktop"
        else:
            cap = vision.capture_window(target=target)
            base_x, base_y = cap.get("left", 0), cap.get("top", 0)
            title = cap.get("title", "Active Window")

        img = Image.open(cap["path"]).convert("RGB")
        w, h = img.size

        # 2. Extract UI elements via Windows UIAutomation (UIA)
        detected_controls: list[Any] = []
        try:
            raw_ctrls = gui.inspect_controls(
                window_title=title if target != "active" else "",
                max_controls=max_elements,
            )
            if isinstance(raw_ctrls, list):
                detected_controls = raw_ctrls
        except Exception as e:
            logger.debug(f"UIA inspect error: {e}")

        # 3. Parse UIA boxes and map to window image coordinates
        uia_boxes: list[dict[str, Any]] = []
        for c in detected_controls:
            if not isinstance(c, dict):
                continue
            bounds_str = c.get("bounds", "")
            if not bounds_str:
                continue
            try:
                parts = [int(float(v)) for v in bounds_str.split(",")]
                if len(parts) != 4:
                    continue
                bx, by, bw, bh = parts
                if bw <= 6 or bh <= 6 or bw > w * 0.95 or bh > h * 0.95:
                    continue

                rx = bx - base_x
                ry = by - base_y
                if rx < 0 or ry < 0 or rx + bw > w or ry + bh > h:
                    continue

                name = c.get("name") or c.get("automation_id") or c.get("control_type", "Control")
                uia_boxes.append({
                    "name": name,
                    "control_type": c.get("control_type", "Button"),
                    "x": rx,
                    "y": ry,
                    "w": bw,
                    "h": bh,
                    "screen_cx": bx + bw // 2,
                    "screen_cy": by + bh // 2,
                    "source": "uia",
                    "confidence": 0.95,
                })
            except Exception:
                continue

        # 4. Run Computer Vision Element Detection (ONNX / Morphological)
        visual_boxes: list[dict[str, Any]] = []
        try:
            detected_vis = self.detector.detect(img, max_elements=max_elements)
            for vb in detected_vis:
                vb["screen_cx"] = base_x + vb["x"] + vb["w"] // 2
                vb["screen_cy"] = base_y + vb["y"] + vb["h"] // 2
                vb["source"] = "vision"
                visual_boxes.append(vb)
        except Exception as e:
            logger.debug(f"Visual detection error: {e}")

        # 5. Intelligent Fusion: Retain all UIA controls + Add novel visual elements missed by UIA
        fused_boxes: list[dict[str, Any]] = list(uia_boxes)
        for vb in visual_boxes:
            # Check if visual box already covered by a UIA control
            overlaps_uia = any(compute_iou(vb, ub) > 0.28 for ub in uia_boxes)
            if not overlaps_uia:
                fused_boxes.append(vb)

        # 6. Apply Non-Maximum Suppression across fused set
        clean_boxes = apply_nms(fused_boxes, iou_threshold=0.35)

        # 7. Sort in natural reading order (top-to-bottom, left-to-right)
        clean_boxes.sort(key=lambda b: (b["y"] // 35, b["x"]))

        # 8. Draw Set-of-Mark (SoM) Visual Overlay
        draw = ImageDraw.Draw(img)
        self._active_boxes.clear()

        colors = ["#E91E63", "#00E676", "#00B0FF", "#FFD600", "#FF6D00", "#D500F9", "#00BCD4"]
        text_lines = []

        for idx, b in enumerate(clean_boxes[:max_elements], start=1):
            color = colors[(idx - 1) % len(colors)]
            x, y, bw, bh = b["x"], b["y"], b["w"], b["h"]

            # Draw bounding box
            draw.rectangle([x, y, x + bw, y + bh], outline=color, width=2)

            # Draw numbered pill badge
            pill_text = f"[{idx}]"
            pill_w = len(pill_text) * 8 + 6
            pill_h = 16
            draw.rectangle([x, max(0, y - pill_h), x + pill_w, y], fill=color)
            draw.text((x + 3, max(0, y - pill_h) + 1), pill_text, fill="#000000")

            self._active_boxes[idx] = b
            src_tag = "UIA" if b.get("source") == "uia" else "Vision"
            label = f"[{idx}] [{src_tag}] {b['control_type']} «{b['name']}» — ({b['screen_cx']}, {b['screen_cy']})"
            text_lines.append(label)

        # Save visual artifact
        annotated_path = self.artifacts_dir / "som_annotated.png"
        img.save(str(annotated_path), quality=90)
        web_link = "http://localhost:8020/artifacts/screenshots/som_annotated.png"

        formatted_map = "DESKTOP SET-OF-MARK (SOM) MAPA:\n" + (
            "\n".join(text_lines) if text_lines else "(No se detectaron controles interactivos en la ventana)"
        )

        header = f"[SoM] {len(self._active_boxes)} elementos etiquetados en «{title}».\n[Web View]: {web_link}"
        return {
            "window_title": title,
            "total_elements": len(self._active_boxes),
            "text_map": formatted_map,
            "annotated_path": str(annotated_path),
            "web_link": web_link,
            "summary": f"{header}\n\n{formatted_map}",
        }

    def click_box(self, box_id: int, click_type: str = "click") -> str:
        """Click the center of the specified Set-of-Mark box ID."""
        if box_id not in self._active_boxes:
            available = list(self._active_boxes.keys())
            return f"[som error] Box [{box_id}] no encontrado. IDs activos: {available[:10]}..."

        b = self._active_boxes[box_id]
        cx, cy = b["screen_cx"], b["screen_cy"]
        name = b["name"]

        from .window_tools import WindowOps

        wops = WindowOps()

        if click_type == "double":
            res = wops.click_at(cx, cy, double=True)
        elif click_type == "right":
            res = wops.click_at(cx, cy, button="right")
        else:
            res = wops.click_at(cx, cy, button="left")

        return f"[som] Clic ejecutado en Box [{box_id}] «{name}» coordenadas ({cx}, {cy}) -> {res}"

    def type_box(self, box_id: int, text: str, clear_first: bool = True, submit: bool = False) -> str:
        """Focus the specified Set-of-Mark box and type text into it."""
        if box_id not in self._active_boxes:
            available = list(self._active_boxes.keys())
            return f"[som error] Box [{box_id}] no encontrado. IDs activos: {available[:10]}..."

        b = self._active_boxes[box_id]
        cx, cy = b["screen_cx"], b["screen_cy"]
        name = b["name"]

        from .window_tools import WindowOps

        wops = WindowOps()

        # 1. Click to acquire focus
        wops.click_at(cx, cy, button="left")
        time.sleep(0.08)

        # 2. Optionally select-all and backspace to clear prior content
        if clear_first:
            wops.hotkey("ctrl", "a")
            time.sleep(0.04)
            wops.press_key("backspace")
            time.sleep(0.04)

        # 3. Type text
        type_res = wops.type_text(text)

        # 4. Optionally submit with Enter
        if submit:
            time.sleep(0.05)
            wops.press_key("enter")

        return f"[som] Texto escrito en Box [{box_id}] «{name}» ({cx}, {cy}): «{text}» -> {type_res}"

    def hover_box(self, box_id: int) -> str:
        """Hover cursor over the center of the specified Set-of-Mark box ID."""
        if box_id not in self._active_boxes:
            available = list(self._active_boxes.keys())
            return f"[som error] Box [{box_id}] no encontrado. IDs activos: {available[:10]}..."

        b = self._active_boxes[box_id]
        cx, cy = b["screen_cx"], b["screen_cy"]
        name = b["name"]

        try:
            import ctypes

            ctypes.windll.user32.SetCursorPos(int(cx), int(cy))
            return f"[som] Cursor posicionado sobre Box [{box_id}] «{name}» en ({cx}, {cy})"
        except Exception as e:
            return f"[som error] Error al mover cursor a Box [{box_id}]: {e}"

    def get_box(self, box_id: int) -> dict[str, Any] | None:
        """Retrieve box metadata dictionary for the given ID."""
        return self._active_boxes.get(box_id)

    def get_active_boxes(self) -> dict[int, dict[str, Any]]:
        """Return a copy of all currently active labeled boxes."""
        return dict(self._active_boxes)


# Alias for backward compatibility with AdvancedDesktopAbility
ScreenMarker = DesktopSoM
