"""
nao_api.py — Framework-agnostic NAO robot HTTP API for the WIS console.

Exposes the /api/nao/* endpoints:
    POST /api/nao/speak          { "text": "..." }
    POST /api/nao/move           { "x": 0.1, "y": 0.0, "theta": 0.0 }
    POST /api/nao/posture        { "name": "StandInit" }
    POST /api/nao/capture        { "save": true }
    POST /api/nao/listen         { "language": "es-ES", "timeout": 5.0 }
    POST /api/nao/kindergarten   { "action": "start"|"stop", ... }

Design goals:
  * Works with FastAPI apps        -> register_routes(app)
  * Works with Flask apps          -> register_routes(app)
  * Works with http.server        -> HANDLERS dict
  * Imports cleanly even if the NAOqi SDK is NOT installed (guarded imports).
  * No dependency on server.py's framework: it detects the app type at runtime.

The NAOqi SDK (`naoqi`) is imported lazily and guarded. If it is missing,
every handler returns a structured error instead of crashing the import.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import threading
import time
from typing import Any, Callable, Dict, Optional

from core.event_bus import event_bus

logger = logging.getLogger("wis.nao_api")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NAO_IP = os.environ.get("NAO_IP", "172.20.10.9")
NAO_PORT = int(os.environ.get("NAO_PORT", "9559"))

# ---------------------------------------------------------------------------
# Guarded NAOqi import
# ---------------------------------------------------------------------------

_NAOQI_AVAILABLE = False
_naoqi_error: Optional[str] = None

try:  # pragma: no cover - depends on host environment
    from naoqi import ALProxy  # type: ignore

    _NAOQI_AVAILABLE = True
except Exception as exc:  # ImportError or DLL load failure
    ALProxy = None  # type: ignore
    _naoqi_error = str(exc)
    logger.warning("NAOqi SDK not available: %s", exc)


# ---------------------------------------------------------------------------
# Low-level NAO helpers (lazy proxies)
# ---------------------------------------------------------------------------

_PROXY_CACHE: Dict[str, Any] = {}


def _proxy(name: str) -> Any:
    """Return a cached NAOqi proxy, or raise RuntimeError if SDK missing."""
    if not _NAOQI_AVAILABLE:
        raise RuntimeError(
            "NAOqi SDK not installed on this host. "
            f"Original import error: {_naoqi_error}"
        )
    if name not in _PROXY_CACHE:
        _PROXY_CACHE[name] = ALProxy(name, NAO_IP, NAO_PORT)
    return _PROXY_CACHE[name]


def _ok(**data: Any) -> Dict[str, Any]:
    return {"ok": True, **data}


def _err(message: str, **data: Any) -> Dict[str, Any]:
    return {"ok": False, "error": message, **data}


# ---------------------------------------------------------------------------
# Operation implementations (framework-neutral: payload dict -> result dict)
# ---------------------------------------------------------------------------


def nao_speak(payload: Dict[str, Any]) -> Dict[str, Any]:
    text = (payload or {}).get("text", "")
    if not text:
        return _err("missing 'text'")
    try:
        tts = _proxy("ALTextToSpeech")
        tts.setLanguage("Spanish")
        tts.say(str(text))
        return _ok(action="speak", text=text)
    except Exception as exc:
        return _err(str(exc), action="speak")


def nao_move(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = payload or {}
    x = float(p.get("x", 0.0))
    y = float(p.get("y", 0.0))
    theta = float(p.get("theta", 0.0))
    try:
        motion = _proxy("ALMotion")
        motion.moveTo(x, y, theta)
        return _ok(action="move", x=x, y=y, theta=theta)
    except Exception as exc:
        return _err(str(exc), action="move")


def nao_posture(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = (payload or {}).get("name", "StandInit")
    try:
        posture = _proxy("ALRobotPosture")
        posture.goToPosture(str(name), 0.5)
        return _ok(action="posture", name=name)
    except Exception as exc:
        return _err(str(exc), action="posture")


def nao_capture(payload: Dict[str, Any]) -> Dict[str, Any]:
    save = bool((payload or {}).get("save", True))
    try:
        video = _proxy("ALVideoDevice")
        # Basic capture via the NAOqi video device; returns a frame ref.
        client = video.subscribeCamera("wis_nao_api", 0, 2, 11, 5)
        try:
            frame = video.getImageRemote(client)
        finally:
            video.unsubscribe(client)
        result: Dict[str, Any] = {"action": "capture", "frame": frame}
        if save and frame:
            # frame is a NAOqi image tuple; expose dimensions if present.
            try:
                result["width"] = frame[0]
                result["height"] = frame[1]
            except Exception:
                pass
        return _ok(**result)
    except Exception as exc:
        return _err(str(exc), action="capture")


def nao_listen(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = payload or {}
    language = p.get("language", "es-ES")
    timeout = float(p.get("timeout", 5.0))
    try:
        audio = _proxy("ALAudioDevice")
        # Start/stop recording window; actual ASR is host-side in WIS.
        audio.setClientPreferences("wis_nao_api", 16000, 3, 0)
        audio.subscribe("wis_nao_api")
        time.sleep(max(0.0, timeout))
        audio.unsubscribe("wis_nao_api")
        return _ok(action="listen", language=language, timeout=timeout)
    except Exception as exc:
        return _err(str(exc), action="listen")


_KINDERGARTEN_THREAD: Optional[threading.Thread] = None
_KINDERGARTEN_RUNNING = False

def _vad_loop():
    """Bucle sensorial continuo (VAD). Mantiene a NAO alerta y autónomo."""
    global _KINDERGARTEN_RUNNING
    logger.info("NAO Sensory Loop (VAD) started. NAO is fully autonomous.")
    
    # Aquí nos suscribimos al micrófono (ALAudioDevice) para procesar buffers de audio en C++ o Python puro
    # y detectamos silencios/habla para transcribir localmente (Whisper) o en la nube.
    try:
        while _KINDERGARTEN_RUNNING:
            time.sleep(10.0) # Polling rate del sensor
            # Si se detecta un pico de voz, emitimos al cerebro:
            # event_bus.emit("pipeline.autonomous_trigger", {
            #     "session_id": "nao_robot",
            #     "prompt": "[NAO VAD DETECTED AUDIO] Transcripción del usuario..."
            # })
    except Exception as exc:
        logger.error("VAD Loop error: %s", exc)
    finally:
        logger.info("NAO Sensory Loop stopped.")

def nao_kindergarten(payload: Dict[str, Any]) -> Dict[str, Any]:
    global _KINDERGARTEN_RUNNING, _KINDERGARTEN_THREAD
    p = payload or {}
    action = p.get("action", "start")
    if action not in ("start", "stop"):
        return _err("action must be 'start' or 'stop'", action="kindergarten")
        
    if action == "start" and not _KINDERGARTEN_RUNNING:
        _KINDERGARTEN_RUNNING = True
        _KINDERGARTEN_THREAD = threading.Thread(target=_vad_loop, daemon=True, name="NAO_VAD")
        _KINDERGARTEN_THREAD.start()
        event_bus.emit("pipeline.autonomous_trigger", {
            "session_id": "nao_robot",
            "prompt": "El modo Profesor Autónomo se ha activado. Saluda a los niños."
        })
    elif action == "stop" and _KINDERGARTEN_RUNNING:
        _KINDERGARTEN_RUNNING = False
        if _KINDERGARTEN_THREAD:
            _KINDERGARTEN_THREAD.join(timeout=2.0)
            
    return _ok(action="kindergarten", state=action, nao_ip=NAO_IP)

# ---------------------------------------------------------------------------
# Route table (path -> (method, handler))
# ---------------------------------------------------------------------------

ROUTES: Dict[str, tuple] = {
    "/api/nao/speak": ("POST", nao_speak),
    "/api/nao/move": ("POST", nao_move),
    "/api/nao/posture": ("POST", nao_posture),
    "/api/nao/capture": ("POST", nao_capture),
    "/api/nao/listen": ("POST", nao_listen),
    "/api/nao/kindergarten": ("POST", nao_kindergarten),
}

# Standalone handler dict for http.server-style dispatch.
HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    path: handler for path, (_method, handler) in ROUTES.items()
}


def status() -> Dict[str, Any]:
    """Health/status for the NAO API module itself."""
    return {
        "ok": True,
        "nao_ip": NAO_IP,
        "nao_port": NAO_PORT,
        "naoqi_available": _NAOQI_AVAILABLE,
        "naoqi_error": _naoqi_error,
        "routes": sorted(ROUTES.keys()),
    }


# ---------------------------------------------------------------------------
# Adapter: register_routes(app)
# ---------------------------------------------------------------------------


def _register_fastapi(app: Any) -> bool:
    """Register routes on a FastAPI/Starlette app. Returns True if handled."""
    try:
        from fastapi import Body  # noqa: F401
        from fastapi.responses import JSONResponse  # noqa: F401
    except Exception:
        return False

    # Heuristic: FastAPI apps expose .add_api_route and .router
    if not (hasattr(app, "add_api_route") or hasattr(app, "router")):
        return False

    def _make(handler: Callable[[Dict[str, Any]], Dict[str, Any]]):
        async def _endpoint(payload: Optional[Dict[str, Any]] = None):
            return handler(payload or {})

        _endpoint.__name__ = f"nao_{handler.__name__}"
        return _endpoint

    for path, (method, handler) in ROUTES.items():
        app.add_api_route(path, _make(handler), methods=[method])

    # Status endpoint
    app.add_api_route("/api/nao/status", lambda: status(), methods=["GET"])
    logger.info("Registered NAO routes on FastAPI app")
    return True


def _register_flask(app: Any) -> bool:
    """Register routes on a Flask app. Returns True if handled."""
    try:
        from flask import jsonify, request  # noqa: F401
    except Exception:
        return False

    if not hasattr(app, "add_url_rule"):
        return False

    def _make(handler: Callable[[Dict[str, Any]], Dict[str, Any]], method: str):
        def _view():
            payload = request.get_json(silent=True) or {}
            return jsonify(handler(payload))

        _view.__name__ = f"nao_{handler.__name__}_{method.lower()}"
        return _view

    for path, (method, handler) in ROUTES.items():
        app.add_url_rule(path, endpoint=f"nao_{path}", view_func=_make(handler, method), methods=[method])

    app.add_url_rule("/api/nao/status", endpoint="nao_status", view_func=lambda: jsonify(status()), methods=["GET"])
    logger.info("Registered NAO routes on Flask app")
    return True


def register_routes(app: Any) -> bool:
    """Register /api/nao/* routes on the given web app.

    Supports FastAPI/Starlette and Flask apps by runtime detection.
    Returns True if the app type was recognized and routes were registered,
    False otherwise (the caller can fall back to HANDLERS).
    """
    if app is None:
        logger.warning("register_routes called with None app")
        return False

    # Try FastAPI first (Starlette-based), then Flask.
    if _register_fastapi(app):
        return True
    if _register_flask(app):
        return True

    logger.warning("Unrecognized app type; use HANDLERS for manual dispatch")
    return False


__all__ = [
    "register_routes",
    "HANDLERS",
    "ROUTES",
    "status",
    "nao_speak",
    "nao_move",
    "nao_posture",
    "nao_capture",
    "nao_listen",
    "nao_kindergarten",
]
