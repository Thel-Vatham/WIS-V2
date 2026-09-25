# -*- coding: utf-8 -*-
"""Prueba de la implementacion CORREGIDA de `listen` (polling de ALMemory).

Hipotesis:
  * `memory.subscriber('WordRecognized')` esta roto en este build de NAOqi
    (Conversion from GenericObject to ALValue failed).
  * `asr.subscribe(name)` + `pause(False)` es lo que realmente enciende el motor.
  * `memory.getData('WordRecognized')` si funciona y permite leer el resultado.

Si esta sonda devuelve texto, el patron es valido para parchear nao_bridge.

Uso:
    set PYTHONPATH=<lib pynaoqi>
    C:\\Python27\\python.exe _probe_asr_fix.py --ip 172.20.10.9 --timeout 8
"""
from __future__ import print_function

import argparse
import sys
import time

from naoqi import ALProxy

VOCAB = [
    "hola", "adios", "si", "no", "gracias", "como estas", "muy bien",
    "juguemos", "vamos a aprender", "amiguitos", "maestra", "maestro",
    "que hora es", "canta una cancion", "cuentame un cuento",
]


def listen_fixed(asr, mem, timeout=6.0, language="Spanish", vocab=None,
                 word_spotting=True, client="wis_probe_fix"):
    """Patron corregido: subscribe del motor + polling de ALMemory."""
    # 1. Limpiar el valor previo para NO leer una transcripcion vieja.
    try:
        mem.insertData("WordRecognized", [])
    except Exception as exc:  # noqa: BLE001
        print("   (warn) no se pudo limpiar WordRecognized: %s" % exc)

    asr.pause(True)
    asr.setLanguage(language)
    if vocab:
        asr.setVocabulary(vocab, word_spotting)

    # 2. Un subscribe previo colgado impide volver a arrancar el motor.
    try:
        asr.unsubscribe(client)
    except Exception:
        pass
    asr.subscribe(client)
    asr.pause(False)

    heard = ""
    conf = 0.0
    try:
        t0 = time.time()
        while time.time() - t0 < timeout:
            data = mem.getData("WordRecognized")
            if data and isinstance(data, list) and len(data) >= 2 and data[0]:
                # Formato: [word1, conf1, word2, conf2, ...]
                best = 0.0
                word = ""
                for i in range(0, len(data) - 1, 2):
                    try:
                        c = float(data[i + 1])
                    except Exception:
                        continue
                    if c > best:
                        best, word = c, str(data[i])
                if word:
                    heard, conf = word, best
                    break
            time.sleep(0.15)
    finally:
        asr.pause(True)
        try:
            asr.unsubscribe(client)
        except Exception:
            pass
    return {"success": True, "text": heard, "confidence": conf}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="172.20.10.9")
    ap.add_argument("--port", type=int, default=9559)
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--no-vocab", action="store_true")
    args = ap.parse_args()

    asr = ALProxy("ALSpeechRecognition", args.ip, args.port)
    mem = ALProxy("ALMemory", args.ip, args.port)

    print("== listen corregido (%s:%s) ==" % (args.ip, args.port))
    print(">> HABLA AL ROBOT AHORA (%.0fs)" % args.timeout)
    res = listen_fixed(
        asr, mem, args.timeout, "Spanish",
        None if args.no_vocab else VOCAB,
    )
    print("RESULTADO: %r" % (res,))
    return 0 if res["text"] else 1


if __name__ == "__main__":
    sys.exit(main())
