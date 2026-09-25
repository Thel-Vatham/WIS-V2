# -*- coding: utf-8 -*-
"""Sonda interactiva en vivo del ASR: muestra en tiempo real lo que NAO oye.

Ademas imprime el estado interno del motor (ALMemory) para distinguir:
  * el motor no esta escuchando  -> problema de subscribe/estado
  * el motor escucha pero no acierta -> problema de vocabulario/idioma
  * el motor acierta pero el bridge no lo lee -> problema de lectura

Uso:
    set PYTHONPATH=<lib pynaoqi>
    C:\\Python27\\python.exe _probe_asr_live.py --ip 172.20.10.9 --seconds 25
"""
from __future__ import print_function

import argparse
import sys
import time

from naoqi import ALProxy

VOCAB = [
    "hola", "adios", "si", "no", "gracias", "como estas", "muy bien",
    "juguemos", "vamos a aprender", "amiguitos", "maestra", "maestro",
    "canta una cancion", "cuentame un cuento",
]

STATUS_KEYS = [
    "ALSpeechRecognition/Status",
    "Device/SubDeviceList/Microphone/Front/Energy/Sensor/Value",
]


def dump_status(mem, tag):
    out = {}
    for key in STATUS_KEYS:
        try:
            out[key.split("/")[-1]] = mem.getData(key)
        except Exception as exc:  # noqa: BLE001
            out[key] = "ERR:%s" % exc
    print("[%s] %s" % (tag, out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="172.20.10.9")
    ap.add_argument("--port", type=int, default=9559)
    ap.add_argument("--seconds", type=float, default=25.0)
    args = ap.parse_args()

    asr = ALProxy("ALSpeechRecognition", args.ip, args.port)
    mem = ALProxy("ALMemory", args.ip, args.port)

    print("== ASR live (%s:%s) ==" % (args.ip, args.port))
    try:
        mem.insertData("WordRecognized", [])
    except Exception as exc:  # noqa: BLE001
        print("(warn) insertData: %s" % exc)

    asr.pause(True)
    asr.setLanguage("Spanish")
    asr.setVocabulary(VOCAB, True)
    try:
        asr.unsubscribe("wis_live")
    except Exception:
        pass
    asr.subscribe("wis_live")
    asr.pause(False)
    print("motor ARRANCADO. Vocabulario de %d palabras." % len(VOCAB))
    dump_status(mem, "status")

    print("")
    print(">>> Di 'hola', 'adios', 'gracias' o 'canta una cancion' durante %.0fs" % args.seconds)
    print("")

    last = None
    t0 = time.time()
    try:
        while time.time() - t0 < args.seconds:
            try:
                data = mem.getData("WordRecognized")
            except Exception as exc:  # noqa: BLE001
                print("getData error: %s" % exc)
                data = None
            if data and data != last:
                print("  [%5.1fs] WordRecognized = %r" % (time.time() - t0, data))
                last = data
            time.sleep(0.15)
    finally:
        asr.pause(True)
        try:
            asr.unsubscribe("wis_live")
        except Exception:
            pass
        dump_status(mem, "final")

    print("")
    print("RESULTADO FINAL: %r" % (last,))
    return 0 if last else 1


if __name__ == "__main__":
    sys.exit(main())
