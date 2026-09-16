
import cv2, numpy as np, os

BASE = os.path.dirname(os.path.abspath(__file__))
proto = os.path.join(BASE, "MobileNetSSD_deploy.prototxt")
model = os.path.join(BASE, "MobileNetSSD_deploy.caffemodel")

net = cv2.dnn.readNetFromCaffe(proto, model)
print("MODEL LOADED OK")

CLASSES = ["background","aeroplane","bicycle","bird","boat","bottle","bus",
"car","cat","chair","cow","diningtable","dog","horse","motorbike","person",
"pottedplant","sheep","sofa","train","tvmonitor"]

# Build a synthetic test image (colored blocks) to confirm the pipeline runs
img = np.zeros((300, 300, 3), dtype=np.uint8)
img[:] = (120, 130, 140)
cv2.rectangle(img, (50, 50), (150, 200), (200, 180, 160), -1)

blob = cv2.dnn.blobFromImage(cv2.resize(img, (300,300)), 0.007843,
                             (300,300), 127.5)
net.setInput(blob)
det = net.forward()
print("forward shape:", det.shape)

count = 0
for i in range(det.shape[2]):
    conf = float(det[0,0,i,2])
    if conf > 0.2:
        count += 1
        idx = int(det[0,0,i,1])
        print(f"  detection: {CLASSES[idx]} conf={conf:.3f}")
print("DETECTIONS FOUND:", count)
print("PIPELINE OK")
