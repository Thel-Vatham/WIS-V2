# -*- coding: utf-8 -*-
"""Probe: can the robot deliver JPEG frames directly?

The panel showed nothing because nao_bridge.capture_b64() returned raw pixel
bytes (colorSpace=11) but the web UI labelled them as `data:image/jpeg;base64`.

NAOqi's ALVideoDevice can encode JPEG on the robot itself using
kJpegColorSpace = 21. If that works we get real JPEG bytes in img[6] and no
host-side conversion is needed.

Run with Python 2.7 + pynaoqi on PYTHONPATH.
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

# NAOqi color space constants
K_RGB = 11
K_JPEG = 21


def probe(video, label, color_space, resolution=1):
    name = "probe_%s" % label
    try:
        video.unsubscribe(name)
    except Exception:
        pass
    try:
        handle = video.subscribeCamera(name, 0, resolution, color_space, 15)
    except Exception as exc:  # noqa: BLE001
        print("%-8s SUBSCRIBE_FAIL: %r" % (label, exc))
        return None
    try:
        img = video.getImageRemote(handle)
    except Exception as exc:  # noqa: BLE001
        print("%-8s GETIMAGE_FAIL: %r" % (label, exc))
        video.unsubscribe(handle)
        return None
    finally:
        try:
            video.unsubscribe(handle)
        except Exception:
            pass

    if not img:
        print("%-8s NO_IMAGE" % label)
        return None

    width, height, nb_layers = img[0], img[1], img[2]
    data = img[6]
    raw = bytes(bytearray(data))
    head = raw[:4]
    is_jpeg = head[:2] == b"\xff\xd8"

    print("%-8s w=%-4s h=%-4s layers=%-2s bytes=%-8s jpeg_magic=%s head=%s" % (
        label, width, height, nb_layers, len(raw), is_jpeg, repr(head),
    ))
    return {
        "label": label,
        "width": width,
        "height": height,
        "layers": nb_layers,
        "raw": raw,
        "is_jpeg": is_jpeg,
    }


def main():
    try:
        video = ALProxy("ALVideoDevice", IP, PORT)
    except Exception as exc:  # noqa: BLE001
        print("PROXY_FAIL: %r" % (exc,))
        return 3

    print("=" * 60)
    rgb = probe(video, "rgb11", K_RGB)
    jpg = probe(video, "jpeg21", K_JPEG)
    print("=" * 60)

    if jpg and jpg["is_jpeg"]:
        out = "probe_jpeg.jpg"
        fh = open(out, "wb")
        fh.write(jpg["raw"])
        fh.close()
        print("JPEG_OK -> wrote %s (%d bytes)" % (out, len(jpg["raw"])))
    elif jpg:
        print("JPEG_FMT_RETURNED_RAW (no SOI marker)")

    if rgb and not rgb["is_jpeg"]:
        out = "probe_raw.bin"
        fh = open(out, "wb")
        fh.write(rgb["raw"])
        fh.close()
        print("RAW_OK -> wrote %s (%d bytes)" % (out, len(rgb["raw"])))

    return 0


if __name__ == "__main__":
    sys.exit(main())
