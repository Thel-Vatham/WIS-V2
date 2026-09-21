"""
WIS System Dashboard - FastAPI Backend
Real-time monitoring of CPU, RAM, processes and WIS logs.
"""
from __future__ import annotations

import os
import time
import asyncio
import datetime as dt
from collections import deque
from pathlib import Path

import psutil
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Root of WIS project (parent of dashboard/)
WIS_ROOT = BASE_DIR.parent
LOGS_DIR = WIS_ROOT / "logs"

app = FastAPI(title="WIS System Dashboard", version="1.0.0")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Prime psutil CPU measurement
psutil.cpu_percent(interval=None)

# Rolling history for real-time charts (last 60 samples)
HISTORY_LEN = 60
cpu_history: deque = deque(maxlen=HISTORY_LEN)
ram_history: deque = deque(maxlen=HISTORY_LEN)
net_history: deque = deque(maxlen=HISTORY_LEN)
_last_net = psutil.net_io_counters()


def _collect_metrics() -> dict:
    """Collect a single snapshot of system metrics."""
    global _last_net

    cpu = psutil.cpu_percent(interval=None)
    per_cpu = psutil.cpu_percent(interval=None, percpu=True)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage(str(WIS_ROOT.anchor or "C:\\"))
    boot = psutil.boot_time()

    net = psutil.net_io_counters()
    sent = net.bytes_sent - _last_net.bytes_sent
    recv = net.bytes_recv - _last_net.bytes_recv
    _last_net = net

    return {
        "timestamp": time.time(),
        "cpu": {
            "percent": cpu,
            "per_cpu": per_cpu,
            "count": psutil.cpu_count(logical=True),
            "freq": (psutil.cpu_freq().current if psutil.cpu_freq() else 0),
        },
        "memory": {
            "percent": mem.percent,
            "used": mem.used,
            "total": mem.total,
            "available": mem.available,
        },
        "swap": {
            "percent": swap.percent,
            "used": swap.used,
            "total": swap.total,
        },
        "disk": {
            "percent": disk.percent,
            "used": disk.used,
            "total": disk.total,
            "free": disk.free,
        },
        "network": {
            "sent_rate": sent,
            "recv_rate": recv,
            "sent_total": net.bytes_sent,
            "recv_total": net.bytes_recv,
        },
        "uptime": time.time() - boot,
        "process_count": len(psutil.pids()),
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/metrics")
async def api_metrics():
    m = _collect_metrics()
    cpu_history.append(m["cpu"]["percent"])
    ram_history.append(m["memory"]["percent"])
    net_history.append(m["network"]["sent_rate"] + m["network"]["recv_rate"])
    return JSONResponse(m)


@app.get("/api/processes")
async def api_processes(limit: int = 15):
    procs = []
    for p in psutil.process_iter(
        ["pid", "name", "cpu_percent", "memory_percent", "status", "username"]
    ):
        try:
            info = p.info
            info["memory_mb"] = (p.memory_info().rss / (1024 * 1024))
            procs.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda x: (x.get("cpu_percent") or 0), reverse=True)
    return JSONResponse({"processes": procs[:limit]})


def _tail_log(path: Path, lines: int = 200) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return list(deque(f, maxlen=lines))
    except Exception as exc:  # pragma: no cover
        return [f"[dashboard] error reading {path.name}: {exc}"]


@app.get("/api/logs")
async def api_logs(lines: int = 150, file: str | None = None):
    if not LOGS_DIR.exists():
        return JSONResponse({"file": None, "lines": ["[dashboard] logs directory not found"], "files": []})

    log_files = sorted(
        [p for p in LOGS_DIR.rglob("*") if p.is_file() and p.suffix in (".log", ".txt")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    names = [str(p.relative_to(LOGS_DIR)) for p in log_files]

    target = None
    if file:
        candidate = LOGS_DIR / file
        if candidate.exists():
            target = candidate
    if target is None and log_files:
        target = log_files[0]

    content = _tail_log(target, lines) if target else ["[dashboard] no log files found"]
    return JSONResponse({
        "file": str(target.relative_to(LOGS_DIR)) if target else None,
        "lines": content,
        "files": names,
    })


@app.get("/api/history")
async def api_history():
    return JSONResponse({
        "cpu": list(cpu_history),
        "ram": list(ram_history),
        "net": list(net_history),
        "length": HISTORY_LEN,
    })


@app.get("/api/stream")
async def api_stream():
    """Server-Sent Events stream of live metrics."""
    async def event_gen():
        while True:
            m = _collect_metrics()
            cpu_history.append(m["cpu"]["percent"])
            ram_history.append(m["memory"]["percent"])
            net_history.append(m["network"]["sent_rate"] + m["network"]["recv_rate"])
            payload = {
                "cpu": m["cpu"]["percent"],
                "ram": m["memory"]["percent"],
                "disk": m["disk"]["percent"],
                "net": m["network"]["sent_rate"] + m["network"]["recv_rate"],
                "process_count": m["process_count"],
                "uptime": m["uptime"],
                "timestamp": m["timestamp"],
            }
            import json
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
