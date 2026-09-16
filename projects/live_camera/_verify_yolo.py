"""Verify YOLOv4-tiny loads and detects multiple COCO objects on a live frame."""
import os, sys
import cv2 as cv
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(BASE, "yolov4-tiny.cfg")
WTS = os.path.join(BASE, "yolov4-tiny.weights")
NAMES = os.path.join(BASE, "coco.names")

with open(NAMES) as f:
    CLASSES = [l.strip() for l in f if l.strip()]

print("OpenCV:", cv.__version__)
print("Classes:", len(CLASSES))
print("has readNetFromDarknet:", hasattr(cv.dnn, "readNetFromDarknet"))

net = cv.dnn.readNetFromDarknet(CFG, WTS)
net.setPreferableBackend(cv.dnn.DNN_BACKEND_OPENCV)
net.setPreferableTarget(cv.dnn.DNN_TARGET_CPU)
print("MODEL LOADED OK")

out_names = net.getUnconnectedOutLayersNames()
print("output layers:", out_names)

cap = cv.VideoCapture(0, cv.CAP_DSHOW)
if not cap.isOpened():
    cap = cv.VideoCapture(0)
print("camera opened:", cap.isOpened())

ok, frame = cap.read()
print("frame read:", ok, None if not ok else frame.shape)
if ok:
    H, W = frame.shape[:2]
    blob = cv.dnn.blobFromImage(frame, 1 / 255.0, (416, 416),
                                swapRB=True, crop=False)
    net.setInput(blob)
    outs = net.forward(out_names)

    boxes, confs, ids = [], [], []
    for out in outs:
        for det in out:
            scores = det[5:]
            cid = int(np.argmax(scores))
            conf = float(scores[cid])
            if conf > 0.15:
                cx, cy, w, h = (det[0] * W, det[1] * H, det[2] * W, det[3] * H)
                boxes.append([int(cx - w / 2), int(cy - h / 2), int(w), int(h)])
                confs.append(conf)
                ids.append(cid)

    keep = cv.dnn.NMSBoxes(boxes, confs, 0.15, 0.4)
    print(f"\nRAW detections >0.15: {len(boxes)}   after NMS: {len(keep)}")
    for i in np.array(keep).flatten():
        print(f"  - {CLASSES[ids[i]]:15s} {confs[i]*100:5.1f}%  box={boxes[i]}")
    print("\nVERIFY OK")

cap.release()
