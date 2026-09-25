# -*- coding: utf-8 -*-
"""Probe 2: determine the channel order and orientation of NAO camera frames.

nao_bridge.capture_b64() returns raw pixels from colorSpace=11 but the web UI
labelled them as JPEG, so nothing was ever displayed.

This probe captures the same scene with colorSpace 11 (kRGBColorSpace) and 13
(kBGRColorSpace) and compares the two frames byte by byte:

  * If they are identical, the SDK ignores the flag -> order must be chosen by
    inspection.
  * If they differ ONLY by a red/blue swap (green untouched), then 11 really
    does return RGB and 13 returns BGR, which settles the question.

It also dumps statistics per channel and the top/bottom brightness split, which
helps decide whether the image is stored bottom-up.
"""
from __future__ import print_function

import sys

try:
    from naoqi import ALProxy
except Exception as exc:  # noqa: BLE001
    print("QI_IMPORT_FAIL: %r" % (exc,))
    sys.exit(2)

IP = "172.20.10.9"
PORT = 9559
K_RGB = 11
K_BGR = 13


def grab(video, color_space, resolution=1):
    name = "probe2_%d" % color_space
    try:
        video.unsubscribe(name)
    except Exception:
        pass
    handle = video.subscribeCamera(name, 0, resolution, color_space, 15)
    try:
        img = video.getImageRemote(handle)
    finally:
        try:
            video.unsubscribe(handle)
        except Exception:
            pass
    if not img:
        return None
    return img[0], img[1], img[2], bytes(bytearray(img[6]))


def stats(raw, w, h):
    n = w * h
    ch = []
    for c in range(3):
        total = 0
        for i in range(c, n * 3, 3):
            total += ord(raw[i])
        ch.append(total / float(n))

    # Brillo medio de la mitad superior vs inferior (para detectar volteo).
    row_bytes = w * 3
    half = h // 2
    top = sum(ord(b) for b in raw[:half * row_bytes]) / float(half * row_bytes)
    bottom = sum(ord(b) for b in raw[half * row_bytes:]) / float((h - half) * row_bytes)
    return ch, top, bottom


def main():
    try:
        video = ALProxy("ALVideoDevice", IP, PORT)
    except Exception as exc:  # noqa: BLE001
        print("PROXY_FAIL: %r" % (exc,))
        return 3

    a = grab(video, K_RGB)
    b = grab(video, K_BGR)
    if not a or not b:
        print("NO_IMAGE (a=%s b=%s)" % (bool(a), bool(b)))
        return 1

    wa, ha, la, ra = a
    wb, hb, lb, rb = b
    print("rgb11 w=%s h=%s layers=%s bytes=%s" % (wa, ha, la, len(ra)))
    print("bgr13 w=%s h=%s layers=%s bytes=%s" % (wb, hb, lb, len(rb)))
    print("-" * 60)

    identical = (ra == rb)
    print("IDENTICAL_FRAMES=%s" % identical)

    if not identical and la == 3 and lb == 3:
        # Comparar solo las posiciones R y B asumiendo que 11 es RGB.
        n = wa * ha
        swap_only = True
        checked = 0
        for i in range(0, n * 3, 3 * 97):  # muestreo, no todos los pixeles
            if ord(ra[i]) != ord(rb[i + 2]) or ord(ra[i + 2]) != ord(rb[i]):
                swap_only = False
                break
            if ord(ra[i + 1]) != ord(rb[i + 1]):
                swap_only = False
                break
            checked += 1
        print("DIFFERS_BY_RB_SWAP_ONLY=%s (sampled %s px)" % (swap_only, checked))

    cha, topa, bota = stats(ra, wa, ha)
    print("rgb11 mean R,G,B = %.1f %.1f %.1f" % tuple(cha))
    print("rgb11 top=%.1f bottom=%.1f (top>bottom=%s)" % (topa, bota, topa > bota))

    fh = open("probe_rgb11.bin", "wb")
    fh.write(ra)
    fh.close()
    fh = open("probe_bgr13.bin", "wb")
    fh.write(rb)
    fh.close()
    print("-" * 60)
    print("wrote probe_rgb11.bin / probe_bgr13.bin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
