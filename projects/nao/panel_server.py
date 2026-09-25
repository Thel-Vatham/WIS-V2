"""
NAO Control Panel Server (Python 3.11)
Serves the web UI and exposes a REST/WebSocket API to the NAO bridge.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except Exception:  # noqa: BLE001
    Image = None
    _PIL_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nao_panel")

app = FastAPI(title="NAO Control Panel")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths
ROOT = Path(__file__).resolve().parent
PANEL_DIR = ROOT / "panel"
BRIDGE_SCRIPT = ROOT / "nao_bridge.py"
PY27 = os.environ.get("NAO_PY27", r"C:\Python27\python.exe")
# IP/port configurables: si el robot cambia de red no hace falta editar codigo.
DEFAULT_NAO_IP = os.environ.get("NAO_IP", "172.20.10.9")
DEFAULT_NAO_PORT = int(os.environ.get("NAO_PORT", "9559"))
PYNAOQI_LIB = os.environ.get(
    "PYNAOQI_LIB",
    r"C:\Users\nicol\OneDrive\Documentos\NAO\pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649\lib",
)

# Make sure panel directory exists
PANEL_DIR.mkdir(exist_ok=True)

class NAOBridgeManager:
    def __init__(self, ip: str = None, port: int = None):
        self.ip = ip or DEFAULT_NAO_IP
        self.port = int(port or DEFAULT_NAO_PORT)
        self.proc = None
        self._lock = asyncio.Lock()
        # Ultimo handshake del bridge: permite distinguir "panel vivo" de
        # "robot alcanzable" sin adivinar por el colorcito del dot.
        self.last_ready: dict = {"connected": False, "error": "not_started"}
        # Backoff: un bridge muerto no debe reintentar el arranque (12s) en
        # cada comando de la telemetria; eso saturaba y bloqueaba el panel.
        self._last_start_attempt = 0.0
        self._start_retry_seconds = 15.0

    def start(self, timeout: float = 12.0, force: bool = False):
        """Arranca el bridge y espera el handshake SIN bloquear indefinidamente.

        Antes esto hacia `self.proc.stdout.readline()` en bucle con un deadline
        que solo se comprobaba *entre* lineas: si el robot no respondia, el
        readline se quedaba bloqueado para siempre y colgaba el arranque
        completo de uvicorn (la web no aceptaba ni una conexion).
        """
        if self.proc and self.proc.poll() is None:
            return self.last_ready.get("connected", False)

        if not force and self._last_start_attempt:
            elapsed = time.time() - self._last_start_attempt
            if elapsed < self._start_retry_seconds:
                return False
        self._last_start_attempt = time.time()

        env = dict(os.environ)
        env["PYTHONPATH"] = PYNAOQI_LIB
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            self.proc = subprocess.Popen(
                [PY27, str(BRIDGE_SCRIPT), "--ip", self.ip, "--port", str(self.port)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                bufsize=1,
                universal_newlines=True,
            )
        except Exception as e:
            logger.error(f"Failed to start bridge: {e}")
            self.last_ready = {"connected": False, "error": str(e)}
            return False

        ready = threading.Event()

        def _reader():
            try:
                for line in iter(self.proc.stdout.readline, ""):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except Exception:
                        continue
                    if msg.get("event") == "ready":
                        self.last_ready = msg
                        ready.set()
                        return
            except Exception:
                pass
            # El proceso murio sin handshake.
            if not ready.is_set():
                self.last_ready = {
                    "connected": False,
                    "error": "bridge_exited_without_handshake",
                }
                ready.set()

        threading.Thread(target=_reader, name="nao-bridge-handshake", daemon=True).start()

        if not ready.wait(timeout):
            # El robot no responde: NO colgamos el panel. Se sigue sirviendo la
            # web y los comandos fallaran con un motivo legible.
            self.last_ready = {
                "connected": False,
                "error": f"timeout esperando handshake de {self.ip}:{self.port}",
            }
            logger.warning("Bridge handshake timeout for %s:%s", self.ip, self.port)
            return False
        return self.last_ready.get("connected", False)

    def _read_reply(self):
        """Lee una linea de respuesta, saltando eventos (p.ej. un 'ready' tardio)."""
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                return line
            # El handshake pudo llegar tarde (timeout); no es una respuesta.
            if isinstance(msg, dict) and msg.get("event") == "ready":
                self.last_ready = msg
                continue
            return msg

    async def send_command(self, action: str, **params):
        async with self._lock:
            if not self.proc or self.proc.poll() is not None:
                if not await asyncio.to_thread(self.start):
                    return {
                        "success": False,
                        "error": (self.last_ready or {}).get("error", "bridge_dead"),
                    }
                    
            req = {"action": action, "params": params}
            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
            except Exception as e:
                return {"success": False, "error": str(e)}
                
            # Read response in a non-blocking way using asyncio
            loop = asyncio.get_event_loop()
            try:
                reply = await asyncio.wait_for(
                    loop.run_in_executor(None, self._read_reply),
                    timeout=10.0
                )
                if reply is None:
                    return {"success": False, "error": "bridge_closed"}
                if isinstance(reply, dict):
                    return reply
                return json.loads(reply)
            except Exception as e:
                return {"success": False, "error": str(e)}

def _raw_frame_to_jpeg_b64(raw_b64, width, height, swap_rb=False, flip=False):
    """Convierte los pixeles crudos RGB de NAOqi a un JPEG real.

    El bridge entrega pixeles crudos porque esta build de NAOqi no sabe
    codificar JPEG (colorSpace=21 devuelve YUV422, verificado en el robot).
    El navegador necesita un formato de imagen real; antes se le daba lo crudo
    etiquetado como JPEG y por eso la camara no mostraba nada.

    Devuelve (jpeg_b64, None) o (None, motivo_del_fallo).
    """
    if not _PIL_AVAILABLE:
        return None, "pillow_not_installed"
    if not width or not height:
        return None, "missing_dimensions"
    try:
        raw = base64.b64decode(raw_b64)
        expected = int(width) * int(height) * 3
        if len(raw) < expected:
            return None, "short_frame:%d<%d" % (len(raw), expected)
        img = Image.frombytes("RGB", (int(width), int(height)), raw[:expected])
        if swap_rb:
            r, g, b = img.split()
            img = Image.merge("RGB", (b, g, r))
        if flip:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode("ascii"), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


bridge = NAOBridgeManager()

@app.on_event("startup")
async def on_startup():
    # El handshake con el robot puede tardar; se lanza en segundo plano para
    # que la web empiece a servir de inmediato (antes bloqueaba uvicorn).
    asyncio.create_task(asyncio.to_thread(bridge.start))

@app.post("/api/nao/config")
async def nao_config(payload: dict = None):
    """Cambia la IP/puerto de NAO y reinicia el bridge (util si cambia de red)."""
    p = payload or {}
    ip = str(p.get("ip") or bridge.ip).strip()
    try:
        port = int(p.get("port") or bridge.port)
    except Exception:
        return JSONResponse(content={"success": False, "error": "invalid_port"})

    if bridge.proc and bridge.proc.poll() is None:
        try:
            bridge.proc.kill()
        except Exception:
            pass
    bridge.ip = ip
    bridge.port = port
    bridge.last_ready = {"connected": False, "error": "restarting"}
    connected = await asyncio.to_thread(lambda: bridge.start(force=True))
    return JSONResponse(content={
        "success": True,
        "connected": connected,
        "nao_ip": ip,
        "nao_port": port,
        **(bridge.last_ready or {}),
    })

@app.post("/api/nao/{action}")
async def nao_api(action: str, payload: dict = None):
    p = payload or {}
    res = await bridge.send_command(action, **p)

    # La camara entrega pixeles crudos: se codifican a JPEG antes de salir.
    if action == "capture_b64" and isinstance(res, dict) and res.get("success"):
        raw_b64 = res.get("image_raw_b64")
        if raw_b64:
            jpeg, err = _raw_frame_to_jpeg_b64(
                raw_b64,
                res.get("width"),
                res.get("height"),
                swap_rb=bool(p.get("swap_rb")),
                flip=bool(p.get("flip")),
            )
            if jpeg:
                res["image_b64"] = jpeg
                res["encoding"] = "jpeg"
            else:
                res["success"] = False
                res["error"] = "jpeg_encode_failed: %s" % err
            res.pop("image_raw_b64", None)

    return JSONResponse(content=res)

@app.get("/api/nao/status")
async def nao_status():
    """Estado real del bridge y del robot (no solo si el panel responde)."""
    alive = bool(bridge.proc and bridge.proc.poll() is None)
    return JSONResponse(content={
        "success": True,
        "bridge_alive": alive,
        "nao_ip": bridge.ip,
        "nao_port": bridge.port,
        **(bridge.last_ready or {}),
    })

# Realtime Telemetry Loop
@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    # El protocolo del bridge es secuencial (un round-trip por comando bajo lock),
    # asi que el audio se sondea a menor frecuencia que el resto.
    tick = 0
    volume_cache = None
    mic_cache = {"success": False, "error": "waiting"}
    batt = {}
    sensors = {}
    joints = {}
    try:
        while True:
            # Gather telemetry: battery, sensors, temperature
            alive = bool(bridge.proc and bridge.proc.poll() is None)
            if alive:
                batt = await bridge.send_command("battery")
                sensors = await bridge.send_command("get_sensors")
                joints = await bridge.send_command("get_joints")

                if tick % 2 == 0:  # ~1 Hz: energia de los 4 microfonos
                    mic = await bridge.send_command("get_mic_level")
                    mic_cache = mic if mic.get("success") else {
                        "success": False,
                        "error": mic.get("error", "mic_unavailable"),
                    }
                if tick % 4 == 0:  # ~2 Hz: volumen del altavoz
                    vol = await bridge.send_command("get_volume")
                    if vol.get("success"):
                        volume_cache = vol.get("volume")

            # Siempre se envia el estado, tambien cuando el bridge esta caido:
            # si no, la UI se quedaba en "Panel activo..." para siempre.
            await websocket.send_json({
                "battery": batt.get("percent", 0) if batt.get("success") else 0,
                "sensors": sensors if sensors.get("success") else {},
                "joints": joints.get("joints", {}) if joints.get("success") else {},
                "mic": mic_cache,
                "volume": volume_cache,
                "bridge": bridge.last_ready,
                "bridge_alive": alive,
            })
            tick += 1
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        logger.info("Telemetry client disconnected")

# Serve the web UI (must be added last to avoid intercepting /api)
app.mount("/", StaticFiles(directory=str(PANEL_DIR), html=True), name="panel")

if __name__ == "__main__":
    uvicorn.run("panel_server:app", host="0.0.0.0", port=7860, reload=True)
