"""
WIS System Ability - System information and control.
Habilidad de sistema: informacion y control del sistema.
========================================
Provee acceso a informacion del sistema operativo (hora, fecha, recursos)
y permite ejecutar comandos de shell de forma controlada (whitelist).
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Optional

from .base import Ability

logger = logging.getLogger("wis.ability.system")


# --------------------------------------------------------------------------- #
# Autoproteccion del runtime de WIS
# --------------------------------------------------------------------------- #
# WIS corre DENTRO de un interprete Python. `close_application` ya protege su
# cierre, pero el agente encontro la vuelta: `taskkill /F /IM python.exe /T` o
# `Stop-Process -Name python` lanzados por la via de shell matan a WIS igual
# (incidente 2026-09-15: log congelado a mitad de turno, cero procesos vivos).
# Por eso el guard cubre TODAS las vias de ejecucion: shell, PowerShell y
# codigo Python. Cerrar un proceso ajeno sigue permitido.

_KILL_IMAGE_RE = re.compile(
    r"taskkill\b[^\n]*?/IM\s+\"?(?P<im1>[\w.\-]+)"
    r"|stop-process\b[^\n]*?-name\s+\"?(?P<im2>[\w.\-]+)"
    r"|pkill\b[^\n]*?(?:-f\s+)?\"?(?P<im3>[\w./\\\-]+)",
    re.IGNORECASE,
)

_KILL_PID_RE = re.compile(
    r"taskkill\b[^\n]*?/PID\s+(?P<pid1>\d+)"
    r"|stop-process\b[^\n]*?-id\s+(?P<pid2>\d+)"
    r"|\bkill\s+(?:-\w+\s+)?(?P<pid3>\d+)",
    re.IGNORECASE,
)


def _protected_images() -> set:
    """Nombres de imagen cuyo cierre mataria a WIS (en minusculas)."""
    names = {os.path.basename(sys.executable).lower()}
    if sys.argv:
        names.add(os.path.basename(str(sys.argv[0])).lower())
    try:
        import psutil  # type: ignore

        proc = psutil.Process(os.getpid())
        for candidate in (proc, proc.parent()):
            if candidate is not None:
                names.add(str(candidate.name()).lower())
    except Exception:
        pass
    names.discard("")
    names.discard("main.py")
    return names


def _protected_pids() -> set:
    """PIDs cuyo cierre mataria a WIS (propio y del padre)."""
    pids = {os.getpid()}
    try:
        import psutil  # type: ignore

        parent = psutil.Process(os.getpid()).parent()
        if parent is not None:
            pids.add(parent.pid)
    except Exception:
        pass
    return pids


def _kills_wis_runtime(payload: str) -> str:
    """Motivo si el payload mataria el runtime de WIS; cadena vacia si es seguro."""
    text = str(payload or "")
    if not text:
        return ""

    protected = _protected_images()
    stems = {n[:-4] if n.endswith(".exe") else n for n in protected}
    for match in _KILL_IMAGE_RE.finditer(text):
        target = (match.group("im1") or match.group("im2") or match.group("im3") or "").strip().lower()
        if not target:
            continue
        base = os.path.basename(target.replace("\\", "/"))
        stem = base[:-4] if base.endswith(".exe") else base
        if stem in stems or base in protected:
            return f"cierra '{target}', que es el runtime que ejecuta WIS"

    pids = _protected_pids()
    for match in _KILL_PID_RE.finditer(text):
        raw = match.group("pid1") or match.group("pid2") or match.group("pid3")
        if raw and int(raw) in pids:
            return f"cierra el PID {raw}, que es el proceso de WIS"
    return ""


def _self_protection_block(reason: str) -> dict:
    return {
        "success": False,
        "data": {"blocked_by": "self_protection"},
        "message": (
            f"Bloqueado por autoproteccion: el comando {reason}. "
            "Cerrarlo mataria a WIS y dejaria el turno muerto. "
            "Usa el nombre exacto del proceso hijo que quieres cerrar."
        ),
    }


class SystemAbility(Ability):
    """
    Habilidad de informacion y control del sistema.

    Notas de seguridad:
      - En modo 'safe' (por defecto), la accion 'run' SOLO permite comandos
        presentes en la whitelist (chequeo sobre el primer token).
      - En modo 'safe', las acciones 'execute_powershell' y 'run_python_code'
        estan BLOQUEADAS (ejecucion irrestricta de codigo).
      - El modo 'autonomous' habilita las capacidades completas (sin whitelist,
        code-exec permitido). Debe activarse de forma explicita y consciente.
      - Se aplica un timeout estricto a toda ejecucion.
    """

    # Whitelist de ejecutables permitidos para la accion 'run'.
    # El chequeo se hace sobre el primer token del comando.
    DEFAULT_ALLOWED = {
        "whoami", "hostname", "ipconfig", "ping", "echo",
        "date", "time", "systeminfo", "tasklist", "where",
        "python", "git", "dir",
    }

    # Modos de ejecucion:
    #   "safe"        -> 'run' solo permite la whitelist; PowerShell/Python BLOQUEADOS.
    #   "autonomous"  -> capacidades completas (whitelist desactivada, code-exec permitido).
    MODE_SAFE = "safe"
    MODE_AUTONOMOUS = "autonomous"

    def __init__(
        self,
        mode: str = "safe",
        timeout: int = 10,
        extra_allowed: Optional[set] = None,
    ):
        self.set_mode(mode)
        self._timeout = timeout
        self._allowed = set(self.DEFAULT_ALLOWED)
        if extra_allowed:
            self._allowed |= {str(x).lower().strip() for x in extra_allowed}
        self._timers = {}
        self._recent_image_opens: dict[str, float] = {}
        self._image_open_dedupe_seconds = 60.0
        self.session_cwds = {}
        self._session_state_path = Path("Data") / "wis_sessions.json"
        self._load_session_cwds()

    def _load_session_cwds(self) -> None:
        try:
            if self._session_state_path.exists():
                data = json.loads(self._session_state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.session_cwds = {
                        str(session): str(cwd)
                        for session, cwd in data.items()
                        if isinstance(cwd, str)
                    }
                    if "default" in self.session_cwds and "main" not in self.session_cwds:
                        self.session_cwds["main"] = self.session_cwds.pop("default")
                        self._save_session_cwds()
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load persistent session directories: %s", exc)

    def _save_session_cwds(self) -> None:
        try:
            self._session_state_path.parent.mkdir(parents=True, exist_ok=True)
            self._session_state_path.write_text(
                json.dumps(self.session_cwds, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not save persistent session directories: %s", exc)

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, val: str) -> None:
        self.set_mode(val)

    def set_mode(self, val: str) -> None:
        m = str(val or "safe").strip().lower()
        if m in ("secure", "safe"):
            self._mode = self.MODE_SAFE
        elif m in ("privileged", "autonomous"):
            self._mode = self.MODE_AUTONOMOUS
        else:
            self._mode = self.MODE_SAFE

    def _first_token(self, command: str) -> str:
        """Extrae y normaliza el primer token de un comando (basename sin extension)."""
        import os

        raw = (command or "").strip()
        # Quita comillas envolventes tipo "C:\\path\\prog.exe" ...
        if raw and raw[0] in ('"', "'"):
            quote = raw[0]
            end = raw.find(quote, 1)
            candidate = raw[1:end] if end > 0 else raw[1:]
        else:
            candidate = raw.split(None, 1)[0] if raw else ""
        if not candidate:
            return ""
        base = os.path.basename(candidate)
        name, _ext = os.path.splitext(base)
        return name.lower().strip()

    def _is_unrestricted_allowed(self) -> bool:
        """True solo si el modo habilita ejecucion irrestricta (PowerShell/Python)."""
        return (self._mode or "").strip().lower() in (self.MODE_AUTONOMOUS, "privileged", "autonomous")

    # ------------------------------------------------------------------ #
    # Metadatos requeridos por Ability
    # ------------------------------------------------------------------ #
    @property
    def name(self) -> str:
        return "system"

    @property
    def description(self) -> str:
        return "System information (time, date, info) and safe shell command execution."

    @property
    def domain(self) -> str:
        return "system"

    # ------------------------------------------------------------------ #
    # Ejecucion de acciones
    # ------------------------------------------------------------------ #
    async def execute(self, action: str, params: dict) -> dict:
        """
        Acciones soportadas:
          - time / get_current_time: hora actual del sistema.
          - date / get_current_date: fecha actual del sistema.
          - info / get_system_info:  informacion del SO y hardware.
          - run / execute_shell:     ejecuta comandos de shell (PowerShell / CMD).
          - execute_powershell:      ejecuta scripts/comandos de PowerShell nativos sin restricciones.
          - run_python_code:         genera y ejecuta scripts de Python en el entorno de runtime.
        """
        action = (action or "").lower().strip()

        if action in ("time", "get_current_time"):
            return self._get_time()
        if action in ("date", "get_current_date"):
            return self._get_date()
        if action in ("info", "get_system_info"):
            return self._get_info()
        if action in ("run", "execute_shell"):
            return await self._run_command(params)
        if action in ("execute_powershell", "powershell"):
            return await self._execute_powershell(params)
        if action in ("run_python_code", "python_script", "run_python"):
            return await self._run_python_code(params)
        if action == "open_application":
            return await self._open_application(params)
        if action == "check_application_running":
            return await self._check_application_running(params)
        if action == "close_application":
            return await self._close_application(params)
        if action == "set_timer":
            return await self._set_timer(params)
        if action == "check_timer_status":
            return await self._check_timer_status(params)
        if action == "set_volume":
            return await self._set_volume(params)
        if action == "get_volume":
            return await self._get_volume(params)
        if action in ("get_active_window", "active_window"):
            return await self._get_active_window()
        if action in ("get_process_list", "process_list"):
            return await self._get_process_list(params)
        if action in ("get_resource_usage", "resource_usage"):
            return self._get_resource_usage()
        if action == "rename_session":
            return self._rename_session_action(params)

        return {
            "success": False,
            "data": None,
            "message": f"Accion de sistema no reconocida: '{action}'.",
        }

    def rename_session(self, old_id: str, new_id: str) -> None:
        """Migra el directorio de trabajo actual (CWD) de la sesion."""
        if old_id in self.session_cwds and old_id != new_id:
            self.session_cwds[new_id] = self.session_cwds.pop(old_id)
            self._save_session_cwds()

    def clear_session(self, session_id: str) -> None:
        """Elimina el CWD persistido de una sesión borrada."""
        if self.session_cwds.pop(str(session_id), None) is not None:
            self._save_session_cwds()

    def _rename_session_action(self, params: dict) -> dict:
        old_id = str(params.get("_session_id", ""))
        new_id = str(params.get("new_id", "")).strip()
        if not new_id:
            return {"success": False, "message": "Falta new_id."}
        
        # El motor central (app) debe manejar la migración completa enviando un evento,
        # pero la habilidad puede realizar su propia migración local:
        self.rename_session(old_id, new_id)
        # Notificar a traves de event_bus podria ser ideal, pero por simplicidad
        # asumimos que la interfaz o el motor de eventos orquestan el resto.
        return {"success": True, "message": f"Sesión renombrada a '{new_id}'. (Requiere recarga si la UI no escuchó el evento)."}

    def _get_time(self) -> dict:
        """Devuelve la hora actual con formato HH:MM:SS."""
        now = datetime.now()
        return {
            "success": True,
            "data": {"time": now.strftime("%H:%M:%S")},
            "message": now.strftime("Current system time is %H:%M:%S."),
        }

    def _get_date(self) -> dict:
        """Devuelve la fecha actual con formato largo."""
        now = datetime.now()
        return {
            "success": True,
            "data": {"date": now.strftime("%Y-%m-%d"), "weekday": now.strftime("%A")},
            "message": now.strftime("Today is %A, %B %d, %Y."),
        }

    def _get_info(self) -> dict:
        """Recolecta informacion basica del sistema operativo y hardware."""
        try:
            import os

            info = {
                "os": platform.system(),
                "os_release": platform.release(),
                "os_version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "python_version": platform.python_version(),
                "hostname": platform.node(),
                "cpu_count": os.cpu_count(),
            }
            return {
                "success": True,
                "data": info,
                "message": f"{info['os']} {info['os_release']} on {info['machine']}.",
            }
        except Exception as exc:
            return {"success": False, "data": None, "message": f"Error reading system info: {exc}"}

    async def _run_command(self, params: dict) -> dict:
        """Ejecuta un comando de shell.

        En modo 'safe' solo se permiten comandos cuya cabecera (primer token)
        este en la whitelist. En modo 'autonomous' se permite cualquier comando.
        """
        command = str(params.get("command", "")).strip()
        if not command:
            return {"success": False, "data": None, "message": "Comando vacio."}

        _guard = _kills_wis_runtime(command)
        if _guard:
            return _self_protection_block(_guard)

        image_path = self._image_open_path(command)
        if image_path:
            now = time.monotonic()
            previous = self._recent_image_opens.get(image_path)
            if previous is not None and now - previous < self._image_open_dedupe_seconds:
                return {
                    "success": True,
                    "data": {"skipped": True, "path": image_path},
                    "message": "Apertura omitida: la misma imagen ya fue abierta recientemente.",
                }
            self._recent_image_opens[image_path] = now
            self._recent_image_opens = {
                path: opened_at
                for path, opened_at in self._recent_image_opens.items()
                if now - opened_at < self._image_open_dedupe_seconds
            }

        # --- Whitelist enforcement (modo safe) ---
        if not self._is_unrestricted_allowed():
            token = self._first_token(command)
            if not token:
                return {"success": False, "data": None, "message": "Comando invalido."}
            if token not in self._allowed and not (token in ("cd", "chdir") and command.startswith("cd ")):
                return {
                    "success": False,
                    "data": {"token": token, "allowed": sorted(self._allowed)},
                    "message": f"Comando '{token}' bloqueado: fuera de la whitelist (modo safe).",
                }

        timeout = float(params.get("timeout") or self._timeout)
        session_id = str(params.get("_session_id", "default"))
        working_dir = str(params.get("working_dir") or params.get("cwd") or "").strip() or None
        
        try:
            import os
            cwd = working_dir if (working_dir and os.path.isdir(working_dir)) else self.session_cwds.get(session_id)
            
            # --- Intercept CD command for session state ---
            if command.lower().startswith("cd ") or command.lower().startswith("chdir "):
                cmd_parts = command.split(" ", 1)[1].strip()
                if cmd_parts.lower().startswith("/d "):
                    cmd_parts = cmd_parts[3:].strip()
                # Un comando compuesto ("cd X && dir") NO es una ruta. Sin separar
                # la cadena, `os.path.isdir` recibe "X && dir" y el comando entero
                # se rechazaba como directorio inexistente.
                chained = re.split(r"\s*(?:&&|\|\||;)\s*", cmd_parts, maxsplit=1)
                new_dir = chained[0].strip().strip('"').strip("'")
                remainder = chained[1].strip() if len(chained) > 1 else ""
                base_dir = cwd or os.getcwd()
                resolved = os.path.abspath(os.path.join(base_dir, new_dir))
                if os.path.isdir(resolved):
                    self.session_cwds[session_id] = resolved
                    self._save_session_cwds()
                    if not remainder:
                        return {"success": True, "message": f"Directorio cambiado a: {resolved}", "data": {"cwd": resolved}}
                    # El resto de la cadena se ejecuta YA dentro del nuevo directorio.
                    cwd = resolved
                    command = remainder
                else:
                    return {"success": False, "message": f"El directorio no existe: {resolved}"}
            
            fire_and_forget = str(params.get("fire_and_forget") or "false").lower() in ("true", "1", "yes")

            if fire_and_forget:
                subprocess.Popen(command, shell=True, cwd=cwd,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {
                    "success": True,
                    "data": {"fire_and_forget": True},
                    "message": f"Comando lanzado en segundo plano: {command[:80]}.",
                }

            cancel_event = params.get("_cancel_event")
            if cancel_event is not None:
                # Ruta abortable: el operador puede matar el comando desde la
                # consola sin esperar a que agote su timeout.
                return await self._run_command_cancellable(
                    command, timeout, cwd, cancel_event
                )

            # Sin canal de cancelacion: comportamiento historico.
            return await self._run_command_blocking(command, timeout, cwd)
        except Exception as exc:
            return {"success": False, "data": None, "message": f"Error ejecutando comando: {exc}"}

    # ------------------------------------------------------------------ #
    # Ejecucion abortable de comandos (cancel del operador)
    # ------------------------------------------------------------------ #
    @staticmethod
    async def _await_cancel(cancel_event: Any) -> None:
        """Se completa cuando el operador cancela el turno."""
        if cancel_event is None:
            await asyncio.sleep(3600)
            return
        wait = getattr(cancel_event, "wait", None)
        if callable(wait):
            await wait()
            return
        # Fallback por polling para implementaciones sin wait() asincrono.
        while True:
            if getattr(cancel_event, "is_set", lambda: False)():
                return
            await asyncio.sleep(0.2)

    @staticmethod
    def _kill_process_tree(pid: int) -> None:
        """Mata el proceso y todos sus hijos (necesario en Windows)."""
        try:
            subprocess.run(
                f"taskkill /F /T /PID {int(pid)}",
                shell=True,
                capture_output=True,
                timeout=3.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("taskkill fallo para pid %s: %s", pid, exc)

    async def _run_command_cancellable(
        self,
        command: str,
        timeout: float,
        cwd: Optional[str],
        cancel_event: Any,
    ) -> dict:
        """Ejecuta el comando en un subproceso abortable.

        `asyncio.to_thread(subprocess.run, ...)` NO se puede cancelar: el hilo
        sigue vivo hasta que el proceso hijo muere, y por eso un turno cancelado
        seguia ocupado (y su lock tambien). Aqui usamos create_subprocess_shell
        para poder matar el arbol de procesos en cuanto llega el cancel.
        """
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        except NotImplementedError:
            # Loop sin soporte de subprocesos (Selector en Windows): degradar
            # al comportamiento anterior en lugar de fallar.
            logger.warning("Sistema: loop sin soporte de subprocesos; cancel no disponible.")
            return await self._run_command_blocking(command, timeout, cwd)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "data": None, "message": f"Error ejecutando comando: {exc}"}

        comm = asyncio.ensure_future(proc.communicate())
        canceller = asyncio.ensure_future(self._await_cancel(cancel_event))
        try:
            done, _ = await asyncio.wait(
                {comm, canceller},
                timeout=float(timeout),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if canceller in done and comm not in done:
                self._kill_process_tree(proc.pid)
                await self._drain(proc, comm)
                return {
                    "success": False,
                    "data": None,
                    "message": "Comando cancelado por el operador.",
                }
            if comm not in done:
                self._kill_process_tree(proc.pid)
                await self._drain(proc, comm)
                return {
                    "success": False,
                    "data": None,
                    "message": f"Timeout de {timeout}s excedido.",
                }
            stdout_b, stderr_b = comm.result()
        except asyncio.CancelledError:
            # Turno abortado de forma dura: no dejar el subproceso huerfano.
            self._kill_process_tree(proc.pid)
            comm.cancel()
            raise
        finally:
            if not canceller.done():
                canceller.cancel()

        output = (stdout_b or b"").decode("utf-8", "replace").strip()
        errors = (stderr_b or b"").decode("utf-8", "replace").strip()
        return {
            "success": True,  # Siempre True para que el agente maneje el exit code
            "data": {
                "returncode": proc.returncode,
                "stdout": output[-3000:],
                "stderr": errors[-3000:],
                "cwd": cwd,
            },
            "message": f"Comando finalizado (exit={proc.returncode}).",
        }

    @staticmethod
    async def _drain(proc: Any, comm: "asyncio.Future") -> None:
        """Cierra el subproceso matado y descarta su salida pendiente."""
        comm.cancel()
        try:
            await proc.wait()
        except Exception:  # noqa: BLE001
            pass

    async def _run_command_blocking(
        self, command: str, timeout: float, cwd: Optional[str]
    ) -> dict:
        """Fallback no abortable (comportamiento historico)."""
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "data": None, "message": f"Timeout de {timeout}s excedido."}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "data": None, "message": f"Error ejecutando comando: {exc}"}
        output = (proc.stdout or "").strip()
        errors = (proc.stderr or "").strip()
        return {
            "success": True,
            "data": {
                "returncode": proc.returncode,
                "stdout": output[-3000:],
                "stderr": errors[-3000:],
                "cwd": cwd,
            },
            "message": f"Comando finalizado (exit={proc.returncode}).",
        }

    @staticmethod
    def _image_open_path(command: str) -> Optional[str]:
        """Extrae una imagen de un comando Windows `start` para deduplicarla."""
        match = re.match(r'^start\s+""\s+"([^"]+\.(?:png|jpe?g|gif|bmp|webp))"\s*$', command, re.IGNORECASE)
        if not match:
            return None
        return os.path.normcase(os.path.realpath(match.group(1)))

    async def _execute_powershell(self, params: dict) -> dict:
        """Ejecuta comandos o scripts de PowerShell nativos.

        Capacidad IRRESTRICTA: solo disponible en modo 'autonomous'.
        En modo 'safe' se bloquea para evitar ejecucion arbitraria de codigo.
        """
        if not self._is_unrestricted_allowed():
            return {
                "success": False,
                "data": None,
                "message": "PowerShell bloqueado en modo 'safe'. Requiere modo 'autonomous'.",
            }
        script = str(params.get("script") or params.get("command") or "").strip()
        if not script:
            return {"success": False, "data": None, "message": "Script de PowerShell vacio."}

        _guard = _kills_wis_runtime(script)
        if _guard:
            return _self_protection_block(_guard)

        timeout = float(params.get("timeout") or self._timeout)
        session_id = str(params.get("_session_id", "default"))
        fire_and_forget = str(params.get("fire_and_forget") or "false").lower() in ("true", "1", "yes")
        as_admin = str(params.get("as_admin") or "false").lower() in ("true", "1", "yes")
        working_dir = str(params.get("working_dir") or params.get("cwd") or "").strip() or None

        if as_admin:
            # Launch elevated via Start-Process
            ps_command = (
                f'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '
                f'"Start-Process powershell -Verb RunAs -ArgumentList \'-NoProfile -ExecutionPolicy Bypass -Command {script}\'"'
            )
        else:
            ps_command = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "{script}"'

        try:
            import os
            cwd = working_dir if (working_dir and os.path.isdir(working_dir)) else self.session_cwds.get(session_id)

            if fire_and_forget:
                subprocess.Popen(ps_command, shell=True, cwd=cwd,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {
                    "success": True,
                    "data": {"fire_and_forget": True},
                    "message": f"PowerShell lanzado en segundo plano.",
                }

            proc = await asyncio.to_thread(
                subprocess.run,
                ps_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            return {
                "success": True,  # Siempre True para que el agente procese el exit code
                "data": {
                    "returncode": proc.returncode,
                    "stdout": (proc.stdout or "").strip()[-3000:],
                    "stderr": (proc.stderr or "").strip()[-3000:],
                    "as_admin": as_admin,
                },
                "message": f"PowerShell finalizado (exit={proc.returncode}).",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "data": None, "message": f"PowerShell timeout de {timeout}s."}
        except Exception as exc:
            return {"success": False, "data": None, "message": f"Error en PowerShell: {exc}"}

    async def _run_python_code(self, params: dict) -> dict:
        """Genera y ejecuta codigo Python en el entorno de runtime de WIS.

        Capacidad IRRESTRICTA: solo disponible en modo 'autonomous'.
        En modo 'safe' se bloquea para evitar ejecucion arbitraria de codigo.
        """
        if not self._is_unrestricted_allowed():
            return {
                "success": False,
                "data": None,
                "message": "Ejecucion de Python bloqueada en modo 'safe'. Requiere modo 'autonomous'.",
            }
        code = str(params.get("code") or params.get("script") or "").strip()
        if not code:
            return {"success": False, "data": None, "message": "Codigo Python vacio."}

        _guard = _kills_wis_runtime(code)
        if _guard:
            return _self_protection_block(_guard)

        timeout = float(params.get("timeout") or self._timeout)
        working_dir = str(params.get("working_dir") or params.get("cwd") or "").strip() or None
        env_vars = params.get("env") or {}  # optional extra environment variables

        import sys
        import os
        import tempfile
        from pathlib import Path

        tmp_dir = Path(tempfile.gettempdir()) / "wis_runtime"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        script_file = tmp_dir / f"script_{int(asyncio.get_event_loop().time() * 1000)}.py"
        cwd = working_dir if (working_dir and os.path.isdir(working_dir)) else None

        # Build runtime environment
        run_env = os.environ.copy()
        if isinstance(env_vars, dict):
            run_env.update({str(k): str(v) for k, v in env_vars.items()})

        try:
            script_file.write_text(code, encoding="utf-8")
            cmd = f'"{sys.executable}" "{script_file}"'
            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=run_env,
            )

            # --- Autonomy Engine: Auto-Install Missing Modules ---
            import re
            if proc.returncode != 0:
                err_text = proc.stderr or ""
                match = re.search(r"ModuleNotFoundError: No module named '([^']+)'", err_text)
                if not match:
                    match = re.search(r"ImportError: No module named '([^']+)'", err_text)
                if match:
                    missing_mod = match.group(1)
                    # Resolucion de paquetes comunes donde el nombre de import no coincide con pip
                    mod_map = {
                        "PIL": "Pillow",
                        "cv2": "opencv-python",
                        "bs4": "beautifulsoup4",
                        "yaml": "pyyaml",
                        "sklearn": "scikit-learn",
                        "dotenv": "python-dotenv"
                    }
                    pkg_name = mod_map.get(missing_mod, missing_mod)
                    
                    pip_cmd = f'"{sys.executable}" -m pip install {pkg_name}'
                    pip_proc = await asyncio.to_thread(
                        subprocess.run, pip_cmd, shell=True, capture_output=True, text=True, timeout=120
                    )
                    
                    # Si instalo con exito, reintentamos la ejecucion original
                    if pip_proc.returncode == 0:
                        proc = await asyncio.to_thread(
                            subprocess.run, cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=run_env
                        )
            # -----------------------------------------------------

            return {
                "success": proc.returncode == 0,
                "data": {
                    "script_path": str(script_file),
                    "returncode": proc.returncode,
                    "stdout": (proc.stdout or "").strip()[-3000:],
                    "stderr": (proc.stderr or "").strip()[-3000:],
                },
                "message": f"Script Python ejecutado (exit={proc.returncode}).",
            }
        except subprocess.TimeoutExpired:
            timeout = float(params.get("timeout") or self._timeout)
            return {"success": False, "data": None, "message": f"Python script timeout ({timeout}s)."}
        except Exception as exc:
            return {"success": False, "data": None, "message": f"Error al ejecutar Python: {exc}"}
        finally:
            try:
                if script_file.exists():
                    script_file.unlink()
            except Exception:
                pass

    def _resolve_app_path_windows(self, app_name: str) -> Optional[str]:
        if platform.system() != "Windows":
            return None
        try:
            import winreg
        except ImportError:
            return None

        term = app_name.lower().strip()
        names = [term]
        if not term.endswith(".exe"):
            names.append(f"{term}.exe")

        # 1. Try Windows Registry App Paths
        for name in names:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    path_key = f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{name}"
                    with winreg.OpenKey(hive, path_key) as key:
                        val, _ = winreg.QueryValueEx(key, "")
                        if val:
                            return str(val).strip('"').strip("'")
                except FileNotFoundError:
                    continue

        # 2. Look in common user and global folders
        import os
        from pathlib import Path
        
        user_profile = os.environ.get("USERPROFILE") or "C:\\Users\\Home"
        search_dirs = [
            Path(user_profile) / "AppData" / "Local" / "Programs",
            Path("C:\\Program Files"),
            Path("C:\\Program Files (x86)"),
        ]
        
        for base_dir in search_dirs:
            if not base_dir.exists():
                continue
            for root, dirs, files in os.walk(str(base_dir)):
                depth = root[len(str(base_dir)):].count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                for f in files:
                    if f.lower().endswith(".exe") and term in f.lower():
                        return os.path.join(root, f)
        return None

    async def _open_application(self, params: dict) -> dict:
        """Abre aplicaciones instaladas en el sistema."""
        app_name = str(params.get("app_name") or params.get("name") or params.get("application") or "").strip()
        if not app_name:
            return {"success": False, "data": None, "message": "Nombre de aplicacion vacio."}

        mode = str(params.get("mode") or "visible").strip().lower()
        args = str(params.get("arguments") or "").strip()

        # Handle headless browser flag
        if mode in ("headless", "background"):
            browser_names = ("chrome", "opera", "edge", "firefox", "browser")
            if any(b in app_name.lower() for b in browser_names):
                if "--headless" not in args:
                    args = f"{args} --headless".strip()

        resolved_path = None
        if platform.system() == "Windows":
            resolved_path = self._resolve_app_path_windows(app_name)

        import shutil
        import os

        parts = app_name.split(None, 1)
        first_token = parts[0] if parts else ""

        is_valid_target = False
        target = resolved_path or app_name

        if os.path.exists(target):
            is_valid_target = True
        elif first_token and os.path.exists(first_token):
            is_valid_target = True
        elif resolved_path is not None:
            is_valid_target = True
        elif shutil.which(app_name) or (first_token and shutil.which(first_token)):
            is_valid_target = True
        else:
            common_sys_apps = {"calc", "notepad", "mspaint", "cmd", "powershell", "explorer", "taskmgr", "control", "write"}
            if app_name.lower().strip() in common_sys_apps or (first_token and first_token.lower().strip() in common_sys_apps):
                is_valid_target = True

        if not is_valid_target:
            return {
                "success": False,
                "data": None,
                "message": f"No se encontró la aplicación o archivo '{app_name}' en el sistema.",
            }

        try:
            if platform.system() == "Windows":
                import os
                target = resolved_path or app_name
                if mode in ("headless", "background"):
                    cmd = f'"{target}" {args}'.strip()
                    await asyncio.to_thread(
                        subprocess.Popen,
                        cmd,
                        shell=True,
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                    )
                else:
                    # Visible GUI application launch
                    if os.path.exists(target):
                        if target.lower().endswith(".exe"):
                            cmd_list = [target]
                            if args:
                                import shlex
                                cmd_list.extend(shlex.split(args))
                            await asyncio.to_thread(subprocess.Popen, cmd_list)
                        else:
                            await asyncio.to_thread(os.startfile, target)
                    else:
                        cmd = f'start "" "{target}"'
                        if args:
                            cmd += f' {args}'
                        await asyncio.to_thread(subprocess.Popen, cmd, shell=True)
            else:
                cmd = f'open -a "{app_name}"'
                if args:
                    cmd = f'{cmd} --args {args}'
                proc = await asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
                if proc.returncode != 0:
                    return {
                        "success": False,
                        "data": None,
                        "message": f"Error al abrir '{app_name}': {proc.stderr}",
                    }

            return {
                "success": True,
                "data": {
                    "app_name": app_name,
                    "resolved_path": resolved_path,
                    "mode": mode,
                    "arguments": args
                },
                "message": f"Aplicacion '{app_name}' iniciada correctamente en modo '{mode}' con argumentos '{args}'.",
            }
        except Exception as exc:
            return {"success": False, "data": None, "message": f"Error al abrir '{app_name}': {exc}"}

    async def _check_application_running(self, params: dict) -> dict:
        """Verifica si un proceso/aplicacion esta actualmente en ejecucion."""
        app_name = str(params.get("app_name") or params.get("name") or params.get("process") or "").strip()
        if not app_name:
            return {"success": False, "data": None, "message": "Nombre de aplicacion vacio."}

        try:
            if platform.system() == "Windows":
                cmd = f'tasklist /FI "IMAGENAME eq {app_name}*" /FO CSV'
            else:
                cmd = f'pgrep -i "{app_name}"'

            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            output = (proc.stdout or "").strip()
            is_running = False

            if platform.system() == "Windows":
                is_running = app_name.lower() in output.lower() and "INFO:" not in output
            else:
                is_running = proc.returncode == 0 and len(output) > 0

            return {
                "success": True,
                "data": {"app_name": app_name, "is_running": is_running},
                "message": f"La aplicacion '{app_name}' {'SI esta abierta' if is_running else 'NO esta abierta'}.",
            }
        except Exception as exc:
            return {"success": False, "data": None, "message": f"Error al verificar '{app_name}': {exc}"}

    async def _close_application(self, params: dict) -> dict:
        """Cierra/termina una aplicacion en ejecucion."""
        app_name = str(params.get("app_name") or params.get("name") or params.get("process") or "").strip()
        if not app_name:
            return {"success": False, "data": None, "message": "Nombre de aplicacion vacio."}

        # ── Autoproteccion (incidente 2026-09-15) ────────────────────────────
        # WIS corre DENTRO de un interprete Python. `taskkill /F /IM "python.exe"`
        # no distingue procesos: mato a WIS a si mismo a mitad de turno y dejo el
        # log congelado y el proceso muerto, sin forma de responder. Nunca
        # cerramos la imagen del interprete que nos hospeda ni la de un proceso
        # padre. Para cerrar un hijo concreto, cerrar por nombre exacto del hijo.
        def _norm_image(image: str) -> str:
            name = os.path.basename(str(image or "")).strip().lower()
            return name[:-4] if name.endswith(".exe") else name

        protected: set[str] = {_norm_image(sys.executable)}
        if sys.argv:
            protected.add(_norm_image(sys.argv[0]))
        try:
            import psutil  # type: ignore

            _self = psutil.Process(os.getpid())
            for _candidate in (_self, _self.parent()):
                if _candidate is not None:
                    protected.add(_norm_image(_candidate.name()))
        except Exception:
            pass
        protected.discard("")
        protected.discard("main.py")

        if _norm_image(app_name) in protected:
            return {
                "success": False,
                "data": {"app_name": app_name, "blocked_by": "self_protection"},
                "message": (
                    f"Bloqueado por autoproteccion: '{app_name}' es el runtime que ejecuta WIS "
                    f"({os.path.basename(sys.executable)}). Cerrarlo mataria a WIS y dejaria el "
                    f"turno muerto. Usa el nombre exacto del proceso hijo que quieres cerrar "
                    f"(p. ej. 'pythonw' si el hijo corre con pythonw.exe)."
                ),
            }

        # force=True: kill -9 / taskkill /F  |  force=False: graceful SIGTERM / WM_CLOSE
        force = str(params.get("force") or "true").lower() not in ("false", "0", "no", "graceful")
        timeout = float(params.get("timeout") or self._timeout)

        try:
            if platform.system() == "Windows":
                exe_name = app_name if app_name.endswith(".exe") else f"{app_name}.exe"
                if force:
                    cmd = f'taskkill /F /IM "{exe_name}"'
                else:
                    # Graceful: send WM_CLOSE without /F
                    cmd = f'taskkill /IM "{exe_name}"'
            else:
                if force:
                    cmd = f'pkill -9 -f "{app_name}"'
                else:
                    cmd = f'pkill -f "{app_name}"'

            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            close_type = "forzadamente" if force else "de forma ordenada"
            return {
                "success": proc.returncode == 0,
                "data": {"app_name": app_name, "returncode": proc.returncode, "force": force},
                "message": f"Aplicacion '{app_name}' cerrada {close_type}." if proc.returncode == 0 else f"No se pudo cerrar '{app_name}'.",
            }
        except Exception as exc:
            return {"success": False, "data": None, "message": f"Error al cerrar '{app_name}': {exc}"}

    async def _timer_worker(self, label: str, duration: float):
        try:
            await asyncio.sleep(duration)
            if label in self._timers:
                self._timers[label]["status"] = "completed"
        except asyncio.CancelledError:
            if label in self._timers:
                self._timers[label]["status"] = "cancelled"

    async def _set_timer(self, params: dict) -> dict:
        """Sets an asynchronous background timer."""
        import time
        duration = float(params.get("duration_seconds") or params.get("duration") or params.get("seconds") or 0.0)
        label = str(params.get("label") or params.get("timer_label") or params.get("name") or f"timer_{int(time.time())}").strip()

        if duration <= 0:
            return {"success": False, "data": None, "message": "Duration must be greater than 0 seconds."}

        if label in self._timers and self._timers[label]["status"] == "running":
            self._timers[label]["task"].cancel()

        self._timers[label] = {
            "start_time": time.time(),
            "duration": duration,
            "status": "running",
            "task": asyncio.create_task(self._timer_worker(label, duration))
        }

        return {
            "success": True,
            "data": {"label": label, "duration_seconds": duration},
            "message": f"Timer '{label}' set for {duration} seconds."
        }

    async def _check_timer_status(self, params: dict) -> dict:
        """Checks status of a timer."""
        import time
        label = str(params.get("timer_label") or params.get("label") or params.get("name") or "").strip()

        if not label:
            active_timers = []
            for k, v in self._timers.items():
                if v["status"] == "running":
                    elapsed = time.time() - v["start_time"]
                    remaining = max(0.0, v["duration"] - elapsed)
                    active_timers.append({"label": k, "status": "running", "remaining_seconds": round(remaining, 1)})
            return {
                "success": True,
                "data": {"timers": active_timers},
                "message": f"Active timers: {active_timers}" if active_timers else "No active timers running."
            }

        if label not in self._timers:
            return {"success": False, "data": None, "message": f"No timer found with label '{label}'."}

        timer = self._timers[label]
        status = timer["status"]
        elapsed = time.time() - timer["start_time"]
        remaining = max(0.0, timer["duration"] - elapsed)

        return {
            "success": True,
            "data": {
                "label": label,
                "status": status,
                "duration_seconds": timer["duration"],
                "remaining_seconds": round(remaining, 1) if status == "running" else 0.0
            },
            "message": f"Timer '{label}' is {status}. Time remaining: {round(remaining, 1)} seconds." if status == "running" else f"Timer '{label}' has {status}."
        }

    async def _set_volume(self, params: dict) -> dict:
        """Establece el volumen master del sistema (0 a 100)."""
        level = params.get("level") or params.get("percent") or params.get("volume")
        if level is None:
            return {"success": False, "data": None, "message": "Nivel de volumen no especificado."}
        try:
            level_str = str(level).replace("%", "").strip()
            level = int(float(level_str))
            level = max(0, min(100, level))
        except (ValueError, TypeError):
            return {"success": False, "data": None, "message": f"Nivel de volumen invalido: '{level}'."}

        self._mock_volume = level
        try:
            if platform.system() == "Windows":
                import comtypes
                try:
                    comtypes.CoInitialize()
                except OSError as exc:
                    if getattr(exc, "hresult", None) != -2147417850 and "-2147417850" not in str(exc):
                        raise
                from pycaw.pycaw import AudioUtilities
                speakers = AudioUtilities.GetSpeakers()
                volume = speakers.EndpointVolume
                await asyncio.to_thread(volume.SetMasterVolumeLevelScalar, level / 100.0, None)
            else:
                if platform.system() == "Darwin":
                    cmd = f"osascript -e 'set volume output volume {level}'"
                else:
                    cmd = f"amixer set Master {level}%"
                await asyncio.to_thread(subprocess.run, cmd, shell=True, capture_output=True)

            return {
                "success": True,
                "data": {"level": level},
                "message": f"Volumen del sistema establecido al {level}%.",
            }
        except Exception as exc:
            return {
                "success": True,
                "data": {"level": level, "virtual": True},
                "message": f"Volumen virtual del sistema establecido al {level}% (sin audio hardware: {exc}).",
            }

    async def _get_volume(self, params: dict) -> dict:
        """Obtiene el nivel de volumen master actual."""
        try:
            level = 0
            if platform.system() == "Windows":
                import comtypes
                try:
                    comtypes.CoInitialize()
                except OSError as exc:
                    if getattr(exc, "hresult", None) != -2147417850 and "-2147417850" not in str(exc):
                        raise
                from pycaw.pycaw import AudioUtilities
                speakers = AudioUtilities.GetSpeakers()
                volume = speakers.EndpointVolume
                val = await asyncio.to_thread(volume.GetMasterVolumeLevelScalar)
                level = int(round(val * 100))
            else:
                if platform.system() == "Darwin":
                    cmd = "osascript -e 'output volume of (get volume settings)'"
                    proc = await asyncio.to_thread(subprocess.run, cmd, shell=True, capture_output=True, text=True)
                    level = int(proc.stdout.strip() or 0)
                else:
                    cmd = "amixer get Master"
                    proc = await asyncio.to_thread(subprocess.run, cmd, shell=True, capture_output=True, text=True)
                    import re
                    match = re.search(r"\[(\d+)%\]", proc.stdout)
                    level = int(match.group(1)) if match else 0

            self._mock_volume = level
            return {
                "success": True,
                "data": {"level": level},
                "message": f"El volumen del sistema actual es {level}%.",
            }
        except Exception as exc:
            fallback_val = getattr(self, "_mock_volume", 50)
            return {
                "success": True,
                "data": {"level": fallback_val, "virtual": True},
                "message": f"El volumen virtual del sistema actual es {fallback_val}% (sin audio hardware: {exc}).",
            }

    async def _get_active_window(self) -> dict:
        """Obtiene el título de la ventana activa en primer plano."""
        title = "Desconocido"
        try:
            if platform.system() == "Windows":
                cmd = 'powershell "(Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | Select-Object -ExpandProperty MainWindowTitle)"'
                proc = await asyncio.to_thread(subprocess.run, cmd, shell=True, capture_output=True, text=True)
                lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
                title = lines[0] if lines else "Escritorio / Sin ventana activa"
            else:
                title = "Ventana activa (Linux/macOS)"

            return {"success": True, "data": {"active_window": title}, "message": f"Ventana activa actual: '{title}'."}
        except Exception as exc:
            return {"success": False, "data": None, "message": f"Error al leer ventana activa: {exc}"}

    async def _get_process_list(self, params: dict) -> dict:
        """Obtiene la lista de los principales procesos en ejecución."""
        limit = int(params.get("limit", 15))
        try:
            if platform.system() == "Windows":
                cmd = 'powershell "Get-Process | Sort-Object CPU -Descending | Select-Object -First ' + str(limit) + ' Name, Id, CPU"'
            else:
                cmd = f"ps aux --sort=-%cpu | head -n {limit+1}"

            proc = await asyncio.to_thread(subprocess.run, cmd, shell=True, capture_output=True, text=True)
            return {
                "success": True,
                "data": {"processes": proc.stdout.strip()},
                "message": f"Lista de {limit} procesos principales obtenida.",
            }
        except Exception as exc:
            return {"success": False, "data": None, "message": f"Error al listar procesos: {exc}"}

    def _get_resource_usage(self) -> dict:
        """Obtiene el porcentaje de uso de CPU, RAM y disco."""
        import psutil
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent
            return {
                "success": True,
                "data": {"cpu_percent": cpu, "ram_percent": ram, "disk_percent": disk},
                "message": f"Recursos del sistema: CPU {cpu}%, RAM {ram}%, Disco {disk}%.",
            }
        except Exception as exc:
            # Nunca inventar metricas: fallar honestamente si psutil no esta disponible.
            return {
                "success": False,
                "data": None,
                "message": f"No se pudieron leer las metricas del sistema (psutil no disponible): {exc}",
            }

    # ------------------------------------------------------------------ #
    # Esquema para el LLM
    # ------------------------------------------------------------------ #
    def get_schema(self) -> list:
        return [
            {
                "action": "get_current_time",
                "description": "Return the current system time.",
                "params": {},
            },
            {
                "action": "get_system_info",
                "description": "Return basic OS, CPU, RAM, and hardware metrics.",
                "params": {},
            },
            {
                "action": "get_active_window",
                "description": "Obtiene el título de la ventana del usuario activa en primer plano (Ambient Awareness).",
                "params": {},
            },
            {
                "action": "get_process_list",
                "description": "Lista los principales procesos en ejecución ordenados por uso de CPU.",
                "params": {"limit": "int (opcional) — número de procesos a devolver. Default: 15"},
            },
            {
                "action": "get_resource_usage",
                "description": "Devuelve el porcentaje de uso actual de CPU, memoria RAM y disco.",
                "params": {},
            },
            {
                "action": "open_application",
                "description": "Open an application installed on the host system (e.g. Opera, Chrome, Notepad). Can be opened in visible (headed) or headless mode.",
                "params": {
                    "app_name": "string (required) - name of application to launch",
                    "mode": "string (optional) - 'visible' to open it normally, or 'headless' / 'background' to run it without a window (supported by browsers and script runtimes).",
                    "arguments": "string (optional) - custom command-line arguments to pass to the application."
                },
            },
            {
                "action": "check_application_running",
                "description": "Check if an application or process is currently running in the OS process list.",
                "params": {"app_name": "string (required) - name of application or process to check"},
            },
            {
                "action": "close_application",
                "description": "Close or terminate a running application or process. Choose between graceful shutdown or forced kill.",
                "params": {
                    "app_name": "string (required) - name of application or process to close",
                    "force": "boolean (optional, default true) - true to force-kill (taskkill /F / kill -9), false for graceful close (WM_CLOSE / SIGTERM)",
                    "timeout": "integer (optional) - seconds to wait before giving up"
                },
            },
            {
                "action": "execute_shell",
                "description": "Run shell commands (CMD / PowerShell) on the host system without restrictions.",
                "params": {
                    "command": "string (required) - shell command to execute",
                    "timeout": "integer (optional) - max seconds to wait before killing the process",
                    "working_dir": "string (optional) - directory to run the command in",
                    "fire_and_forget": "boolean (optional) - if true, launch in background and return immediately without waiting for output"
                },
            },
            {
                "action": "execute_powershell",
                "description": "Run native PowerShell commands or scripts without restrictions.",
                "params": {
                    "script": "string (required) - PowerShell script or command",
                    "timeout": "integer (optional) - max seconds to wait",
                    "as_admin": "boolean (optional) - if true, launch with elevated UAC privileges",
                    "working_dir": "string (optional) - directory to run the script in",
                    "fire_and_forget": "boolean (optional) - if true, launch in background without waiting"
                },
            },
            {
                "action": "run_python_code",
                "description": "Generate and execute dynamic Python code in the Python runtime environment.",
                "params": {
                    "code": "string (required) - Python code block to execute",
                    "timeout": "integer (optional) - max seconds to wait for execution to finish",
                    "working_dir": "string (optional) - directory to set as working dir inside the script",
                    "env": "object (optional) - additional environment variables to inject, e.g. {\"MY_VAR\": \"value\"}"
                },
            },
            {
                "action": "set_timer",
                "description": "Set an async background timer that finishes after the specified duration.",
                "params": {
                    "duration_seconds": "integer (required) - duration in seconds",
                    "label": "string (optional) - description label for the timer"
                },
            },
            {
                "action": "check_timer_status",
                "description": "Check the remaining time and status of an active or finished timer.",
                "params": {
                    "timer_label": "string (optional) - the label of the timer to check. If empty, lists all active timers."
                },
            },
            {
                "action": "set_volume",
                "description": "Set the master volume level of the system speaker (0 to 100).",
                "params": {
                    "level": "integer (required) - target volume level from 0 (muted) to 100 (max volume)"
                },
            },
            {
                "action": "get_volume",
                "description": "Get the current master volume level of the system speaker.",
                "params": {},
            },
        ]
