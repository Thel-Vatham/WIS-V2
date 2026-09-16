
import cv2, time, os
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
time.sleep(1.5)
ok, frame = cap.read()
cap.release()
if ok:
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_frame.png")
    cv2.imwrite(out, frame)
    print("FRAME OK", frame.shape, out)
else:
    print("FRAME FAIL")
