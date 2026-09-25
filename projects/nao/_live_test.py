# -*- coding: utf-8 -*-
"""Live integration test for nao_bridge.py (run with the WIS venv = Python 3).

PROTOCOL (this is what the old file got wrong)
----------------------------------------------
The bridge speaks JSON-per-line and expects:

    {"action": "<name>", "params": { ... }}      -> request
    {"success": true|false, ...}                  -> exactly ONE reply line

On startup it emits a single ready line:

    {"event": "ready", "connected": true|false, "ip": ..., "port": ...}

The previous version of this file sent {"cmd": "connect", "ip": ...}, so
*every* request landed on the bridge's `unknown_action` branch: the test
looked like it ran but never exercised a single robot command.

Usage:
    python _live_test.py [ip] [port]
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "nao_bridge.py")
SDK_LIB = (
    r"C:\Users\nicol\OneDrive\Documentos\NAO"
    r"\pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649\lib"
)
PY27 = r"C:\Python27\python.exe"

IP = sys.argv[1] if len(sys.argv) > 1 else "172.20.10.9"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9559

# La consola Windows usa cp1252: nada de emojis en prints.
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("[%s] %-16s %s" % ("PASS" if ok else "FAIL", name, detail))


class Bridge(object):
    def __init__(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = SDK_LIB
        env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(
            [PY27, BRIDGE, "--ip", IP, "--port", str(PORT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            bufsize=0,
        )

    def _readline(self, timeout=45.0):
        """Devuelve la siguiente linea JSON del bridge.

        El SDK naoqi escribe warnings antes del handshake, p.ej.
            [W] ... qi.path.sdklayout: No Application was created...
        asi que se descartan las lineas que no son JSON.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                continue
            text = line.decode("utf-8", "replace").strip()
            if not text:
                continue
            if not (text.startswith("{") and text.endswith("}")):
                continue  # log/warning del SDK, no una respuesta
            try:
                return json.loads(text)
            except ValueError:
                continue
        return None

    def wait_ready(self, timeout=45.0):
        return self._readline(timeout)

    def call(self, action, timeout=45.0, **params):
        payload = {"action": action, "params": params}
        self.proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        reply = self._readline(timeout)
        if reply is None:
            return {"success": False, "error": "timeout_no_reply"}
        return reply

    def close(self):
        try:
            self.proc.stdin.write(
                (json.dumps({"action": "quit"}) + "\n").encode("utf-8")
            )
            self.proc.stdin.flush()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def main():
    if not os.path.isfile(BRIDGE):
        print("FAIL bridge not found: %s" % BRIDGE)
        return 2
    if not os.path.isfile(PY27):
        print("SKIP Python 2.7 interpreter not found: %s" % PY27)
        return 2

    print("BRIDGE : %s" % BRIDGE)
    print("TARGET : %s:%s" % (IP, PORT))
    print("-" * 62)

    bridge = Bridge()
    try:
        ready = bridge.wait_ready()
        if ready is None:
            check("ready", False, "no handshake line from bridge")
            return 1
        if "event" not in ready:
            check("ready", False, "unexpected first line: %r" % ready)
            return 1
        connected = bool(ready.get("connected"))
        check("ready", True, "connected=%s" % connected)
        if not connected:
            check("connection", False, str(ready.get("error", "unknown")))
            print("\nRobot unreachable. Fix the network/IP and re-run.")
            return 1

        # --- the four actions that used to fail hard ------------------- #
        r = bridge.call("speak", text="Hola, soy WIS. La conexion funciona.")
        check("speak", r.get("success"), json.dumps(r, ensure_ascii=False))

        r = bridge.call("battery")
        check(
            "battery",
            r.get("success") and isinstance(r.get("percent"), int),
            json.dumps(r),
        )

        r = bridge.call("leds", color="0x0066FF", led="FaceLeds")
        check("leds(hex str)", r.get("success"), json.dumps(r))

        r = bridge.call("leds", color="#FF0000", led="EarLeds")
        check("leds(#hex)", r.get("success"), json.dumps(r))

        r = bridge.call("leds_off")
        check("leds_off", r.get("success"), json.dumps(r))

        # --- posture (was shadowed by self.posture proxy) -------------- #
        r = bridge.call("posture", name="Stand")
        check("posture", r.get("success"), json.dumps(r))

        # --- regressions: these already worked, keep them covered ------ #
        r = bridge.call("set_language", language="Spanish")
        check("set_language", r.get("success"), json.dumps(r))

        r = bridge.call("get_joints")
        joints = r.get("joints") or {}
        check("get_joints", r.get("success") and len(joints) > 0,
              "%d joints" % len(joints))

        r = bridge.call("get_sensors")
        check("get_sensors", r.get("success"),
              json.dumps(r)[:120])

        # --- acentos: pynaoqi rechaza `unicode` (Void to String) -------- #
        r = bridge.call("speak", text="Ninos y ninas, manana es el dia.")
        check("speak ascii", r.get("success"), json.dumps(r, ensure_ascii=False)[:90])

        r = bridge.call("posture", name="Sit")
        check("posture Sit", r.get("success"), json.dumps(r)[:90])
    finally:
        bridge.close()

    print("-" * 62)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("RESULT: %d/%d passed" % (passed, total))
    failed = [n for n, ok, _ in RESULTS if not ok]
    if failed:
        print("FAILED: %s" % ", ".join(failed))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
