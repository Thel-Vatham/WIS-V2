# -*- coding: utf-8 -*-
"""Sonda de acciones contra el panel NAO ya en marcha (Python 3).

A diferencia de `_live_test.py` (que arranca su PROPIO bridge contra el robot),
esta sonda pega al panel HTTP en http://127.0.0.1:7860 y ejecuta las acciones
tal y como las ejecuta la UI. Sirve para localizar QUE accion concreta devuelve
un error y con que mensaje, sin tocar el robot por otra via.

Uso:
    python _probe_actions.py                 # bateria de acciones por defecto
    python _probe_actions.py diag get_volume
    python _probe_actions.py set_angles '{"names":["HeadYaw"],"angles":[0.3]}'
"""
from __future__ import print_function

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:7860/api/nao"

# (accion, params). Evitamos kindergarten_* a proposito: hace hablar al robot.
DEFAULT = [
    ("status", None),
    ("diag", None),
    ("battery", {}),
    ("get_volume", {}),
    ("get_mic_level", {}),
    ("get_joints", {}),
    ("get_sensors", {}),
    ("get_temperature", {}),
    ("posture", {"name": "StandInit"}),
    ("set_stiffness", {"name": "Body", "stiffness": 1.0}),
    ("set_angles", {"names": ["HeadYaw"], "angles": [0.2], "speed": 0.2}),
    ("leds", {"color": "0x0066FF", "led": "FaceLeds"}),
    ("leds_off", {}),
    ("animated_say", {"text": "Prueba de voz animada.", "language": "Spanish"}),
    ("capture", {}),
    ("capture_b64", {"resolution": 0}),
    ("listen", {"timeout": 1.0, "language": "Spanish"}),
]


def call(action, params):
    url = "%s/%s" % (BASE, action)
    body = json.dumps(params if params is not None else {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(path):
    url = "%s/%s" % (BASE, path)
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def summarize(action, res):
    """Devuelve (ok, texto) recortando los campos enormes (imagenes)."""
    if not isinstance(res, dict):
        return False, repr(res)[:160]
    if action == "status":
        return bool(res.get("connected")), json.dumps(res)
    if not res.get("success"):
        return False, "ERROR: %s" % res.get("error", res)
    clean = dict(res)
    for big in ("image_b64", "raw_b64"):
        if big in clean:
            clean[big] = "<%d chars>" % len(clean.pop(big, "") or "")
    return True, json.dumps(clean)[:160]


def main():
    if len(sys.argv) > 1:
        # Permite "accion" o "accion '{json}'" en pares.
        args = sys.argv[1:]
        cases = []
        i = 0
        while i < len(args):
            act = args[i]
            params = {}
            if i + 1 < len(args) and args[i + 1].strip().startswith("{"):
                params = json.loads(args[i + 1])
                i += 1
            cases.append((act, params))
            i += 1
    else:
        cases = DEFAULT

    print("PANEL: %s" % BASE)
    print("-" * 70)
    failures = []
    for action, params in cases:
        if action == "status":
            try:
                res = get("status")
            except Exception as exc:  # noqa: BLE001
                print("[FAIL] %-16s no responde: %s" % (action, exc))
                failures.append(action)
                continue
        else:
            try:
                res = call(action, params)
            except Exception as exc:  # noqa: BLE001
                print("[FAIL] %-16s excepcion HTTP: %s" % (action, exc))
                failures.append(action)
                continue
        ok, text = summarize(action, res)
        print("[%s] %-16s %s" % ("PASS" if ok else "FAIL", action, text))
        if not ok:
            failures.append(action)

    print("-" * 70)
    if failures:
        print("FALLAN: %s" % ", ".join(failures))
    else:
        print("Todas las acciones respondieron OK.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
