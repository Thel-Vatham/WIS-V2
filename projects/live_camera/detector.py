"""
WIS Object Detector
===================
Real-time object detection using MobileNet-SSD (Caffe) via OpenCV DNN.
Detects 20 object classes (VOC): person, car, dog, cat, bottle, chair, etc.

Runs in an isolated venv with OpenCV 4.x (see venv/).
"""

import os
import sys
import time
import argparse

import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROTOTXT = os.path.join(BASE_DIR, "MobileNetSSD_deploy.prototxt")
CAFFEMODEL = os.path.join(BASE_DIR, "MobileNetSSD_deploy.caffemodel")

# VOC 20-class labels used by the standard MobileNet-SSD Caffe model
CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle",
    "bus", "car", "cat", "chair", "cow", "diningtable", "dog", "horse",
    "motorbike", "person", "pottedplant", "sheep", "sofa", "train",
    "tvmonitor",
]

# A distinct BGR colour per class (deterministic, readable)
RNG = np.random.RandomState(42)
COLORS = RNG.randint(0, 255, size=(len(CLASSES), 3), dtype=np.uint8)


def load_net():
    """Load the Caffe MobileNet-SSD network."""
    if not os.path.exists(PROTOTXT):
        raise FileNotFoundError(f"Missing prototxt: {PROTOTXT}")
    if not os.path.exists(CAFFEMODEL):
        raise FileNotFoundError(f"Missing caffemodel: {CAFFEMODEL}")
    net = cv2.dnn.readNetFromCaffe(PROTOTXT, CAFFEMODEL)
    return net


def detect(net, frame, confidence_threshold=0.5):
    """Run detection on a BGR frame. Returns list of (label, conf, box)."""
    h, w = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.resize(frame, (300, 300)),
        scalefactor=0.007843,
        size=(300, 300),
        mean=(127.5, 127.5, 127.5),
    )
    net.setInput(blob)
    detections = net.forward()

    results = []
    for i in range(detections.shape[2]):
        confidence = float(detections[0, 0, i, 2])
        if confidence < confidence_threshold:
            continue
        class_id = int(detections[0, 0, i, 1])
        box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
        x1, y1, x2, y2 = box.astype("int")
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w - 1, x2), min(h - 1, y2)
        label = CLASSES[class_id] if class_id < len(CLASSES) else f"id{class_id}"
        results.append((label, confidence, (x1, y1, x2, y2)))
    return results


def draw(frame, results):
    """Draw bounding boxes + labels on a copy of the frame."""
    out = frame.copy()
    for label, conf, (x1, y1, x2, y2) in results:
        idx = CLASSES.index(label) if label in CLASSES else 0
        color = tuple(int(c) for c in COLORS[idx])
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        text = f"{label}: {conf * 100:.1f}%"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
        cv2.putText(
            out, text, (x1 + 2, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
        )
    return out


def detect_image(net, path, output_path=None, threshold=0.5):
    """Detect objects in a single image file."""
    frame = cv2.imread(path)
    if frame is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    results = detect(net, frame, threshold)
    annotated = draw(frame, results)

    if output_path is None:
        root, ext = os.path.splitext(path)
        output_path = f"{root}_detected{ext}"
    cv2.imwrite(output_path, annotated)

    print(f"Image: {path}")
    print(f"Output: {output_path}")
    if results:
        print(f"Detected {len(results)} object(s):")
        for label, conf, box in results:
            print(f"  - {label}: {conf * 100:.1f}%  box={box}")
    else:
        print("No objects detected above threshold.")
    return results, output_path


def detect_camera(net, camera_index=0, threshold=0.5):
    """Live detection from the webcam. Press 'q' to quit, 's' to save a frame."""
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {camera_index}")

    print("Live detection running. Press 'q' to quit, 's' to save a snapshot.")
    fps_time = time.time()
    frames = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Failed to grab frame.")
            break

        results = detect(net, frame, threshold)
        annotated = draw(frame, results)

        frames += 1
        elapsed = time.time() - fps_time
        if elapsed >= 1.0:
            fps = frames / elapsed
            cv2.putText(
                annotated, f"FPS: {fps:.1f}", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
            )
            frames = 0
            fps_time = time.time()

        cv2.imshow("WIS Object Detector", annotated)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            snap = os.path.join(BASE_DIR, f"snapshot_{int(time.time())}.png")
            cv2.imwrite(snap, annotated)
            print(f"Saved: {snap}")

    cap.release()
    cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="WIS Object Detector (MobileNet-SSD)")
    parser.add_argument("--image", "-i", help="Path to an image file to analyze")
    parser.add_argument("--camera", "-c", action="store_true", help="Run live webcam detection")
    parser.add_argument("--camera-index", type=int, default=0, help="Webcam index (default 0)")
    parser.add_argument("--output", "-o", help="Output path for annotated image")
    parser.add_argument("--threshold", "-t", type=float, default=0.5, help="Confidence threshold (0-1)")
    args = parser.parse_args()

    print("Loading MobileNet-SSD...")
    net = load_net()
    print("Model loaded.\n")

    if args.image:
        detect_image(net, args.image, args.output, args.threshold)
    elif args.camera:
        detect_camera(net, args.camera_index, args.threshold)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
