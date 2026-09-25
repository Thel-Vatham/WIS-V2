# -*- coding: utf-8 -*-
"""Offline protocol test for nao_bridge.py -- no robot, no Python 2.7 needed.

Runs the REAL bridge as a subprocess under the WIS venv interpreter, but with
`_stub_naoqi` first on PYTHONPATH so `from naoqi import ALProxy` resolves to a
recorder instead of the pynaoqi SDK.

What it proves:
  1. The stdin/stdout JSON protocol works: {"action","params"} -> one reply line.
  2. `leds` and `posture` are reachable (they used to be shadowed by the
     self.leds / self.posture proxy attributes -> "object is not callable").
  3. LED colors arrive at ALLeds as INTs, whatever the caller sent
     ("0xff0000", "#ff0000", "ff0000", int).
  4. Non-serializable naoqi return values (Event) no longer abort the reply.
  5. A non-serializable *parameter* does not kill the command.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "nao_bridge.py")
STUB = os.path.join(HERE, "_stub_naoqi")
PY = sys.executable

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("[%s] %-24s %s" % ("PASS" if ok else "FAIL", name, detail))


def run_bridge_session(requests, timeout=30.0):
    env = dict(os.environ)
    env["PYTHONPATH"] = STUB + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen(
        [PY, BRIDGE, "--ip", "127.0.0.1", "--port", "9559"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        bufsize=1,
        universal_newlines=True,
    )

    def readline():
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = proc.stdout.readline()
            if line:
                return line.strip()
        return None

    ready_raw = readline()
    try:
        ready = json.loads(ready_raw) if ready_raw else None
    except ValueError:
        ready = None

    replies = []
    for req in requests:
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        raw = readline()
        try:
            replies.append(json.loads(raw) if raw else None)
        except ValueError:
            replies.append({"__non_json__": raw})

    try:
        proc.stdin.write(json.dumps({"action": "quit"}) + "\n")
        proc.stdin.flush()
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

    stderr = proc.stderr.read() if proc.stderr else ""
    return ready, replies, stderr


def main():
    if not os.path.isfile(BRIDGE):
        print("bridge not found: %s" % BRIDGE)
        return 2

    # (etiqueta, peticion, success esperado)
    cases = [
        ("leds 0xff0000 FaceLeds",
         {"action": "leds", "params": {"color": "0xff0000", "led": "FaceLeds"}}, True),
        ("leds #00ff00 EarLeds",
         {"action": "leds", "params": {"color": "#00ff00", "led": "EarLeds"}}, True),
        ("leds 0000ff (no prefix)",
         {"action": "leds", "params": {"color": "0000ff"}}, True),
        ("leds int",
         {"action": "leds", "params": {"color": 16711680}}, True),
        ("leds color invalido",
         {"action": "leds", "params": {"color": "no-es-un-color"}}, True),
        ("leds_off", {"action": "leds_off", "params": {}}, True),
        ("posture Stand", {"action": "posture", "params": {"name": "Stand"}}, True),
        ("battery", {"action": "battery", "params": {}}, True),
        ("speak",
         {"action": "speak", "params": {"text": "hola", "language": "Spanish"}}, True),
        ("set_language", {"action": "set_language", "params": {"language": "Spanish"}}, True),
        ("get_joints", {"action": "get_joints", "params": {}}, True),
        ("get_sensors", {"action": "get_sensors", "params": {}}, True),
        ("capture", {"action": "capture", "params": {}}, True),
        ("list_behaviors", {"action": "list_behaviors", "params": {}}, True),
        ("unknown action", {"action": "no_existe", "params": {}}, False),
        # --- audio (panel: control de volumen + medidor de microfonos) ---
        ("get_volume", {"action": "get_volume", "params": {}}, True),
        ("set_volume 70", {"action": "set_volume", "params": {"level": 70}}, True),
        ("set_volume >100 clampa",
         {"action": "set_volume", "params": {"level": 150}}, True),
        ("set_volume <0 clampa",
         {"action": "set_volume", "params": {"level": -5}}, True),
        ("get_mic_level", {"action": "get_mic_level", "params": {}}, True),
        # --- camara: NAOqi no da JPEG, el bridge manda pixeles crudos ---
        ("capture_b64", {"action": "capture_b64", "params": {}}, True),
        # --- escucha (ASR): antes fallaba SIEMPRE ---
        # El stub reproduce los dos fallos reales (event subscriber roto y
        # motor sordo sin `subscribe`), asi que este caso solo pasa con el
        # patron corregido.
        ("listen reconoce palabra",
         {"action": "listen", "params": {"timeout": 4, "language": "Spanish"}}, True),
    ]

    ready, replies, stderr = run_bridge_session([c[1] for c in cases])

    print("=" * 66)
    print("OFFLINE BRIDGE PROTOCOL TEST (%s)" % os.path.basename(PY))
    print("=" * 66)

    check("handshake", bool(ready and ready.get("event") == "ready"),
          json.dumps(ready))

    labels = [c[0] for c in cases]
    expected = [c[2] for c in cases]

    for label, want_ok, rep in zip(labels, expected, replies):
        if rep is None:
            check(label, False, "no reply")
        elif "__non_json__" in rep:
            check(label, False, "non-JSON reply: %r" % rep["__non_json__"])
        else:
            ok = (rep.get("success") is True) == want_ok
            check(label, ok, json.dumps(rep)[:90])

    # --- detailed assertions ------------------------------------------ #
    print("-" * 66)

    c1 = replies[0] or {}
    check("leds color -> int", c1.get("color") == 0xFF0000,
          "0xff0000 => %r" % c1.get("color"))
    check("leds led respetado", c1.get("led") == "FaceLeds",
          "led=%r" % c1.get("led"))

    c2 = replies[1] or {}
    check("leds #hex -> int", c2.get("color") == 0x00FF00,
          "#00ff00 => %r" % c2.get("color"))

    c3 = replies[2] or {}
    check("leds sin prefijo", c3.get("color") == 0x0000FF,
          "0000ff => %r" % c3.get("color"))

    c4 = replies[3] or {}
    check("leds int intacto", c4.get("color") == 16711680,
          "int => %r" % c4.get("color"))

    c5 = replies[4] or {}
    check("leds no crashea con basura", c5.get("success") is True,
          "color=%r" % c5.get("color"))

    bat = replies[7] or {}
    check("battery percent", bat.get("percent") == 87,
          "percent=%r" % bat.get("percent"))

    pos = replies[6] or {}
    check("posture eco", pos.get("posture") == "Stand",
          "posture=%r (shadowing roto daba 'not callable')" % pos.get("posture"))

    joints = (replies[10] or {}).get("joints") or {}
    check("get_joints mapa", len(joints) == 3, "%d joints" % len(joints))

    beh = replies[13] or {}
    check("Event dentro de lista no rompe",
          beh.get("success") is True and isinstance(beh.get("behaviors"), list),
          json.dumps(beh)[:90])

    unk = replies[14] or {}
    check("unknown action controlado",
          unk.get("success") is False and "unknown_action" in str(unk.get("error")),
          json.dumps(unk)[:90])

    # --- audio ------------------------------------------------------- #
    gvol = replies[15] or {}
    check("get_volume lee del robot", gvol.get("volume") == 65,
          "volume=%r" % gvol.get("volume"))

    svol = replies[16] or {}
    check("set_volume aplica", svol.get("volume") == 70,
          "volume=%r" % svol.get("volume"))

    hi = replies[17] or {}
    check("set_volume >100 se clampa a 100", hi.get("volume") == 100,
          "volume=%r" % hi.get("volume"))

    lo = replies[18] or {}
    check("set_volume <0 se clampa a 0", lo.get("volume") == 0,
          "volume=%r" % lo.get("volume"))

    mic = replies[19] or {}
    energy = mic.get("energy") or {}
    check("get_mic_level devuelve 4 capsulas",
          mic.get("success") is True and len(energy) == 4,
          "energy=%r" % energy)
    check("get_mic_level nivel normalizado 0..1",
          isinstance(mic.get("level"), float) and 0.0 <= mic["level"] <= 1.0,
          "level=%r" % mic.get("level"))
    check("get_mic_level detecta que si oye",
          mic.get("hearing") is True, "hearing=%r" % mic.get("hearing"))
    check("get_mic_level via ALAudioDevice",
          mic.get("source") == "audio_device", "source=%r" % mic.get("source"))

    # --- camara ------------------------------------------------------ #
    cam = replies[20] or {}
    check("capture_b64 devuelve pixeles crudos",
          cam.get("encoding") == "raw_rgb" and "image_raw_b64" in cam,
          "encoding=%r keys=%s" % (cam.get("encoding"), sorted(cam.keys())))
    check("capture_b64 no miente con image_b64",
          "image_b64" not in cam,
          "el bridge NO debe enviar crudo etiquetado como jpeg")
    check("capture_b64 dimensiones coherentes",
          cam.get("width") == 4 and cam.get("height") == 2
          and cam.get("layers") == 3,
          "%sx%s layers=%s" % (cam.get("width"), cam.get("height"), cam.get("layers")))

    import base64 as _b64
    try:
        raw = _b64.b64decode(cam.get("image_raw_b64") or "")
    except Exception:
        raw = b""
    check("capture_b64 frame completo y conserva R/G/B",
          len(raw) == 4 * 2 * 3 and raw[:3] == b"\xff\x00\x00"
          and raw[3:6] == b"\x00\xff\x00" and raw[6:9] == b"\x00\x00\xff",
          "%d bytes head=%r" % (len(raw), raw[:9]))

    # --- escucha (ASR) ------------------------------------------------ #
    # Guardas de regresion de los DOS fallos que dejaban a NAO sordo:
    #   * `ALMemory.subscriber` esta roto -> el stub lo hace lanzar el error
    #     real, asi que volver a ese patron rompe este test.
    #   * sin `asr.subscribe` el motor no publica nada -> el stub devuelve
    #     vacio y `text` quedaria en "".
    lis = replies[21] or {}
    check("listen reconoce el texto dictado", lis.get("text") == "Hola",
          "text=%r conf=%r" % (lis.get("text"), lis.get("confidence")))
    check("listen marca matched", lis.get("matched") is True,
          "matched=%r" % lis.get("matched"))
    check("listen devuelve confianza", lis.get("confidence") == 0.885,
          "confidence=%r" % lis.get("confidence"))
    check("listen limpia marcadores de word-spotting",
          "<...>" not in (lis.get("text") or ""),
          "text=%r" % lis.get("text"))
    check("listen pausa el motor antes de setVocabulary",
          "vocabulary_warning" not in lis,
          "warning=%r" % lis.get("vocabulary_warning"))

    # Sala en silencio: debe agotar el timeout sin romper ni inventar texto.
    os.environ["NAO_STUB_ASR_SILENT"] = "1"
    try:
        _r2, replies2, _e2 = run_bridge_session([
            {"action": "listen", "params": {"timeout": 0.5}},
        ])
    finally:
        os.environ.pop("NAO_STUB_ASR_SILENT", None)
    silent = (replies2 or [{}])[0] or {}
    check("listen sin voz: success y text vacio",
          silent.get("success") is True and silent.get("text") == ""
          and silent.get("matched") is False,
          json.dumps(silent)[:90])

    if stderr.strip():
        print("-" * 66)
        print("STDERR (informativo):")
        print(stderr.strip()[:800])

    print("=" * 66)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("RESULT: %d/%d passed" % (passed, total))
    failed = [n for n, ok, _ in RESULTS if not ok]
    if failed:
        print("FAILED: " + ", ".join(failed))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
