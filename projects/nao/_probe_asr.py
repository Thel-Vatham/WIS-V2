# -*- coding: utf-8 -*-
"""Sonda del servicio ALSpeechRecognition (Python 2.7 / pynaoqi).

Aisla QUE llamada concreta del ASR devuelve
    "Conversion from GenericObject to ALValue failed"
y con que variante de argumentos funciona. No forma parte del runtime;
es una herramienta de diagnostico que se ejecuta a mano.

Uso:
    set PYTHONPATH=<ruta lib pynaoqi>
    C:\\Python27\\python.exe _probe_asr.py --ip 172.20.10.9 --port 9559
"""
from __future__ import print_function

import argparse
import sys
import time

from naoqi import ALProxy


def try_call(label, fn, *args):
    try:
        res = fn(*args)
        print("[ OK ] %-28s -> %r" % (label, res))
        return True, res
    except Exception as exc:  # noqa: BLE001
        print("[FAIL] %-28s -> %s" % (label, exc))
        return False, exc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="172.20.10.9")
    ap.add_argument("--port", type=int, default=9559)
    ap.add_argument("--timeout", type=float, default=6.0)
    args = ap.parse_args()

    print("== ALSpeechRecognition probe %s:%s ==" % (args.ip, args.port))
    asr = ALProxy("ALSpeechRecognition", args.ip, args.port)
    mem = ALProxy("ALMemory", args.ip, args.port)

    try_call("pause(True)", asr.pause, True)
    try_call("pause(False)", asr.pause, False)

    # 1) setLanguage con bytes nativos vs unicode.
    try_call("setLanguage('Spanish') str", asr.setLanguage, "Spanish")
    try_call("setLanguage(u'Spanish') uni", asr.setLanguage, u"Spanish")

    # 2) setVocabulary: la variante que supuestamente rompe.
    vocab_py2_str = ["hola", "amiguitos", "vamos", "a", "aprender"]
    try_call("setVocabulary(list, True)", asr.setVocabulary, vocab_py2_str, True)
    try_call("setVocabulary(list, False)", asr.setVocabulary, vocab_py2_str, False)

    # 3) getVocabulary para saber si quedo cargado.
    try_call("getVocabulary()", asr.getVocabulary)

    # 4) getAvailableLanguages (a veces sin argumentos falla por ALValue).
    try_call("getAvailableLanguages()", asr.getAvailableLanguages)

    # 5) Ciclo completo: subscribe + WordRecognized + unsubscribe.
    try:
        asr.pause(False)
        asr.setVocabulary(vocab_py2_str, True)
        asr.subscribe("wis_probe_asr")
        print("[ OK ] subscribe('wis_probe_asr')")
        heard = {"text": None}

        def cb(key, value, msg):
            if key == "WordRecognized" and value and value[0]:
                heard["text"] = value[0]

        sub = mem.subscriber("WordRecognized")
        sub.signal.connect(cb)
        t0 = time.time()
        while time.time() - t0 < args.timeout and not heard["text"]:
            time.sleep(0.2)
        try:
            sub.signal.disconnect(cb)
        except Exception:  # noqa: BLE001
            pass
        try:
            asr.unsubscribe("wis_probe_asr")
        except Exception:
            pass
        asr.pause(True)
        print("[INFO] texto reconocido: %r" % heard["text"])
    except Exception as exc:  # noqa: BLE001
        print("[FAIL] ciclo subscribe/unsubscribe -> %s" % exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
