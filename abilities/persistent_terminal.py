"""
WIS Persistent Terminal Manager.
================================
Habilidad para crear y gestionar sesiones de terminal con estado
(background processes) que sobreviven entre ejecuciones de WIS.
Permite conexiones SSH interactivas y servidores en segundo plano.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict

from abilities.base import Ability

logger = logging.getLogger("wis.abilities.persistent_terminal")

# Estado global compartido entre instancias de la habilidad
_active_terminals: Dict[str, "TerminalSession"] = {}
_terminals_lock = threading.RLock()
_STATE_PATH = Path("Data") / "persistent_terminals.json"
_MAX_RESTARTS = 3
_RESTART_BACKOFF_SECONDS = 2.0


class TerminalSession:
    def __init__(self, name: str, cwd: str = None, startup_command: str = "", persistent: bool = False,
                 restart_count: int = 0):
        self.name = name
        self.cwd = cwd or os.getcwd()
        self.startup_command = startup_command
        self.persistent = persistent
        self.restart_count = restart_count
        self.next_restart_at = 0.0
        self.proc = None
        self.output_queue = queue.Queue()
        self.running = False
        self._stdout_thread = None
        self._stderr_thread = None

    def start(self):
        # En Windows usamos cmd.exe por defecto. En Linux usaríamos bash.
        shell_cmd = ["cmd.exe"] if os.name == "nt" else ["bash"]
        
        self.proc = subprocess.Popen(
            shell_cmd,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        self.running = True

        def _enqueue_output(out, q):
            for line in iter(out.readline, ""):
                if line:
                    q.put(line)
            out.close()

        self._stdout_thread = threading.Thread(target=_enqueue_output, args=(self.proc.stdout, self.output_queue), daemon=True)
        self._stderr_thread = threading.Thread(target=_enqueue_output, args=(self.proc.stderr, self.output_queue), daemon=True)
        
        self._stdout_thread.start()
        self._stderr_thread.start()

    def send(self, command: str):
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError("La terminal no está corriendo.")
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def read_all(self) -> str:
        lines = []
        try:
            while True:
                lines.append(self.output_queue.get_nowait())
        except queue.Empty:
            pass
        return "".join(lines)

    def kill(self):
        self.running = False
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def is_alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)


class PersistentTerminalAbility(Ability):
    """Gestor de terminales y procesos en segundo plano con estado."""

    _supervisor_started = False
    _supervisor_guard = threading.Lock()

    @property
    def name(self) -> str:
        return "persistent_terminal"

    @property
    def description(self) -> str:
        return (
            "Crea y maneja terminales persistentes en segundo plano. "
            "Útil para correr servidores (npm run dev, python server.py), "
            "conectarse por SSH, o mantener el estado (cd dir). "
            "Las terminales sobreviven entre comandos de WIS."
        )

    @property
    def domain(self) -> str:
        return "system"

    def __init__(self) -> None:
        self._load_persistent_terminals()
        with self._supervisor_guard:
            if not self._supervisor_started:
                self._supervisor = threading.Thread(target=self._watchdog_loop, daemon=True)
                self._supervisor.start()
                type(self)._supervisor_started = True

    @staticmethod
    def _read_state() -> Dict[str, Dict[str, str]]:
        try:
            if _STATE_PATH.exists():
                data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load persistent terminals: %s", exc)
        return {}

    @staticmethod
    def _write_state() -> None:
        try:
            _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            state = {
                name: {
                    "cwd": session.cwd,
                    "startup_command": session.startup_command,
                    "persistent": session.persistent,
                    "restart_count": session.restart_count,
                }
                for name, session in _active_terminals.items()
                if session.persistent
            }
            _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not save persistent terminals: %s", exc)

    def _load_persistent_terminals(self) -> None:
        for name, state in self._read_state().items():
            if name in _active_terminals:
                continue
            cwd = state.get("cwd") or os.getcwd()
            if not os.path.isdir(cwd):
                logger.warning("Skipping terminal '%s': CWD does not exist: %s", name, cwd)
                continue
            session = TerminalSession(
                name, cwd, state.get("startup_command", ""),
                persistent=bool(state.get("persistent", True)),
                restart_count=int(state.get("restart_count", 0) or 0),
            )
            try:
                session.start()
                if session.startup_command:
                    session.send(session.startup_command)
                _active_terminals[name] = session
                logger.info("Persistent terminal restored: %s", name)
            except Exception as exc:
                logger.warning("Could not restore terminal '%s': %s", name, exc)

    def _watchdog_loop(self) -> None:
        while True:
            time.sleep(1.0)
            self.reconcile()

    def reconcile(self) -> None:
        """Detecta terminales muertas y las reinicia con backoff limitado."""
        now = time.monotonic()
        changed = False
        with _terminals_lock:
            sessions = list(_active_terminals.values())
        for session in sessions:
            if not session.persistent or session.is_alive() or not session.startup_command:
                continue
            if session.restart_count >= _MAX_RESTARTS or now < session.next_restart_at:
                continue
            try:
                session.start()
                session.send(session.startup_command)
                session.restart_count += 1
                session.next_restart_at = now + _RESTART_BACKOFF_SECONDS * (2 ** (session.restart_count - 1))
                changed = True
                logger.warning("Persistent terminal restarted: %s (attempt %d)", session.name, session.restart_count)
            except Exception as exc:
                session.restart_count += 1
                session.next_restart_at = now + _RESTART_BACKOFF_SECONDS * (2 ** max(session.restart_count - 1, 0))
                changed = True
                logger.warning("Could not restart terminal '%s': %s", session.name, exc)
        if changed:
            self._write_state()

    def rename_session(self, old_id: str, new_id: str) -> None:
        with _terminals_lock:
            session = _active_terminals.pop(old_id, None)
            if session:
                session.name = new_id
                _active_terminals[new_id] = session
                self._write_state()

    def delete_session(self, session_id: str) -> None:
        with _terminals_lock:
            session = _active_terminals.pop(str(session_id), None)
        if session:
            session.kill()
            self._write_state()

    def health(self) -> Dict[str, Any]:
        with _terminals_lock:
            terminals = list(_active_terminals.values())
        return {
            "total": len(terminals),
            "alive": sum(1 for session in terminals if session.is_alive()),
            "persistent": sum(1 for session in terminals if session.persistent),
            "degraded": [session.name for session in terminals
                          if session.persistent and not session.is_alive()],
        }

    def get_schema(self) -> list:
        return [
            {
                "action": "terminal_create",
                "description": "Crea una nueva terminal persistente con un nombre.",
                "params": {
                    "name": "str - Nombre único de la sesión (ej. 'Dashboard')",
                    "cwd": "str? - Directorio inicial (opcional)",
                    "persistent": "bool? - Restaurar automáticamente al iniciar WIS"
                }
            },
            {
                "action": "terminal_send",
                "description": "Envía un comando a una terminal activa.",
                "params": {
                    "name": "str - Nombre de la sesión",
                    "command": "str - Comando a ejecutar (ej. 'cd C:/', 'ssh pi@ip')",
                    "persistent": "bool? - Reejecutar este proceso al iniciar WIS"
                }
            },
            {
                "action": "terminal_read",
                "description": "Lee el output acumulado de una terminal activa.",
                "params": {
                    "name": "str - Nombre de la sesión"
                }
            },
            {
                "action": "terminal_list",
                "description": "Lista todas las terminales activas.",
                "params": {}
            },
            {
                "action": "terminal_kill",
                "description": "Mata forzosamente una terminal activa.",
                "params": {
                    "name": "str - Nombre de la sesión"
                }
            }
        ]

    async def execute(self, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        
        if action == "terminal_create":
            name = params.get("name")
            if not name:
                return {"success": False, "error": "Falta el nombre de la terminal."}
            if name in _active_terminals:
                return {"success": True, "message": f"La terminal '{name}' ya existe."}
            
            cwd = params.get("cwd")
            persistent = bool(params.get("persistent", False))
            session = TerminalSession(name, cwd, persistent=persistent)
            session.start()
            with _terminals_lock:
                _active_terminals[name] = session
            self._write_state()
            return {"success": True, "message": f"Terminal '{name}' creada y en ejecución."}

        if action == "terminal_send":
            name = params.get("name")
            command = params.get("command", "")
            if name not in _active_terminals:
                return {"success": False, "error": f"Terminal '{name}' no encontrada."}
            
            session = _active_terminals[name]
            try:
                normalized = command.strip()
                if normalized.lower().startswith(("cd ", "chdir ")):
                    target = normalized.split(" ", 1)[1].strip().strip('"').strip("'")
                    resolved = os.path.abspath(os.path.join(session.cwd, target))
                    if os.path.isdir(resolved):
                        session.cwd = resolved
                        self._write_state()
                if params.get("persistent") and command.strip():
                    session.persistent = True
                    session.startup_command = command
                    self._write_state()
                session.send(command)
                # Damos un breve tiempo para que el output empiece a fluir
                await asyncio.sleep(0.5)
                output = session.read_all()
                return {"success": True, "output": output}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if action == "terminal_read":
            name = params.get("name")
            if name not in _active_terminals:
                return {"success": False, "error": f"Terminal '{name}' no encontrada."}
            
            session = _active_terminals[name]
            output = session.read_all()
            return {"success": True, "output": output}

        if action == "terminal_list":
            terms = []
            for name, sess in _active_terminals.items():
                terms.append({"name": name, "cwd": sess.cwd, "alive": sess.is_alive(),
                              "persistent": sess.persistent, "restart_count": sess.restart_count})
            return {"success": True, "terminals": terms}

        if action == "terminal_kill":
            name = params.get("name")
            if name not in _active_terminals:
                return {"success": False, "error": f"Terminal '{name}' no encontrada."}
            
            session = _active_terminals.pop(name)
            session.kill()
            self._write_state()
            return {"success": True, "message": f"Terminal '{name}' eliminada."}

        return {"success": False, "error": f"Acción desconocida: {action}"}
