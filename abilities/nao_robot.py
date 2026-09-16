"""
WIS NAO Robot Ability
=====================
Bridges WIS (Python 3.11) to the NAOqi SDK (Python 2.7-only) through a
long-lived subprocess worker (`nao_bridge.py`), speaking JSON over stdio.

Exposes NAO's full control surface as a standard WIS Ability:
  - Speech (Spanish voice by default)
  - Motion / postures / joints
  - LEDs
  - Camera / vision
  - Microphone / speech recognition
  - Battery & system status
  - Autonomous kindergarten-teacher mode
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from abilities.base import Ability


PY27 = r"C:\Python27\python.exe"
# El puente vive dentro del proyecto aislado `Projects/nao/` (no en la raiz de
# WIS). Se mantienen respaldos por si el proyecto se movio o se archivo en old/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_NAO_BRIDGE_CANDIDATES = (
    _REPO_ROOT / "Projects" / "nao" / "nao_bridge.py",
    _REPO_ROOT / "nao" / "nao_bridge.py",
    _REPO_ROOT / "old" / "nao" / "nao_bridge.py",
)
BRIDGE = str(
    next(
        (p for p in _NAO_BRIDGE_CANDIDATES if p.is_file()),
        _NAO_BRIDGE_CANDIDATES[0],
    )
)
SDK_LIB = (
    r"C:\Users\nicol\OneDrive\Documentos\NAO"
    r"\pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649\lib"
)
DEFAULT_IP = "172.20.10.9"
DEFAULT_PORT = 9559


class NAORobotAbility(Ability):
    """Control and interact with a NAO robot through the NAOqi SDK."""

    name = "nao_robot"
    description = (
        "Control a NAO robot: speech (Spanish voice), motion, postures, LEDs, "
        "camera vision, microphone listening, battery status, and an autonomous "
        "kindergarten-teacher mode."
    )
    domain = "robotics"

    def __init__(self) -> None:
        super().__init__()
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._ip = DEFAULT_IP
        self._port = DEFAULT_PORT
        self._connected = False

    # ------------------------------------------------------------------ #
    #  Bridge lifecycle
    # ------------------------------------------------------------------ #
    def _env(self) -> Dict[str, str]:
        import os

        env = dict(os.environ)
        env["PYTHONPATH"] = SDK_LIB
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def _start_bridge(self) -> bool:
        if self._proc and self._proc.poll() is None:
            return True
        if not Path(PY27).exists():
            return False
        if not Path(BRIDGE).exists():
            return False
        self._proc = subprocess.Popen(
            [PY27, BRIDGE, "--ip", self._ip, "--port", str(self._port)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
            bufsize=1,
            universal_newlines=True,
        )
        # Wait for READY line
        deadline = time.time() + 20
        while time.time() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("event") == "ready":
                self._connected = bool(msg.get("connected"))
                return True
            if msg.get("event") == "error":
                return False
        return False

    def _send(self, action: str, **params: Any) -> Dict[str, Any]:
        with self._lock:
            if not self._start_bridge():
                return {"success": False, "error": "bridge_start_failed"}
            payload = {"action": action, "params": params}
            try:
                self._proc.stdin.write(json.dumps(payload) + "\n")
                self._proc.stdin.flush()
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "error": "write_failed: %s" % exc}
            deadline = time.time() + 60
            while time.time() < deadline:
                line = self._proc.stdout.readline()
                if not line:
                    return {"success": False, "error": "bridge_closed"}
                try:
                    return json.loads(line)
                except ValueError:
                    continue
            return {"success": False, "error": "timeout"}

    # ------------------------------------------------------------------ #
    #  Ability contract
    # ------------------------------------------------------------------ #
    def get_schema(self) -> list:
        return [
            {"action": "connect", "description": "Connect to NAO robot", "params": {"ip": "str?", "port": "int?"}},
            {"action": "speak", "description": "Speak given text", "params": {"text": "str", "language": "str? (default Spanish)"}},
            {"action": "set_language", "description": "Set system language", "params": {"language": "str"}},
            {"action": "move", "description": "Move with velocity", "params": {"x": "float", "y": "float", "theta": "float"}},
            {"action": "walk_to", "description": "Walk to absolute coordinates", "params": {"x": "float", "y": "float", "theta": "float"}},
            {"action": "stop_move", "description": "Stop current movement", "params": {}},
            {"action": "posture", "description": "Go to predefined posture", "params": {"name": "str (Stand|Sit|Crouch|LyingBack)"}},
            {"action": "set_angles", "description": "Set specific joint angles", "params": {"names": "list", "angles": "list", "speed": "float?"}},
            {"action": "leds", "description": "Set LED colors", "params": {"color": "str hex", "led": "str?"}},
            {"action": "leds_off", "description": "Turn off all LEDs", "params": {}},
            {"action": "capture", "description": "Capture image from camera", "params": {}},
            {"action": "listen", "description": "Listen and transcribe speech", "params": {"timeout": "float?", "language": "str?"}},
            {"action": "battery", "description": "Get battery level", "params": {}},
            {"action": "status", "description": "Check connection status", "params": {}},
            {"action": "kindergarten_start", "description": "Start autonomous interactive teacher mode", "params": {"topic": "str?"}},
            {"action": "kindergarten_stop", "description": "Stop teacher mode", "params": {}},
        ]

    async def execute(self, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        import asyncio
        params = params or {}
        if action == "status":
            return {
                "success": True,
                "connected": self._connected,
                "ip": self._ip,
                "port": self._port,
                "bridge_alive": bool(self._proc and self._proc.poll() is None),
            }
        if action == "connect":
            self._ip = params.get("ip", self._ip)
            self._port = int(params.get("port", self._port))
            self._stop_bridge()
            ok = await asyncio.to_thread(self._start_bridge)
            return {"success": ok, "connected": self._connected}
        if action == "kindergarten_stop":
            return await asyncio.to_thread(self._send, "kindergarten_stop")
        if action == "kindergarten_start":
            return await asyncio.to_thread(self._send, "kindergarten_start", topic=params.get("topic", ""))
        return await asyncio.to_thread(self._send, action, **params)

    def _stop_bridge(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write(json.dumps({"action": "quit"}) + "\n")
                self._proc.stdin.flush()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self._proc.kill()
        self._proc = None
        self._connected = False
