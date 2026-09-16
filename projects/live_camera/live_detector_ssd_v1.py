"""
WIS Live Object Detector
=========================
Real-time object detection on the webcam feed using MobileNet-SSD (Caffe)
via OpenCV DNN. Runs in an isolated venv (OpenCV 4.14.0).

Controls:
    Q / ESC  -> quit
    S        -> save a snapshot (with boxes) to snapshots/
    SPACE    -> pause / resume the live feed

Detects 20 VOC classes: aeroplane, bicycle, bird, boat, bottle, bus, car,
cat, chair, cow, diningtable, dog, horse, motorbike, person, pottedplant,
sheep, sofa, train, tvmonitor.
"""

import os
import sys
import time
import datetime

import cv2 as cv
import numpy as np

# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROTOTXT = os.path.join(BASE_DIR, "MobileNetSSD_deploy.prototxt")
CAFFEMODEL = os.path.join(BASE_DIR, "MobileNetSSD_deploy.caffemodel")
SNAP_DIR = os.path.join(BASE_DIR, "snapshots")

# ----------------------------------------------------------------------
# Model config
# ----------------------------------------------------------------------
CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus",
    "car", "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike",
    "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor",
]

# Deterministic per-class colors (BGR) so each class keeps its color.
rng = np.random.default_rng(42)
COLORS = rng.integers(50, 255, size=(len(CLASSES), 3)).tolist()

CONF_THRESHOLD = 0.5
INPUT_SIZE = (300, 300)
MEAN = (127.5, 127.5, 127.5)
SCALE = 0.007843


def load_net():
    """Load the Caffe MobileNet-SSD model. Raises if files are missing."""
    for p in (PROTOTXT, CAFFEMODEL):
        if not os.path.isfile(p):
            raise FileNotFoundError(f"Missing model file: {p}")
    if not hasattr(cv.dnn, "readNetFromCaffe"):
        raise RuntimeError(
            "This OpenCV build has no readNetFromCaffe. "
            "Use the isolated venv with OpenCV 4.14.0."
        )
    net = cv.dnn.readNetFromCaffe(PROTOTXT, CAFFEMODEL)
    return net


def detect(net, frame, conf_threshold=CONF_THRESHOLD):
    """Run detection on a single BGR frame. Returns list of (label, conf, box)."""
    h, w = frame.shape[:2]
    blob = cv.dnn.blobFromImage(
        cv.resize(frame, INPUT_SIZE), SCALE, INPUT_SIZE, MEAN, swapRB=True, crop=False
    )
    net.setInput(blob)
    detections = net.forward()

    results = []
    for i in range(detections.shape[2]):
        confidence = float(detections[0, 0, i, 2])
        if confidence < conf_threshold:
            continue
        idx = int(detections[0, 0, i, 1])
        if idx < 0 or idx >= len(CLASSES):
            continue
        box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
        x1, y1, x2, y2 = box.astype("int")
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w - 1, x2), min(h - 1, y2)
        results.append((CLASSES[idx], confidence, (x1, y1, x2, y2)))
    return results


def draw(frame, results):
    """Draw bounding boxes + labels on the frame."""
    for label, conf, (x1, y1, x2, y2) in results:
        color = COLORS[CLASSES.index(label)]
        cv.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        text = f"{label}: {conf * 100:.1f}%"
        (tw, th), _ = cv.getTextSize(text, cv.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        # label background for readability
        cv.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), color, -1)
        cv.putText(
            frame, text, (x1 + 3, max(12, y1 - 5)),
            cv.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv.LINE_AA,
        )
    return frame


def draw_hud(frame, fps, n_objs, paused):
    """Top status bar with FPS, object count, and state."""
    h, w = frame.shape[:2]
    bar = np.zeros((34, w, 3), dtype=np.uint8)
    cv.putText(bar, f"WIS Object Detector   FPS: {fps:5.1f}   Objects: {n_objs}",
               (10, 23), cv.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1, cv.LINE_AA)
    state = "PAUSED" if paused else "LIVE"
    color = (0, 165, 255) if paused else (0, 255, 0)
    cv.putText(bar, state, (w - 90, 23), cv.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv.LINE_AA)
    return np.vstack([bar, frame])


def main():
    print("[WIS] Loading MobileNet-SSD model...")
    net = load_net()
    print("[WIS] Model loaded OK")

    os.makedirs(SNAP_DIR, exist_ok=True)

    cap = cv.VideoCapture(0, cv.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv.VideoCapture(0)  # fallback without backend hint
    if not cap.isOpened():
        print("[WIS] ERROR: could not open camera.")
        return 1

    cap.set(cv.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv.CAP_PROP_FRAME_HEIGHT, 720)

    print("[WIS] Camera open. Press Q/ESC to quit, S to snapshot, SPACE to pause.")
    paused = False
    last = time.time()
    fps = 0.0
    last_results = []

    while True:
        if not paused:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("[WIS] WARNING: dropped frame.")
                continue
            last_results = detect(net, frame)
            frame = draw(frame, last_results)
        else:
            # keep showing last frame while paused
            if 'frame' not in locals():
                continue

        now = time.time()
        dt = now - last
        last = now
        if dt > 0:
            fps = 0.9 * fps + 0.1 * (1.0 / dt)  # smoothed

        display = draw_hud(frame.copy(), fps, len(last_results), paused)
        cv.imshow("WIS Object Detector", display)

        key = cv.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord('s'):
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(SNAP_DIR, f"snapshot_{ts}.png")
            cv.imwrite(path, display)
            print(f"[WIS] Snapshot saved: {path}")
        elif key == ord(' '):
            paused = not paused
            print(f"[WIS] {'PAUSED' if paused else 'RESUMED'}")

    cap.release()
    cv.destroyAllWindows()
    print("[WIS] Detector closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
