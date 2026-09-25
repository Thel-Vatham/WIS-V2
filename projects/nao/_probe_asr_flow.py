# -*- coding: utf-8 -*-
"""Sonda paso a paso del ciclo ASR que usa `nao_bridge.NAO.listen`.

Reproduce la secuencia EXACTA del bridge para localizar en que llamada
aparece "Conversion from GenericObject to ALValue failed" y verificar el
patron correcto (subscribe/unsubscribe + lectura de WordRecognized).

Uso:
    set PYTHONPATH=<lib pynaoqi>
    C:\\Python27\\python.exe _probe_asr_flow.py --ip 172.20.10.9
"""
from __future__ import print_function

import argparse
import sys
import time

from naoqi import ALProxy


def step(label, fn, *args):
    try:
        res = fn(*args)
        print("[ OK ] %-34s -> %r" % (label, res))
        return True, res
    except Exception as exc:  # noqa: BLE001
        print("[FAIL] %-34s -> %s" % (label, exc))
        return False, exc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="172.20.10.9")
    ap.add_argument("--port", type=int, default=9559)
    ap.add_argument("--timeout", type=float, default=8.0)
    args = ap.parse_args()

    asr = ALProxy("ALSpeechRecognition", args.ip, args.port)
    mem = ALProxy("ALMemory", args.ip, args.port)

    print("== FASE 1: replica del bridge tal cual esta hoy ==")
    step("asr.pause(True)", asr.pause, True)
    step("asr.setLanguage('Spanish')", asr.setLanguage, "Spanish")
    step("asr.pause(False)", asr.pause, False)
    ok, sub = step("mem.subscriber('WordRecognized')", mem.subscriber, "WordRecognized")
    if ok:
        def cb(key, value, msg):
            print("   [EVENT] %s = %r" % (key, value))
        step("sub.signal.connect(cb)", sub.signal.connect, cb)
        time.sleep(2.0)
        step("sub.signal.disconnect(cb)", sub.signal.disconnect, cb)
    step("asr.pause(True)", asr.pause, True)

    print("")
    print("== FASE 2: patron correcto con subscribe del motor ==")
    step("asr.pause(True)", asr.pause, True)
    step("asr.setLanguage('Spanish')", asr.setLanguage, "Spanish")
    step("asr.setVocabulary(vocab, True)", asr.setVocabulary,
         ["hola", "amiguitos", "vamos", "a", "aprender", "si", "no"], True)
    step("asr.pause(False)", asr.pause, False)
    ok_sub, _ = step("asr.subscribe('wis_probe')", asr.subscribe, "wis_probe")

    heard = {"text": None}

    def cb2(key, value, msg):
        if key == "WordRecognized" and value and value[0]:
            heard["text"] = value[0]
            print("   [EVENT] WordRecognized = %r" % (value,))

    ok_ev, sub2 = step("mem.subscriber('WordRecognized')", mem.subscriber, "WordRecognized")
    if ok_ev:
        step("signal.connect(cb2)", sub2.signal.connect, cb2)

    print(">> Escuchando %.1fs ... habla al robot ahora." % args.timeout)
    t0 = time.time()
    while time.time() - t0 < args.timeout and not heard["text"]:
        time.sleep(0.2)

    if ok_ev:
        try:
            sub2.signal.disconnect(cb2)
        except Exception:
            pass
    step("mem.getData('WordRecognized')", mem.getData, "WordRecognized")
    if ok_sub:
        step("asr.unsubscribe('wis_probe')", asr.unsubscribe, "wis_probe")
    step("asr.pause(True)", asr.pause, True)

    print("")
    print("RESULTADO: text=%r" % heard["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
