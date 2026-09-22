"""
NAO Control Panel Server (Python 3.11)
Serves the web UI and exposes a REST/WebSocket API to the NAO bridge.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

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
PY27 = r"C:\Python27\python.exe"

# Make sure panel directory exists
PANEL_DIR.mkdir(exist_ok=True)

class NAOBridgeManager:
    def __init__(self, ip: str = "172.20.10.9", port: int = 9559):
        self.ip = ip
        self.port = port
        self.proc = None
        self._lock = asyncio.Lock()
        
    def start(self):
        if self.proc and self.proc.poll() is None:
            return True
        env = dict(os.environ)
        env["PYTHONPATH"] = r"C:\Users\nicol\OneDrive\Documentos\NAO\pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649\lib"
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
            # wait for ready
            end = time.time() + 15
            while time.time() < end:
                line = self.proc.stdout.readline()
                if not line: break
                try:
                    msg = json.loads(line.strip())
                    if msg.get("event") == "ready":
                        return msg.get("connected", False)
                except:
                    pass
        except Exception as e:
            logger.error(f"Failed to start bridge: {e}")
            return False
        return False
        
    async def send_command(self, action: str, **params):
        async with self._lock:
            if not self.proc or self.proc.poll() is not None:
                if not self.start():
                    return {"success": False, "error": "bridge_dead"}
                    
            req = {"action": action, "params": params}
            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
            except Exception as e:
                return {"success": False, "error": str(e)}
                
            # Read response in a non-blocking way using asyncio
            loop = asyncio.get_event_loop()
            try:
                line = await asyncio.wait_for(
                    loop.run_in_executor(None, self.proc.stdout.readline),
                    timeout=10.0
                )
                if not line:
                    return {"success": False, "error": "bridge_closed"}
                return json.loads(line.strip())
            except Exception as e:
                return {"success": False, "error": str(e)}

bridge = NAOBridgeManager()

@app.on_event("startup")
async def on_startup():
    bridge.start()

@app.post("/api/nao/{action}")
async def nao_api(action: str, payload: dict = None):
    res = await bridge.send_command(action, **(payload or {}))
    return JSONResponse(content=res)

# Realtime Telemetry Loop
@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Gather telemetry: battery, sensors, temperature
            if bridge.proc and bridge.proc.poll() is None:
                batt = await bridge.send_command("battery")
                sensors = await bridge.send_command("get_sensors")
                joints = await bridge.send_command("get_joints")
                await websocket.send_json({
                    "battery": batt.get("percent", 0) if batt.get("success") else 0,
                    "sensors": sensors if sensors.get("success") else {},
                    "joints": joints.get("joints", {}) if joints.get("success") else {},
                })
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        logger.info("Telemetry client disconnected")

# Serve the web UI (must be added last to avoid intercepting /api)
app.mount("/", StaticFiles(directory=str(PANEL_DIR), html=True), name="panel")

if __name__ == "__main__":
    uvicorn.run("panel_server:app", host="0.0.0.0", port=7860, reload=True)
