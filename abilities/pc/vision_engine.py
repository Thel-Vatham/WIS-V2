"""Ultra-Fast CPU-Native Vision & Multimodal Engine for AVRORA.

Performs deep neural visual feature recognition (CLIP-ViT ONNX), geometric shape
detection (OpenCV), dominant color analysis, and on-screen text/subtitle extraction
(RapidOCR ONNX) in strictly < 2.0 seconds on CPU without dedicated GPU VRAM.
Includes 64-bit difference hash (dHash) perceptual frame caching (<0.3 ms on static screens).
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

logger = logging.getLogger("AVRORA.PC.VisionEngine")

# Visual semantic taxonomy for Zero-Shot Neural Recognition
_VISUAL_TAXONOMY = [
    ("Escena de anime, animación japonesa o caricatura 2D", "an anime scene, 2d japanese animation or animated cartoon"),
    ("Reproductor de video o película en pantalla", "a video player, media player interface or movie playing on screen"),
    ("Entorno de desarrollo de software, editor de código o terminal", "a software development code editor, ide, terminal or programming code"),
    ("Navegador web o página de internet", "a web browser with internet pages, search results or web articles"),
    ("Videojuego o gráficos 3D interactivos", "a 3d video game with gameplay graphics or gaming interface"),
    ("Diálogo de error del sistema, advertencia o alerta", "a system error dialog, warning popup window or crash alert message"),
    ("Documento de texto, hoja de cálculo o reporte", "a text document, spreadsheet table or pdf report"),
    ("Foto de personas, rostros o personajes", "a photograph of people, human faces or portraits"),
    ("Foto o ilustración de animal (perro, gato, fauna)", "a photograph or illustration of an animal, dog, cat or wildlife"),
    ("Paisaje natural, exteriores, bosque o cielo", "a natural landscape, outdoor nature scene, mountains, forest or sky"),
    ("Diagrama, formas geométricas, gráficos o círculos", "geometric shapes, circle, flowchart diagram or infographic chart"),
]


class VisionEngine:
    """CPU-native multimodal perception and deep visual analysis engine."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ocr_engine: Any = None
        self._clip_vision: Any = None
        self._clip_text: Any = None
        self._cached_txt_embeddings: np.ndarray | None = None
        self._last_frame_hash: int | None = None
        self._last_frame_result: dict[str, Any] | None = None

    @staticmethod
    def compute_dhash(img: Image.Image) -> int:
        """Compute fast 64-bit difference hash (dHash) for screen frame comparison (<0.3ms)."""
        resized = img.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
        pixels = list(np.array(resized).flatten())
        diff = []
        for row in range(8):
            row_start = row * 9
            for col in range(8):
                diff.append(pixels[row_start + col] > pixels[row_start + col + 1])
        hash_val = 0
        for bit in diff:
            hash_val = (hash_val << 1) | int(bit)
        return hash_val

    def _get_ocr(self) -> Any:
        """Lazy load RapidOCR ONNX engine with thread safety and diagnostic logging."""
        with self._lock:
            if self._ocr_engine is None:
                try:
                    from rapidocr_onnxruntime import RapidOCR
                    self._ocr_engine = RapidOCR()
                except Exception as exc:
                    logger.warning("RapidOCR load failed: %s. Continuing without OCR.", exc)
                    self._ocr_engine = False
            return self._ocr_engine if self._ocr_engine is not False else None

    def _get_clip(self) -> tuple[Any, np.ndarray | None]:
        """Lazy load CLIP ONNX Vision Transformer and pre-cached taxonomy embeddings."""
        with self._lock:
            if self._clip_vision is None:
                try:
                    from fastembed import ImageEmbedding, TextEmbedding

                    self._clip_vision = ImageEmbedding(model_name="Qdrant/clip-ViT-B-32-vision")
                    txt_model = TextEmbedding(model_name="Qdrant/clip-ViT-B-32-text")

                    # Precompute text embeddings for taxonomy
                    english_prompts = [p[1] for p in _VISUAL_TAXONOMY]
                    raw_embs = np.array(list(txt_model.embed(english_prompts)))
                    norms = np.linalg.norm(raw_embs, axis=1, keepdims=True)
                    norms[norms == 0] = 1.0
                    self._cached_txt_embeddings = raw_embs / norms
                except Exception as exc:
                    logger.warning("CLIP load failed: %s. Degrading to geometry-only vision.", exc)
                    self._clip_vision = False
                    self._cached_txt_embeddings = None
            return self._clip_vision if self._clip_vision is not False else None, self._cached_txt_embeddings

    # ------------------------------------------------------------------
    # Main Analysis Pipeline (< 2.0s SLA on CPU)
    # ------------------------------------------------------------------
    def analyze_image(
        self,
        image_input: str | Path | Image.Image,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Perform full multimodal visual analysis on CPU in under 2.0 seconds."""
        t_start = time.perf_counter()

        # 1. Normalize image to PIL Image and NumPy RGB array
        if isinstance(image_input, (str, Path)):
            pil_img = Image.open(str(image_input)).convert("RGB")
        elif isinstance(image_input, Image.Image):
            pil_img = image_input.convert("RGB")
        else:
            raise ValueError(f"Unsupported image input type: {type(image_input)}")

        w, h = pil_img.size
        rgb_arr = np.array(pil_img)

        # Check perceptual difference hash for 0ms static screen cache hit
        frame_hash = self.compute_dhash(pil_img)
        if self._last_frame_hash is not None and self._last_frame_result is not None:
            hamming = bin(frame_hash ^ self._last_frame_hash).count("1")
            if hamming <= 2 and not prompt:
                cached_res = dict(self._last_frame_result)
                cached_res["cached"] = True
                cached_res["elapsed_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
                return cached_res

        # 2. Geometric Shape & Color Analysis via OpenCV (~30-80ms)
        shapes_info, colors_info = self._analyze_geometry_and_colors(rgb_arr, w, h)

        # 3. High-Speed On-Screen Text & Subtitle OCR (~300-600ms)
        text_lines, full_text = self._extract_ocr_text(rgb_arr)

        # 4. Deep Neural Visual Feature Classification via CLIP ONNX ViT-B/32 (~50-100ms)
        visual_recognitions = self._classify_visual_features(pil_img)

        # 5. Scene Context Synthesis
        scene_type, scene_confidence = self._infer_scene_type(
            visual_recognitions, text_lines, shapes_info, colors_info
        )

        elapsed_ms = (time.perf_counter() - t_start) * 1000

        # 6. Build Human & LLM-Readable Visual Perception Report
        summary = self._build_summary(
            w=w,
            h=h,
            scene_type=scene_type,
            scene_confidence=scene_confidence,
            visual_recognitions=visual_recognitions,
            shapes=shapes_info,
            colors=colors_info,
            text_lines=text_lines,
            full_text=full_text,
            elapsed_ms=elapsed_ms,
            prompt=prompt,
        )

        result = {
            "elapsed_ms": round((time.perf_counter() - t_start) * 1000, 2),
            "dimensions": {"width": w, "height": h},
            "scene": {"type": scene_type, "confidence": scene_confidence, "features": visual_recognitions},
            "ocr": {"detected": bool(text_lines), "line_count": len(text_lines), "full_text": full_text, "lines": text_lines[:15]},
            "shapes": shapes_info,
            "colors": colors_info,
            "summary": summary,
            "cached": False,
        }
        self._last_frame_hash = frame_hash
        self._last_frame_result = result
        return result

    # ------------------------------------------------------------------
    # Deep Neural Visual Feature Recognition (CLIP ONNX)
    # ------------------------------------------------------------------
    def _classify_visual_features(self, pil_img: Image.Image) -> list[dict[str, Any]]:
        clip_model, txt_embs = self._get_clip()
        if clip_model is None or txt_embs is None:
            return []

        try:
            # Resize image to 224x224 for instant CLIP embedding (<50ms)
            thumb = pil_img.resize((224, 224), Image.Resampling.BILINEAR)
            img_emb = np.array(list(clip_model.embed([thumb]))[0])
            norm = np.linalg.norm(img_emb)
            if norm > 0:
                img_emb = img_emb / norm

            sims = np.dot(txt_embs, img_emb)
            top_indices = np.argsort(-sims)

            results = []
            for idx in top_indices[:4]:
                es_label, _ = _VISUAL_TAXONOMY[idx]
                score = float(sims[idx])
                # Convert cosine similarity (-1 to 1) into relative confidence percentage
                conf_pct = min(99, max(10, int((score + 0.1) * 220)))
                results.append({"label": es_label, "score": round(score, 4), "confidence_pct": conf_pct})
            return results
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Geometric Shape & Color Palette Detection
    # ------------------------------------------------------------------
    def _analyze_geometry_and_colors(
        self, rgb_arr: np.ndarray, width: int, height: int
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        try:
            import cv2

            scale = 1.0
            if width > 1600 or height > 1000:
                scale = 0.5
                proc_img = cv2.resize(rgb_arr, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
            else:
                proc_img = rgb_arr

            bgr = cv2.cvtColor(proc_img, cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)

            # Detect Circles via Hough Transform
            min_r = max(10, int(15 * scale))
            max_r = max(min_r + 10, int(300 * scale))
            circles = cv2.HoughCircles(
                blurred,
                cv2.HOUGH_GRADIENT,
                dp=1.2,
                minDist=int(40 * scale),
                param1=50,
                param2=30,
                minRadius=min_r,
                maxRadius=max_r,
            )
            detected_circles = []
            if circles is not None:
                for c in circles[0][:8]:
                    cx, cy, r = int(c[0] / scale), int(c[1] / scale), int(c[2] / scale)
                    detected_circles.append({"x": cx, "y": cy, "radius": r})

            # Detect Major Rectangular Regions & Circular Contours
            edges = cv2.Canny(blurred, 40, 140)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            detected_rects = []
            min_area = (width * height) * 0.005
            for cnt in contours:
                area = cv2.contourArea(cnt) / (scale * scale)
                if area > min_area:
                    perimeter = cv2.arcLength(cnt, True) / scale
                    if perimeter > 0:
                        circularity = 4 * np.pi * (area / (perimeter * perimeter))
                        if circularity > 0.70 and len(detected_circles) == 0:
                            (circle_x, circle_y), circle_radius = cv2.minEnclosingCircle(cnt)
                            detected_circles.append({"x": int(circle_x / scale), "y": int(circle_y / scale), "radius": int(circle_radius / scale)})
                    x, y, rw, rh = cv2.boundingRect(cnt)
                    detected_rects.append({
                        "x": int(x / scale),
                        "y": int(y / scale),
                        "width": int(rw / scale),
                        "height": int(rh / scale),
                        "area_pct": round((area / (width * height)) * 100, 1),
                    })
            detected_rects.sort(key=lambda r: r["area_pct"], reverse=True)
            detected_rects = detected_rects[:6]

            # Calculate Dominant Colors via Fast K-Means
            pixels = proc_img.reshape(-1, 3).astype(np.float32)
            sample_step = max(1, len(pixels) // 1000)
            sample_pixels = pixels[::sample_step]
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
            _, labels, centers = cv2.kmeans(sample_pixels, 4, None, criteria, 3, cv2.KMEANS_RANDOM_CENTERS)  # type: ignore[call-overload,arg-type]
            counts = np.bincount(labels.flatten())
            total = len(labels)

            dominant_colors = []
            for i in np.argsort(-counts):
                r, g, b = [int(v) for v in centers[i]]
                hex_code = f"#{r:02x}{g:02x}{b:02x}"
                pct = round(float(counts[i] / total) * 100, 1)
                name = self._classify_color_name(r, g, b)
                dominant_colors.append({"name": name, "hex": hex_code, "rgb": [r, g, b], "percentage": pct})

            shapes_info = {
                "circle_count": len(detected_circles),
                "circles": detected_circles,
                "rectangle_count": len(detected_rects),
                "major_regions": detected_rects,
            }
            return shapes_info, dominant_colors

        except Exception:
            # Robust pure NumPy & PIL fallback (zero external C++ dependencies)
            dominant_colors = []
            detected_circles = []
            detected_rects = []
            try:
                pixels = rgb_arr[::max(1, height // 100), ::max(1, width // 100)].reshape(-1, 3)
                quantized = (pixels // 32) * 32
                unique_colors, counts = np.unique(quantized, axis=0, return_counts=True)
                sorted_idx = np.argsort(-counts)
                total = len(pixels)
                for idx in sorted_idx[:4]:
                    mask = np.all(quantized == unique_colors[idx], axis=1)
                    cluster_pixels = pixels[mask]
                    r, g, b = [int(v) for v in np.median(cluster_pixels, axis=0)]
                    hex_code = f"#{r:02x}{g:02x}{b:02x}"
                    pct = round(float(counts[idx] / total) * 100, 1)
                    name = self._classify_color_name(r, g, b)
                    dominant_colors.append({"name": name, "hex": hex_code, "rgb": [r, g, b], "percentage": pct})
            except Exception as _exc:
                logger.debug("Operacion no fatal suprimida: %s", _exc)

            # Detect bounding boxes and shape outlines in pure numpy
            try:
                bg_color = dominant_colors[0]["rgb"] if dominant_colors else [255, 255, 255]
                diff_map = np.sum(np.abs(rgb_arr.astype(int) - bg_color), axis=2) > 40
                if np.any(diff_map):
                    col_proj = np.any(diff_map, axis=0)
                    idxs = np.where(col_proj)[0]
                    if len(idxs) > 0:
                        splits = np.where(np.diff(idxs) > 5)[0]
                        seg_starts = [idxs[0]] + [idxs[s + 1] for s in splits]
                        seg_ends = [idxs[s] for s in splits] + [idxs[-1]]

                        for cmin, cmax in zip(seg_starts, seg_ends, strict=True):
                            sub_diff = diff_map[:, cmin : cmax + 1]
                            row_proj = np.any(sub_diff, axis=1)
                            row_idxs = np.where(row_proj)[0]
                            if len(row_idxs) == 0:
                                continue
                            rmin, rmax = row_idxs[0], row_idxs[-1]
                            box_w = int(cmax - cmin)
                            box_h = int(rmax - rmin)
                            if box_w < 10 or box_h < 10:
                                continue

                            aspect = box_w / max(1, box_h)
                            area = box_w * box_h
                            sub_fill = np.mean(sub_diff[rmin : rmax + 1, :])

                            # A circle has aspect ~ 1.0 and fill ~ pi/4 (0.75 - 0.85)
                            if 0.75 <= aspect <= 1.35 and 0.55 <= sub_fill <= 0.88:
                                detected_circles.append({
                                    "x": int((cmin + cmax) / 2),
                                    "y": int((rmin + rmax) / 2),
                                    "radius": int(box_w / 2),
                                })
                            else:
                                detected_rects.append({
                                    "x": int(cmin),
                                    "y": int(rmin),
                                    "width": int(box_w),
                                    "height": int(box_h),
                                    "area_pct": round((area / (width * height)) * 100, 1),
                                })
            except Exception as _exc:
                logger.debug("Operacion no fatal suprimida: %s", _exc)

            return {
                "circle_count": len(detected_circles),
                "circles": detected_circles,
                "rectangle_count": len(detected_rects),
                "major_regions": detected_rects,
            }, dominant_colors

    # ------------------------------------------------------------------
    # RapidOCR ONNX Text & Subtitle Extraction
    # ------------------------------------------------------------------
    def _extract_ocr_text(self, rgb_arr: np.ndarray, pil_img: Image.Image | None = None) -> tuple[list[str], str]:
        ocr = self._get_ocr()
        if ocr is not None:
            try:
                result, _ = ocr(rgb_arr)
                if result:
                    lines = []
                    for item in result:
                        if len(item) >= 2 and item[1]:
                            txt = str(item[1]).strip()
                            score = float(item[2]) if len(item) >= 3 else 1.0
                            if score >= 0.4 and len(txt) > 0:
                                lines.append(txt)
                    if lines:
                        return lines, "\n".join(lines)
            except Exception as _exc:
                logger.debug("Operacion no fatal suprimida: %s", _exc)

        return [], ""

    # ------------------------------------------------------------------
    # Semantic Scene Classification
    # ------------------------------------------------------------------
    def _infer_scene_type(
        self,
        visual_recognitions: list[dict[str, Any]],
        text_lines: list[str],
        shapes: dict[str, Any],
        colors: list[dict[str, Any]],
    ) -> tuple[str, int]:
        combined_text = " ".join(text_lines).lower()

        # If CLIP neural recognition has high confidence, use it
        if visual_recognitions and visual_recognitions[0]["confidence_pct"] >= 65:
            top_rec = visual_recognitions[0]
            return top_rec["label"], top_rec["confidence_pct"]

        # Text-based overrides
        anime_keywords = ["mushoku", "episode", "episodio", "capitulo", "reproductor", "media player", "vlc", "sub", "raw", "mkv", "mp4"]
        if any(k in combined_text for k in anime_keywords):
            return "Reproductor de Video / Serie Anime", 95

        code_keywords = ["def ", "class ", "import ", "function", "const ", "vscode", "antigravity", "terminal", "powershell", "python", "git"]
        if any(k in combined_text for k in code_keywords):
            return "Editor de Código / Entorno de Desarrollo (IDE)", 92

        if shapes.get("circle_count", 0) > 0:
            return "Diagrama Visual / Formas Geométricas", 85

        return "Escritorio / Ventana de Windows", 75

    def _classify_color_name(self, r: int, g: int, b: int) -> str:
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        if brightness < 40:
            return "Oscuro / Negro"
        if brightness > 220 and max(r, g, b) - min(r, g, b) < 20:
            return "Blanco / Claro"
        if max(r, g, b) - min(r, g, b) < 25:
            return "Gris"

        if r > g and r > b:
            return "Rojo / Cálido" if r > (g + b) * 0.7 else "Naranja / Marrón"
        if g > r and g > b:
            return "Verde"
        if b > r and b > g:
            return "Azul"
        if r > 150 and g > 150 and b < 100:
            return "Amarillo"
        if r > 120 and b > 120 and g < 100:
            return "Morado / Magenta"
        return "Color Mixto"

    # ------------------------------------------------------------------
    # Summary Synthesizer
    # ------------------------------------------------------------------
    def _build_summary(
        self,
        w: int,
        h: int,
        scene_type: str,
        scene_confidence: int,
        visual_recognitions: list[dict[str, Any]],
        shapes: dict[str, Any],
        colors: list[dict[str, Any]],
        text_lines: list[str],
        full_text: str,
        elapsed_ms: float,
        prompt: str = "",
    ) -> str:
        lines = [
            f"[vision:cpu] Análisis visual neuronal completado en {elapsed_ms:.1f}ms ({w}x{h} px)",
            f"• Escena principal: {scene_type} (Confianza: {scene_confidence}%)",
        ]

        # Deep Neural Visual Features (CLIP)
        if visual_recognitions:
            top_items = [f"{r['label']} ({r['confidence_pct']}%)" for r in visual_recognitions[:3]]
            lines.append(f"• Reconocimiento de contenido visual: {', '.join(top_items)}")

        # Shapes
        c_count = shapes.get("circle_count", 0)
        r_count = shapes.get("rectangle_count", 0)
        if c_count > 0 or r_count > 0:
            shape_parts = []
            if c_count > 0:
                shape_parts.append(f"{c_count} círculo(s)")
            if r_count > 0:
                shape_parts.append(f"{r_count} región(es) rectangular(es)/ventanas")
            lines.append(f"• Formas y regiones: {', '.join(shape_parts)}")

        # Colors
        if colors:
            palette = ", ".join(f"{c['name']} ({c['percentage']}%)" for c in colors[:3])
            lines.append(f"• Paleta de color: {palette}")

        # Text & Subtitles — send ALL lines so the LLM has full page/video context
        if text_lines:
            snippet = "\n    ".join(text_lines)
            lines.append(f"• Texto y subtítulos detectados ({len(text_lines)} líneas):\n    {snippet}")
        else:
            lines.append("• Texto: No se detectaron líneas de texto destacadas.")

        return "\n".join(lines)
