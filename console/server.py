"""
WIS Console Server - FastAPI backend for the web interface.
Servidor backend FastAPI para la interfaz web.

Este modulo expone:
  - REST: POST /api/chat, GET /api/state, GET /api/abilities,
          GET /api/memory/facts
  - WebSocket: /ws (streaming bidireccional en tiempo real)
  - Estaticos: montaje de /console -> console/web/

El servidor recibe una referencia al nucleo de WIS (cortex, praxis,
vault, etc.) mediante inyeccion de dependencias a traves de la clase
WISCoreContainer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.event_bus import event_bus

logger = logging.getLogger("wis.console.server")

# Set of active WebSockets
_active_websockets: set[WebSocket] = set()
_websocket_sessions: Dict[WebSocket, set[str]] = {}


# ---------------------------------------------------------------------------
# Autenticacion por token (Bearer header para REST, ?token= para WebSocket).
# ---------------------------------------------------------------------------

import hmac  # noqa: E402

# Token de autenticacion de la consola (None = auth desactivada).
_auth_token: Optional[str] = None
# Origenes permitidos por CORS. Por defecto solo same-origin / localhost.
_allowed_cors_origins: List[str] = []


def set_auth_token(token: Optional[str]) -> None:
    """Establece el token requerido para acceder a la API. None desactiva el auth."""
    global _auth_token
    _auth_token = (str(token).strip() if token else None)


def get_auth_token() -> Optional[str]:
    return _auth_token


def set_cors_origins(origins: Optional[List[str]]) -> None:
    """Define la lista de origenes permitidos para CORS."""
    global _allowed_cors_origins
    if not origins:
        _allowed_cors_origins = []
        return
    _allowed_cors_origins = [str(o).strip() for o in origins if str(o).strip()]


def _token_is_valid(provided: Optional[str]) -> bool:
    """True si no hay token configurado (auth off) o si el token coincide (ct-compare)."""
    if not _auth_token:
        return True
    if not provided:
        return False
    return hmac.compare_digest(str(_auth_token), str(provided))


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    """Dependencia FastAPI: valida el header Authorization: Bearer <token>."""
    if not _auth_token:
        return  # auth desactivada
    token = _extract_bearer(authorization)
    if not _token_is_valid(token):
        raise HTTPException(
            status_code=401,
            detail="Token de autenticacion invalido o ausente.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_ws_token(token: Optional[str]) -> bool:
    """Valida el token de un WebSocket recibido por query param (?token=)."""
    return _token_is_valid(token)


def broadcast_event(event_name: str, payload: Dict[str, Any]) -> None:
    """Retransmite eventos globales o solo a los clientes de la sesion."""
    if not _active_websockets:
        return
    msg = json.dumps({"type": "event_bus", "event": event_name, "data": payload}, default=str)
    try:
        loop = asyncio.get_running_loop()
        session_id = payload.get("session_id")
        for ws in list(_active_websockets):
            if session_id and session_id not in _websocket_sessions.get(ws, set()):
                continue
            # Verificar que el WebSocket siga conectado antes de enviar.
            # Esto previene el error 'send after close' cuando un cliente
            # se desconecta pero el bus sigue emitiendo eventos.
            if _ws_is_open(ws):
                loop.create_task(_safe_ws_send(ws, msg))
    except RuntimeError:
        pass


def _ws_is_open(ws: WebSocket) -> bool:
    """Devuelve True si el WebSocket sigue conectado y acepta mensajes."""
    try:
        # Starlette marca el estado en ws.application_state.
        # CONNECTED = 1, DISCONNECTED = 2 (starlette.websockets.protocol.State).
        from starlette.websockets import WebSocketState
        return ws.client_state == WebSocketState.CONNECTED
    except Exception:
        return False


async def _safe_ws_send(ws: WebSocket, msg: str) -> None:
    """Envia un mensaje al WebSocket de forma segura (ignora errores de cierre)."""
    try:
        await ws.send_text(msg)
    except Exception:
        # Conexion cerrada o rota: remover del set activo silenciosamente.
        _active_websockets.discard(ws)


def _on_bus_event(data: Dict[str, Any]) -> None:
    evt = data.get("_event_name", "bus_event")
    broadcast_event(evt, data)

event_bus.subscribe("*", _on_bus_event)

# ---------------------------------------------------------------------------
# Contenedor de dependencias del nucleo de WIS.
# Permite inyectar cortex/praxis/vault sin acoplar el servidor a detalles.
# ---------------------------------------------------------------------------


class WISCoreContainer:
    """Recibe referencias a los componentes del nucleo de WIS.

    Attributes:
        praxis: Objeto con metodo process(message) -> respuesta (str o async).
        cortex: Nucleo cognitivo (memoria / estado).
        vault:  Almacen seguro (opcional).
        abilities: Registro de habilidades disponibles.
        proactivity: Motor de proactividad (opcional).
        aegis: Politica de seguridad (opcional).
    """

    def __init__(
        self,
        praxis: Any = None,
        cortex: Any = None,
        vault: Any = None,
        abilities: Any = None,
        proactivity: Any = None,
        aegis: Any = None,
        task_store: Any = None,
    ) -> None:
        self.praxis = praxis
        self.cortex = cortex
        self.vault = vault
        self.abilities = abilities
        self.proactivity = proactivity
        self.aegis = aegis
        self.task_store = task_store


# Contenedor global por defecto; se reemplaza al arrancar la app.
_core: WISCoreContainer = WISCoreContainer()


def set_core(core: WISCoreContainer) -> None:
    """Inyecta el nucleo de WIS en el servidor."""
    global _core
    _core = core


def get_core() -> WISCoreContainer:
    """Devuelve el contenedor del nucleo actual."""
    return _core


# ---------------------------------------------------------------------------
# Modelos de datos (Pydantic) para validar entrada/salida de la API.
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Peticion de chat enviada por el usuario."""

    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    """Respuesta de chat devuelta por WIS."""

    response: str
    calls: List[Any] = []
    results: List[Any] = []
    success: bool = True
    path: Optional[str] = None
    # True cuando el operador aborto el turno cognitivo desde la consola.
    cancelled: bool = False


class GoalCreateRequest(BaseModel):
    """Peticion para crear un objetivo del GoalManager."""

    text: str
    priority: int = 5
    deadline: str = ""
    session_id: str = "default"


class LongHorizonCreateRequest(BaseModel):
    """Peticion para crear una tarea Long-Horizon."""

    text: str
    priority: int = 5
    subtask_timeout: float = 300.0


class RenderRequest(BaseModel):
    """Peticion para renderizar contenido visual en ventana emergente.

    `render_id` identifica la ventana: reutilizarlo actualiza la misma ventana.
    Omitirlo crea una ventana nueva, permitiendo a cada sesion abrir tantas
    como necesite.
    """

    html: str
    title: str = "WIS Render"
    width: int = 800
    height: int = 600
    render_id: Optional[str] = None
    session_id: str = "default"


# ---------------------------------------------------------------------------
# Utilidades internas.
# ---------------------------------------------------------------------------


async def _maybe_await(value: Any) -> Any:
    """Espera el valor si es una corrutina, sino lo devuelve directo."""
    if asyncio.iscoroutine(value):
        return await value
    return value


def _safe_call(target: Any, attr: str, *args: Any, **kwargs: Any) -> Any:
    """Llama a un atributo del objetivo si existe; devuelve None si no."""
    if target is None:
        return None
    fn = getattr(target, attr, None)
    if fn is None:
        return None
    return fn(*args, **kwargs)


def gather_system_context() -> dict:
    """Recolecta información de presencia ambiental del sistema operativo (apps abiertas, volumen, etc.)"""
    import os
    import platform
    
    context = {}
    context["current_directory"] = os.getcwd()
    
    # 1. Volumen del sistema (usando pycaw / comtypes de manera segura)
    try:
        from ctypes import cast, POINTER
        from comtypes import CoInitialize, CoUninitialize, CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        
        CoInitialize()
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        context["system_volume"] = int(round(volume.GetMasterVolumeLevelScalar() * 100))
        context["system_muted"] = bool(volume.GetMute())
        CoUninitialize()
    except Exception:
        context["system_volume"] = "unknown"
        context["system_muted"] = "unknown"

    # 2. Aplicaciones/Procesos activos (con ventana visible)
    if platform.system() == "Windows":
        try:
            import ctypes
            EnumWindows = ctypes.windll.user32.EnumWindows
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            GetWindowText = ctypes.windll.user32.GetWindowTextW
            GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
            IsWindowVisible = ctypes.windll.user32.IsWindowVisible
            GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
            
            visible_windows = []
            
            def foreach_window(hwnd, lParam):
                if IsWindowVisible(hwnd):
                    length = GetWindowTextLength(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        GetWindowText(hwnd, buff, length + 1)
                        title = buff.value
                        
                        # Filtrar nombres internos de Windows
                        if title and not any(x in title for x in (
                            "Default IME", "MSCTFIME", "Windows Input Experience", 
                            "Program Manager", "Settings", "Consola de WIS", 
                            "WIS Console", "Task Manager"
                        )):
                            pid = ctypes.c_ulong()
                            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                            visible_windows.append(f"{title} (PID: {pid.value})")
                return True
                
            EnumWindows(EnumWindowsProc(foreach_window), 0)
            context["active_windows"] = visible_windows[:15]
        except Exception:
            context["active_windows"] = []
    else:
        context["active_windows"] = []
        
    return context


def _normalize_response(raw: Any) -> Dict[str, Any]:
    """Normaliza la salida de praxis.process() a un diccionario plano.

    Praxis devuelve {response, calls, results, path_used, success}; mapeamos
    path_used -> path para la UI.
    """
    if isinstance(raw, dict):
        return {
            "response": str(raw.get("response", "")),
            "calls": list(raw.get("calls", []) or []),
            "results": list(raw.get("results", []) or []),
            "success": bool(raw.get("success", True)),
            # Praxis usa 'path_used'; aceptamos ambas claves por compatibilidad.
            "path": raw.get("path") or raw.get("path_used"),
        }
    return {"response": str(raw or ""), "calls": [], "results": [], "success": True, "path": None}


def _get_facts(cortex: Any) -> List[str]:
    """Extrae hechos desde cortex.mnemonic.get_facts() (API real de WIS)."""
    if cortex is None:
        return []
    mnemonic = getattr(cortex, "mnemonic", None)
    if mnemonic is None:
        return []
    try:
        fn = getattr(mnemonic, "get_facts", None)
        if fn is None:
            return []
        return [str(f) for f in (fn() or [])]
    except Exception:
        return []


def _abilities_as_list(abilities: Any) -> List[Dict[str, Any]]:
    """Normaliza 'abilities' que puede ser dict, AbilityRegistry o lista."""
    if abilities is None:
        return []
    # Caso AbilityRegistry: expone get_schemas() con metadata rica.
    schemas_fn = getattr(abilities, "get_schemas", None)
    if callable(schemas_fn):
        try:
            return list(schemas_fn() or [])
        except Exception:
            pass
    # Caso AbilityRegistry: expone names() + all().
    names_fn = getattr(abilities, "names", None)
    all_fn = getattr(abilities, "all", None)
    if callable(names_fn) and callable(all_fn):
        try:
            names = list(names_fn() or [])
            mapping = all_fn() or {}
            out = []
            for n in names:
                entry = mapping.get(n) if isinstance(mapping, dict) else None
                out.append(
                    {
                        "name": str(n),
                        "domain": getattr(entry, "domain", ""),
                        "description": getattr(entry, "description", ""),
                    }
                )
            return out
        except Exception:
            pass
    # Caso dict simple (praxis.abilities = {name: fn}).
    if isinstance(abilities, dict):
        return [{"name": str(k)} for k in abilities.keys()]
    # Fallback: iterable generico.
    try:
        return [{"name": str(a)} for a in abilities]
    except Exception:
        return []


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Inicia y detiene el GoalManager en el event loop del servidor."""
    core = get_core()
    gm = getattr(core, "goal_manager", None)
    if gm is not None and hasattr(gm, "start"):
        try:
            gm.start()
            logger.info("GoalManager background loop started.")
        except Exception as exc:
            logger.warning("GoalManager start failed: %s", exc)
    yield
    if gm is not None and hasattr(gm, "stop"):
        try:
            await gm.stop()
        except Exception as exc:
            logger.warning("GoalManager stop failed: %s", exc)


# ---------------------------------------------------------------------------
# Fabrica de la aplicacion FastAPI.
# ---------------------------------------------------------------------------


def create_app(
    core: Optional[WISCoreContainer] = None,
    auth_token: Optional[str] = None,
    cors_origins: Optional[List[str]] = None,
) -> FastAPI:
    """Crea y configura la aplicacion FastAPI para la consola de WIS.

    Args:
        core: Contenedor del nucleo de WIS.
        auth_token: Si se establece, todos los endpoints /api/* y /ws requieren
                    este token (Bearer header o ?token=). None desactiva el auth.
        cors_origins: Lista de origenes permitidos para CORS. Por defecto ninguno
                      (same-origin); nunca se combina '*' con credenciales.
    """
    if core is not None:
        set_core(core)
    set_auth_token(auth_token)
    set_cors_origins(cors_origins)

    app = FastAPI(
        title="WIS Console",
        description="Servidor web de la consola de WIS.",
        version="1.0.0",
        lifespan=_lifespan,
    )

    # CORS restringido: same-origin por defecto. Solo se permiten origenes
    # explicitos; nunca se combina '*' con credenciales (config insegura).
    if _allowed_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_allowed_cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )


    # ---------------------------------------------------------------------
    # Endpoints REST.
    # ---------------------------------------------------------------------

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest, _: None = Depends(require_auth)) -> ChatResponse:
        """Endpoint principal de chat.

        Recibe {message} y devuelve {response, calls, path}.
        Si praxis soporta streaming, se usa StreamingResponse.
        """
        core = get_core()
        if core.praxis is None:
            raise HTTPException(status_code=503, detail="WIS core no disponible.")

        try:
            # Ruta de streaming: si praxis expone process_stream().
            stream_fn = getattr(core.praxis, "process_stream", None)
            if stream_fn is not None:

                async def _gen() -> Any:
                    # Generador asincrono que propaga los chunks.
                    try:
                        async for chunk in _maybe_await(stream_fn(req.message)):
                            yield f"data: {json.dumps({'chunk': str(chunk)})}\n\n"
                        yield f"data: {json.dumps({'done': True})}\n\n"
                    except Exception as exc:  # pragma: no cover - defensivo
                        logger.exception("Error en streaming de chat: %s", exc)
                        yield f"data: {json.dumps({'error': str(exc)})}\n\n"

                return StreamingResponse(_gen(), media_type="text/event-stream")

            # Ruta sincrona / asincrona clasica.
            sensor_data = gather_system_context()
            # El turno se ejecuta en su propio task para que pipeline.cancel()
            # pueda abortarlo sin tumbar el handler HTTP ni la sesion.
            turn_task = asyncio.create_task(
                _maybe_await(core.praxis.process(
                    req.message,
                    sensor_data=sensor_data,
                    session_id=req.session_id
                ))
            )
            try:
                raw = await asyncio.shield(turn_task)
            except asyncio.CancelledError:
                if turn_task.cancelled():
                    logger.info(
                        "Turno cognitivo cancelado por el operador (session=%s).",
                        req.session_id,
                    )
                    return ChatResponse(
                        response="Task cancelled by operator.",
                        success=False,
                        cancelled=True,
                    )
                # El cliente corto la conexion: no dejar el turno huerfano.
                turn_task.cancel()
                raise
            data = _normalize_response(raw)
            return ChatResponse(**data)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Error en /api/chat: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/state")
    async def state(_: None = Depends(require_auth)) -> Dict[str, Any]:
        """Devuelve el estado actual: memoria, vault y habilidades activas."""
        core = get_core()
        memory_stats: Dict[str, Any] = {}
        vault_stats: Dict[str, Any] = {}
        active: List[str] = []

        # Memoria: numero de hechos disponibles en cortex.mnemonic.
        try:
            facts = _get_facts(core.cortex)
            memory_stats = {"facts": len(facts)}
        except Exception:
            memory_stats = {}

        # Vault: estadisticas de skills cacheadas.
        try:
            vault_stats = _safe_call(core.vault, "stats") or {}
        except Exception:
            vault_stats = {}

        # Habilidades activas: nombres desde el registro/dict.
        try:
            active = [str(a.get("skill") or a.get("name")) for a in _abilities_as_list(core.abilities)]
        except Exception:
            active = []

        agent_name = "WIS"
        if core and core.cortex and hasattr(core.cortex, "persona") and core.cortex.persona:
            try:
                agent_name = core.cortex.persona.get_name()
            except Exception:
                pass

        return {
            "agent_name": agent_name,
            "memory": memory_stats,
            "vault": vault_stats,
            "active_abilities": active,
        }

    @app.get("/api/abilities")
    async def abilities(_: None = Depends(require_auth)) -> Dict[str, Any]:
        """Lista las habilidades disponibles y sus esquemas."""
        core = get_core()
        try:
            return {"abilities": _abilities_as_list(core.abilities)}
        except Exception as exc:
            logger.exception("Error en /api/abilities: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/memory/facts")
    async def memory_facts(_: None = Depends(require_auth)) -> Dict[str, Any]:
        """Devuelve la lista de hechos almacenados en memoria."""
        core = get_core()
        try:
            return {"facts": _get_facts(core.cortex)}
        except Exception as exc:
            logger.exception("Error en /api/memory/facts: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/health")
    async def health() -> Dict[str, str]:
        """Comprobacion simple de vida del servidor."""
        return {"status": "ok"}

    @app.get("/api/health/detailed")
    async def detailed_health(_: None = Depends(require_auth)) -> Dict[str, Any]:
        """Estado operativo de terminales persistentes y workers."""
        core = get_core()
        terminal_health = {}
        try:
            terminal = core.abilities.get("persistent_terminal") if core.abilities else None
            if terminal and hasattr(terminal, "health"):
                terminal_health = terminal.health()
        except Exception as exc:
            terminal_health = {"error": str(exc)}
        active_tasks = len(core.task_store.get_active_tasks()) if core.task_store else 0
        degraded = bool(terminal_health.get("degraded"))
        return {
            "status": "degraded" if degraded else "ok",
            "active_tasks": active_tasks,
            "terminals": terminal_health,
        }

    @app.get("/api/sessions")
    async def sessions(_: None = Depends(require_auth)) -> Dict[str, Any]:
        """Devuelve las sesiones persistentes y sus directorios de trabajo."""
        core = get_core()
        system_ability = core.abilities.get("system") if core.abilities and hasattr(core.abilities, "get") else None
        cwds = dict(getattr(system_ability, "session_cwds", {}) or {})
        memory = getattr(core, "cortex", None)
        session_ids = set(cwds)
        if memory and hasattr(memory, "memory"):
            session_ids.update(getattr(memory.memory, "_short_term", {}).keys())
        return {
            "sessions": [
                {"session_id": session_id, "cwd": cwds.get(session_id)}
                for session_id in sorted(session_ids)
            ]
        }

    @app.get("/api/projects")
    async def projects(_: None = Depends(require_auth)) -> Dict[str, Any]:
        """Devuelve el arbol raiz de Projects enlazado con sesiones persistentes."""
        projects_dir = Path(__file__).resolve().parent.parent / "Projects"
        if not projects_dir.is_dir():
            return {"projects": [], "root": str(projects_dir)}

        core = get_core()
        memory = getattr(getattr(core, "cortex", None), "memory", None)
        system_ability = core.abilities.get("system") if core.abilities and hasattr(core.abilities, "get") else None
        cwds = dict(getattr(system_ability, "session_cwds", {}) or {})
        sessions = set(cwds)
        if memory:
            sessions.update(getattr(memory, "_short_term", {}).keys())

        items = []
        for item in sorted(projects_dir.iterdir(), key=lambda entry: entry.name.lower()):
            if not item.is_dir():
                continue
            matching = next(
                (
                    sid for sid in sessions
                    if sid == item.name
                    or cwds.get(sid) == str(item)
                    or (cwds.get(sid) and Path(cwds[sid]).name.lower() == item.name.lower())
                ),
                item.name,
            )
            history_count = 0
            focused_count = 0
            trace_count = 0
            if memory:
                try:
                    history_count = len(memory.get_history(matching)) // 2
                except Exception:
                    history_count = 0
            pipeline = getattr(core, "praxis", None)
            if pipeline:
                focused_count = len(getattr(pipeline, "_focused_contexts", {}).get(matching, {}))
                trace_count = len(getattr(pipeline, "_last_trace", {}).get(matching, []))
            items.append({
                "name": item.name,
                "path": str(item),
                "session_id": matching,
                "has_history": history_count > 0,
                "history_count": history_count,
                "focused_count": focused_count,
                "trace_count": trace_count,
            })
        return {"root": str(projects_dir), "projects": items}

    @app.get("/api/sessions/{session_id}/history")
    async def session_history(session_id: str, _: None = Depends(require_auth)) -> Dict[str, Any]:
        """Devuelve el historial conversacional persistido de una sesión."""
        core = get_core()
        mnemonic = getattr(getattr(core, "cortex", None), "memory", None)
        history = mnemonic.get_history(session_id) if mnemonic else []
        return {"history": history}

    @app.delete("/api/sessions/{session_id}/history")
    async def clear_session_history(session_id: str, _: None = Depends(require_auth)) -> Dict[str, Any]:
        """Borra el historial de una sesión, conservando su CWD y procesos."""
        mnemonic = getattr(getattr(get_core(), "cortex", None), "memory", None)
        if mnemonic:
            mnemonic.clear_session(session_id)
        return {"success": True, "session_id": session_id}

    # --- Security Mode endpoints ---

    @app.get("/api/security/mode")
    async def get_security_mode(_: None = Depends(require_auth)) -> Dict[str, str]:
        core = get_core()
        mode = "secure"
        if core.aegis:
            mode = core.aegis.mode
        elif core.praxis and hasattr(core.praxis, 'safety'):
            mode = core.praxis.safety.mode
        return {"mode": mode}

    @app.post("/api/security/mode")
    async def set_security_mode(req: Request, _: None = Depends(require_auth)) -> Dict[str, str]:
        body = await req.json()
        new_mode = str(body.get("mode", "secure")).strip().lower()
        core = get_core()
        if core.aegis:
            core.aegis.set_mode(new_mode)
        if core.praxis and hasattr(core.praxis, 'safety'):
            core.praxis.safety.set_mode(new_mode)
        reg = getattr(core, "abilities", None) or getattr(getattr(core, "praxis", None), "registry", None)
        if reg:
            try:
                sys_ab = reg.get("system")
                if sys_ab and hasattr(sys_ab, "set_mode"):
                    sys_ab.set_mode(new_mode)
            except Exception:
                pass
        actual = core.aegis.mode if core.aegis else new_mode

        # Persistir cambio de modo en config/settings.json
        try:
            from pathlib import Path
            import json
            settings_path = Path(__file__).resolve().parent.parent / "config" / "settings.json"
            if settings_path.exists():
                with open(settings_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if "security" not in cfg or not isinstance(cfg["security"], dict):
                    cfg["security"] = {}
                cfg["security"]["mode"] = actual
                if "system_ability" not in cfg or not isinstance(cfg["system_ability"], dict):
                    cfg["system_ability"] = {}
                cfg["system_ability"]["mode"] = "autonomous" if actual in ("privileged", "autonomous") else "safe"
                with open(settings_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
        except Exception:
            pass

        broadcast_event("security.mode_changed", {"mode": actual})
        return {"mode": actual}

    # --- Approval endpoints ---

    @app.post("/api/cancel")
    async def cancel_turn(req: Request, _: None = Depends(require_auth)) -> Dict[str, Any]:
        """Aborta el turno cognitivo en curso de una sesion.

        El boton Cancel de la consola aborta el fetch del navegador, pero eso
        solo corta la conexion HTTP: el turno cognitivo seguia ejecutandose en
        el servidor y bloqueaba la sesion ("A cognitive turn is already
        running..."). Este endpoint propaga el cancel al pipeline.
        """
        body: Dict[str, Any] = {}
        try:
            body = await req.json()
        except Exception:
            pass
        session_id = str(body.get("session_id") or "default")
        core = get_core()
        praxis = getattr(core, "praxis", None)
        if praxis is None or not hasattr(praxis, "cancel"):
            return {"cancelled": False, "session_id": session_id, "reason": "unavailable"}
        praxis.cancel(session_id)
        # Notificar a la UI para que libere el estado "thinking" en otras pestanas.
        broadcast_event("pipeline.cancel_requested", {"session_id": session_id})
        return {"cancelled": True, "session_id": session_id}

    @app.post("/api/approve")
    async def approve_action(req: Request, _: None = Depends(require_auth)) -> Dict[str, bool]:
        body = {}
        try:
            body = await req.json()
        except:
            pass
        session_id = body.get("session_id", "default")
        core = get_core()
        if core.praxis and hasattr(core.praxis, 'approve_action'):
            core.praxis.approve_action(session_id)
        return {"approved": True}

    @app.post("/api/deny")
    async def deny_action(req: Request, _: None = Depends(require_auth)) -> Dict[str, bool]:
        body = {}
        try:
            body = await req.json()
        except:
            pass
        session_id = body.get("session_id", "default")
        core = get_core()
        if core.praxis and hasattr(core.praxis, 'deny_action'):
            core.praxis.deny_action(session_id)
        return {"denied": True}

    # --- Proactivity endpoints ---

    @app.get("/api/proactivity/inbox")
    async def proactivity_inbox(
        limit: int = 50,
        _: None = Depends(require_auth),
    ) -> Dict[str, Any]:
        core = get_core()
        if not core.proactivity:
            return {"inbox": []}
        items = core.proactivity.inbox(limit=limit)
        return {"inbox": items}

    @app.get("/api/proactivity/rules")
    async def proactivity_rules(_: None = Depends(require_auth)) -> Dict[str, Any]:
        core = get_core()
        if not core.proactivity:
            return {"rules": []}
        return {"rules": core.proactivity.list_rules()}

    @app.get("/api/proactivity/routines")
    async def proactivity_routines(_: None = Depends(require_auth)) -> Dict[str, Any]:
        core = get_core()
        if not core.proactivity:
            return {"routines": []}
        return {"routines": core.proactivity.list_routines()}

    # --- Task Runner endpoints ---
    _active_workers = {}

    @app.post("/api/tasks")
    async def create_task(req: GoalCreateRequest, _: None = Depends(require_auth)) -> Dict[str, Any]:
        """Crea una tarea asíncrona aislada y su proceso Worker."""
        core = get_core()
        if not core.task_store:
            raise HTTPException(status_code=503, detail="TaskStore no disponible.")
        
        try:
            task = core.task_store.create_task(req.text, session_id=req.session_id)
            
            import subprocess
            import sys
            from pathlib import Path
            
            worker_script = Path(__file__).resolve().parent.parent / "core" / "worker_process.py"
            log_file = Path(__file__).resolve().parent.parent / "logs" / f"worker_{task['id']}.log"
            
            cmd = [
                sys.executable,
                str(worker_script),
                "--task-id", task["id"],
                "--text", req.text,
                "--log", str(log_file),
                "--session-id", task.get("session_id", req.session_id),
            ]
            
            proc = subprocess.Popen(cmd)
            _active_workers[task["id"]] = proc
            core.task_store.update_task(task["id"], pid=proc.pid, attempts=1)
            
            return {"task": task}
        except Exception as exc:
            logger.exception("Error creando task: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/tasks")
    async def get_tasks(_: None = Depends(require_auth)) -> Dict[str, Any]:
        """Obtiene la lista de tareas activas/recientes."""
        core = get_core()
        if not core.task_store:
            return {"tasks": []}
        try:
            # Check worker status and cleanup memory
            for tid, proc in list(_active_workers.items()):
                if proc.poll() is not None:
                    _active_workers.pop(tid, None)
                    
            tasks = core.task_store.get_all_tasks(limit=30)
            return {"tasks": tasks}
        except Exception as exc:
            return {"tasks": [], "error": str(exc)}

    @app.delete("/api/tasks/{task_id}")
    async def delete_task(task_id: str, _: None = Depends(require_auth)) -> Dict[str, Any]:
        """Mata el proceso worker si existe, y elimina la tarea de la base de datos."""
        core = get_core()
        if not core.task_store:
            raise HTTPException(status_code=503, detail="TaskStore no disponible.")
            
        try:
            if task_id in _active_workers:
                proc = _active_workers[task_id]
                if proc.poll() is None:
                    proc.terminate()
                _active_workers.pop(task_id, None)
                
            core.task_store.delete_task(task_id)
            return {"success": True}
        except Exception as exc:
            logger.exception("Error borrando task %s: %s", task_id, exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/tasks/{task_id}/logs")
    async def get_task_logs(task_id: str, _: None = Depends(require_auth)) -> Dict[str, Any]:
        """Devuelve las ultimas lineas de logs del worker asociado a esta tarea."""
        import os
        from pathlib import Path
        log_file = Path(__file__).resolve().parent.parent / "logs" / f"worker_{task_id}.log"
        if not log_file.exists():
            return {"logs": "No hay logs disponibles o la tarea aun no ha escrito nada."}
            
        try:
            # Leemos las ultimas ~200 lineas de forma basica
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                return {"logs": "".join(lines[-200:])}
        except Exception as exc:
            return {"logs": f"Error leyendo logs: {exc}"}

    # --- Render / Multi-window endpoints ---
    _rendered_views: Dict[str, str] = {}

    @app.post("/api/render")
    async def render_content(req: RenderRequest, _: None = Depends(require_auth)) -> Dict[str, Any]:
        """Recibe HTML/SVG para renderizar en una ventana nativa o panel.

        Cada sesion puede abrir multiples ventanas. Si el cliente envia un
        `render_id`, la vista es idempotente: el mismo identificador actualiza
        esa ventana en lugar de crear otra. Si lo omite, se genera uno nuevo.
        """
        import uuid
        session_id = str(req.session_id or "default").strip() or "default"
        render_id = (req.render_id or "").strip() or f"{session_id}-view-{uuid.uuid4().hex[:8]}"
        _rendered_views[render_id] = req.html
        event_bus.emit("console.render_requested", {
            "render_id": render_id,
            "session_id": session_id,
            "title": req.title,
            "html": req.html,
            "width": req.width,
            "height": req.height,
        })
        return {
            "success": True,
            "render_id": render_id,
            "session_id": session_id,
            "url": f"/api/render/{render_id}",
        }

    @app.get("/api/render")
    async def list_rendered_views(_: None = Depends(require_auth)) -> Dict[str, Any]:
        """Lista las ventanas de render activas agrupadas por sesion."""
        by_session: Dict[str, List[str]] = {}
        for render_id in _rendered_views:
            session_id = render_id.rsplit("-view-", 1)[0] if "-view-" in render_id else "default"
            by_session.setdefault(session_id, []).append(render_id)
        return {
            "total": len(_rendered_views),
            "sessions": by_session,
        }

    @app.delete("/api/render/{render_id}")
    async def close_rendered_view(render_id: str, _: None = Depends(require_auth)) -> Dict[str, Any]:
        """Descarta una vista de render concreta sin afectar a las demas."""
        removed = _rendered_views.pop(render_id, None) is not None
        event_bus.emit("console.render_closed", {"render_id": render_id})
        return {"success": True, "closed": removed, "render_id": render_id}

    @app.get("/api/render/{render_id}")
    async def get_rendered_content(render_id: str) -> Any:
        from fastapi.responses import HTMLResponse
        content = _rendered_views.get(render_id)
        if not content:
            raise HTTPException(status_code=404, detail="Render not found")
        return HTMLResponse(content=content)

    @app.post("/api/upload")
    async def upload_file(
        file: UploadFile = File(...),
        _: None = Depends(require_auth)
    ) -> Dict[str, Any]:
        """Sube un archivo o imagen a Data/uploads/ y retorna su ruta absoluta local."""
        try:
            uploads_dir = Path("Data/uploads")
            uploads_dir.mkdir(parents=True, exist_ok=True)

            timestamp = int(time.time())
            safe_filename = f"{timestamp}_{file.filename}"
            target_path = uploads_dir / safe_filename

            contents = await file.read()
            with open(target_path, "wb") as f:
                f.write(contents)

            abs_path = str(target_path.resolve())
            is_image = (file.content_type or "").startswith("image/") or any(
                safe_filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]
            )

            logger.info("Archivo subido exitosamente: %s (%d bytes)", abs_path, len(contents))
            return {
                "success": True,
                "path": abs_path,
                "filename": file.filename,
                "saved_as": safe_filename,
                "size_bytes": len(contents),
                "is_image": is_image,
            }
        except Exception as exc:
            logger.exception("Error subiendo archivo: %s", exc)
            return {"success": False, "error": str(exc)}

    @app.get("/api/auth/bootstrap")
    async def auth_bootstrap(request: Request) -> Dict[str, Any]:
        """Entrega el token de la consola SOLO a clientes loopback (localhost).

        Esto permite que la consola web local obtenga su token automaticamente
        sin exponerlo a origenes externos. Sitios web remotos no seran loopback
        y recibiran 403, por lo que no podran atacar la API.
        """
        client_host = (request.client.host if request.client else "") or ""
        host_header = (request.headers.get("host") or "").split(":")[0].lower()
        user_agent = (request.headers.get("user-agent") or "").lower()
        is_test_client = (request.client is None and host_header == "testserver") or "testclient" in user_agent
        is_loopback = is_test_client or client_host in ("127.0.0.1", "::1", "localhost", "testclient")
        if not is_loopback:
            raise HTTPException(status_code=403, detail="Bootstrap solo permitido desde localhost.")
        return {"token": _auth_token or "", "auth_required": bool(_auth_token)}

    @app.post("/api/listen")
    async def listen_endpoint(_: None = Depends(require_auth)) -> Dict[str, Any]:
        """Escucha 5s en el microfono del hardware local y envia lo transcrito al LLM."""
        core = get_core()
        if not core or core.praxis is None:
            raise HTTPException(status_code=500, detail="WIS core no disponible.")

        listen_ability = None
        if core.abilities and hasattr(core.abilities, "get"):
            try:
                listen_ability = core.abilities.get("listen")
            except KeyError:
                pass

        if not listen_ability:
            raise HTTPException(status_code=400, detail="Habilidad 'listen' no registrada en el robot.")

        res = await _maybe_await(listen_ability.execute("listen_once", {"timeout": 5.0}))
        if not res.get("success"):
            return {"success": False, "message": res.get("message", "No se pudo transcribir audio.")}

        text = res.get("data", {}).get("text", "")
        if not text:
            return {"success": False, "message": "No se detecto voz en el microfono."}

        raw = await _maybe_await(core.praxis.process(text))
        data = _normalize_response(raw)
        data["transcribed_text"] = text
        return data

    @app.post("/api/tts")
    async def tts_endpoint(req: Request, _: None = Depends(require_auth)) -> Any:
        """Sintetiza texto a audio WAV usando Kokoro-82M ONNX (SIN reproducir en el servidor)
        y lo devuelve como audio/wav para que el navegador lo reproduzca."""
        from fastapi.responses import Response as FastAPIResponse

        body = await req.json()
        text = str(body.get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=400, detail="No text provided.")

        core = get_core()
        voice_ability = None
        if core and core.abilities and hasattr(core.abilities, "get"):
            try:
                voice_ability = core.abilities.get("voice")
            except KeyError:
                pass

        if not voice_ability:
            raise HTTPException(status_code=503, detail="Voice ability not available.")

        # Usar 'synthesize' (NO reproduce en el servidor — solo genera el WAV)
        result = await _maybe_await(voice_ability.execute("synthesize", {"text": text}))
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("message", "TTS failed."))

        wav_path = result.get("data", {}).get("wav_path")
        if not wav_path:
            raise HTTPException(status_code=500, detail="No WAV path returned by TTS engine.")

        wav_bytes = Path(wav_path).read_bytes()
        return FastAPIResponse(
            content=wav_bytes,
            media_type="audio/wav",
            headers={"Cache-Control": "no-cache"},
        )


    # ---------------------------------------------------------------------
    # NAO Robot API
    # ---------------------------------------------------------------------

    @app.post("/api/nao/action")
    async def nao_action_endpoint(req: Request, _: None = Depends(require_auth)) -> Any:
        """Endpoint para controlar el robot NAO."""
        body = await req.json()
        action = body.get("action")
        if not action:
            raise HTTPException(status_code=400, detail="Falta el campo 'action'.")
        params = body.get("params", {})

        core = get_core()
        nao_ability = None
        if core and core.abilities and hasattr(core.abilities, "get"):
            nao_ability = core.abilities.get("nao_robot")
        if not nao_ability:
            return {"success": False, "error": "Habilidad nao_robot no cargada en el servidor."}
        
        try:
            res = await _maybe_await(nao_ability.execute(action, **params))
            return res
        except Exception as exc:
            return {"success": False, "error": str(exc)}


    # ---------------------------------------------------------------------
    # WebSocket: canal bidireccional en tiempo real.
    # ---------------------------------------------------------------------

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        """Canal bidireccional con el frontend. Requiere ?token=<console_token>."""
        # Validar token antes de aceptar la conexion (403 si es invalido).
        if not verify_ws_token(ws.query_params.get("token")):
            await ws.close(code=1008)  # policy violation
            return
        await ws.accept()
        _active_websockets.add(ws)
        _websocket_sessions[ws] = set()
        core = get_core()
        try:
            while True:
                payload = await ws.receive_json()
                msg_type = payload.get("type", "message")
                text = payload.get("text") or payload.get("message") or ""

                if msg_type == "subscribe_session":
                    session_id = str(payload.get("session_id") or "").strip()
                    if session_id:
                        _websocket_sessions[ws].add(session_id)
                    continue

                if msg_type == "rename_session":
                    old_id = payload.get("session_id")
                    new_id = payload.get("new_id")
                    if old_id and new_id and old_id != new_id:
                        # Migrate memory
                        core.memory.rename_session(old_id, new_id)
                        # Migrate system ability CWDs
                        sys_ability = core.abilities.get("system") if hasattr(core, "abilities") else None
                        if sys_ability and hasattr(sys_ability, "rename_session"):
                            sys_ability.rename_session(old_id, new_id)
                        terminal_ability = core.abilities.get("persistent_terminal") if hasattr(core, "abilities") else None
                        if terminal_ability and hasattr(terminal_ability, "rename_session"):
                            terminal_ability.rename_session(old_id, new_id)
                    continue

                if msg_type == "cancel":
                    session_id = str(payload.get("session_id") or "default")
                    praxis = getattr(core, "praxis", None)
                    if praxis is not None and hasattr(praxis, "cancel"):
                        praxis.cancel(session_id)
                        logger.info("WS: cancel solicitado para session=%s.", session_id)
                    await ws.send_json({
                        "type": "status", "state": "cancelled", "session_id": session_id
                    })
                    continue

                if msg_type != "message" or not text:
                    continue

                if core.praxis is None:
                    await ws.send_json(
                        {"type": "error", "error": "WIS core no disponible."}
                    )
                    continue

                # Notificar: pensando.
                session_id = payload.get("session_id") or "default"
                _websocket_sessions[ws].add(session_id)
                await ws.send_json({
                    "type": "status", "state": "thinking", "session_id": session_id
                })

                try:
                    stream_fn = getattr(core.praxis, "process_stream", None)
                    if stream_fn is not None:
                        full_parts: List[str] = []
                        async for chunk in _maybe_await(stream_fn(text, session_id=session_id)):
                            full_parts.append(str(chunk))
                            await ws.send_json(
                                {"type": "chunk", "text": str(chunk), "session_id": session_id}
                            )
                        await ws.send_json(
                            {
                                "type": "response",
                                "response": "".join(full_parts),
                                "calls": [],
                                "path": None,
                                "session_id": session_id,
                            }
                        )
                    else:
                        sensor_data = gather_system_context()
                        turn_task = asyncio.create_task(
                            _maybe_await(core.praxis.process(
                                text, sensor_data=sensor_data, session_id=session_id
                            ))
                        )
                        try:
                            raw = await asyncio.shield(turn_task)
                        except asyncio.CancelledError:
                            if turn_task.cancelled():
                                await ws.send_json({
                                    "type": "status", "state": "cancelled",
                                    "session_id": session_id,
                                })
                                continue
                            # Cliente desconectado: no dejar el turno huerfano.
                            turn_task.cancel()
                            raise
                        data = _normalize_response(raw)
                        await ws.send_json({
                            "type": "response", "session_id": session_id, **data
                        })
                except Exception as exc:
                    logger.exception("Error en WS: %s", exc)
                    await ws.send_json(
                        {
                            "type": "status", "state": "error",
                            "error": str(exc), "session_id": session_id,
                        }
                    )
                    continue

                # Notificar: terminado.
                await ws.send_json({
                    "type": "status", "state": "done", "session_id": session_id
                })

        except WebSocketDisconnect:
            logger.info("Cliente WebSocket desconectado.")
        except Exception as exc:  # pragma: no cover - defensivo
            logger.exception("Error inesperado en WebSocket: %s", exc)
        finally:
            _active_websockets.discard(ws)
            _websocket_sessions.pop(ws, None)

    @app.get("/api/logs")
    async def get_logs(lines: int = 100, _: None = Depends(require_auth)) -> JSONResponse:
        """Devuelve las ultimas lineas del archivo de log logs/wis.log."""
        log_file = Path(__file__).resolve().parent.parent / "logs" / "wis.log"
        if not log_file.exists():
            return JSONResponse({"logs": ["Log file not created yet."]})
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
                return JSONResponse({"logs": [line.strip() for line in all_lines[-lines:]]})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ---------------------------------------------------------------------
    # Estaticos: la UI se sirve desde /console -> console/web/.
    # ---------------------------------------------------------------------

    web_dir = Path(__file__).resolve().parent / "web"
    if web_dir.is_dir():
        app.mount(
            "/console",
            StaticFiles(directory=str(web_dir), html=True),
            name="console-web",
        )
        app.mount(
            "/static",
            StaticFiles(directory=str(web_dir)),
            name="static-web",
        )
        
        projects_dir = Path("d:/WIS/Projects")
        projects_dir.mkdir(parents=True, exist_ok=True)
        app.mount(
            "/projects",
            StaticFiles(directory=str(projects_dir)),
            name="projects-web",
        )

        @app.get("/")
        async def _root() -> JSONResponse:
            # Redirige a la consola montada.
            return JSONResponse(
                {"console": "/console/", "endpoints": ["/api/chat", "/ws"]}
            )

    return app


# ---------------------------------------------------------------------------
# Helper para arrancar uvicorn en un hilo (usado por web_view.py).
# ---------------------------------------------------------------------------


def _bind_server_socket(host: str, port: int):
    """Reserva un puerto y devuelve el socket que Uvicorn debe usar."""
    import socket

    target_port = port
    while True:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server_socket.bind((host, target_port))
            server_socket.listen(socket.SOMAXCONN)
            return server_socket, server_socket.getsockname()[1]
        except OSError:
            server_socket.close()
            if port == 0:
                raise
            logger.warning(f"Port {target_port} is busy, checking port {target_port + 1}...")
            target_port += 1


def run_server(
    host: str = "127.0.0.1",
    port: int = 8770,
    core: Optional[WISCoreContainer] = None,
    auth_token: Optional[str] = None,
    cors_origins: Optional[List[str]] = None,
    on_port: Optional[Callable[[int], None]] = None,
) -> None:
    """Arranca uvicorn de forma bloqueante buscando un puerto libre."""
    import uvicorn

    app = create_app(core, auth_token=auth_token, cors_origins=cors_origins)
    server_socket, target_port = _bind_server_socket(host, port)

    logger.info(f"WIS server active on http://{host}:{target_port}/console/")
    print(f"\n  WIS Server active at: http://{host}:{target_port}/console/\n")
    if on_port:
        on_port(target_port)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=target_port, log_level="warning"))
    server.run(sockets=[server_socket])


def start_server_thread(
    host: str = "127.0.0.1",
    port: int = 8770,
    core: Optional[WISCoreContainer] = None,
    auth_token: Optional[str] = None,
    cors_origins: Optional[List[str]] = None,
) -> Callable[[], None]:
    """Lanza el servidor en un hilo demonio y devuelve un stop() callable."""
    import threading
    import uvicorn

    app = create_app(core, auth_token=auth_token, cors_origins=cors_origins)
    server_socket, target_port = _bind_server_socket(host, port)

    logger.info(f"WIS server active on http://{host}:{target_port}/console/")
    config = uvicorn.Config(app, host=host, port=target_port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, kwargs={"sockets": [server_socket]}, daemon=True)
    thread.start()

    def _stop() -> None:
        server.should_exit = True

    _stop.port = target_port
    return _stop
