
import cv2
print("cv2", cv2.__version__)
backends = {
    "CAP_DSHOW": cv2.CAP_DSHOW,
    "CAP_MSMF": cv2.CAP_MSMF,
    "CAP_ANY": cv2.CAP_ANY,
}
for name, be in backends.items():
    for idx in range(3):
        cap = cv2.VideoCapture(idx, be)
        ok = cap.isOpened()
        frame_ok = False
        if ok:
            ret, frame = cap.read()
            frame_ok = ret and frame is not None
        cap.release()
        print(f"{name} idx={idx} opened={ok} frame={frame_ok}")
