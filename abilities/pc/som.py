"""AVRORA Universal Desktop Set-of-Mark (SoM) Grounding Engine.

Enables autonomous, precise visual interaction with ANY native closed-source Windows
application (Photoshop, Blender, CAD, ERP, legacy Win32/Qt/MFC, custom canvases)
by extracting UI elements (via hybrid UIA + ONNX/Morphological computer vision)
and stamping numbered pills [1], [2], [3] over the controls in RAM.
"""
from __future__ import annotations

import ast
import difflib
import logging
import os
import threading
import time
from collections.abc import Sequence
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


def containment_ratio(inner: dict[str, Any], outer: dict[str, Any]) -> float:
    """Fraction of ``inner``'s area that lies inside ``outer`` (1.0 = fully contained)."""
    ix1 = max(int(inner.get("x", 0)), int(outer.get("x", 0)))
    iy1 = max(int(inner.get("y", 0)), int(outer.get("y", 0)))
    ix2 = min(int(inner.get("x", 0)) + int(inner.get("w", 0)), int(outer.get("x", 0)) + int(outer.get("w", 0)))
    iy2 = min(int(inner.get("y", 0)) + int(inner.get("h", 0)), int(outer.get("y", 0)) + int(outer.get("h", 0)))
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    inner_area = int(inner.get("w", 0)) * int(inner.get("h", 0))
    if inner_area <= 0:
        return 0.0
    return inter / inner_area


#: A nested region this contained in an outer control is treated as its inner detail
#: (the caption glyphs of a button, the icon inside a toolbutton…).
_CONTAINED_RATIO = 0.78
#: The inner region must be at least this much smaller than the outer control.
_CONTAINED_MIN_AREA_RATIO = 2.0
#: Two labelled boxes with captions this dissimilar are distinct controls that
#: merely overlap, so neither is allowed to absorb the other.
_CONTAINED_CAPTION_SIMILARITY = 0.55

#: Only concrete controls may absorb their own inner detail. Generic containers
#: (cards, panels, canvases) must never swallow a real control they enclose.
_ABSORBING_TYPES = frozenset({"Button", "Icon/ToolButton", "Input/Field"})


def merge_contained_boxes(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse nested detections of the same control into a single entry.

    The edge-based detector legitimately finds *both* a button's border and the
    glyphs inside it. Because the inner region is small, Intersection-over-Union
    stays low (≈0.15-0.20) and Non-Maximum Suppression cannot collapse them, so
    the marked map listed the same control twice — once as a useful
    ``Button «Guardar»`` and once as a misleading ``Input/Field «Guardar»``.

    The pass keeps the OUTER box (the real clickable control), adopts the inner
    box's OCR caption when the outer has none, and drops the inner entry.

    Safety rules, in order of importance:

    - Only concrete controls (``Button``, ``Icon/ToolButton``, ``Input/Field``)
      may absorb an inner region, so a card enclosing a button does not eat it.
    - The inner region must be at least twice as small (no upper bound: glyph
      fragments inside a control can be arbitrarily tiny).
    - Two boxes whose captions are clearly different are treated as distinct
      overlapping controls and are both preserved.
    """
    if len(boxes) < 2:
        return boxes

    def _area(b: dict[str, Any]) -> int:
        return max(0, int(b.get("w", 0))) * max(0, int(b.get("h", 0)))

    ordered = sorted(boxes, key=_area, reverse=True)
    consumed: set[int] = set()
    result: list[dict[str, Any]] = []

    for i, outer in enumerate(ordered):
        if i in consumed:
            continue

        outer_area = _area(outer)
        outer_type = str(outer.get("control_type", ""))
        can_absorb = outer_area > 0 and outer_type in _ABSORBING_TYPES
        outer_caption = str(outer.get("name") or "") if outer.get("label_source") == "ocr" else ""

        best_caption: tuple[int, str] | None = None
        if can_absorb:
            for j, inner in enumerate(ordered):
                if i == j or j in consumed:
                    continue
                inner_area = _area(inner)
                if inner_area <= 0:
                    continue
                if outer_area / inner_area < _CONTAINED_MIN_AREA_RATIO:
                    continue
                if containment_ratio(inner, outer) < _CONTAINED_RATIO:
                    continue

                inner_caption = str(inner.get("name") or "") if inner.get("label_source") == "ocr" else ""
                if outer_caption and inner_caption:
                    similarity = difflib.SequenceMatcher(None, outer_caption.lower(), inner_caption.lower()).ratio()
                    if similarity < _CONTAINED_CAPTION_SIMILARITY:
                        continue

                consumed.add(j)
                if inner_caption and (best_caption is None or inner_area > best_caption[0]):
                    best_caption = (inner_area, inner_caption)

        merged = dict(outer)
        if best_caption is not None and outer.get("label_source") != "ocr":
            merged["name"] = best_caption[1]
            merged["label_source"] = "ocr"
            merged["confidence"] = min(0.95, float(merged.get("confidence", 0.7)) + 0.1)
        result.append(merged)

    return result


# ---------------------------------------------------------------------------
# YOLO-style ONNX decoding
# ---------------------------------------------------------------------------
#: Detection confidence below which a decoded box is discarded.
_ONNX_CONF_THRESHOLD = 0.25
#: Guard against a malformed model emitting a runaway anchor count.
_ONNX_MAX_RAW_BOXES = 1000
#: Label used when the model ships no class names (a generic clickable region).
_ONNX_FALLBACK_LABEL = "Element"


def decode_yolo_outputs(
    raw: np.ndarray,
    *,
    input_w: int,
    input_h: int,
    orig_w: int,
    orig_h: int,
    labels: Sequence[str] | None = None,
    conf_threshold: float = _ONNX_CONF_THRESHOLD,
    max_detections: int = _ONNX_MAX_RAW_BOXES,
) -> list[dict[str, Any]]:
    """Decode a YOLO-style detection tensor into AVRORA box dictionaries.

    Accepts both layouts an exported YOLO can produce:

    - ``(4 + num_classes, num_anchors)`` — Ultralytics default, transposed here;
    - ``(num_anchors, 4 + num_classes)`` — already in row-major order.

    The first four channels are ``cx, cy, w, h`` expressed in **input-image**
    pixels; the remaining channels are per-class scores. Ultralytics exports fold
    objectness into the class score, so the detection confidence is the **highest**
    class score.

    Bug fixed here: the previous inline loop read channel 4 unconditionally
    (``float(row[4]) if len(row) > 4``), and its ``np.max(row[4:])`` alternative was
    unreachable dead code. That is only correct for single-class models — for a
    multi-class model it reported class 0's score and mislabelled every detection.

    Pure function (no ONNX session, no image) so the decoding is unit-testable with
    synthetic tensors, which is the only reliable way to validate it without
    shipping model weights.

    Returns boxes in **original image** coordinates, without NMS.
    """
    if raw is None or np.asarray(raw).size == 0:
        return []

    arr = np.asarray(raw, dtype=np.float32)
    # Drop only the batch dimension, so a single-anchor tensor keeps its 2-D shape
    # (np.squeeze() alone would collapse (1, 5, 1) into a 1-D vector and lose the
    # channel/anchor distinction).
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = np.squeeze(arr, axis=0)
    else:
        arr = np.squeeze(arr)
    single_row = arr.ndim == 1
    if single_row:  # a bare detection row: already (1 anchor, channels)
        arr = arr.reshape(1, -1)
    if arr.ndim != 2:
        return []

    # Normalise to (num_anchors, channels). In an Ultralytics export the channel
    # dimension is the smaller one; the second branch additionally covers
    # degenerate anchor counts, where only one orientation can hold 4 box
    # channels plus at least one score.
    if not single_row:
        if arr.shape[0] < arr.shape[1]:
            arr = arr.T
        elif arr.shape[0] >= 5 and arr.shape[1] < 5:
            arr = arr.T
    channels = arr.shape[1]
    if channels < 5:
        # Not a detection tensor: needs 4 box channels plus at least one score.
        return []

    scale_x = orig_w / float(input_w) if input_w else 1.0
    scale_y = orig_h / float(input_h) if input_h else 1.0

    names = list(labels) if labels else []
    num_classes = channels - 4

    # Score every anchor first, then keep the best ones. Truncating before
    # thresholding would be wrong: anchor order carries no meaning, so cutting by
    # index silently drops valid detections that happen to sit beyond the cut
    # (a real omission caught by test_handles_realistic_yolov8_shape, where the
    # only detection lives at anchor 4211 — past a 1000-anchor window).
    class_scores = arr[:, 4:]
    class_ids = np.argmax(class_scores, axis=1)
    confs = class_scores[np.arange(class_scores.shape[0]), class_ids]
    xywh = arr[:, :4]

    keep = (
        np.isfinite(confs)
        & (confs >= conf_threshold)
        & np.isfinite(xywh).all(axis=1)
        & (xywh[:, 2] > 0)
        & (xywh[:, 3] > 0)
    )
    selected = np.nonzero(keep)[0]
    if selected.size > max_detections:
        # Keep the most confident, not the first in anchor order.
        selected = selected[np.argsort(confs[selected])[::-1][:max_detections]]

    boxes: list[dict[str, Any]] = []
    for i in selected:
        cx, cy, w, h = (float(v) for v in xywh[i])
        class_idx = int(class_ids[i])
        conf = float(confs[i])

        bx = int(round((cx - w / 2.0) * scale_x))
        by = int(round((cy - h / 2.0) * scale_y))
        bw_px = int(round(w * scale_x))
        bh_px = int(round(h * scale_y))

        # Never invent a class name that the model did not provide.
        if class_idx < len(names) and names[class_idx]:
            label = names[class_idx]
        elif num_classes == 1:
            label = _ONNX_FALLBACK_LABEL
        else:
            label = f"{_ONNX_FALLBACK_LABEL} {class_idx + 1}"

        boxes.append({
            "name": f"{label} ({bx + bw_px // 2}, {by + bh_px // 2})",
            "control_type": label,
            "x": max(0, bx),
            "y": max(0, by),
            "w": max(10, bw_px),
            "h": max(10, bh_px),
            "confidence": conf,
            "class_id": class_idx,
        })

    return boxes


class VisualElementDetector:
    """Hybrid Computer Vision UI element detector.

    Supports local ONNX inference sessions (e.g. YOLOv8-Icon ONNX / OmniParser) when
    weights exist, with zero-dependency, ultra-fast Morphological Contour Analysis
    in pure NumPy + PIL (<25 ms) as default sovereign engine.
    """

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = model_path or (Path.cwd() / "data" / "models" / "vision" / "icon_detect.onnx")
        # An onnxruntime.InferenceSession once a valid model has loaded, else None.
        # Typed as Any because onnxruntime ships no inline stubs for this attribute.
        self._onnx_session: Any = None
        self._onnx_labels: list[str] = []
        self._onnx_input_name = ""
        self._onnx_input_size: tuple[int, int] = (640, 640)
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
            if not self._validate_onnx_contract():
                # Refuse to run an incompatible model: a wrong tensor silently
                # produces meaningless boxes, which is worse than no model at all.
                self._onnx_session = None
                return
            self._onnx_labels = self._load_onnx_labels()
            logger.info(
                "SoM ONNX visual detector loaded from %s (input %dx%d, %s)",
                self.model_path,
                self._onnx_input_size[0],
                self._onnx_input_size[1],
                f"{len(self._onnx_labels)} labelled classes" if self._onnx_labels else "no class labels",
            )
        except Exception as e:
            logger.warning(f"Failed to load ONNX model {self.model_path}: {e}. Falling back to Morphological Vision.")
            self._onnx_session = None

    def _validate_onnx_contract(self) -> bool:
        """Check that the model matches the YOLO-style contract this decoder assumes.

        Validates shape rather than trusting the filename. On failure the session
        is discarded so the caller falls back to the morphological engine instead
        of feeding detected garbage into the marked map.
        """
        try:
            inputs = self._onnx_session.get_inputs()
            outputs = self._onnx_session.get_outputs()
        except Exception as exc:  # noqa: BLE001 — introspection failure is non-fatal
            logger.warning("SoM ONNX ignored: could not introspect the model (%s).", exc)
            return False

        if len(inputs) != 1:
            logger.warning("SoM ONNX ignored: expected 1 input, found %d.", len(inputs))
            return False
        if not outputs:
            logger.warning("SoM ONNX ignored: the model declares no outputs.")
            return False

        in_shape = list(inputs[0].shape)
        if len(in_shape) != 4:
            logger.warning("SoM ONNX ignored: input rank %d (expected 4, NCHW).", len(in_shape))
            return False

        # Honour static dimensions; symbolic/None ones fall back to 640x640.
        h = in_shape[2] if isinstance(in_shape[2], int) and in_shape[2] > 0 else 640
        w = in_shape[3] if isinstance(in_shape[3], int) and in_shape[3] > 0 else 640
        self._onnx_input_name = inputs[0].name
        self._onnx_input_size = (w, h)

        out_shape = list(outputs[0].shape)
        if len(out_shape) not in (2, 3):
            logger.warning("SoM ONNX ignored: output rank %d (expected 2 or 3).", len(out_shape))
            return False

        # Drop the batch dimension, then require >= 5 channels somewhere
        # (4 box channels + at least one class score).
        candidates = out_shape[1:] if len(out_shape) == 3 else out_shape
        concrete = [d for d in candidates if isinstance(d, int) and d > 0]
        if concrete and min(concrete) < 5:
            logger.warning(
                "SoM ONNX ignored: output shape %s cannot hold box+score channels.", out_shape
            )
            return False
        return True

    def _load_onnx_labels(self) -> list[str]:
        """Resolve the model's class names, or return an empty list if unknown.

        Priority: the model's own ONNX metadata (Ultralytics embeds a ``names``
        mapping), then a ``<model>.labels.txt`` sidecar (one label per line).
        Returning an empty list is deliberate: detections are then named
        generically rather than pretending to know a class the model never told us.
        """
        try:
            meta = self._onnx_session.get_modelmeta().custom_metadata_map or {}
            raw = meta.get("names")
            if raw:
                parsed = ast.literal_eval(raw)
                if isinstance(parsed, dict):
                    return [str(v) for _, v in sorted(parsed.items(), key=lambda kv: int(kv[0]))]
                if isinstance(parsed, (list, tuple)):
                    return [str(v) for v in parsed]
        except Exception as exc:  # noqa: BLE001 — metadata is optional
            logger.debug("SoM ONNX: no usable class metadata (%s).", exc)

        sidecar = self.model_path.with_suffix(".labels.txt")
        try:
            if sidecar.exists():
                lines = [ln.strip() for ln in sidecar.read_text(encoding="utf-8").splitlines()]
                return [ln for ln in lines if ln]
        except Exception as exc:  # noqa: BLE001 — sidecar is optional
            logger.debug("SoM ONNX: could not read %s (%s).", sidecar, exc)

        return []

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

    def model_info(self) -> dict[str, Any]:
        """Diagnostics for the active detector backend (used by tooling and the UI).

        Reports whether the ONNX model was accepted, its input geometry and the
        class names it provides — so a rejected model is visible instead of
        silently degrading to morphology.
        """
        return {
            "model_path": str(self.model_path),
            "model_present": self.model_path.exists(),
            "onnx_loaded": self._onnx_session is not None,
            "input_name": self._onnx_input_name,
            "input_size": self._onnx_input_size,
            "labels": list(self._onnx_labels),
            "backend": "onnx" if self._onnx_session is not None else "morphological",
        }

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
        """Run the ONNX detector and decode its YOLO-style output."""
        if self._onnx_session is None:
            return []

        orig_w, orig_h = img.size
        target_w, target_h = self._onnx_input_size

        resized = img.resize((target_w, target_h), Image.Resampling.BILINEAR)
        arr = np.array(resized).astype(np.float32) / 255.0

        # Channels-first format (1, 3, H, W)
        if arr.ndim == 3 and arr.shape[2] == 3:
            arr = np.transpose(arr, (2, 0, 1))
        tensor = np.expand_dims(arr, axis=0)

        outputs = self._onnx_session.run(None, {self._onnx_input_name: tensor})
        if not outputs:
            return []

        boxes = decode_yolo_outputs(
            # onnxruntime returns a broad union (ndarray | SparseTensor | list | dict);
            # the decoder expects a dense tensor, so normalise it at the boundary.
            np.asarray(outputs[0]),
            input_w=target_w,
            input_h=target_h,
            orig_w=orig_w,
            orig_h=orig_h,
            labels=self._onnx_labels,
        )
        return apply_nms(boxes, iou_threshold=0.35)[:max_elements]


class DesktopSoM:
    """Desktop Set-of-Mark (SoM) Visual Grounding and Coordinate Dispatcher."""

    _instance: DesktopSoM | None = None
    _instance_lock = threading.Lock()

    #: A marked map is only trustworthy while the screen still looks the same.
    #: Acting on stale coordinates silently clicks the wrong place, so the map
    #: expires and the caller is told to re-inspect instead.
    DEFAULT_MAX_AGE_S = 25.0

    def __init__(self, artifacts_dir: Path | None = None) -> None:
        self.artifacts_dir = artifacts_dir or (Path.cwd() / ".avrora" / "artifacts" / "screenshots")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.detector = VisualElementDetector()
        self._active_boxes: dict[int, dict[str, Any]] = {}
        self._boxes_ts: float = 0.0
        self._boxes_rect: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._state_lock = threading.RLock()
        self._vision_engine: Any = None

    @classmethod
    def get_instance(cls) -> DesktopSoM:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ------------------------------------------------------------------
    # Capture stabilization
    # ------------------------------------------------------------------
    def _stabilize_capture(
        self,
        capture_fn: Any,
        attempts: int = 4,
        interval: float = 0.15,
    ) -> tuple[dict[str, Any], Image.Image]:
        """Capture until two consecutive frames are identical.

        Windows composites asynchronously: capturing right after focusing a
        window often grabs a half-painted frame, and the detector then labels
        controls that are about to move. Waiting for a stable perceptual hash
        removes that whole class of mis-grounding.
        """
        from .vision_engine import VisionEngine

        prev_hash: int | None = None
        cap: dict[str, Any] = {}
        img: Image.Image | None = None
        for attempt in range(max(1, attempts)):
            cap = capture_fn()
            img = Image.open(cap["path"]).convert("RGB")
            digest = VisionEngine.compute_dhash(img)
            if prev_hash is not None and digest == prev_hash:
                return cap, img
            prev_hash = digest
            if attempt < attempts - 1:
                time.sleep(interval)
        return cap, img if img is not None else Image.new("RGB", (1, 1))

    def _next_capture_rect(self) -> tuple[int, int, int, int]:
        """Screen rectangle the last marked map was captured from."""
        with self._state_lock:
            return self._boxes_rect

    def inspect(
        self,
        target: str = "active",
        max_elements: int = 30,
        monitor: int | None = None,
        ocr_labels: bool = True,
    ) -> dict[str, Any]:
        """Capture screen/window, detect controls (UIA + Vision), stamp visual marks, and build interactive map.

        ``ocr_labels`` names CV-detected controls by reading their text. It costs
        roughly one full OCR pass (~4-6 s on a loaded CPU), so callers that only
        need geometry can switch it off; UIA-named controls are unaffected either
        way because they arrive with their labels from the accessibility tree.
        """
        from .gui_driver import GUIDriver
        from .screen_vision import ScreenVision

        vision = ScreenVision(artifacts_dir=self.artifacts_dir.parent)
        gui = GUIDriver()

        # 1. Capture target window or full screen (waiting for a stable frame)
        if target.lower() in ("screen", "desktop", "fullscreen"):
            cap, img = self._stabilize_capture(lambda: vision.capture_screen(monitor_idx=monitor))
            # Virtual-screen captures can have a non-zero origin (a monitor left
            # of / above the primary one gives negative offsets). Using 0,0 here
            # shifted every click. Honour the real origin.
            base_x, base_y = int(cap.get("left", 0)), int(cap.get("top", 0))
            title = "Desktop"
        else:
            cap, img = self._stabilize_capture(lambda: vision.capture_window(target=target))
            base_x, base_y = int(cap.get("left", 0)), int(cap.get("top", 0))
            title = cap.get("title", "Active Window")

        w, h = img.size

        # 2. Extract UI elements via Windows UIAutomation (UIA)
        #
        # CRITICAL: ``GUIDriver.inspect_controls`` returns a dict payload
        # (``{"status", "controls", "count", "window"}``), not a bare list. The
        # original ``isinstance(raw_ctrls, list)`` check therefore rejected every
        # real result and left ``detected_controls`` empty, silently disabling the
        # entire UIA channel: all grounding fell back to the name-less
        # morphological detector. Accept both shapes.
        detected_controls: list[Any] = []
        try:
            raw_ctrls = gui.inspect_controls(
                window_title=title if target != "active" else "",
                max_controls=max_elements,
            )
            if isinstance(raw_ctrls, list):
                detected_controls = raw_ctrls
            elif isinstance(raw_ctrls, dict):
                controls = raw_ctrls.get("controls")
                if isinstance(controls, list):
                    detected_controls = controls
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

        # 4b. Semantic labelling via OCR.
        # The geometric detector only knows shapes, so canvas/custom controls used
        # to be reported as «VisualBox (640, 300)» — impossible to choose between.
        # Matching one OCR pass to the boxes turns them into «Button «Guardar»»,
        # which is what makes the map usable on ANY application. Switchable because
        # that pass is the dominant cost of an inspection.
        if ocr_labels:
            started = time.perf_counter()
            self._label_visual_boxes_with_ocr(img, visual_boxes)
            logger.info(
                "som_inspect: OCR labelling took %.2fs for %d visual box(es)",
                time.perf_counter() - started,
                len(visual_boxes),
            )

        # 4c. Collapse nested detections of the same control. The detector finds both
        # a button's border and the glyphs inside it; IoU between them is too low for
        # NMS, so without this pass the map listed every labelled control twice (once
        # as a real «Button», once as a misclassified «Input/Field»).
        visual_boxes = merge_contained_boxes(visual_boxes)
        for vb in visual_boxes:
            vb["screen_cx"] = base_x + vb["x"] + vb["w"] // 2
            vb["screen_cy"] = base_y + vb["y"] + vb["h"] // 2

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
        with self._state_lock:
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

        # Record provenance: the marked map is only valid for this screen state.
        with self._state_lock:
            self._boxes_rect = (base_x, base_y, w, h)
            self._boxes_ts = time.time()

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
            "rect": {"left": base_x, "top": base_y, "width": w, "height": h},
            "summary": f"{header}\n\n{formatted_map}",
        }

    def _get_vision_engine(self) -> Any:
        """Lazy, shared VisionEngine (avoids reloading the ONNX sessions per call)."""
        if self._vision_engine is None:
            from .vision_engine import VisionEngine

            self._vision_engine = VisionEngine()
        return self._vision_engine

    @staticmethod
    def _assign_text_to_box(box: dict[str, Any], regions: list[dict[str, Any]]) -> str:
        """Join the OCR fragments whose centre lies inside ``box``, in reading order.

        Centre containment is used rather than full containment so a label that
        slightly overflows its control (common with tight padding and anti-aliased
        glyphs) is still attributed correctly.
        """
        bx, by = int(box["x"]), int(box["y"])
        bw, bh = int(box["w"]), int(box["h"])
        bx2, by2 = bx + bw, by + bh

        picked: list[dict[str, Any]] = []
        for region in regions:
            cx = region["x"] + region["w"] / 2.0
            cy = region["y"] + region["h"] / 2.0
            if bx <= cx <= bx2 and by <= cy <= by2:
                picked.append(region)

        if not picked:
            return ""
        picked.sort(key=lambda r: (r["y"] // 12, r["x"]))
        return " ".join(r["text"] for r in picked).strip()

    def _label_visual_boxes_with_ocr(
        self, img: Image.Image, boxes: list[dict[str, Any]], limit: int = 60
    ) -> None:
        """Name geometry-only controls by matching a single OCR pass to their boxes.

        Previous implementation OCR-ed each control's crop separately, which costs
        a full OCR invocation per control — measured at roughly a second each on
        CPU regardless of crop size, so a busy screen spent ~22 s inside
        ``som_inspect``. Passing the whole frame once and assigning fragments by
        geometry is 1 call instead of N, labels controls whose caption falls on a
        border that no crop would have captured, and removes the artificial cap on
        how many controls can be named.

        ``limit`` now caps only the labelling work per box (a cheap pure-Python
        containment test), not OCR invocations.
        """
        if not boxes:
            return
        engine = self._get_vision_engine()
        try:
            regions = engine.ocr_regions(img)
        except Exception as exc:  # noqa: BLE001 — labelling is best-effort
            logger.debug("OCR labelling skipped: %s", exc)
            return
        if not regions:
            return

        for box in boxes[: max(0, limit)]:
            try:
                if int(box.get("w", 0)) < 6 or int(box.get("h", 0)) < 6:
                    continue
                text = self._assign_text_to_box(box, regions)
                if text:
                    box["name"] = text[:60]
                    box["label_source"] = "ocr"
                    box["confidence"] = min(0.95, float(box.get("confidence", 0.7)) + 0.1)
            except Exception as exc:  # noqa: BLE001 — labelling is best-effort
                logger.debug("OCR labelling failed for one box: %s", exc)

    # ------------------------------------------------------------------
    # Freshness & validity guards
    # ------------------------------------------------------------------
    def _assert_fresh(self, max_age: float | None = None) -> str | None:
        """Return an error string when the marked map can no longer be trusted.

        Clicking coordinates captured from an older screen state is the worst
        failure mode of visual automation: it silently activates the wrong
        control instead of reporting a problem.
        """
        with self._state_lock:
            if not self._active_boxes:
                return "[som error] No hay mapa SoM activo. Ejecuta primero action='som_inspect'."
            age = time.time() - self._boxes_ts
        limit = self.DEFAULT_MAX_AGE_S if max_age is None else max_age
        if age > limit:
            return (
                f"[som error] El mapa SoM tiene {age:.0f}s (límite {limit:.0f}s) y puede estar obsoleto. "
                "Ejecuta action='som_inspect' para recapturar antes de actuar."
            )
        return None

    def _invalidate_boxes(self) -> None:
        """Drop the marked map: any interaction may have changed the screen."""
        with self._state_lock:
            self._active_boxes.clear()
            self._boxes_ts = 0.0

    def _validate_point(self, x: int, y: int) -> str | None:
        """Reject coordinates outside every physical monitor."""
        try:
            from .window_tools import WindowOps

            monitors = WindowOps().get_monitors()
            if not monitors:
                return None
            for m in monitors:
                if m["left"] <= x < m["right"] and m["top"] <= y < m["bottom"]:
                    return None
            return f"[som error] La coordenada ({x}, {y}) está fuera de todos los monitores."
        except Exception as exc:  # noqa: BLE001 — validation is best-effort
            logger.debug("Point validation failed: %s", exc)
            return None

    def find_box(self, text: str, fuzzy: bool = True) -> dict[str, Any]:
        """Locate a marked element by its visible label instead of its number.

        Lets the model ask for «Guardar» or «Aceptar» directly, which is far more
        natural (and far more robust) than memorising numeric ids between turns.
        """
        needle = (text or "").strip().lower()
        if not needle:
            return {"error": "empty search text"}

        with self._state_lock:
            snapshot = dict(self._active_boxes)

        scored: list[tuple[float, int, dict[str, Any]]] = []
        for box_id, box in snapshot.items():
            hay = str(box.get("name", "")).lower()
            if not hay:
                continue
            if needle == hay:
                scored.append((1.0, box_id, box))
                continue
            if needle in hay:
                scored.append((0.92, box_id, box))
                continue
            if fuzzy:
                ratio = difflib.SequenceMatcher(None, needle, hay).ratio()
                if ratio >= 0.6:
                    scored.append((ratio, box_id, box))

        if not scored:
            names = [b.get("name") for b in snapshot.values()][:15]
            return {"error": f"no element matching «{text}»", "available": names}

        scored.sort(key=lambda item: item[0], reverse=True)
        score, box_id, box = scored[0]
        return {
            "box_id": box_id,
            "name": box.get("name"),
            "control_type": box.get("control_type"),
            "score": round(score, 2),
            "screen_cx": box.get("screen_cx"),
            "screen_cy": box.get("screen_cy"),
            "alternatives": [
                {"box_id": bid, "name": bx.get("name"), "score": round(sc, 2)}
                for sc, bid, bx in scored[1:4]
            ],
        }

    def wait_for_change(self, timeout: float = 6.0, interval: float = 0.4, target: str = "active") -> dict[str, Any]:
        """Block until the watched surface stops changing (or timeout elapses).

        Essential after actions that open menus, dialogs or load content: acting
        again before the UI settles is what produces mismatched coordinates.
        """
        from .screen_vision import ScreenVision
        from .vision_engine import VisionEngine

        vision = ScreenVision(artifacts_dir=self.artifacts_dir.parent)
        deadline = time.time() + max(0.5, float(timeout))

        def _sample() -> int:
            if target not in ("screen", "desktop"):
                cap = vision.capture_window(target=target)
            else:
                cap = vision.capture_screen()
            return VisionEngine.compute_dhash(Image.open(cap["path"]).convert("RGB"))

        baseline = _sample()
        while time.time() < deadline:
            time.sleep(max(0.05, interval))
            current = _sample()
            if current != baseline:
                return {"changed": True, "elapsed": round(timeout - (deadline - time.time()), 2)}
        return {"changed": False, "elapsed": round(timeout, 2)}

    def _format_click_result(
        self,
        box_id: int,
        name: str,
        cx: int,
        cy: int,
        raw: str,
        changed: bool | None = None,
    ) -> str:
        """Human/LLM-readable outcome, including whether the screen reacted."""
        feedback = ""
        if changed is True:
            feedback = " Pantalla actualizada: la acción tuvo efecto."
        elif changed is False:
            feedback = " La pantalla no cambió: verifica el objetivo antes de reintentar."
        return f"[som] Clic ejecutado en Box [{box_id}] «{name}» coordenadas ({cx}, {cy}) -> {raw}.{feedback}"

    def click_box(self, box_id: int, click_type: str = "click", verify: bool = True) -> str:
        """Click the center of the specified Set-of-Mark box ID."""
        stale = self._assert_fresh()
        if stale:
            return stale

        with self._state_lock:
            box = self._active_boxes.get(box_id)
        if box is None:
            return f"[som error] Box [{box_id}] no encontrado. IDs activos: {list(self._active_boxes.keys())[:10]}..."

        cx, cy = int(box["screen_cx"]), int(box["screen_cy"])
        name = box["name"]

        out_of_bounds = self._validate_point(cx, cy)
        if out_of_bounds:
            return out_of_bounds

        from .window_tools import WindowOps

        wops = WindowOps()

        if click_type == "double":
            res = wops.click_at(cx, cy, double=True)
        elif click_type == "right":
            res = wops.click_at(cx, cy, button="right")
        else:
            res = wops.click_at(cx, cy, button="left")

        # Post-action verification: did the UI actually react? Without this the
        # agent cannot tell a successful click from one that landed on nothing.
        changed: bool | None = None
        if verify:
            try:
                changed = bool(self.wait_for_change(timeout=2.5, interval=0.3).get("changed"))
            except Exception as exc:  # noqa: BLE001 — verification is best-effort
                logger.debug("Post-click verification failed: %s", exc)

        # Any interaction can move, rename or destroy controls: drop the map so
        # the next action must re-inspect instead of trusting stale numbers.
        self._invalidate_boxes()
        return self._format_click_result(box_id, name, cx, cy, res, changed)

    def type_box(
        self,
        box_id: int,
        text: str,
        clear_first: bool = True,
        submit: bool = False,
        verify: bool = False,
    ) -> str:
        """Focus the specified Set-of-Mark box and type text into it."""
        stale = self._assert_fresh()
        if stale:
            return stale

        with self._state_lock:
            box = self._active_boxes.get(box_id)
        if box is None:
            return f"[som error] Box [{box_id}] no encontrado. IDs activos: {list(self._active_boxes.keys())[:10]}..."

        cx, cy = int(box["screen_cx"]), int(box["screen_cy"])
        name = box["name"]

        out_of_bounds = self._validate_point(cx, cy)
        if out_of_bounds:
            return out_of_bounds

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

        # Typing usually mutates the layout (autocomplete, validation, focus
        # shift), so the previous map is no longer trustworthy.
        self._invalidate_boxes()
        return f"[som] Texto escrito en Box [{box_id}] «{name}» ({cx}, {cy}): «{text}» -> {type_res}"

    def hover_box(self, box_id: int) -> str:
        """Hover cursor over the center of the specified Set-of-Mark box ID."""
        stale = self._assert_fresh()
        if stale:
            return stale
        with self._state_lock:
            box = self._active_boxes.get(box_id)
        if box is None:
            available = list(self._active_boxes.keys())
            return f"[som error] Box [{box_id}] no encontrado. IDs activos: {available[:10]}..."

        cx, cy = box["screen_cx"], box["screen_cy"]
        name = box["name"]

        try:
            import ctypes

            ctypes.windll.user32.SetCursorPos(int(cx), int(cy))
            return f"[som] Cursor posicionado sobre Box [{box_id}] «{name}» en ({cx}, {cy})"
        except Exception as e:
            return f"[som error] Error al mover cursor a Box [{box_id}]: {e}"

    def get_box(self, box_id: int) -> dict[str, Any] | None:
        """Retrieve box metadata dictionary for the given ID."""
        with self._state_lock:
            return self._active_boxes.get(box_id)

    def get_active_boxes(self) -> dict[int, dict[str, Any]]:
        """Return a copy of all currently active labeled boxes."""
        with self._state_lock:
            return dict(self._active_boxes)

class ScreenMarker:
    """Backward compatibility adapter for WIS abilities."""
    def __init__(self):
        self.som = DesktopSoM.get_instance()
    
    def annotate_screen(self):
        res = self.som.inspect(target="desktop")
        return res["annotated_path"], res.get("text_map", "")
