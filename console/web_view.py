"""
WIS Console - pywebview window launcher & AGI Multi-Window Render Engine.
Lanzador de ventana pywebview para la consola con soporte multi-ventana.

Arranca el servidor FastAPI en un hilo en segundo plano y abre una
ventana nativa con pywebview apuntando a la UI servida por /console/.
Permite a WIS renderizar sus propias ventanas emergentes (HTML/SVG/capturas SOM).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .server import WISCoreContainer, start_server_thread

logger = logging.getLogger("wis.console.web_view")


class WISJsApi:
    """Python API bridge expuesta al frontend via window.pywebview.api."""

    def __init__(self) -> None:
        self._window: Any = None
        self._render_windows: list[Any] = []

    def set_window(self, win: Any) -> None:
        self._window = win

    def minimize(self) -> None:
        if self._window:
            try:
                self._window.minimize()
            except Exception as e:
                logger.warning("Minimize failed: %s", e)

    def close_window(self) -> None:
        if self._window:
            try:
                self._window.destroy()
            except Exception as e:
                logger.warning("Close failed: %s", e)

    def maximize(self) -> None:
        if self._window:
            try:
                self._window.toggle_fullscreen()
            except Exception as e:
                logger.warning("Maximize failed: %s", e)

    def open_render_window(
        self,
        html: str,
        title: str = "WIS Render Engine",
        width: int = 800,
        height: int = 600,
    ) -> None:
        """Abre una nueva ventana nativa pywebview renderizando HTML arbitrario."""
        try:
            import webview
            win = webview.create_window(
                title=title,
                html=html,
                width=width,
                height=height,
                frameless=False,
                easy_drag=True,
                background_color="#050508",
            )
            self._render_windows.append(win)
        except Exception as e:
            logger.warning("open_render_window failed: %s", e)

    def get_window_rect(self) -> dict:
        """Devuelve la posicion y dimensiones actuales de la ventana nativa."""
        if self._window:
            try:
                return {
                    "x": int(self._window.x),
                    "y": int(self._window.y),
                    "width": int(self._window.width),
                    "height": int(self._window.height),
                }
            except Exception as e:
                logger.debug("get_window_rect error: %s", e)
        return {"x": 100, "y": 100, "width": 1200, "height": 820}

    def move_window(self, x: int, y: int) -> None:
        """Mueve la ventana nativa a las coordenadas especificadas."""
        if self._window:
            try:
                self._window.move(int(x), int(y))
            except Exception as e:
                logger.debug("move_window failed: %s", e)

    def resize_window(self, width: int, height: int) -> None:
        """Redimensiona la ventana nativa al ancho y alto especificados."""
        if self._window:
            try:
                self._window.resize(int(width), int(height))
            except Exception as e:
                logger.debug("resize_window failed: %s", e)

    def set_window_rect(self, x: int, y: int, width: int, height: int) -> None:
        """Mueve y redimensiona la ventana nativa de forma atomica."""
        if self._window:
            try:
                self._window.move(int(x), int(y))
                self._window.resize(int(width), int(height))
            except Exception as e:
                logger.debug("set_window_rect failed: %s", e)

    def get_platform_info(self) -> dict:
        import platform
        return {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
        }


def _wait_for_server(url: str, timeout: float = 10.0) -> bool:
    """Espera a que el servidor responda antes de abrir la ventana."""
    import urllib.request
    import urllib.error

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status < 500:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.25)
    return False


def launch_console(
    url: str = "http://127.0.0.1:8770/console/",
    title: str = "WIS — Cognitive OS",
    width: int = 1200,
    height: int = 820,
    core: Optional[WISCoreContainer] = None,
    auth_token: Optional[str] = None,
    cors_origins: Optional[list] = None,
    frameless: bool = True,
    **_webview_kwargs: Any,
) -> None:
    """Abre la consola de WIS en una ventana nativa de pywebview.

    Args:
        url:    URL de la UI servida por el backend.
        title:  Titulo de la ventana.
        width:  Ancho inicial en pixeles.
        height: Alto inicial en pixeles.
        core:   Contenedor con el nucleo de WIS (cortex/praxis/...).
        auth_token:  Token requerido por la API (Bearer / ?token=).
        cors_origins: Origenes permitidos por CORS.
        frameless: Si la ventana es frameless (chrome personalizado via CSS).
    """
    # Arranca el servidor en segundo plano (hilo demonio).
    host = "127.0.0.1"
    port = 8770
    if url:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            if parsed.hostname:
                host = parsed.hostname
            if parsed.port:
                port = parsed.port
        except Exception:
            pass

    start_server_thread(
        host=host, port=port, core=core,
        auth_token=auth_token, cors_origins=cors_origins,
    )

    # Espera a que el servidor este listo antes de abrir la ventana.
    base = f"http://{host}:{port}/"
    if not _wait_for_server(base):
        logger.warning("El servidor no respondio a tiempo; abriendo de todos modos.")

    # Import diferido: pywebview puede no estar instalado en algunos entornos.
    try:
        import webview
    except ImportError as exc:  # pragma: no cover - dependencia opcional
        raise RuntimeError(
            "pywebview no esta instalado. Instala con: pip install pywebview"
        ) from exc

    # Instanciar JS API bridge
    api = WISJsApi()

    # Escuchar solicitudes de render desde el backend (event_bus)
    try:
        from core.event_bus import event_bus

        def _on_render_event(evt: dict) -> None:
            html = evt.get("html", "")
            title_ = evt.get("title", "WIS Render Engine")
            w = evt.get("width", 800)
            h = evt.get("height", 600)
            if html:
                api.open_render_window(html=html, title=title_, width=w, height=h)

        event_bus.subscribe("console.render_requested", _on_render_event)
    except Exception as e:
        logger.warning("Could not subscribe to console.render_requested: %s", e)

    # Crea la ventana principal y arranca el loop de pywebview
    main_window = webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        min_size=(640, 420),
        frameless=frameless,
        easy_drag=False,
        resizable=True,
        text_select=True,
        background_color="#050508",
        js_api=api,
    )
    api.set_window(main_window)

    webview.start(debug=False)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    launch_console()
