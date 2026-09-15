"""Anti-estancamiento del ciclo ReAct (validacion 2026-09-15).

Sintoma reportado: WIS dice "I'll verify…" / "voy a revisar…" y se queda
parado hasta que el usuario escribe otro mensaje.

Causa raiz en `ActionPipeline._try_new`: `if not calls: final_ok = True; break`
trataba una NARRACION como tarea terminada. Estas pruebas fijan el contrato:
una promesa sin tool calls NO cierra el turno; se exige ejecucion real.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.event_bus import event_bus  # noqa: E402
from core.pipeline import ActionPipeline  # noqa: E402

PROMISE = "I'll examine the render engine implementation to understand what needs improvement."
FINAL = "Hecho: el directorio contiene 3 archivos .py, verificado con list_directory."


class _StubMemory:
    def __init__(self) -> None:
        self.remembered: list[tuple[str, str]] = []

    def remember(self, text: str, response: str, session_id: str = "default") -> None:
        self.remembered.append((text, response))

    def clear_session(self, session_id: str) -> None:  # pragma: no cover - no usado
        pass


class _StubReasoning:
    """Devuelve respuestas guionizadas: promete, luego ejecuta, luego concluye."""

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.calls_made = 0
        self.prompts: list[str] = []
        self.memory = _StubMemory()

    async def think(self, prompt, sensor_data=None, tools=None, session_id="default"):
        self.calls_made += 1
        self.prompts.append(prompt)
        if self.script:
            return self.script.pop(0)
        return {"calls": [], "text": FINAL}


class _StubSkills:
    def __init__(self) -> None:
        self.successes: list[str] = []
        self.failures: list[str] = []

    def lookup(self, text: str):
        return None

    def record_success(self, text, calls, response) -> None:
        self.successes.append(text)

    def record_failure(self, text, calls) -> None:
        self.failures.append(text)


def _make_pipeline(script: list[dict], max_steps: int = 6) -> tuple[ActionPipeline, _StubReasoning]:
    reasoning = _StubReasoning(script)
    pipeline = ActionPipeline(
        reasoning=reasoning,  # type: ignore[arg-type]
        skill_memory=_StubSkills(),  # type: ignore[arg-type]
        abilities={},
        max_steps=max_steps,
    )

    async def _fake_execute(calls, session_id="default", executed_calls=None):
        results = [
            {"ok": True, "call": c, "output": {"data": {"items": ["a", "b", "c"]}}}
            for c in calls
        ]
        return results, True

    pipeline._execute_calls = _fake_execute  # type: ignore[assignment]

    async def _noop(text, calls, response):  # evita red en la destilacion
        return None

    pipeline._distill_and_cache = _noop  # type: ignore[assignment]
    return pipeline, reasoning


def _run(script: list[dict], max_steps: int = 6, session: str = "stall_test"):
    pipeline, reasoning = _make_pipeline(script, max_steps=max_steps)

    nudges: list[dict] = []
    promises: list[dict] = []
    event_bus.subscribe("pipeline.loop_nudged", lambda d: nudges.append(d or {}))
    event_bus.subscribe("pipeline.promise_instead_of_result", lambda d: promises.append(d or {}))

    result = asyncio.run(
        pipeline._try_new("arregla el render engine", None, None, session_id=session)
    )
    return result, reasoning, nudges, promises


# ── Contrato principal ────────────────────────────────────────────────────
def test_promise_without_tool_calls_does_not_end_turn():
    """La promesa se rechaza; WIS debe continuar y ejecutar."""
    script = [
        {"calls": [], "text": PROMISE},
        {"calls": [{"skill": "system", "action": "list_directory", "params": {}}], "text": ""},
        {"calls": [], "text": FINAL},
    ]
    result, reasoning, nudges, _ = _run(script)

    assert reasoning.calls_made == 3, "debe re-preguntar tras la promesa, no cerrar el turno"
    assert len(nudges) == 1
    assert nudges[0]["announced"].startswith("I'll examine")
    assert result["response"].strip() == FINAL
    assert result["success"] is True


def test_nudge_prompt_tells_llm_to_act_not_announce():
    script = [
        {"calls": [], "text": PROMISE},
        {"calls": [{"skill": "system", "action": "list_directory", "params": {}}], "text": ""},
        {"calls": [], "text": FINAL},
    ]
    _, reasoning, _, _ = _run(script)
    second_prompt = reasoning.prompts[1]
    assert "[NUDGE" in second_prompt
    assert "Anunciar no es hacer" in second_prompt


def test_persistent_promise_ends_with_honest_report_not_the_promise():
    """Si insiste en prometer, nunca se devuelve la promesa como resultado."""
    script = [{"calls": [], "text": PROMISE} for _ in range(5)]
    result, _, nudges, promises = _run(script)

    assert len(nudges) == 2, "reintenta como maximo max_nudges veces"
    assert promises, "debe emitir el evento de promesa-sin-resultado"
    assert "[AVISO]" in result["response"]
    assert "PENDIENTE" in result["response"]
    assert PROMISE in result["response"], "la promesa original se conserva como contexto"
    assert result["success"] is False, "sin acciones verificadas no puede declararse exito"


def test_final_answer_is_never_flagged_as_promise():
    """Una respuesta final real no debe disparar nudges ni avisos."""
    result, reasoning, nudges, promises = _run([{"calls": [], "text": FINAL}])

    assert reasoning.calls_made == 1
    assert nudges == [] and promises == []
    assert result["response"].strip() == FINAL
    assert result["success"] is True


CALL = {"skill": "system", "action": "execute_shell", "params": {"command": "taskkill /F /PID 1"}}
PROMISE_ON_DUPLICATE = "I can see two processes. Let me kill them directly by PID using taskkill."


def test_duplicate_call_ending_in_promise_is_reported_honestly():
    """Caso real del log (Calculadora, 15:46): el turno se corto por una accion
    duplicada y devolvio la PROMESA como resultado final con success=True."""
    pipeline, reasoning = _make_pipeline(
        [
            {"calls": [CALL], "text": ""},
            {"calls": [CALL], "text": PROMISE_ON_DUPLICATE},
        ]
    )

    calls_seen = {"n": 0}

    async def _execute(calls, session_id="default", executed_calls=None):
        calls_seen["n"] += 1
        if calls_seen["n"] == 1:
            return [{"ok": True, "call": CALL, "output": {"data": {"opened": True}}}], True
        return [{"ok": False, "call": CALL, "output": {"reason": "duplicate_call_in_request"}}], False

    pipeline._execute_calls = _execute  # type: ignore[assignment]

    promises: list[dict] = []
    event_bus.subscribe("pipeline.promise_instead_of_result", lambda d: promises.append(d or {}))

    result = asyncio.run(pipeline._try_new("cierra la calculadora", None, None, session_id="dup_test"))

    # Sigue parando el bucle en el duplicado (no repite efectos ni gasta pasos).
    # El auto-repair puede pedir una llamada extra al LLM, por eso se mide el
    # paso real del turno, no el numero de invocaciones al razonador.
    assert result["steps_used"] == 2
    # ...pero la promesa NUNCA se entrega como resultado final.
    assert promises, "el evento de promesa debe emitirse"
    assert "[AVISO]" in result["response"]
    assert "PENDIENTE" in result["response"]
    assert PROMISE_ON_DUPLICATE in result["response"]
    assert not result["response"].strip().startswith("I can see two processes")

