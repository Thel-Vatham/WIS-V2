"""
WIS Live Object Detector v2  --  Multi-objeto en vivo
=====================================================
Detector de objetos en tiempo real usando **YOLOv4-tiny (COCO 80 clases)**.

A diferencia de la version anterior (MobileNet-SSD / VOC-20), este modelo SI
conoce clases como: cell phone (celular), bottle (botella), cup (vaso),
laptop, keyboard, mouse, book, clock, scissors, backpack, chair, tv, etc.

Caracteristicas:
  * Detecta VARIOS objetos a la vez (no solo uno).
  * NMS para eliminar cajas duplicadas.
  * Tracker por IoU -> etiquetas estables, sin parpadeo.
  * Panel lateral con la lista de objetos y su conteo.
  * Voz en espanol cuando aparece un objeto nuevo (te dice QUE es).
  * Aviso en consola cuando aparece un objeto nuevo.

Controles:
    Q / ESC ...... salir
    S ............ guardar captura (con cajas) en snapshots/
    ESPACIO ...... pausar / reanudar
    [ / ] ........ bajar / subir el umbral de confianza
    - / + ........ bajar / subir la resolucion de entrada (320/448/608)
    V ............ activar / desactivar la voz
    P ............ activar / desactivar el panel lateral
    O ............ modo "objeto generico" (contornos) para cosas que el
                   modelo no conoce (ej. un boligrafo)
"""

import os
import sys
import time
import argparse
import datetime
import threading
import subprocess

import cv2 as cv
import numpy as np

# ----------------------------------------------------------------------
# Rutas y modelo
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_FILE = os.path.join(BASE_DIR, "yolov4-tiny.cfg")
WEIGHTS_FILE = os.path.join(BASE_DIR, "yolov4-tiny.weights")
NAMES_FILE = os.path.join(BASE_DIR, "coco.names")
SNAP_DIR = os.path.join(BASE_DIR, "snapshots")

if not os.path.isfile(NAMES_FILE):
    raise SystemExit(f"[WIS] Falta el archivo de clases: {NAMES_FILE}")

with open(NAMES_FILE, "r", encoding="utf-8") as _f:
    CLASSES = [line.strip() for line in _f if line.strip()]

# Nombres en espanol para las clases mas comunes
ES_NAMES = {
    "person": "persona", "bicycle": "bicicleta", "car": "carro", "motorcycle": "moto",
    "airplane": "avion", "bus": "autobus", "train": "tren", "truck": "camion",
    "boat": "barco", "bench": "banca", "bird": "pajaro", "cat": "gato",
    "dog": "perro", "horse": "caballo", "sheep": "oveja", "cow": "vaca",
    "elephant": "elefante", "bear": "oso", "zebra": "cebra", "giraffe": "jirafa",
    "backpack": "mochila", "umbrella": "paraguas", "handbag": "bolso",
    "suitcase": "maleta", "bottle": "botella", "wine glass": "copa",
    "cup": "vaso", "fork": "tenedor", "knife": "cuchillo", "spoon": "cuchara",
    "bowl": "tazon", "banana": "banano", "apple": "manzana", "sandwich": "sandwich",
    "orange": "naranja", "pizza": "pizza", "donut": "dona", "cake": "pastel",
    "chair": "silla", "couch": "sofa", "potted plant": "planta",
    "bed": "cama", "dining table": "mesa", "toilet": "inodoro", "tv": "televisor",
    "laptop": "laptop", "mouse": "mouse", "remote": "control", "keyboard": "teclado",
    "cell phone": "celular", "microwave": "microondas", "oven": "horno",
    "toaster": "tostadora", "sink": "lavamanos", "refrigerator": "nevera",
    "book": "libro", "clock": "reloj", "vase": "florero", "scissors": "tijeras",
    "teddy bear": "peluche", "hair drier": "secador", "toothbrush": "cepillo",
}

# Colores deterministas por clase (BGR)
_RNG = np.random.default_rng(7)
COLORS = _RNG.integers(60, 255, size=(len(CLASSES), 3)).tolist()

SIZES = (320, 448, 608)          # resoluciones de entrada ciclicas
NMS_THRESHOLD = 0.40


def es_label(name):
    """Nombre en espanol si existe, si no el original."""
    return ES_NAMES.get(name, name)


# ----------------------------------------------------------------------
# Modelo
# ----------------------------------------------------------------------
def load_net():
    """Carga YOLOv4-tiny con el backend DNN de OpenCV."""
    for path in (CFG_FILE, WEIGHTS_FILE):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Falta el archivo del modelo: {path}")
    if not hasattr(cv.dnn, "readNetFromDarknet"):
        raise RuntimeError("Esta build de OpenCV no tiene readNetFromDarknet.")
    net = cv.dnn.readNetFromDarknet(CFG_FILE, WEIGHTS_FILE)
    net.setPreferableBackend(cv.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv.dnn.DNN_TARGET_CPU)
    return net


def detect(net, out_names, frame, conf_threshold, input_size, nms=NMS_THRESHOLD):
    """
    Corre la deteccion sobre un frame BGR.
    Devuelve lista de (label_en, confianza, (x, y, w, h)).
    """
    h, w = frame.shape[:2]
    blob = cv.dnn.blobFromImage(frame, 1 / 255.0, (input_size, input_size),
                                swapRB=True, crop=False)
    net.setInput(blob)
    outputs = net.forward(out_names)

    boxes, confs, class_ids = [], [], []
    for out in outputs:
        for det in out:
            scores = det[5:]
            cid = int(np.argmax(scores))
            conf = float(scores[cid])
            if conf < conf_threshold:
                continue
            cx, cy, bw, bh = det[0] * w, det[1] * h, det[2] * w, det[3] * h
            x = int(cx - bw / 2)
            y = int(cy - bh / 2)
            boxes.append([x, y, int(bw), int(bh)])
            confs.append(conf)
            class_ids.append(cid)

    if not boxes:
        return []

    keep = cv.dnn.NMSBoxes(boxes, confs, conf_threshold, nms)
    results = []
    if len(keep) > 0:
        for i in np.array(keep).flatten():
            x, y, bw, bh = boxes[i]
            x = max(0, min(x, w - 1))
            y = max(0, min(y, h - 1))
            bw = max(1, min(bw, w - x))
            bh = max(1, min(bh, h - y))
            results.append((CLASSES[class_ids[i]], confs[i], (x, y, bw, bh)))
    return results


# ----------------------------------------------------------------------
# Tracker simple por IoU (etiquetas estables, sin parpadeo)
# ----------------------------------------------------------------------
def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


class Tracker:
    """Asigna IDs estables a las detecciones y marca las nuevas."""

    def __init__(self, iou_thr=0.30, max_missing=6):
        self.iou_thr = iou_thr
        self.max_missing = max_missing
        self.tracks = {}          # id -> dict(label, box, missing, conf, seen)
        self.next_id = 1

    def update(self, detections):
        for t in self.tracks.values():
            t["missing"] += 1

        used = set()
        out = []
        for label, conf, box in detections:
            best_id, best_iou = None, self.iou_thr
            for tid, t in self.tracks.items():
                if tid in used or t["label"] != label:
                    continue
                v = iou(box, t["box"])
                if v >= best_iou:
                    best_id, best_iou = tid, v
            if best_id is None:
                tid = self.next_id
                self.next_id += 1
                self.tracks[tid] = {"label": label, "box": box, "missing": 0,
                                    "conf": conf, "seen": 1}
                is_new = True
            else:
                tid = best_id
                self.tracks[tid]["box"] = box
                self.tracks[tid]["missing"] = 0
                self.tracks[tid]["conf"] = conf
                self.tracks[tid]["seen"] += 1
                is_new = False
            used.add(tid)
            out.append((tid, label, conf, box, is_new))

        for tid in [t for t, v in self.tracks.items() if v["missing"] > self.max_missing]:
            del self.tracks[tid]
        return out


# ----------------------------------------------------------------------
# Deteccion de "objeto generico" (para lo que el modelo no conoce)
# ----------------------------------------------------------------------
def detect_generic(gray, min_area=2500, max_boxes=6):
    """Contornos grandes = objetos sin nombre conocido (ej. un boligrafo)."""
    blur = cv.GaussianBlur(gray, (5, 5), 0)
    edges = cv.Canny(blur, 45, 140)
    edges = cv.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv.findContours(edges, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    found = []
    for c in contours:
        area = cv.contourArea(c)
        if area >= min_area:
            found.append((area, cv.boundingRect(c)))
    found.sort(key=lambda t: t[0], reverse=True)
    return [b for _, b in found[:max_boxes]]


# ----------------------------------------------------------------------
# Voz (SAPI via PowerShell, en hilo aparte para no bloquear el video)
# ----------------------------------------------------------------------
_voice_lock = threading.Lock()
_last_spoken = {}
SPEAK_COOLDOWN = 8.0


def speak(text):
    """Dice el texto en voz alta (Windows SAPI). No bloquea."""
    safe = text.replace("'", "").replace('"', "")[:60]
    if not safe:
        return

    def _run():
        try:
            cmd = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$s.Rate = 1; "
                f"$s.Speak('{safe}')"
            )
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           creationflags=flags, timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    with _voice_lock:
        threading.Thread(target=_run, daemon=True).start()


def announce(label, conf, voice_enabled, cooldown=SPEAK_COOLDOWN):
    """Avisa por consola y (opcional) por voz cuando aparece un objeto nuevo."""
    now = time.time()
    if now - _last_spoken.get(label, 0.0) < cooldown:
        return
    _last_spoken[label] = now
    pretty = es_label(label)
    print(f"[NUEVO] {pretty}  ({conf * 100:.0f}%)")
    if voice_enabled:
        speak(f"Detecto {pretty}")


# ----------------------------------------------------------------------
# Dibujo
# ----------------------------------------------------------------------
def draw(frame, tracked, generics=()):
    """Dibuja cajas etiquetadas. Devuelve el conteo por clase."""
    counts = {}
    for _tid, label, conf, (x, y, w, h), _new in tracked:
        idx = CLASSES.index(label)
        color = tuple(int(c) for c in COLORS[idx])
        cv.rectangle(frame, (x, y), (x + w, y + h), color, 2)

        text = f"{es_label(label)} {conf * 100:.0f}%"
        (tw, th), _ = cv.getTextSize(text, cv.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        ty = y - th - 10 if y - th - 10 > 0 else y + th + 6
        cv.rectangle(frame, (x, ty), (x + tw + 8, ty + th + 8), color, -1)
        cv.putText(frame, text, (x + 4, ty + th + 2),
                   cv.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv.LINE_AA)

        pretty = es_label(label)
        counts[pretty] = counts.get(pretty, 0) + 1

    for (x, y, w, h) in generics:
        cv.rectangle(frame, (x, y), (x + w, y + h), (255, 128, 0), 1)
        cv.putText(frame, "objeto?", (x + 2, max(14, y - 6)),
                   cv.FONT_HERSHEY_SIMPLEX, 0.45, (255, 128, 0), 1, cv.LINE_AA)
    return counts


def draw_hud(frame, fps, counts, threshold, input_size, paused, voice_on, panel_on):
    """Barra superior de estado + panel lateral de objetos."""
    h, w = frame.shape[:2]
    bar = np.zeros((34, w, 3), dtype=np.uint8)
    total = sum(counts.values())
    cv.putText(bar,
               f"WIS  |  FPS {fps:5.1f}  |  objetos {total}  |  conf {threshold:.2f}"
               f"  |  {input_size}px  |  voz {'ON' if voice_on else 'off'}",
               (10, 23), cv.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 0), 1, cv.LINE_AA)
    state = "PAUSA" if paused else "VIVO"
    color = (0, 165, 255) if paused else (0, 255, 0)
    cv.putText(bar, state, (w - 78, 23), cv.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv.LINE_AA)
    out = np.vstack([bar, frame])

    if panel_on:
        ph = out.shape[0]
        panel = np.zeros((ph, 230, 3), dtype=np.uint8)
        cv.putText(panel, "OBJETOS", (12, 26), cv.FONT_HERSHEY_SIMPLEX, 0.6,
                   (0, 220, 255), 2, cv.LINE_AA)
        y = 58
        if not counts:
            cv.putText(panel, "(ninguno)", (12, y), cv.FONT_HERSHEY_SIMPLEX, 0.5,
                       (140, 140, 140), 1, cv.LINE_AA)
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            cv.putText(panel, f"- {name} x{n}", (12, y), cv.FONT_HERSHEY_SIMPLEX,
                       0.52, (240, 240, 240), 1, cv.LINE_AA)
            y += 26
            if y > ph - 60:
                break
        cv.putText(panel, "Q salir   S foto", (12, ph - 34), cv.FONT_HERSHEY_SIMPLEX,
                   0.42, (120, 160, 120), 1, cv.LINE_AA)
        cv.putText(panel, "[ ] conf   - + px", (12, ph - 16), cv.FONT_HERSHEY_SIMPLEX,
                   0.42, (120, 160, 120), 1, cv.LINE_AA)
        out = np.hstack([out, panel])
    return out


# ----------------------------------------------------------------------
# Principal
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="WIS Live Object Detector v2 (YOLOv4-tiny)")
    ap.add_argument("--camera", type=int, default=0, help="indice de camara (default 0)")
    ap.add_argument("--conf", type=float, default=0.35, help="umbral de confianza (default 0.35)")
    ap.add_argument("--size", type=int, default=448, choices=list(SIZES),
                    help="resolucion de entrada (default 448)")
    ap.add_argument("--no-voice", action="store_true", help="desactivar la voz")
    ap.add_argument("--no-generic", action="store_true", help="desactivar objetos genericos")
    args = ap.parse_args()

    print("[WIS] Cargando YOLOv4-tiny (COCO 80 clases)...")
    net = load_net()
    out_names = net.getUnconnectedOutLayersNames()
    print(f"[WIS] Modelo cargado. Clases: {len(CLASSES)}  Salidas: {out_names}")

    os.makedirs(SNAP_DIR, exist_ok=True)

    cap = cv.VideoCapture(args.camera, cv.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv.VideoCapture(args.camera)
    if not cap.isOpened():
        print("[WIS] ERROR: no se pudo abrir la camara.")
        return 1
    cap.set(cv.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv.CAP_PROP_FRAME_HEIGHT, 720)

    threshold = args.conf
    input_size = args.size
    voice_on = not args.no_voice
    generic_on = not args.no_generic
    panel_on = True
    paused = False
    tracker = Tracker()

    print("[WIS] Camara lista. Q=salir  S=foto  ESPACIO=pausa  [ ]=confianza  - + =resolucion")
    print("[WIS] V=voz  P=panel  O=objetos genericos")

    frame = None
    last_counts = {}
    last_generics = []
    fps, last_t = 0.0, time.time()

    while True:
        if not paused:
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            dets = detect(net, out_names, frame, threshold, input_size)
            tracked = tracker.update(dets)

            for _tid, label, conf, _box, is_new in tracked:
                if is_new:
                    announce(label, conf, voice_on)

            last_generics = []
            if generic_on:
                gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
                detected_boxes = [b for _, _, _, b, _ in tracked]
                for gb in detect_generic(gray):
                    if any(iou(gb, db) > 0.4 for db in detected_boxes):
                        continue
                    last_generics.append(gb)

            last_counts = draw(frame, tracked, last_generics)
        elif frame is None:
            continue

        now = time.time()
        dt = now - last_t
        last_t = now
        if dt > 0:
            fps = 0.9 * fps + 0.1 * (1.0 / dt)

        display = draw_hud(frame.copy(), fps, last_counts, threshold,
                           input_size, paused, voice_on, panel_on)
        cv.imshow("WIS Object Detector", display)

        key = cv.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord('s'):
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(SNAP_DIR, f"snapshot_{ts}.png")
            cv.imwrite(path, display)
            print(f"[WIS] Captura guardada: {path}")
        elif key == ord(' '):
            paused = not paused
            print(f"[WIS] {'PAUSADO' if paused else 'REANUDADO'}")
        elif key == ord('['):
            threshold = max(0.05, round(threshold - 0.05, 2))
            print(f"[WIS] Umbral de confianza: {threshold:.2f}")
        elif key == ord(']'):
            threshold = min(0.95, round(threshold + 0.05, 2))
            print(f"[WIS] Umbral de confianza: {threshold:.2f}")
        elif key in (ord('-'), ord('_')):
            input_size = SIZES[max(0, SIZES.index(input_size) - 1)]
            print(f"[WIS] Resolucion de entrada: {input_size}px")
        elif key in (ord('+'), ord('=')):
            input_size = SIZES[min(len(SIZES) - 1, SIZES.index(input_size) + 1)]
            print(f"[WIS] Resolucion de entrada: {input_size}px")
        elif key == ord('v'):
            voice_on = not voice_on
            print(f"[WIS] Voz {'ACTIVADA' if voice_on else 'DESACTIVADA'}")
        elif key == ord('p'):
            panel_on = not panel_on
        elif key == ord('o'):
            generic_on = not generic_on
            print(f"[WIS] Objetos genericos {'ACTIVADOS' if generic_on else 'DESACTIVADOS'}")

    cap.release()
    cv.destroyAllWindows()
    print("[WIS] Detector cerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
