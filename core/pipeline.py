"""WIS Action Pipeline v3.0 — Pure-LLM Agentic ReAct loop.

Cognitive architecture (AVRORA philosophy):
  - NO hardcoded heuristics, regex fastpaths, or shortcuts.
  - EVERY initial user query goes directly to the LLM ReAct loop:
      think → parallel execute → empirical verify → metacognitive check
      → auto-repair → synthesize → cache in SkillMemory.
  - The ONLY fast execution is SkillMemory (proven+verified sequences).
    Speed is earned dynamically through synthesis, never hardcoded.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from core.safety import SafetyPolicy, FailureClassifier
from core.reasoning import ReasoningEngine
from core.event_bus import event_bus
from core.skill_memory import SkillMemory

from core.verifier import MetacognitiveVerifier
from core.kernel import WISKernel

logger = logging.getLogger("wis.core.pipeline")

PATH_KNOWN = "known"
PATH_NEW = "new"

DEFAULT_MAX_STEPS = 10
STEP_TIMEOUT_S = 60

AbilityFn = Callable[[Dict[str, Any]], Any]

# Un turno que SOLO anuncia lo que va a hacer ("I'll examine…", "Let me verify…",
# "voy a revisar…") NO es un turno terminado: es un turno estancado que obligaba
# al usuario a escribir otro mensaje para que WIS continuara. Estas senales lo
# detectan para forzar la ejecucion real en vez de cortar el turno.
_PROMISE_SIGNALS = (
    r"\bi(?:'ll| will| am going to| am about to)\b",
    r"\blet me\b",
    r"\bvoy a\b",
    r"\bvamos a\b",
    r"\bprocedo a\b",
    r"\bahora (?:voy|procedo|ejecuto|reviso|verifico)\b",
    r"\bd[eé]jame\b",
)
_PROMISE_FALSE_POSITIVES = re.compile(
    # Marcadores que DESCALIFICAN la deteccion: negaciones ("I will NOT kill
    # WIS") y ofertas condicionales ("give me the PID and I'll execute it",
    # "if you tell me X, I'll do Y"). Sin esto, respuestas finales correctas
    # (incluso un rechazo de seguridad) se marcaban como turno estancado.
    r"let me know"
    r"|i'?ll let you know"
    r"|av[ií]same"
    r"|dime si"
    r"|\bi\s+(?:will|'ll)\s+not\b"
    r"|\bi\s+won'?t\b"
    r"|\bi\s+(?:cannot|can'?t|will not be able)\b"
    r"|\bno\s+voy\s+a\b"
    r"|\bno\s+procedo\s+a\b"
    # Promesa atada a una accion del usuario: "..., and I'll ..." / "then I'll ..."
    r"|\b(?:and|then)\s+i'?(?:ll|will)\b"
    r"|\bif you\b"
    r"|\bonce you\b"
    r"|\bsi me\s+(?:das|dices|indicas)\b",
    re.IGNORECASE,
)


def _announces_future_action(text: str) -> bool:
    """True si el texto es una promesa de actuar en vez de un resultado final."""
    sample = (text or "").strip()[-700:]
    if not sample:
        return False
    if _PROMISE_FALSE_POSITIVES.search(sample):
        return False
    return any(re.search(pat, sample, re.IGNORECASE) for pat in _PROMISE_SIGNALS)


# Acciones SIN efectos secundarios: repetirlas es inocuo y a menudo necesario
# (p. ej. volver a listar un directorio despues de lanzar algo). El filtro
# anti-duplicados existe para no repetir EFECTOS, no para bloquear lecturas.
# Cuando se aplicaba a una lectura, la llamada se descartaba en silencio y el
# turno terminaba sin ejecutar el paso anunciado: incidente 2026-09-15 20:57,
# "Run the main program" acabo en [AVISO] porque un code_list_dir repetido
# nunca llego a ejecutarse y el bucle se corto por "duplicado".
_READ_ONLY_ACTION_RE = re.compile(
    r"^(?:code_|code_tools_)?"
    r"(?:list|get|view|read|check|describe|grep|find|search|inspect|probe|"
    r"info|status|capture|detect|analyze|verify|health)",
    re.IGNORECASE,
)


def _is_repeatable_call(call: Dict[str, Any]) -> bool:
    """True si la llamada es de solo lectura, por tanto segura de repetir."""
    if not isinstance(call, dict):
        return False
    action = str(call.get("action") or call.get("name") or "").strip()
    return bool(action) and bool(_READ_ONLY_ACTION_RE.match(action))


def _build_repair_prompt(text: str, step: int, category: str, error_desc: str) -> str:
    """Prompt de auto-reparacion, escalado segun la naturaleza del fallo.

    Un defecto de codigo no se arregla reintentando otra herramienta. Antes TODO
    fallo recibia la misma instruccion ("elige otra tool y otros parametros"),
    asi que WIS jamas reparaba su propio codigo: solo lo rodeaba. Aqui se le da
    autorizacion explicita para leer y parchear la fuente cuando corresponde.
    """
    if category == "SOFTWARE_DEFECT":
        return (
            f"{text}\n\n"
            f"[AUTO-REPAIR — Step {step}]: Previous action failed ({category}): {error_desc}.\n"
            f"This is a DEFECT IN THE CODE, not a hardware fault and not a bad\n"
            f"parameter: retrying the same tool with different arguments will NOT fix it.\n"
            f"You are authorized and expected to repair the source code. Do it:\n"
            f"  1. Read the failing module with code_tools.code_grep / code_tools.code_view_file.\n"
            f"  2. Name the EXACT defect (wrong/incompatible API, stale path,\n"
            f"     swallowed exception, misleading error message...).\n"
            f"  3. Apply the minimal fix with code_tools.code_replace_content.\n"
            f"  4. Re-run the failed action to PROVE the fix works.\n"
            f"Do not invent files, and do not claim success without re-running."
        )
    return (
        f"{text}\n\n"
        f"[AUTO-REPAIR — Step {step}]: Previous action failed ({category}): {error_desc}.\n"
        f"Please consult the ## AVAILABLE TOOLS AND SCHEMAS section in the system prompt to find the correct, canonical tool and action name, along with their exact parameter schemas.\n"
        f"Generate alternative tool calls or parameters."
    )


@dataclass
class TurnContext:
    """Estado efímero y aislado de una sola ejecución cognitiva."""

    turn_id: str
    session_id: str
    objective: str
    planner_steps: int = 0
    plan: list[Dict[str, Any]] = field(default_factory=list)
    calls: list[Dict[str, Any]] = field(default_factory=list)
    results: list[Dict[str, Any]] = field(default_factory=list)
    trace: list[Dict[str, Any]] = field(default_factory=list)
    executed_calls: set[str] = field(default_factory=set)


class ActionPipeline:
    """Pipeline de accion puramente agentico con razonamiento LLM y SkillMemory."""

    def __init__(
        self,
        reasoning: ReasoningEngine,
        skill_memory: SkillMemory,
        abilities: Optional[Union[Dict[str, AbilityFn], Any]] = None,
        safety: Optional[SafetyPolicy] = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        fastpath: Optional[Any] = None,
        hardware_memory: Optional[Any] = None,
    ) -> None:
        self.reasoning: ReasoningEngine = reasoning
        self.skill_memory: SkillMemory = skill_memory
        self.fastpath = None  # Deprecated & bypassed: 100% LLM driven
        self.hardware_memory = hardware_memory
        if isinstance(abilities, dict):
            self.abilities: Any = dict(abilities)
        elif abilities is not None:
            self.abilities = abilities
        else:
            self.abilities = {}
        self.safety: SafetyPolicy = safety or SafetyPolicy()
        self.max_steps: int = max(1, int(max_steps or DEFAULT_MAX_STEPS))

        # Goal Manager integration (set externally)
        self.goal_manager = None

        # Approval mechanism for secure mode
        self._approval_events: Dict[str, asyncio.Event] = {}
        self._approval_results: Dict[str, bool] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}
        
        # Transient Context Memory (Focus System)
        self._focused_contexts: Dict[str, Dict[str, str]] = {}
        
        # Swarm OS Kernel
        self.kernel = WISKernel(self)
        self._last_trace: Dict[str, list] = {}
        self._session_state_path = Path("Data") / "wis_cognitive_sessions.json"
        self._load_session_state()
        self._active_turns: Dict[str, str] = {}
        # Task asyncio que sirve cada turno cognitivo, para poder abortarlo de
        # verdad (no solo marcar un flag) cuando el operador pulsa Cancel.
        self._turn_tasks: Dict[str, "asyncio.Task[Any]"] = {}
        # Margen entre el cancel cooperativo y el cancel duro del task.
        self._cancel_grace_seconds: float = 1.5

        # Swarm Telepathy Bus: Inyección asíncrona de conocimiento
        event_bus.subscribe("swarm.broadcast", self._on_telepathy)

        self._reflex_table: Dict[str, str] = {
            "hi": "Hello.",
            "hello": "Hello.",
            "hey": "Hello.",
            "hola": "Hello.",
            "buenas": "Good morning.",
            "buena": "Good morning.",
            "buenas dias": "Good morning.",
            "buenos dias": "Good morning.",
            "buenas tardes": "Good afternoon.",
            "buenas noches": "Good night.",
            "que tal": "Hello! How can I help you?",
            "como estas": "I'm doing great, thanks for asking! How can I help?",
            "thanks": "You're welcome.",
            "gracias": "You're welcome.",
            "bye": "Goodbye.",
            "adios": "Goodbye.",
            "chao": "Goodbye.",
            "hasta luego": "Goodbye.",
        }

    def register_ability(self, name: str, fn: AbilityFn) -> None:
        if isinstance(self.abilities, dict):
            self.abilities[name] = fn

    def register_reflex(self, trigger: str, response: str) -> None:
        key = (trigger or "").strip().lower()
        if key:
            self._reflex_table[key] = str(response or "")

    def _load_session_state(self) -> None:
        try:
            if not self._session_state_path.exists():
                return
            payload = json.loads(self._session_state_path.read_text(encoding="utf-8"))
            for session_id, state in payload.items():
                if str(session_id) in ("main", "default"):
                    continue
                if not isinstance(state, dict):
                    continue
                focused = state.get("focused_contexts", {})
                trace = state.get("last_trace", [])
                if isinstance(focused, dict):
                    self._focused_contexts[str(session_id)] = {
                        str(name): str(content) for name, content in focused.items()
                    }
                if isinstance(trace, list):
                    self._last_trace[str(session_id)] = trace
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Could not restore cognitive session state: %s", exc)

    def _save_session_state(self, session_id: str) -> None:
        if str(session_id) in ("main", "default"):
            return
        try:
            self._session_state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {}
            if self._session_state_path.exists():
                try:
                    payload = json.loads(self._session_state_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = {}
            payload[str(session_id)] = {
                "focused_contexts": self._focused_contexts.get(session_id, {}),
                "last_trace": self._last_trace.get(session_id, []),
            }
            self._session_state_path.write_text(
                json.dumps(payload, ensure_ascii=False, default=str, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not save cognitive session state: %s", exc)

    def delete_session_state(self, session_id: str) -> None:
        try:
            if not self._session_state_path.exists():
                return
            payload = json.loads(self._session_state_path.read_text(encoding="utf-8"))
            payload.pop(str(session_id), None)
            self._session_state_path.write_text(
                json.dumps(payload, ensure_ascii=False, default=str, indent=2),
                encoding="utf-8",
            )
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Could not delete cognitive session state: %s", exc)

    @staticmethod
    def _persistent_session(session_id: str) -> bool:
        """Indica si la sesion debe persistirse en la memoria episodica.

        Antes se excluian 'main' y 'default' para mantener la consola principal
        como transitoria. Como el chat principal usa justamente session_id
        'default' (ver ChatRequest en console/server.py), NINGUNA interaccion de
        la consola se guardaba nunca: el historial vivia solo en el deque de RAM
        y se perdia por completo al reiniciar WIS.
        """
        return bool(str(session_id or "").strip())

    # ---- Approval API (called from server.py) -----------------------------

    def approve_action(self, session_id: str = "default") -> None:
        """Aprueba la accion riesgosa en espera."""
        self._approval_results[session_id] = True
        if session_id in self._approval_events:
            self._approval_events[session_id].set()

    def deny_action(self, session_id: str = "default") -> None:
        """Deniega la accion riesgosa."""
        self._approval_results[session_id] = False
        if session_id in self._approval_events:
            self._approval_events[session_id].set()

    def cancel(self, session_id: str = "default") -> None:
        """Detiene el turno cognitivo en curso de la sesion.

        Antes esto solo hacia `_cancel_events[session_id].set()` y nadie lo
        llamaba nunca, ademas de que el bucle ReAct solo consultaba el flag al
        inicio de cada paso: si el turno estaba bloqueado esperando al LLM o a
        un subproceso, el "cancel" no ocurria nunca.

        Ahora hace dos cosas:
          1. Cooperativa -> marca el flag. El bucle ReAct, la ejecucion de
             herramientas y ShellOps lo consultan y abortan en <200 ms.
          2. Dura -> cancela el task asyncio del turno tras un margen de
             gracia, lo que interrumpe tambien los awaits largos (LLM httpx).
        """
        event = self._cancel_events.get(session_id)
        if event is None:
            event = asyncio.Event()
            self._cancel_events[session_id] = event
        event.set()

        turn_id = self._active_turns.get(session_id)
        task = self._turn_tasks.get(session_id)
        hard = bool(task and not task.done())
        if hard:
            try:
                loop = asyncio.get_running_loop()

                def _hard_kill() -> None:
                    if task and not task.done():
                        # Cancela el task que sirve el turno (no el del cliente):
                        # server.py lo aisla con create_task + shield del ciclo.
                        task.cancel()

                loop.call_later(self._cancel_grace_seconds, _hard_kill)
            except RuntimeError:
                # Sin event loop activo (llamada desde hilo): solo cooperativo.
                hard = False

        event_bus.emit("pipeline.cancel_requested", {
            "session_id": session_id,
            "turn_id": turn_id,
            "hard": hard,
        })
        logger.info(
            "pipeline: cancel solicitado (session=%s turn=%s hard=%s).",
            session_id, turn_id, hard,
        )

    def is_busy(self, session_id: str = "default") -> bool:
        """True si la sesion tiene un turno cognitivo en ejecucion."""
        return session_id in self._active_turns

    def _release_turn(self, session_id: str) -> None:
        """Libera el lock de turno de forma idempotente.

        Se llama desde el finally de process(); debe poder ejecutarse varias
        veces sin efectos secundarios.
        """
        self._active_turns.pop(session_id, None)
        self._turn_tasks.pop(session_id, None)

    def _current_cancel_event(self, session_id: str) -> Optional[asyncio.Event]:
        """Evento de cancelacion vigente para la sesion (o None)."""
        return self._cancel_events.get(session_id)

    def _is_cancelled(self, session_id: str) -> bool:
        """Consulta cooperativa del flag de cancelacion."""
        event = self._cancel_events.get(session_id)
        return bool(event is not None and event.is_set())

    def _on_telepathy(self, payload: Dict[str, Any]) -> None:
        """
        Intercepta mensajes telepáticos de otros agentes (Buzón Pasivo).
        Guarda el descubrimiento en la memoria semántica a corto plazo 
        sin interrumpir el hilo actual de ejecución.
        """
        topic = payload.get("topic", "General")
        message = payload.get("message", "")
        if message:
            telepathy_text = f"SYSTEM [Telepathy - {topic}]: {message}"
            self.reasoning.memory.add_system_message(telepathy_text)
            logger.info("Pipeline asimiló conocimiento telepático: %s", topic)

    # ---- Main Process -----------------------------------------------------

    async def process(
        self,
        text: str,
        sensor_data: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        session_id: str = "default",
    ) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {
                "response": "",
                "calls": [],
                "results": [],
                "path_used": PATH_NEW,
                "success": True,
            }

        if tools is None and self.abilities:
            if hasattr(self.abilities, "get_schemas"):
                tools = self.abilities.get_schemas()

        event_bus.emit("pipeline.input_received", { "session_id": session_id,"text": text, "session_id": session_id})

        # Reset del flag de cancelacion SOLO si no hay un turno vivo en esta sesion.
        # Si hay un turno en curso, este mensaje sera rechazado por el guard de
        # _try_new; recrear el evento borraria un cancel pendiente y dejaria la
        # sesion atrapada con el turno antiguo sin poder detenerse.
        if session_id not in self._active_turns or session_id not in self._cancel_events:
            self._cancel_events[session_id] = asyncio.Event()

        # --- Slash Commands Interceptor ---
        if text.startswith("/"):
            parts = text.split(" ", 1)
            cmd = parts[0].lower().strip()
            args = parts[1].strip() if len(parts) > 1 else ""
            
            resp_text = f"Command {cmd} executed."
            
            if cmd == "/goal":
                event_bus.emit("terminal.spawn_goal", { "session_id": session_id, "text": args })
                resp_text = "Goal submitted to Long Horizon Engine."
                
            elif cmd == "/cd":
                if session_id == "main":
                    resp_text = "The main console is transient. Open a project from the Projects tree before changing directories."
                elif hasattr(self.abilities, "execute"):
                    await self.abilities.execute("system", "execute_shell", {
                        "command": f"cd {args}", "_session_id": session_id
                    })
                    await self.abilities.execute("persistent_terminal", "terminal_create", {"name": session_id, "persistent": True})
                    await self.abilities.execute("persistent_terminal", "terminal_send", {"name": session_id, "command": f"cd {args}", "persistent": True})
                resp_text = f"Terminal session anchored to: {args}"
                
            elif cmd == "/new":
                if hasattr(self.abilities, "execute"):
                    import os
                    proj_path = os.path.join(r"d:\WIS\Projects", args)
                    os.makedirs(proj_path, exist_ok=True)
                resp_text = f"Created project directory: {proj_path}. Open it from the Projects tree to start working."

            elif cmd == "/projects":
                from pathlib import Path
                projects_dir = Path(r"D:\WIS\Projects")
                if not projects_dir.is_dir():
                    resp_text = f"Projects directory not found: {projects_dir}"
                else:
                    project_names = sorted(
                        item.name for item in projects_dir.iterdir() if item.is_dir()
                    )
                    if project_names:
                        resp_text = "Projects:\n" + "\n".join(
                            f"- {name}" for name in project_names
                        )
                    else:
                        resp_text = "Projects directory is empty."

            elif cmd == "/stop":
                if hasattr(self.abilities, "execute"):
                    await self.abilities.execute("persistent_terminal", "terminal_kill", {"name": session_id})
                resp_text = "Persistent terminal processes stopped."
                
            elif cmd == "/delete":
                import os, shutil
                confirmed = args.lower().endswith(" --confirmed")
                project_name = args[:-11].strip() if confirmed else args.strip()
                if not confirmed:
                    resp_text = f"Confirmation required. Type /delete {project_name} again and confirm the dialog."
                elif not project_name or project_name in (".", "..") or os.path.basename(project_name) != project_name:
                    resp_text = "Invalid project name."
                else:
                    proj_path = os.path.join(r"d:\WIS\Projects", project_name)
                    if not os.path.isdir(proj_path):
                        resp_text = f"Project not found: {project_name}"
                    else:
                        terminal_ability = self.abilities.get("persistent_terminal") if hasattr(self.abilities, "get") else None
                        system_ability = self.abilities.get("system") if hasattr(self.abilities, "get") else None
                        if terminal_ability and hasattr(terminal_ability, "delete_session"):
                            terminal_ability.delete_session(project_name)
                        if system_ability and hasattr(system_ability, "clear_session"):
                            system_ability.clear_session(project_name)
                        self.reasoning.memory.clear_session(project_name)
                        self._focused_contexts.pop(project_name, None)
                        self._last_trace.pop(project_name, None)
                        self.delete_session_state(project_name)
                        shutil.rmtree(proj_path)
                        resp_text = f"Project {project_name} and all persisted history/context deleted."
                
            elif cmd == "/swarm":
                if hasattr(self.abilities, "execute"):
                    res = await self.abilities.execute("persistent_terminal", "terminal_list", {})
                    resp_text = "Swarm Status:\n" + str(res.get("terminals", []))
                else:
                    resp_text = "Swarm Status unavailable."

            elif cmd == "/hw-scan":
                import subprocess
                try:
                    p = subprocess.run(["python", "-c", "import serial.tools.list_ports; print([p.device for p in serial.tools.list_ports.comports()])"], capture_output=True, text=True)
                    ports = p.stdout.strip()
                    resp_text = f"Hardware Scan Result:\nCOM Ports: {ports}"
                except Exception as e:
                    resp_text = f"HW Scan failed: {e}"

            elif cmd == "/port":
                if hasattr(self.abilities, "execute"):
                    port = args if args else "8080"
                    await self.abilities.execute("persistent_terminal", "terminal_send", {
                        "name": session_id,
                        "command": f"python -m http.server {port}",
                        "persistent": True,
                    })
                    resp_text = f"Static server starting on port {port}..."

            elif cmd == "/git":
                if hasattr(self.abilities, "execute"):
                    msg = args if args else "Auto commit"
                    await self.abilities.execute("persistent_terminal", "terminal_send", {"name": session_id, "command": f"git add . && git commit -m \\\"{msg}\\\" && git push"})
                    resp_text = "Git add/commit/push command sent to background."

            elif cmd == "/build":
                if hasattr(self.abilities, "execute"):
                    # Detecta e invoca el comando de build
                    await self.abilities.execute("persistent_terminal", "terminal_send", {"name": session_id, "command": "npm install || pip install -r requirements.txt || make"})
                    resp_text = "Build process triggered."
            
            elif cmd == "/reboot":
                if self.reasoning and hasattr(self.reasoning, "memory"):
                    self.reasoning.memory.clear_session(session_id)
                resp_text = "LLM short-term memory formatted. Reboot successful."

            elif cmd == "/clear":
                if self.reasoning and hasattr(self.reasoning, "memory"):
                    self.reasoning.memory.clear_session(session_id)
                resp_text = "Conversation history cleared for this session."
                    
            elif cmd == "/proactividad":
                state = args.lower() == "on"
                event_bus.emit("system.proactivity.toggle", {"active": state})
                resp_text = f"Proactivity Daemon set to: {'ON' if state else 'OFF'}"
                
            elif cmd == "/ping":
                import subprocess
                try:
                    p = subprocess.run(["ping", "-n", "4", args], capture_output=True, text=True)
                    resp_text = f"Ping Results for {args}:\n{p.stdout.strip()}"
                except Exception as e:
                    resp_text = f"Ping failed: {e}"
                    
            elif cmd == "/list":
                import os
                try:
                    res = await self.abilities.execute("persistent_terminal", "terminal_list", {})
                    # Find cwd of the current session
                    terminals = res.get("terminals", [])
                    cwd = "d:/WIS/Projects"
                    for t in terminals:
                        if t.startswith(session_id):
                            parts = t.split("(")
                            if len(parts) > 1:
                                cwd = parts[1].replace(")", "").strip()
                            break
                    if os.path.exists(cwd):
                        files = os.listdir(cwd)
                        resp_text = f"Directory List for {cwd}:\n" + "\n".join(files)
                    else:
                        resp_text = f"Path {cwd} not found."
                except Exception as e:
                    resp_text = f"List failed: {e}"
                    
            elif cmd == "/run":
                import subprocess, os
                try:
                    # Get cwd
                    res = await self.abilities.execute("persistent_terminal", "terminal_list", {})
                    cwd = "d:/WIS/Projects"
                    for t in res.get("terminals", []):
                        if t.startswith(session_id) and "(" in t:
                            cwd = t.split("(")[1].replace(")", "").strip()
                            break
                            
                    p = subprocess.run(args, shell=True, capture_output=True, text=True, cwd=cwd)
                    output = p.stdout if p.stdout else p.stderr
                    if not output:
                        output = "Command finished with no output."
                        
                    event_bus.emit("ui.show_log", {"content": f"$ {args}\n{output}"})
                    resp_text = "Command executed. Output sent to Log Modal."
                except Exception as e:
                    resp_text = f"Run failed: {e}"
                    
            elif cmd == "/open":
                import os
                try:
                    res = await self.abilities.execute("persistent_terminal", "terminal_list", {})
                    cwd = "d:/WIS/Projects"
                    for t in res.get("terminals", []):
                        if t.startswith(session_id) and "(" in t:
                            cwd = t.split("(")[1].replace(")", "").strip()
                            break
                            
                    full_path = os.path.join(cwd, args)
                    if os.path.exists(full_path):
                        # Map absolute path to relative /projects/ path
                        rel_path = os.path.relpath(full_path, "d:/WIS/Projects").replace("\\\\", "/")
                        event_bus.emit("ui.open_file", {"path": rel_path})
                        resp_text = f"Opening {rel_path} in new tab..."
                    else:
                        resp_text = f"File {args} not found in {cwd}."
                except Exception as e:
                    resp_text = f"Open failed: {e}"

            elif cmd == "/sys":
                import psutil
                try:
                    cpu = psutil.cpu_percent(interval=0.1)
                    ram = psutil.virtual_memory()
                    disk = psutil.disk_usage('/')
                    resp_text = f"Host Telemetry:\nCPU: {cpu}%\nRAM: {ram.percent}% ({ram.used/(1024**3):.1f}GB / {ram.total/(1024**3):.1f}GB)\nDisk: {disk.percent}%"
                except Exception as e:
                    resp_text = f"Sys fetch failed: {e}"
                    
            elif cmd == "/focus":
                import os
                try:
                    res = await self.abilities.execute("persistent_terminal", "terminal_list", {})
                    cwd = "d:/WIS/Projects"
                    for t in res.get("terminals", []):
                        if t.startswith(session_id) and "(" in t:
                            cwd = t.split("(")[1].replace(")", "").strip()
                            break
                    full_path = os.path.join(cwd, args)
                    if os.path.exists(full_path):
                        with open(full_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        
                        # Store in transient context memory
                        if session_id not in self._focused_contexts:
                            self._focused_contexts[session_id] = {}
                        self._focused_contexts[session_id][args] = content
                        self._save_session_state(session_id)
                        
                        resp_text = f"File {args} fully memorized by AI (Transient Context)."
                    else:
                        resp_text = f"File {args} not found in {cwd}."
                except Exception as e:
                    resp_text = f"Focus failed: {e}"
                    
            elif cmd == "/unfocus":
                try:
                    if session_id in self._focused_contexts and args in self._focused_contexts[session_id]:
                        del self._focused_contexts[session_id][args]
                        self._save_session_state(session_id)
                        resp_text = f"File {args} removed from AI memory."
                    else:
                        resp_text = f"File {args} is not currently in focus."
                except Exception as e:
                    resp_text = f"Unfocus failed: {e}"
                    
            elif cmd == "/context":
                try:
                    ctx = self._focused_contexts.get(session_id, {})
                    if not ctx:
                        resp_text = "No files currently in focus."
                    else:
                        resp_text = "Active Context Files:\n" + "\n".join(f"- {f}" for f in ctx.keys())
                except Exception as e:
                    resp_text = f"Context check failed: {e}"
                    
            elif cmd == "/clear-context":
                try:
                    self._focused_contexts[session_id] = {}
                    self._save_session_state(session_id)
                    resp_text = "Transient memory context fully cleared."
                except Exception as e:
                    resp_text = f"Clear context failed: {e}"
                    
            elif cmd == "/search":
                import subprocess
                try:
                    res = await self.abilities.execute("persistent_terminal", "terminal_list", {})
                    cwd = "d:/WIS/Projects"
                    for t in res.get("terminals", []):
                        if t.startswith(session_id) and "(" in t:
                            cwd = t.split("(")[1].replace(")", "").strip()
                            break
                    # findstr /s /i "query" *.*
                    p = subprocess.run(f'findstr /s /i "{args}" *.*', shell=True, cwd=cwd, capture_output=True, text=True)
                    out = p.stdout.strip()
                    if not out: out = "No matches found."
                    event_bus.emit("ui.show_log", {"content": f"$ search '{args}'\n{out}"})
                    resp_text = "Search complete. Results sent to Log Modal."
                except Exception as e:
                    resp_text = f"Search failed: {e}"
                    
            elif cmd == "/logs":
                import os
                try:
                    log_file = r"d:\WIS\logs\wis.log"
                    if os.path.exists(log_file):
                        with open(log_file, "r", encoding="utf-8") as f:
                            lines = f.readlines()[-100:]
                            content = "".join(lines)
                        event_bus.emit("ui.show_log", {"content": content})
                        resp_text = "System logs sent to Log Modal."
                    else:
                        resp_text = "Log file not found."
                except Exception as e:
                    resp_text = f"Logs fetch failed: {e}"
                    
            elif cmd == "/speak":
                # Dispara un evento genérico de TTS al ecosistema WIS
                event_bus.emit("robot.speak", {"text": args})
                # Intenta ejecutar la habilidad nativa 'voice' de paso
                if hasattr(self.abilities, "execute"):
                    try:
                        await self.abilities.execute("voice", "synthesize", {"text": args})
                    except Exception:
                        pass
                resp_text = f"TTS Command dispatched: '{args}'"
                
            # --- SWARM OS KERNEL PRIMITIVES ---
            elif cmd == "/ps":
                resp_text = self.kernel.process_list()
            elif cmd == "/kill":
                resp_text = self.kernel.process_kill(args)
            elif cmd == "/memory-map":
                resp_text = self.kernel.memory_map(session_id)
            elif cmd == "/undo":
                resp_text = self.kernel.undo_last(session_id)
            elif cmd == "/why":
                resp_text = self.kernel.why_last_action(session_id)
            elif cmd == "/trace":
                resp_text = self.kernel.trace_execution(session_id)
                event_bus.emit("ui.show_log", {"content": resp_text})
                resp_text = "Trace sent to Log Modal."

            else:
                resp_text = f"Unknown command: {cmd}"
                
            return {
                "response": resp_text,
                "calls": [], "results": [], "path_used": "command", "success": True
            }

        # --- Path: Known (SkillMemory cache) ---
        # SkillMemory provides a hint (few-shot), but does NOT execute blindly to prevent structural risks.
        known_skill = self._try_known(text)
        if known_skill is not None:
            event_bus.emit("pipeline.known_hit", { "session_id": session_id,"text": text[:80]})

        # --- Path: Pure-LLM ReAct Loop (ALL new tasks go directly to LLM) ---
        event_bus.emit("pipeline.new_path", { "session_id": session_id,"text": text[:80]})
        event_bus.emit("pipeline.path_start", { "session_id": session_id,"path": PATH_NEW, "text": text[:80]})
        # Blindaje del lock de turno: pase lo que pase (cancelacion del operador,
        # desconexion del cliente, excepcion del LLM o de una habilidad) la sesion
        # DEBE quedar libre. Sin este finally, un turno abortado dejaba
        # _active_turns[session_id] colgado para siempre y todo mensaje posterior
        # respondia "A cognitive turn is already running for this session."
        try:
            result = await self._try_new(text, sensor_data, tools, known_skill=known_skill, session_id=session_id)
        except asyncio.CancelledError:
            self._release_turn(session_id)
            event_bus.emit("pipeline.turn_aborted", {
                "session_id": session_id, "reason": "cancelled", "text": text[:80],
            })
            logger.info("pipeline: turno cancelado y lock liberado (session=%s).", session_id)
            return self._finalize(
                {
                    "response": "Task cancelled by operator.",
                    "calls": [],
                    "results": [],
                    "success": False,
                    "cancelled": True,
                },
                PATH_NEW,
                success=False,
                session_id=session_id,
            )
        except BaseException:
            self._release_turn(session_id)
            event_bus.emit("pipeline.turn_aborted", {
                "session_id": session_id, "reason": "error", "text": text[:80],
            })
            raise
        return self._finalize(result, PATH_NEW, success=result["success"], session_id=session_id)

    # ---- Reflexive & Known -------------------------------------------------

    async def _try_reflexive(self, text: str) -> Optional[Dict[str, Any]]:
        normalized = text.strip().lower()
        if not normalized:
            return None

        normalized = re.sub(r"[?!.,]+$", "", normalized).strip()

        if normalized in self._reflex_table:
            return {
                "response": self._reflex_table[normalized],
                "calls": [],
                "results": [],
            }

        if normalized in ("who are you", "quien eres", "quien sos", "tu nombre"):
            name = self.reasoning.identity.get_name()
            desc = self.reasoning.identity.get_description()
            return {
                "response": f"I am {name}. {desc}",
                "calls": [],
                "results": [],
            }



        if any(h in normalized for h in ("que hora es", "dime la hora", "dime hora actual")):
            return {
                "response": "Checking current time...",
                "calls": [{"action": "get_current_time"}],
                "results": [],
            }

        if any(h in normalized for h in ("estado del sistema", "system info", "informacion del sistema", "como esta el sistema")):
            return {
                "response": "Checking system metrics...",
                "calls": [{"action": "get_system_info"}],
                "results": [],
            }

        # Semantic Intent Classifier using LocalLLMClient
        return await self._fast_intent_classification(text)

    async def _fast_intent_classification(self, text: str) -> Optional[Dict[str, Any]]:
        """Embedding-based intent classifier — no LLM, ~3ms, purely local.

        Uses cosine similarity against pre-defined intent anchor phrases via
        the same fastembed model used by SkillMemory. Falls through to LLM
        ReAct loop if no confident match (threshold 0.82).
        """
        try:
            from core.memory import _Embedder, _cosine_similarity
            embedder = _Embedder()

            # Intent anchors — minimal set for truly reflexive queries only.
            # Anything that requires reasoning goes straight to LLM.
            INTENT_ANCHORS: Dict[str, List[str]] = {
                "time": [
                    "what time is it", "current time", "que hora es",
                    "tell me the time", "dime la hora", "hora actual",
                ],
                "identity": [
                    "who are you", "what are you", "quien eres",
                    "introduce yourself", "your name",
                ],
                "open_app": [
                    "open application", "launch program", "abre la aplicacion",
                    "inicia el programa", "ejecuta la app", "start app"
                ],
            }

            query_vec = embedder.embed(text)
            best_intent: Optional[str] = None
            best_score: float = 0.0

            for intent, anchors in INTENT_ANCHORS.items():
                for anchor in anchors:
                    anchor_vec = embedder.embed(anchor)
                    score = _cosine_similarity(query_vec, anchor_vec)
                    if score > best_score:
                        best_score = score
                        best_intent = intent

            # High threshold — only intercept if very confident it's trivial
            if best_intent and best_score >= 0.82:
                if best_intent == "time":
                    return {
                        "response": "Checking current time...",
                        "calls": [{"action": "get_current_time"}],
                        "results": [],
                    }
                if best_intent == "identity":
                    name = self.reasoning.identity.get_name()
                    desc = self.reasoning.identity.get_description()
                    return {
                        "response": f"I am {name}. {desc}",
                        "calls": [],
                        "results": [],
                    }
                if best_intent == "open_app":
                    import os
                    known_apps = [
                        "chrome", "brave", "opera", "edge", "notepad", "calculator", "calc",
                        "word", "excel", "powerpoint", "winword", "powerpnt", "code", "vs code",
                        "spotify", "cmd", "powershell", "terminal", "paint", "mspaint"
                    ]
                    text_lower = text.lower()
                    target_app = None
                    for app in known_apps:
                        if app in text_lower:
                            target_app = app
                            break
                    if target_app:
                        return {
                            "response": f"Opening {target_app}...",
                            "calls": [{"action": "open_application", "app_name": target_app}],
                            "results": [],
                        }

        except Exception as e:
            logger.debug(f"pipeline: embedding classifier skipped: {e}")

        # Anything else → LLM ReAct loop
        return None

    @staticmethod
    def _compose_result_response(
        placeholder: str,
        calls: List[Dict[str, Any]],
        results: List[Dict[str, Any]],
    ) -> str:
        """Compone la respuesta final con datos REALES de las tool calls reflejas.

        Antes de esta correccion, el placeholder ("Checking current time...")
        se devolvia como respuesta final aunque la herramienta ya hubiera
        devuelto el resultado (ej. la hora actual).
        """
        if not results:
            return placeholder

        lines: List[str] = []
        for call, res in zip(calls, results):
            action = str(call.get("action") or "").lower()
            output = res.get("output") or {}
            ok = bool(res.get("ok", False))

            if isinstance(output, dict):
                data = output.get("data") or {}
                message = output.get("message") or ""
            else:
                data, message = {}, str(output or "")

            if not ok:
                reason = (
                    res.get("reason")
                    or (output.get("message") if isinstance(output, dict) else None)
                    or (output.get("error") if isinstance(output, dict) else None)
                    or "unknown error"
                )
                lines.append(f"I couldn't complete that: {reason}")
                continue

            if action in ("time", "get_current_time"):
                t = data.get("time") if isinstance(data, dict) else None
                lines.append(f"The current time is {t}." if t else message)
            elif action in ("date", "get_current_date"):
                lines.append(message or (str(data) if data else placeholder))
            elif action in ("info", "get_system_info"):
                lines.append(message or (str(data) if data else placeholder))
            elif action in ("open_application", "launch", "execute"):
                params = call.get("params") if isinstance(call.get("params"), dict) else {}
                app = (
                    call.get("app_name")
                    or call.get("application")
                    or params.get("app_name")
                    or params.get("application")
                    or "application"
                )
                lines.append(f"Done. {app} launched successfully.")
            else:
                lines.append(message or placeholder)

        return " ".join(line for line in lines if line) or placeholder

    def _try_known(self, text: str) -> Optional[Dict[str, Any]]:
        skill = self.skill_memory.lookup(text)
        if not skill:
            return None
        return {
            "response": skill.get("response", ""),
            "calls": skill.get("calls", []),
            "results": [],
        }

    # ---- Multi-Step Agentic Loop -------------------------------------------

    async def _try_new(
        self,
        text: str,
        sensor_data: Optional[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        known_skill: Optional[Dict[str, Any]] = None,
        session_id: str = "default",
    ) -> Dict[str, Any]:
        """Full-agentic ReAct loop: think → parallel execute → verify → metacognitive check → repair → synthesize."""
        active_turn = self._active_turns.get(session_id)
        if active_turn:
            return {
                "response": "A cognitive turn is already running for this session.",
                "calls": [],
                "results": [],
                "path_used": PATH_NEW,
                "success": False,
                "steps_used": 0,
                "session_id": session_id,
            }
        turn = TurnContext(
            turn_id=uuid.uuid4().hex,
            session_id=session_id,
            objective=text,
        )
        self._active_turns[session_id] = turn.turn_id
        try:
            self._turn_tasks[session_id] = asyncio.current_task()  # type: ignore[assignment]
        except RuntimeError:  # sin loop (tests sincronos)
            pass
        event_bus.emit("pipeline.turn_started", {
            "session_id": session_id,
            "turn_id": turn.turn_id,
            "objective": text[:160],
        })

        all_calls = turn.calls
        all_results = turn.results
        text_response = ""
        final_ok = True
        turn_cancelled = False
        trace = turn.trace
        step_count = 0
        _verifier = MetacognitiveVerifier()
        executed_calls = turn.executed_calls

        # Anti-estancamiento: si el LLM solo narra la intencion sin emitir tool
        # calls, no damos el turno por terminado; le exigimos ejecutar.
        nudge_attempts = 0
        max_nudges = 2
        pending_nudge = ""

        for step in range(1, self.max_steps + 1):
            step_count = step
            turn.planner_steps = step

            # Cancellation check (cooperativa): se consulta antes de cada paso,
            # antes de cada llamada al LLM y antes de cada herramienta.
            if self._is_cancelled(session_id):
                turn_cancelled = True
                event_bus.emit("pipeline.loop_cancelled", { "session_id": session_id,"step": step, "text": text[:80]})
                break

            event_bus.emit("pipeline.loop_step", { "session_id": session_id,
                "step": step, "max_steps": self.max_steps,
                "text": text[:80],
            })

            # Build prompt with accumulated context
            if step == 1:
                prompt = text
                if known_skill:
                    cached_calls = known_skill.get("calls", [])
                    if cached_calls:
                        prompt += f"\n\n[HINT: A similar task was previously solved using these tools: {json.dumps(cached_calls)}. You can use them if they match the current context.]"
            else:
                # Condense trace to prevent context inflation
                condensed_trace = []
                for t in trace:
                    st = "OK" if t.get("verified") else "FAIL"
                    act = t.get("call", {}).get("action", "unknown")
                    note = t.get("verification_note", "")
                    
                    res = t.get("result", {})
                    out = res.get("data") or res.get("output")
                    out_str = ""
                    if out:
                        out_str = f" | Output: {str(out)[:800]}"
                        
                    condensed_trace.append(f"Step {t.get('step')}: {act} -> [{st}] {note}{out_str}")
                trace_str = "\n".join(condensed_trace)
                prompt = (
                    f"{text}\n\n"
                    f"[MULTI-STEP CONTEXT — Step {step}/{self.max_steps}]\n"
                    f"Previous actions and results:\n{trace_str}\n\n"
                    f"Continue working towards the user's goal. "
                    f"If the task is COMPLETE, respond with ONLY your final answer (no tool calls). "
                    f"If more actions are needed, emit tool calls."
                )
            # Inject Transient Context (if any)
            active_context_str = ""
            ctx_dict = self._focused_contexts.get(session_id, {})
            if ctx_dict:
                active_context_str = "\n[ACTIVE CONTEXT FILES (TRANSIENT)]\n"
                for fname, fcontent in ctx_dict.items():
                    active_context_str += f"\n--- {fname} ---\n{fcontent}\n"
                active_context_str += "\n[/ACTIVE CONTEXT FILES]\n\n"
                
            final_prompt = active_context_str + prompt
            if pending_nudge:
                final_prompt += pending_nudge
                pending_nudge = ""

            thought = await self.reasoning.think(final_prompt, sensor_data=sensor_data, tools=tools, session_id=session_id)
            calls = thought.get("calls", []) or []
            text_response = thought.get("text", "") or ""
            turn.plan.append({"step": step, "calls": calls})
            event_bus.emit("pipeline.plan_step", {
                "session_id": session_id,
                "turn_id": turn.turn_id,
                "step": step,
                "call_count": len(calls),
            })

            # If no tool calls, the LLM considers the task done — PERO solo si de
            # verdad lo ha hecho. Si unicamente anuncio una intencion en futuro,
            # eso no es una tarea cumplida: es el turno estancado que el usuario
            # describia como "dice que va a verificar y se queda parado".
            if not calls:
                if nudge_attempts < max_nudges and _announces_future_action(text_response):
                    nudge_attempts += 1
                    pending_nudge = (
                        "\n\n[NUDGE — ACCION ANUNCIADA PERO NO EJECUTADA]\n"
                        "Tu mensaje anterior solo ANUNCIO una accion en futuro y NO "
                        "emitiste ninguna tool call. Anunciar no es hacer.\n"
                        "Emite AHORA las tool calls necesarias para ejecutar el "
                        "siguiente paso real. No repitas el anuncio.\n"
                        "Usa texto plano solo si la tarea esta COMPLETA y verificada "
                        "con evidencia concreta.\n"
                    )
                    logger.warning(
                        "pipeline: turno estancado en paso %s de '%s' "
                        "(0 tool calls, solo narracion) — nudge %s/%s",
                        step, text[:60], nudge_attempts, max_nudges,
                    )
                    event_bus.emit("pipeline.loop_nudged", {
                        "session_id": session_id,
                        "turn_id": turn.turn_id,
                        "step": step,
                        "attempt": nudge_attempts,
                        "text": text[:80],
                        "announced": text_response[:200],
                    })
                    continue
                final_ok = True
                break

            # Execute calls (with approval check in secure mode)
            results, ok = await self._execute_calls(
                calls, session_id=session_id, executed_calls=executed_calls
            )
            all_calls.extend(calls)
            all_results.extend(results)
            duplicate_only = bool(results) and all(
                (result.get("output") or {}).get("reason") == "duplicate_call_in_request"
                for result in results
            )

            # ── Post-Action Verification ─────────────────────────────────────
            # For each call+result pair, attempt empirical verification.
            # This prevents WIS from claiming success without real evidence.
            for call, result in zip(calls, results):
                verified = result.get("ok", result.get("success", False))
                verification_note = ""

                try:
                    skill = call.get("skill", "") or ""
                    action = call.get("action", "") or ""
                    output = result.get("output") or result.get("data") or {}

                    # Verify process launch
                    if action in ("open_application", "launch", "execute") or "open" in action:
                        pid = output.get("pid") if isinstance(output, dict) else None
                        if pid:
                            import psutil
                            if psutil.pid_exists(int(pid)):
                                verified = True
                                verification_note = f"PID {pid} confirmed running."
                            else:
                                verified = False
                                verification_note = f"PID {pid} NOT found — process may have crashed."
                        else:
                            verification_note = "No PID returned — cannot confirm process started."

                    # Verify file creation/write
                    elif action in ("write_file", "save_file", "create_file", "write") or "file" in action:
                        import os
                        path = (
                            output.get("path") or output.get("file_path") or output.get("wav_path")
                            if isinstance(output, dict) else None
                        )
                        if path and os.path.exists(path):
                            size = os.path.getsize(path)
                            verified = True
                            verification_note = f"File confirmed on disk: {path} ({size} bytes)."
                        elif path:
                            verified = False
                            verification_note = f"File NOT found on disk: {path}"
                        else:
                            verification_note = "No file path returned — cannot confirm file exists."

                except Exception as vex:
                    verification_note = f"Verification skipped: {vex}"

                # Record in structured trace
                trace.append({
                    "step": step,
                    "call": call,
                    "result": result,
                    "verified": verified,
                    "verification_note": verification_note,
                })
                if not verified:
                    ok = False

            # Build trace summary for LLM context (structured JSON, not free text)
            trace_json = json.dumps(trace, ensure_ascii=False, default=str, indent=2)

            if not ok:
                # Auto-repair attempt
                failed_msgs = [
                    r.get("reason") or (r.get("output", {}) or {}).get("message")
                    or (r.get("output", {}) or {}).get("error")
                    for r in results if not r.get("ok", False)
                ]
                error_desc = " | ".join(str(m) for m in failed_msgs if m)
                category = FailureClassifier.classify(error_desc)
                event_bus.emit("pipeline.failure_classified", { "session_id": session_id,
                    "category": category, "error": error_desc, "text": text[:80]
                })

                # El prompt escala a reparacion de codigo si el fallo es un
                # defecto de software; si no, pide otra tool/parametros.
                repair_prompt = _build_repair_prompt(text, step, category, error_desc)
                try:
                    repair_thought = await self.reasoning.think(active_context_str + repair_prompt, sensor_data=sensor_data, tools=tools, session_id=session_id)
                    repair_calls = repair_thought.get("calls", []) or []
                    if repair_calls:
                        repair_results, repair_ok = await self._execute_calls(
                            repair_calls,
                            session_id=session_id,
                            executed_calls=executed_calls,
                        )
                        if repair_ok:
                            text_response = repair_thought.get("text", "") or text_response
                            all_calls.extend(repair_calls)
                            all_results.extend(repair_results)
                            ok = True
                            for rc, rr in zip(repair_calls, repair_results):
                                trace.append({
                                    "step": step,
                                    "call": rc,
                                    "result": rr,
                                    "verified": rr.get("ok", False),
                                    "verification_note": "auto-repair",
                                })
                except Exception as exc:
                    logger.warning(f"pipeline: auto-repair failed: {exc}")

            final_ok = ok

            if duplicate_only:
                # El LLM repitio una accion ya ejecutada: se detiene el bucle (no
                # tiene sentido repetir efectos). Antes se marcaba success=True
                # creyendo su texto, y asi el turno terminaba en una PROMESA
                # ("Let me kill them by PID") con exito falso. Ahora el exito
                # exige evidencia verificada, y el guard final convierte
                # cualquier promesa en un informe honesto.
                text_response = (
                    text_response.strip()
                    or "The requested actions were already completed; no duplicate action was executed."
                )
                final_ok = any(t.get("verified") for t in trace)
                break

            # Post-exec synthesis + MetaCognitive Verification
            if step == self.max_steps or not calls:
                try:
                    verified_count = sum(1 for t in trace if t.get("verified"))
                    failed_count = len(trace) - verified_count
                    
                    if failed_count > 0:
                        # Enforce failure honestly, skip LLM synthesis hallucination risk
                        failed_notes = " | ".join(t.get("verification_note", "") for t in trace if not t.get("verified"))
                        text_response = f"I failed to complete the task. Reason: {failed_notes}"
                        final_ok = False
                    else:
                        synth_prompt = (
                            f"{text}\n\n"
                            f"[POST-EXECUTION SYNTHESIS]\n"
                            f"Execution trace (structured — {verified_count} verified):\n"
                            f"{json.dumps(trace, ensure_ascii=False, default=str, indent=2)}\n\n"
                            f"IMPORTANT INSTRUCTIONS FOR YOUR RESPONSE:\n"
                            f"- Report ONLY outcomes confirmed in the trace above (verified=true).\n"
                            f"- Be concise and factual."
                        )
                        synth = await self.reasoning.think(active_context_str + synth_prompt, sensor_data=sensor_data, session_id=session_id)
                        if synth.get("text"):
                            text_response = synth["text"].strip()
                except Exception as exc:
                    logger.warning(f"pipeline: synthesis skipped: {exc}")

                # ── MetaCognitive Verification ─────────────────────────────
                verification = _verifier.verify(
                    agent_response=text_response,
                    tool_results=all_results,
                    action_trace=trace,
                )
                if not verification.passed:
                    event_bus.emit("pipeline.metacognitive_correction", { "session_id": session_id,
                        "issue": verification.issue,
                        "severity": verification.severity,
                    })
                    if verification.reflection_prompt and verification.severity == "critical":
                        try:
                            reflection = await self.reasoning.think(
                                active_context_str + verification.reflection_prompt, sensor_data=sensor_data, session_id=session_id
                            )
                            if reflection.get("text"):
                                text_response = reflection["text"].strip()
                        except Exception as exc:
                            logger.warning(f"pipeline: reflection skipped: {exc}")

        if turn_cancelled:
            text_response = "Task cancelled by operator."
            final_ok = False
            event_bus.emit("pipeline.turn_aborted", {
                "session_id": session_id, "reason": "cancelled",
                "text": text[:80], "turn_id": turn.turn_id,
            })

        event_bus.emit("pipeline.loop_done", { "session_id": session_id,
            "steps": step_count, "max_steps": self.max_steps,
            "success": final_ok, "text": text[:80], "turn_id": turn.turn_id,
        })
        event_bus.emit("pipeline.turn_finished", {
            "session_id": session_id,
            "turn_id": turn.turn_id,
            "steps": turn.planner_steps,
            "calls": len(turn.calls),
            "trace_entries": len(turn.trace),
            "success": final_ok,
        })
        if self._active_turns.get(session_id) == turn.turn_id:
            self._active_turns.pop(session_id, None)
        self._turn_tasks.pop(session_id, None)

        # ── Guard: si ambos LLMs (API + local) fallaron, no devolver silencio ──
        if not (text_response or "").strip():
            text_response = (
                "I'm sorry, I couldn't reach my language model right now "
                "(offline or connection error). Please check the API key / network "
                "and try again."
            )
            final_ok = False
            event_bus.emit("pipeline.empty_response_fallback", { "session_id": session_id,"text": text[:80]})

        # ── Guard anti-promesa ───────────────────────────────────────────────
        # El turno puede cerrarse (llamada duplicada, max_steps, cancelacion) con
        # el texto de una PROMESA en vez de un resultado: "Let me kill them
        # directly by PID using taskkill". Eso es exactamente lo que el usuario
        # vivia como "dice que va a verificar y se queda parado". La promesa
        # nunca se devuelve como resultado: se convierte en informe honesto.
        if _announces_future_action(text_response):
            ok_actions = sorted({
                str(t.get("call", {}).get("action") or t.get("call", {}).get("name") or "?")
                for t in trace if t.get("verified")
            })
            failed_actions = sorted({
                str(t.get("call", {}).get("action") or t.get("call", {}).get("name") or "?")
                for t in trace if not t.get("verified")
            })
            logger.warning(
                "pipeline: turno cerrado en promesa para '%s' (pasos=%s, ok=%s, fallos=%s)",
                text[:60], step_count, ok_actions, failed_actions,
            )
            event_bus.emit("pipeline.promise_instead_of_result", {
                "session_id": session_id,
                "turn_id": turn.turn_id,
                "steps": step_count,
                "ok_actions": ok_actions,
                "failed_actions": failed_actions,
                "announced": text_response[:200],
            })
            report = [
                "[AVISO] El turno termino sin ejecutar la accion que anunciaba, "
                "asi que NO hay resultado confirmado de ese paso.",
                "Acciones verificadas: " + (", ".join(ok_actions) if ok_actions else "ninguna") + ".",
            ]
            if failed_actions:
                report.append("Acciones que fallaron: " + ", ".join(failed_actions) + ".")
            report.append("Lo anunciado queda PENDIENTE, no hecho.")
            text_response = "\n".join(report) + "\n\n---\n" + text_response
            if not ok_actions:
                final_ok = False

        if self._persistent_session(session_id):
            try:
                self.reasoning.memory.remember(text, text_response, session_id=session_id)
            except Exception:
                logger.warning("pipeline: could not remember interaction.")

        if final_ok:
            self.skill_memory.record_success(text, all_calls, text_response)
            # Tarea asíncrona de destilación para enriquecer el Modo Rápido (Offline Mode)
            asyncio.create_task(self._distill_and_cache(text, all_calls, text_response))
        else:
            self.skill_memory.record_failure(text, all_calls)
            
        self._last_trace[session_id] = trace
        self._save_session_state(session_id)

        return {
            "response": text_response,
            "calls": all_calls,
            "results": all_results,
            "success": final_ok,
            "steps_used": step_count,
            "raw_response": "",
            "model_used": "",
        }

    async def _distill_and_cache(self, user_text: str, calls: List[Dict[str, Any]], response: str) -> None:
        """Destila una tarea exitosa usando el LLM online para extraer variaciones 
        y guardarlas en SkillMemory. Esto hace que el Modo Offline sea super robusto."""
        if not calls:
            return
            
        from core.skill_memory import _is_cacheable
        if not _is_cacheable(user_text, calls):
            return

        try:
            fast_model = self.reasoning.router.route(user_text, has_tools=False)
            system_msg = {
                "role": "system",
                "content": (
                    "You are an expert AI linguist. Your task is to extract highly precise, natural, "
                    "and professional alternative phrasings for a user's intent. "
                    "Return ONLY a valid JSON array of strings without markdown formatting or explanation."
                )
            }
            user_msg = {
                "role": "user",
                "content": (
                    f"The user successfully executed an action by saying: '{user_text}'.\n"
                    f"Please generate 3 alternative short, natural phrasings that a user might say to request this exact same action, in the same language.\n"
                    f"Example format: [\"phrase 1\", \"phrase 2\", \"phrase 3\"]"
                )
            }
            
            res = await self.reasoning.llm_client.chat([system_msg, user_msg], model=fast_model, temperature=0.3)
            text = res.get("text", "")
            
            import re
            import json
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                phrasings = json.loads(match.group(0))
                for phrase in phrasings:
                    if isinstance(phrase, str) and len(phrase) > 2:
                        self.skill_memory.record_success(phrase, calls, response)
                logger.info(f"pipeline: distilled {len(phrasings)} professional variations for offline fast-mode.")
        except Exception as e:
            logger.debug(f"pipeline: background distillation skipped (possibly offline): {e}")

    # ---- Execute Calls (with approval) ------------------------------------

    # ── Autonomous telemetry trigger handler ────────────────────────────────

    async def handle_autonomous_trigger(self, event: Dict[str, Any]) -> None:
        """Called by TelemetryEngine when a threshold rule fires.
        Processes the action autonomously without waiting for user input.
        """
        prompt = event.get("action_prompt", "")
        sensor_data = event.get("readings")
        if not prompt:
            return
        logger.info("pipeline: autonomous trigger fired: %s", prompt[:80])
        event_bus.emit("pipeline.autonomous_trigger", { "session_id": session_id,"prompt": prompt[:80]})
        try:
            await self.process(prompt, sensor_data=sensor_data)
        except Exception as exc:
            logger.error("pipeline: autonomous trigger failed: %s", exc)

    async def _execute_calls(
        self,
        calls: List[Dict[str, Any]],
        session_id: str = "default",
        executed_calls: Optional[set[str]] = None,
    ) -> tuple:
        if not calls:
            return [], True

        results: List[Dict[str, Any]] = []
        all_ok = True

        seen = executed_calls if executed_calls is not None else set()
        for call in calls:
            # Cooperativa: no arrancar la siguiente herramienta si el operador cancelo.
            if self._is_cancelled(session_id):
                results.append({
                    "ok": False,
                    "name": call.get("skill") or call.get("name") or call.get("action") or "unknown",
                    "action": call.get("action") or "",
                    "output": {"error": "cancelled_by_operator"},
                    "reason": "cancelled_by_operator",
                })
                all_ok = False
                continue

            fingerprint = self._call_fingerprint(call)
            # Las lecturas se pueden repetir sin riesgo; solo se deduplican las
            # acciones con efectos secundarios.
            repeatable = _is_repeatable_call(call)
            if not repeatable and fingerprint in seen:
                result = {
                    "ok": True,
                    "name": call.get("skill") or call.get("name") or call.get("action") or "unknown",
                    "action": call.get("action") or "",
                    "output": {"skipped": True, "reason": "duplicate_call_in_request"},
                }
            else:
                result = await self._execute_single_call(
                    call,
                    require_approval=self.safety.needs_approval(call),
                    session_id=session_id,
                )
                if result.get("ok", False) and not repeatable:
                    seen.add(fingerprint)
            results.append(result)
            if not result.get("ok", False):
                all_ok = False

        return results, all_ok

    @staticmethod
    def _call_fingerprint(call: Dict[str, Any]) -> str:
        """Stable identity for preventing repeated side effects in one request."""
        return json.dumps(call, sort_keys=True, ensure_ascii=False, default=str)

    async def _execute_single_call(
        self, call: Dict[str, Any], require_approval: bool = False, session_id: str = "default"
    ) -> Dict[str, Any]:
        """Execute a single tool call with safety, optional approval gate, and dispatch."""
        if not isinstance(call, dict):
            return {"error": "invalid_call", "call": call, "ok": False}

        # Hard safety block
        allowed, reason = self.safety.check(call)
        if not allowed:
            call_name = call.get("skill") or call.get("name") or "unknown"
            event_bus.emit("pipeline.call_blocked", { "session_id": session_id,"name": call_name, "reason": reason})
            return {"blocked": True, "reason": reason, "name": call_name, "ok": False}

        # Approval gate
        if require_approval:
            call_name = (
                call.get("skill") or call.get("name") or
                call.get("action") or call.get("tool") or "unknown"
            )
            event_bus.emit("pipeline.approval_required", { "session_id": session_id,
                "call": call, "name": call_name,
                "action": call.get("action") or call.get("tool") or "",
                "params": call.get("params") or call.get("arguments") or {},
            })
            self._approval_events[session_id] = asyncio.Event()
            self._approval_results[session_id] = False
            try:
                await asyncio.wait_for(self._approval_events[session_id].wait(), timeout=120)
            except asyncio.TimeoutError:
                self._approval_results[session_id] = False
            if not self._approval_results.get(session_id, False):
                event_bus.emit("pipeline.call_denied", { "session_id": session_id,"name": call_name})
                return {
                    "ok": False, "name": call_name,
                    "action": call.get("action") or "",
                    "output": {"error": "denied_by_user"},
                }
            event_bus.emit("pipeline.call_approved", { "session_id": session_id,"name": call_name})

        # Resolve skill / action / params
        skill_name = str(call.get("skill") or call.get("name") or call.get("tool") or "").strip()
        raw_action = str(call.get("action") or "").strip()
        raw_type = str(call.get("type") or "").strip()

        if isinstance(call.get("params"), dict):
            params = dict(call["params"])
        elif isinstance(call.get("arguments"), dict):
            params = dict(call["arguments"])
        else:
            params = {
                k: v for k, v in call.items()
                if k not in ("skill", "name", "action", "type", "domain", "tool", "params", "arguments")
            }
        
        # Inject context for abilities that support multitenancy
        params["_session_id"] = session_id
        # Canal cooperativo de cancelacion para habilidades que lanzan
        # subprocesos (shell, repl, scripts): ShellOps y el interprete lo
        # consultan cada ~200 ms y matan el arbol de procesos.
        cancel_event = self._cancel_events.get(session_id)
        if cancel_event is not None:
            params["_cancel_event"] = cancel_event

        if "command" in call and "command" not in params:
            params["command"] = call["command"]
        if "app_name" in call and "app_name" not in params:
            params["app_name"] = call["app_name"]

        action = raw_action or skill_name
        if not action or action in ("exec", "shell", "cmd", "powershell", "bash", "run"):
            if raw_type in ("exec", "shell", "cmd", "powershell", "bash", "run") or "command" in params:
                action = "execute_shell"
            elif "app_name" in params or "application" in params:
                action = "open_application"
            elif "query" in params:
                action = "web_search"
            elif "level" in params or "volume" in params:
                action = "set_volume"

        if not skill_name and self.abilities:
            if hasattr(self.abilities, "all"):
                for ab_name, ab in self.abilities.all().items():
                    supported = [a.get("action", "").lower() for a in ab.get_schema() if isinstance(a, dict)]
                    if (
                        action.lower() in supported
                        or action.lower() == ab_name.lower()
                        or action.lower() == ab.domain.lower()
                    ):
                        skill_name = ab_name
                        break

        event_bus.emit("pipeline.call_start", { "session_id": session_id,"skill": skill_name, "action": action, "params": params})

        output = None
        success = False

        if hasattr(self.abilities, "execute") and callable(getattr(self.abilities, "execute")):
            try:
                res = await self.abilities.execute(skill_name, action, params)
                output = res
                success = res.get("success", False) if isinstance(res, dict) else True
            except Exception as exc:
                logger.warning("pipeline: ability execute failed: %s", exc)
                output = {"error": str(exc)}
                success = False
        elif isinstance(self.abilities, dict):
            fn = self.abilities.get(skill_name) or self.abilities.get(action)
            if fn is None:
                output = {"error": "unknown_ability", "name": skill_name or action}
                success = False
            else:
                try:
                    if inspect.iscoroutinefunction(fn):
                        output = await fn(call)
                    else:
                        output = fn(call)
                    success = True
                except Exception as exc:
                    output = {"error": str(exc)}
                    success = False
        else:
            output = {"error": "no_abilities_registered"}
            success = False

        event_bus.emit("pipeline.call_result", { "session_id": session_id,
            "skill": skill_name, "action": action,
            "success": success, "output": output,
        })
        return {"ok": success, "name": skill_name or action, "action": action, "output": output}

    @staticmethod
    def _finalize(result: Dict[str, Any], path: str, success: bool, session_id: str = "default") -> Dict[str, Any]:
        final_dict = {
            "response": result.get("response", ""),
            "calls": result.get("calls", []),
            "results": result.get("results", []),
            "path_used": path,
            "success": bool(result.get("success", success)),
            "steps_used": result.get("steps_used", 1),
        }
        final_dict["session_id"] = session_id
        event_bus.emit("pipeline.response_ready", final_dict)
        return final_dict
