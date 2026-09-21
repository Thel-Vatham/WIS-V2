"""Regresiones del incidente 2026-09-15 20:57-21:05.

Dos fallos reales observados en el log de WIS:

D4 - El filtro anti-duplicados descartaba llamadas de SOLO LECTURA y cortaba
     el turno. Evidencia: `Run the main program` emitio
     `calls=1 ["code_tools_code_list_dir"]`, no hubo TOOL_CALL/TOOL_RESULT
     (la llamada se salto como duplicada), y el turno cerro en paso 4 sin
     lanzar el programa -> [AVISO]. Las lecturas deben poder repetirse.

D5 - `vision.detect_objects` decia "faltan models/detection/yolov4-tiny.cfg,
     .weights o coco.names" cuando los tres archivos EXISTEN: el fallo real es
     que OpenCV 5.0 elimino el importador Darknet. El mensaje enganoso mandaba
     al agente a buscar archivos inexistentes en bucle (AUTO_REPAIR).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pipeline import ActionPipeline, _is_repeatable_call  # noqa: E402


class _StubReasoning:
    def __init__(self) -> None:
        class _M:
            def remember(self, *a, **k):
                return None

            def clear_session(self, *a, **k):
                return None

        self.memory = _M()


class _StubSkills:
    def lookup(self, text):
        return None

    def record_success(self, *a, **k):
        return None

    def record_failure(self, *a, **k):
        return None


def _pipeline() -> ActionPipeline:
    return ActionPipeline(
        reasoning=_StubReasoning(),  # type: ignore[arg-type]
        skill_memory=_StubSkills(),  # type: ignore[arg-type]
        abilities={},
    )


# ── D4: clasificación de solo lectura ─────────────────────────────────────
@pytest.mark.parametrize(
    "call",
    [
        {"skill": "code_tools", "action": "code_list_dir", "params": {"path": "X"}},
        {"skill": "code_tools", "action": "code_view_file", "params": {"path": "X"}},
        {"skill": "code_tools", "action": "code_grep", "params": {"pattern": "x"}},
        {"skill": "system", "action": "get_process_list", "params": {}},
        {"skill": "system", "action": "check_application_running", "params": {}},
        {"skill": "vision", "action": "capture", "params": {}},
        {"skill": "vision", "action": "describe", "params": {}},
        {"skill": "vision", "action": "detect_objects", "params": {}},
        {"skill": "file_manager", "action": "list_directory", "params": {}},
        {"skill": "file_manager", "action": "read_file", "params": {}},
    ],
)
def test_read_only_calls_are_repeatable(call: Dict[str, Any]):
    assert _is_repeatable_call(call) is True, call


@pytest.mark.parametrize(
    "call",
    [
        {"skill": "system", "action": "execute_shell", "params": {"command": "x"}},
        {"skill": "system", "action": "close_application", "params": {"app_name": "x"}},
        {"skill": "system", "action": "open_application", "params": {"app_name": "x"}},
        {"skill": "desktop", "action": "kill_process", "params": {"pid": 1}},
        {"skill": "code_tools", "action": "code_replace_content", "params": {}},
        {"skill": "file_manager", "action": "write_file", "params": {}},
    ],
)
def test_side_effecting_calls_are_not_repeatable(call: Dict[str, Any]):
    assert _is_repeatable_call(call) is False, call


def _run_twice(call: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
    """Ejecuta la misma llamada dos veces en el mismo turno (mismo `seen`)."""
    pipeline = _pipeline()
    counter = {"n": 0}

    async def _single(c, require_approval=False, session_id="default"):
        counter["n"] += 1
        return {
            "ok": True,
            "name": c.get("action") or "",
            "action": c.get("action") or "",
            "output": {"data": {"ok": True}},
        }

    pipeline._execute_single_call = _single  # type: ignore[assignment]
    seen: set[str] = set()
    asyncio.run(pipeline._execute_calls([call], executed_calls=seen))
    results, _ = asyncio.run(pipeline._execute_calls([call], executed_calls=seen))
    return counter["n"], results[0]


def test_repeated_read_only_call_is_actually_executed():
    """El caso del log: un `code_list_dir` repetido debe ejecutarse, no saltarse."""
    runs, result = _run_twice(
        {"skill": "code_tools", "action": "code_list_dir", "params": {"path": "D:\\X"}}
    )
    assert runs == 2, "una lectura repetida no debe descartarse"
    assert result["output"].get("reason") != "duplicate_call_in_request"
    assert result["ok"] is True


def test_repeated_side_effecting_call_is_still_skipped():
    """No se repiten efectos secundarios: contrato original intacto."""
    runs, result = _run_twice(
        {"skill": "system", "action": "execute_shell", "params": {"command": "start x"}}
    )
    assert runs == 1, "no debe re-ejecutarse un efecto secundario"
    assert result["output"]["reason"] == "duplicate_call_in_request"


# ── D5: el error de visión no debe culpar a archivos que existen ──────────
class _FakeDnn:
    """Simula OpenCV 5: sin importador Darknet."""

    DNN_BACKEND_OPENCV = 0
    DNN_TARGET_CPU = 0


class _FakeCv2NoDarknet:
    __version__ = "5.0.0"
    dnn = _FakeDnn()


def _vision_ability():
    from abilities.vision import VisionAbility

    return VisionAbility()


def test_yolo_error_names_the_real_cause_not_missing_files():
    ability = _vision_ability()
    base = ability._yolo_asset_dir()
    required = ("yolov4-tiny.cfg", "yolov4-tiny.weights", "coco.names")
    if not all((Path(base) / n).is_file() for n in required):
        pytest.skip("assets YOLO no presentes en este entorno")

    net, names = ability._load_yolo_sync(_FakeCv2NoDarknet())

    assert net is None and names == []
    assert ability._yolo_error, "debe registrar el motivo real"
    assert "OpenCV" in ability._yolo_error
    assert "readNetFromDarknet" in ability._yolo_error
    # El mensaje enganoso original culpaba a archivos ausentes.
    assert "faltan" not in ability._yolo_error.lower()


def test_yolo_error_reports_missing_files_when_they_really_are_missing(monkeypatch):
    ability = _vision_ability()
    monkeypatch.setattr(
        type(ability), "_yolo_asset_dir", staticmethod(lambda: str(ROOT / "no_such_dir"))
    )

    net, names = ability._load_yolo_sync(_FakeCv2NoDarknet())

    assert net is None and names == []
    assert "faltan" in ability._yolo_error.lower()
