"""Self-test: run the new live_detector pipeline on a real camera frame and
save an annotated image so the boxes can be visually verified."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2 as cv
import live_detector as L

print("clases:", len(L.CLASSES))
net = L.load_net()
out_names = net.getUnconnectedOutLayersNames()
print("modelo OK, salidas:", out_names)

cap = cv.VideoCapture(0, cv.CAP_DSHOW)
if not cap.isOpened():
    cap = cv.VideoCapture(0)
ok, frame = cap.read()
print("frame:", ok, None if not ok else frame.shape)

if ok:
    # grab a few frames so auto-exposure settles
    for _ in range(10):
        cap.read()
    ok, frame = cap.read()

    tracker = L.Tracker()
    for thresh in (0.50, 0.35, 0.20):
        dets = L.detect(net, out_names, frame, thresh, 448)
        print(f"\numbral {thresh:.2f} -> {len(dets)} deteccion(es) tras NMS")
        for label, conf, box in dets:
            print(f"   - {L.es_label(label):14s} ({label:14s}) {conf*100:5.1f}%  {box}")

    dets = L.detect(net, out_names, frame, 0.25, 448)
    tracked = tracker.update(dets)
    counts = L.draw(frame, tracked, [])

    gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
    generics = [g for g in L.detect_generic(gray)
                if not any(L.iou(g, b) > 0.4 for _, _, _, b, _ in tracked)]
    frame2 = cv.imread("_frame_dummy.png") if False else None
    counts = L.draw(frame, tracked, generics)

    hud = L.draw_hud(frame.copy(), 30.0, counts, 0.25, 448, False, True, True)
    out_path = os.path.join(L.SNAP_DIR, "_selftest_annotated.png")
    os.makedirs(L.SNAP_DIR, exist_ok=True)
    cv.imwrite(out_path, hud)
    print("\nconteo por clase:", counts)
    print("genericos:", len(generics))
    print("imagen anotada:", out_path, os.path.getsize(out_path), "bytes")
    print("SELFTEST OK")

cap.release()
