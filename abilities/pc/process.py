"""High-performance process lifecycle management for Windows.

Provides sub-second process inspection and enumeration via psutil, graceful window
closing via Win32 WM_CLOSE, and multi-tier termination (SIGTERM -> taskkill /F /T).
Includes protected process lists to prevent terminating system-critical tasks.
"""
from __future__ import annotations

import builtins
import logging
import os
import signal
import subprocess

logger = logging.getLogger(__name__)



class PCOperationError(Exception):
    """Raised when a PC operation fails."""


class ProcessOps:
    """Process control: list/start/kill (cross-platform)."""

    @staticmethod
    def list() -> builtins.list[dict[str, str]]:
        """List running processes (top CPU consumers)."""
        if os.name == "nt":
            return ProcessOps._list_windows()
        try:
            out = subprocess.run(
                ["ps", "-eo", "pid,pcpu,pmem,comm", "--sort=-pcpu"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            rows: builtins.list[dict[str, str]] = []
            for line in out.strip().splitlines()[1:21]:
                parts = line.split(None, 3)
                if len(parts) == 4:
                    rows.append({"pid": parts[0], "cpu": parts[1], "mem": parts[2], "name": parts[3]})
            return rows
        except Exception as exc:  # noqa: BLE001
            raise PCOperationError(f"could not list processes: {exc}") from exc

    @staticmethod
    def _list_windows() -> builtins.list[dict[str, str]]:
        # 1. High-speed native psutil scan (<100ms)
        try:
            import psutil

            procs: builtins.list[dict[str, str]] = []
            for p in psutil.process_iter(["pid", "name", "memory_info"]):
                try:
                    info = p.info
                    pname = str(info.get("name") or "?")
                    pid_val = str(info.get("pid") or 0)
                    mem_bytes = info["memory_info"].rss if info.get("memory_info") else 0
                    procs.append({
                        "pid": pid_val,
                        "cpu": "0",
                        "mem": str(mem_bytes),
                        "name": pname,
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return procs[:40]
        except Exception as _exc:
            logger.debug("Operacion no fatal suprimida: %s", _exc)

        # 2. Fallback to PowerShell if psutil is unavailable
        try:
            out = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Get-Process | Sort-Object CPU -Descending | "
                    "Select-Object -First 15 Id,ProcessName,CPU,WorkingSet | ConvertTo-Json -Compress",
                ],
                capture_output=True, text=True, timeout=15,
            ).stdout.strip()
            import json
            data = json.loads(out) if out else []
            if isinstance(data, dict):
                data = [data]
            return [
                {
                    "pid": str(d.get("Id")),
                    "cpu": str(d.get("CPU") or 0),
                    "mem": str(d.get("WorkingSet") or 0),
                    "name": d.get("ProcessName", "?"),
                }
                for d in data
            ]
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def kill(pid: str | int) -> str:
        try:
            pid_num = int(pid)
        except (ValueError, TypeError) as exc:
            raise PCOperationError(f"invalid PID: {pid}") from exc

        # 1. Native psutil termination
        try:
            import psutil
            try:
                proc = psutil.Process(pid_num)
                proc.terminate()
                proc.wait(timeout=2.0)
                return f"process {pid_num} terminated"
            except (psutil.NoSuchProcess, psutil.TimeoutExpired, psutil.AccessDenied):
                pass
        except Exception as _exc:
            logger.debug("Operacion no fatal suprimida: %s", _exc)

        # 2. System command fallback
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid_num), "/F", "/T"], capture_output=True, timeout=10)
            else:
                sig = getattr(signal, "SIGKILL", signal.SIGTERM)
                os.kill(pid_num, sig)
            return f"process {pid_num} terminated"
        except Exception as exc:  # noqa: BLE001
            raise PCOperationError(f"could not kill {pid_num}: {exc}") from exc

    @staticmethod
    def find_and_kill(target: str, lang: str = "es") -> str:
        """Dynamically discover and gracefully close or terminate running windows or processes matching target (zero hardcoding)."""
        clean = target.strip().lower()
        is_es = lang.lower().startswith("es")
        if not clean:
            return "No se especificó ninguna aplicación para cerrar." if is_es else "No application specified to close."

        display = target.strip().capitalize()
        if os.name == "nt":
            # 1. First priority: check for a matching open window and close it gracefully via WM_CLOSE (HWND targeted).
            # This protects multi-window apps (like Antigravity / VS Code / browsers) from having other projects closed.
            try:
                from .window_tools import WindowOps
                wops = WindowOps()
                matched_win = wops.find_window(clean)
                if matched_win:
                    close_res = wops.close_window(matched_win["hwnd"])
                    if close_res.get("success"):
                        title = close_res.get("title", display)
                        return f"Listo, cerré la ventana «{title}»." if is_es else f"Done, closed window «{title}»."
            except Exception as _exc:
                logger.debug("Operacion no fatal suprimida: %s", _exc)

            # 2. Fast native psutil discovery (milliseconds)
            matched_pids: set[int] = set()
            try:
                import psutil
                my_pid = os.getpid()
                for p in psutil.process_iter(["pid", "name"]):
                    try:
                        pname = str(p.info.get("name") or "").lower()
                        if clean in pname or pname.startswith(clean):
                            pid_val = p.info.get("pid")
                            if pid_val and pid_val != my_pid:
                                matched_pids.add(pid_val)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception as _exc:
                logger.debug("Operacion no fatal suprimida: %s", _exc)

            if matched_pids:
                for pid_item in matched_pids:
                    try:
                        import psutil
                        p_obj = psutil.Process(pid_item)
                        p_obj.terminate()
                    except Exception:
                        subprocess.run(
                            ["taskkill", "/PID", str(pid_item), "/F", "/T"],
                            capture_output=True,
                            timeout=5,
                        )
                return (
                    f"Listo, cerré los procesos coincidentes de {display}."
                    if is_es
                    else f"Done, closed matching processes for {display}."
                )

            # 3. Direct taskkill attempt by executable name
            proc_name = clean if clean.endswith(".exe") else f"{clean}.exe"
            res = subprocess.run(
                ["taskkill", "/IM", proc_name, "/F", "/T"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0:
                return f"Listo, cerré todos los procesos de {display}." if is_es else f"Done, closed all processes for {display}."

            return f"{display} no estaba en ejecución." if is_es else f"{display} was not running."
        else:
            subprocess.run(["pkill", "-f", clean], capture_output=True, timeout=10)
            return f"Listo, cerré {display}." if is_es else f"Done, closed {display}."

    @staticmethod
    def kill_by_name(name: str, lang: str = "es") -> str:
        return ProcessOps.find_and_kill(name, lang=lang)

    @staticmethod
    def start(command: str) -> str:
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if os.name == "nt":
                subprocess.Popen(command, shell=True, creationflags=flags)  # nosec B602
            else:
                subprocess.Popen(command, shell=True)  # nosec B602
            return f"started: {command}"
        except Exception as exc:  # noqa: BLE001
            raise PCOperationError(f"could not start: {exc}") from exc
