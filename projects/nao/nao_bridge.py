# -*- coding: utf-8 -*-
"""
WIS NAO Bridge (Python 2.7)
===========================
Long-lived worker that loads the pynaoqi SDK and exposes NAO control
over a JSON-per-line stdin/stdout protocol.

Run by the Python 3.11 WIS ability `nao_robot`. Do NOT run under Python 3.
"""

from __future__ import print_function

import json
import sys
import time
import threading

try:
    from naoqi import ALProxy
except Exception as exc:  # noqa: BLE001
    print(json.dumps({"event": "error", "error": "naoqi_import_failed: %s" % exc}))
    sys.stdout.flush()
    sys.exit(1)

DEFAULT_IP = "172.20.10.9"
DEFAULT_PORT = 9559


def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


class NAO(object):
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.tts = None
        self.motion = None
        self.posture = None
        self.leds = None
        self.video = None
        self.memory = None
        self.battery_svc = None
        self.asr = None
        self.audio = None
        self._kg_thread = None
        self._kg_running = False

    def connect(self):
        self.tts = ALProxy("ALTextToSpeech", self.ip, self.port)
        self.motion = ALProxy("ALMotion", self.ip, self.port)
        self.posture = ALProxy("ALRobotPosture", self.ip, self.port)
        self.leds = ALProxy("ALLeds", self.ip, self.port)
        self.memory = ALProxy("ALMemory", self.ip, self.port)
        self.battery_svc = ALProxy("ALBattery", self.ip, self.port)
        try:
            self.video = ALProxy("ALVideoDevice", self.ip, self.port)
        except Exception:  # noqa: BLE001
            self.video = None
        try:
            self.asr = ALProxy("ALSpeechRecognition", self.ip, self.port)
        except Exception:  # noqa: BLE001
            self.asr = None
        try:
            self.audio = ALProxy("ALAudioDevice", self.ip, self.port)
        except Exception:  # noqa: BLE001
            self.audio = None
        return True

    # ------------------------------------------------------------------ #
    def speak(self, text, language="Spanish"):
        try:
            self.tts.setLanguage(language)
        except Exception:  # noqa: BLE001
            pass
        self.tts.say(text)
        return {"success": True, "said": text, "language": language}

    def set_language(self, language):
        self.tts.setLanguage(language)
        return {"success": True, "language": language}

    def move(self, x, y, theta):
        self.motion.moveTo(float(x), float(y), float(theta))
        return {"success": True}

    def stop_move(self):
        self.motion.stopMove()
        return {"success": True}

    def posture(self, name):
        self.posture.goToPosture(name, 0.6)
        return {"success": True, "posture": name}

    def set_angles(self, names, angles, speed=0.2):
        self.motion.setAngles(names, angles, float(speed))
        return {"success": True}

    def leds(self, color, led="AllLeds"):
        self.leds.fadeRGB(led, color, 0.3)
        return {"success": True}

    def leds_off(self):
        self.leds.fadeRGB("AllLeds", 0x000000, 0.3)
        return {"success": True}

    def battery(self):
        return {"success": True, "percent": self.battery_svc.getBatteryCharge()}

    def capture(self):
        if not self.video:
            return {"success": False, "error": "no_video_service"}
        name = "wis_cam"
        try:
            self.video.unsubscribe(name)
        except Exception:  # noqa: BLE001
            pass
        handle = self.video.subscribeCamera(name, 0, 2, 11, 5)
        img = self.video.getImageRemote(handle)
        self.video.unsubscribe(handle)
        if not img:
            return {"success": False, "error": "no_image"}
        return {
            "success": True,
            "width": img[0],
            "height": img[1],
            "data_len": len(img[6]),
        }

    def listen(self, timeout=6.0, language="Spanish"):
        if not self.asr:
            return {"success": False, "error": "no_asr_service"}
        vocab = ["hola", "si", "no", "gracias", "maestro", "ayuda", "adios"]
        self.asr.pause(True)
        self.asr.setLanguage(language)
        self.asr.setVocabulary(vocab, False)
        self.asr.pause(False)
        heard = {"text": None}

        def cb(key, value, msg):
            if key == "WordRecognized" and value and value[0]:
                heard["text"] = value[0]

        sub = self.memory.subscriber("WordRecognized")
        sub.signal.connect(cb)
        t0 = time.time()
        while time.time() - t0 < timeout and not heard["text"]:
            time.sleep(0.2)
        self.asr.pause(True)
        try:
            sub.signal.disconnect(cb)
        except Exception:  # noqa: BLE001
            pass
        return {"success": True, "text": heard["text"] or ""}

    # ------------------------------------------------------------------ #
    #  Autonomous kindergarten-teacher mode
    # ------------------------------------------------------------------ #
    def kindergarten_start(self, topic=""):
        if self._kg_running:
            return {"success": True, "already": True}
        self._kg_running = True
        self._kg_thread = threading.Thread(target=self._kg_loop, args=(topic,))
        self._kg_thread.daemon = True
        self._kg_thread.start()
        return {"success": True, "started": True}

    def kindergarten_stop(self):
        self._kg_running = False
        return {"success": True, "stopped": True}

    def _kg_loop(self, topic):
        self.leds.fadeRGB("FaceLeds", 0x66CCFF, 0.5)
        self.posture.goToPosture("Stand", 0.6)
        self.speak(
            "Hola ninos y ninas. Soy WIS, su maestra. Vamos a aprender juntos.",
            "Spanish",
        )
        while self._kg_running:
            time.sleep(1)
        self.leds.fadeRGB("AllLeds", 0x000000, 0.5)
        self.speak("Hasta luego, amigos.", "Spanish")


def main():
    ip = DEFAULT_IP
    port = DEFAULT_PORT
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--ip" and i + 1 < len(args):
            ip = args[i + 1]
        if a == "--port" and i + 1 < len(args):
            port = int(args[i + 1])

    nao = NAO(ip, port)
    try:
        nao.connect()
        out({"event": "ready", "connected": True, "ip": ip, "port": port})
    except Exception as exc:  # noqa: BLE001
        out({"event": "ready", "connected": False, "error": str(exc)})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:  # noqa: BLE001
            out({"success": False, "error": "bad_json"})
            continue
        action = msg.get("action")
        p = msg.get("params", {}) or {}
        if action == "quit":
            out({"success": True, "bye": True})
            break
        try:
            if action == "speak":
                res = nao.speak(p.get("text", ""), p.get("language", "Spanish"))
            elif action == "set_language":
                res = nao.set_language(p.get("language", "Spanish"))
            elif action == "move":
                res = nao.move(p.get("x", 0), p.get("y", 0), p.get("theta", 0))
            elif action == "walk_to":
                res = nao.move(p.get("x", 0), p.get("y", 0), p.get("theta", 0))
            elif action == "stop_move":
                res = nao.stop_move()
            elif action == "posture":
                res = nao.posture(p.get("name", "Stand"))
            elif action == "set_angles":
                res = nao.set_angles(p.get("names", []), p.get("angles", []), p.get("speed", 0.2))
            elif action == "leds":
                res = nao.leds(p.get("color", "0xffffff"), p.get("led", "AllLeds"))
            elif action == "leds_off":
                res = nao.leds_off()
            elif action == "battery":
                res = nao.battery()
            elif action == "capture":
                res = nao.capture()
            elif action == "listen":
                res = nao.listen(p.get("timeout", 6.0), p.get("language", "Spanish"))
            elif action == "kindergarten_start":
                res = nao.kindergarten_start(p.get("topic", ""))
            elif action == "kindergarten_stop":
                res = nao.kindergarten_stop()
            else:
                res = {"success": False, "error": "unknown_action: %s" % action}
        except Exception as exc:  # noqa: BLE001
            res = {"success": False, "error": str(exc)}
        out(res)


if __name__ == "__main__":
    main()
