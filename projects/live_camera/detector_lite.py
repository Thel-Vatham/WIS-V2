"""
WIS Object Detector (Lite) — no downloads, no deep learning required.
--------------------------------------------------------------------
Works on OpenCV 5.0.0 using ONLY built-in classical detectors:
  * Face detection   -> Haar cascade (bundled with opencv-python)
  * Motion detection -> frame differencing
  * Object/blob      -> contour + edge detection

Usage:
    python detector_lite.py                 # live camera window
    python detector_lite.py --image foo.png # single image
    python detector_lite.py --mode motion   # only motion
    python detector_lite.py --mode faces    # only faces
    python detector_lite.py --mode contours # only blobs/objects
"""

import os
import sys
import argparse
import time

import cv2
import numpy as np

# ----------------------------------------------------------------------
# Detector backends
# ----------------------------------------------------------------------
def load_face_cascade():
    """Load the Haar face cascade shipped with opencv-python."""
    path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    if not os.path.exists(path):
        return None
    cascade = cv2.CascadeClassifier(path)
    return None if cascade.empty() else cascade


def detect_faces(gray, cascade, scale=1.1, neighbors=5, min_size=40):
    faces = cascade.detectMultiScale(
        gray, scaleFactor=scale, minNeighbors=neighbors,
        minSize=(min_size, min_size)
    )
    return list(faces) if len(faces) else []


def detect_motion(prev_gray, gray, min_area=800, thresh=25):
    """Return bounding boxes of moving regions via frame differencing."""
    if prev_gray is None:
        return []
    diff = cv2.absdiff(prev_gray, gray)
    diff = cv2.GaussianBlur(diff, (7, 7), 0)
    _, mask = cv2.threshold(diff, thresh, 255, cv2.THRESH_BINARY)
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        if cv2.contourArea(c) >= min_area:
            boxes.append(cv2.boundingRect(c))
    return boxes


def detect_contours(gray, min_area=1500, max_boxes=12):
    """Detect salient objects as large contours (edges -> contour)."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        area = cv2.contourArea(c)
        if area >= min_area:
            boxes.append((cv2.boundingRect(c), area))
    boxes.sort(key=lambda b: b[1], reverse=True)
    return [b[0] for b in boxes[:max_boxes]]


# ----------------------------------------------------------------------
# Drawing
# ----------------------------------------------------------------------
COLORS = {
    "face":     (0, 255, 0),    # green
    "motion":   (0, 165, 255),  # orange
    "contour":  (255, 128, 0),  # blue
}


def draw_boxes(frame, boxes, label, color, thickness=2):
    for (x, y, w, h) in boxes:
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, thickness)
        cv2.putText(frame, label, (x, max(20, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def annotate(frame, mode, cascade, prev_gray):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    results = {}

    if mode in ("all", "faces"):
        faces = detect_faces(gray, cascade) if cascade is not None else []
        results["faces"] = faces
        draw_boxes(frame, faces, "face", COLORS["face"])

    if mode in ("all", "motion"):
        motions = detect_motion(prev_gray, gray)
        results["motion"] = motions
        draw_boxes(frame, motions, "motion", COLORS["motion"])

    if mode in ("all", "contours"):
        objs = detect_contours(gray)
        results["objects"] = objs
        draw_boxes(frame, objs, "object", COLORS["contour"])

    return frame, gray, results


# ----------------------------------------------------------------------
# Modes
# ----------------------------------------------------------------------
def run_image(path, mode, cascade):
    frame = cv2.imread(path)
    if frame is None:
        print(f"[ERROR] Could not read image: {path}")
        return 1
    out, _, results = annotate(frame, mode, cascade, None)
    out_path = os.path.splitext(path)[0] + "_detected.png"
    cv2.imwrite(out_path, out)
    print(f"[OK] Annotated image saved: {out_path}")
    for k, v in results.items():
        print(f"     {k}: {len(v)} detected")
    return 0


def run_camera(mode, cascade, camera_index=0):
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print("[ERROR] Could not open camera.")
        return 1

    print("[INFO] Camera running. Press 'q' to quit.")
    prev_gray = None
    fps_t, fps_n, fps = time.time(), 0, 0.0

    while True:
        ok, frame = cap.read()
        if not ok:
            print("[ERROR] Failed to read frame.")
            break

        frame, gray, results = annotate(frame, mode, cascade, prev_gray)
        prev_gray = gray

        fps_n += 1
        if time.time() - fps_t >= 1.0:
            fps = fps_n / (time.time() - fps_t)
            fps_t, fps_n = time.time(), 0
        cv2.putText(frame, f"FPS: {fps:.1f}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        cv2.imshow("WIS Object Detector (Lite)", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    return 0


# ----------------------------------------------------------------------
# Entry
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="WIS Object Detector (Lite)")
    ap.add_argument("--image", help="path to a single image instead of live camera")
    ap.add_argument("--mode", default="all",
                    choices=["all", "faces", "motion", "contours"])
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()

    cascade = load_face_cascade()
    if cascade is None:
        print("[WARN] Face cascade not found — face detection disabled.")
    else:
        print("[INFO] Face cascade loaded.")

    if args.image:
        return run_image(args.image, args.mode, cascade)
    return run_camera(args.mode, cascade, args.camera)


if __name__ == "__main__":
    sys.exit(main())
