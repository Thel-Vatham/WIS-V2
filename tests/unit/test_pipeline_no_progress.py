# -*- coding: utf-8 -*-
"""Regresion del bucle de re-verificacion (D7).

Evidencia del log real (`logs/wis.log`, 2026-09-15 .. 2026-09-22):

    llamadas totales ................... 921
    repeticiones EXACTAS ............... 354  (38%)
    nao_robot.status identico .......... x28
    code_list_dir D:\\WIS\\paper_wis ..... x26
    racha de code_view_file ............ x39 consecutivos
    ratio lectura : escritura .......... 61 : 1
    turnos que agotaron 21+ pasos ...... 125
    turnos cerrados en promesa ......... 9

Causa: `_is_repeatable_call` exime las LECTURAS de la deduplicacion (correcto,
repetir una lectura es inocuo) pero NADA detectaba que el turno no estaba
avanzando. El agente releia lo mismo hasta agotar `max_steps` y cerraba con una
promesa en vez de un resultado.

Contrato que se fija aqui:
  * repetir una lectura identica NO puede consumir el presupuesto de pasos;
  * debe emitirse `pipeline.loop_no_progress` y cortar el turno pronto;
  * volver a leer despues de ESCRIBIR no es redundante (el contenido cambio);
  * un paso productivo reinicia la racha;
  * un turno cerrado en promesa no se cachea como skill exitosa.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from core.event_bus import event_bus
from core.pipeline import ActionPipeline, _MAX_REDUNDANT_STEPS


# ── Stubs ──────────────────────────────────────────────────────────────────
class _StubMemory:
    def remember(self, text: str, response: str, session_id: str = "default") -> None:
        pass

    def clear_session(self, session_id: str) -> None:  # pragma: no cover
        pass


class _StubReasoning:
    """Devuelve el guion paso a paso; registra los prompts recibidos."""

    def __init__(self, script: List[Dict[str, Any]]) -> None:
        self.script = list(script)
        self.i = 0
        self.prompts: List[str] = []
        self.memory = _StubMemory()

    async def think(self, prompt: str, sensor_data=None, tools=None, session_id="default"):
        self.prompts.append(prompt)
        if self.i < len(self.script):
            step = self.script[self.i]
        else:
            step = {"calls": [], "text": "done"}
        self.i += 1
        return step

    @property
    def calls_made(self) -> int:
        return self.i


class _StubSkills:
    def __init__(self) -> None:
        self.successes: List[str] = []
        self.failures: List[str] = []

    def lookup(self, text: str):
        return None

    def record_success(self, text, calls, response) -> None:
        self.successes.append(text)

    def record_failure(self, text, calls) -> None:
        self.failures.append(text)


# ── Helpers ────────────────────────────────────────────────────────────────
READ = {"skill": "code_tools", "action": "code_view_file",
        "params": {"path": "core/pipeline.py", "start_line": 1, "end_line": 20}}
READ_SAME = dict(READ)  # identico: mismo fingerprint
WRITE = {"skill": "code_tools", "action": "code_write_file",
         "params": {"path": "core/pipeline.py", "content": "x"}}
OTHER_READ = {"skill": "code_tools", "action": "code_view_file",
              "params": {"path": "core/kernel.py", "start_line": 1, "end_line": 20}}


def _make_pipeline(script, max_steps=50):
    reasoning = _StubReasoning(script)
    skills = _StubSkills()
    pipeline = ActionPipeline(
        reasoning=reasoning,  # type: ignore[arg-type]
        skill_memory=skills,  # type: ignore[arg-type]
        abilities={},
        max_steps=max_steps,
    )

    async def _fake_execute(calls, session_id="default", executed_calls=None):
        return [{"ok": True, "call": c, "output": {"data": "ok"}} for c in calls], True

    pipeline._execute_calls = _fake_execute  # type: ignore[assignment]

    async def _noop(text, calls, response):
        return None

    pipeline._distill_and_cache = _noop  # type: ignore[assignment]
    return pipeline, reasoning, skills


def _run(script, max_steps=50, session="noprogress_test"):
    pipeline, reasoning, skills = _make_pipeline(script, max_steps=max_steps)

    events: List[Dict[str, Any]] = []
    event_bus.subscribe("pipeline.loop_no_progress", lambda d: events.append(d or {}))

    result = asyncio.run(
        pipeline._try_new("arregla el bucle", None, None, session_id=session)
    )
    return result, reasoning, skills, events


# ── Tests ──────────────────────────────────────────────────────────────────
def test_identical_reads_do_not_consume_max_steps():
    """NUNCA puede agotar 50 pasos releyendo el mismo archivo."""
    script = [{"calls": [READ_SAME], "text": ""} for _ in range(50)]

    result, reasoning, _skills, events = _run(script, max_steps=50)

    # Antes: steps_used == 50. Ahora corta en cuanto detecta la racha.
    assert result["steps_used"] <= _MAX_REDUNDANT_STEPS + 1, (
        "el bucle de re-lecturas consumo %s pasos" % result["steps_used"]
    )
    assert reasoning.calls_made <= _MAX_REDUNDANT_STEPS + 1
    assert events, "debe emitirse pipeline.loop_no_progress"
    assert events[-1]["streak"] >= 2


def test_no_progress_turn_is_reported_honestly():
    """El turno cortado no puede declararse exitoso."""
    script = [{"calls": [READ_SAME], "text": ""} for _ in range(50)]

    result, _reasoning, skills, _events = _run(script)

    assert result["success"] is False
    assert result["response"], "debe haber un informe del corte"
    assert "re_lecturas" in result["response"] or "lecturas" in result["response"]
    assert skills.successes == [], "no puede registrarse como skill exitosa"
    assert skills.failures, "debe registrarse como fallo"


def test_second_repeat_triggers_a_nudge_prompt():
    """Antes de cortar, se le exige al LLM cambiar de estrategia."""
    script = [{"calls": [READ_SAME], "text": ""} for _ in range(50)]

    _result, reasoning, _skills, _events = _run(script)

    joined = "\n".join(reasoning.prompts)
    assert "[NUDGE - SIN PROGRESO" in joined, (
        "el LLM debe recibir el nudge de re-lectura, no solo un corte silencioso"
    )


def test_reread_after_write_is_not_flagged_as_redundant():
    """Escribir cambia el estado: volver a leer SI aporta informacion.

    Sin esto, el detector daria un falso positivo en el flujo legitimo
    leer -> parchear -> verificar.
    """
    script = [
        {"calls": [READ], "text": ""},        # productivo: primera lectura
        {"calls": [WRITE], "text": ""},       # cambio real -> limpia el cache
        {"calls": [READ_SAME], "text": ""},   # re-lectura legitima tras escribir
        {"calls": [], "text": "Listo."},
    ]

    result, _reasoning, skills, events = _run(script)

    assert events == [], "no debe marcar no-progreso en leer->escribir->leer"
    assert result["steps_used"] == 4
    assert result["success"] is True
    assert skills.successes, "un turno realmente completo si se cachea"


def test_productive_step_resets_the_streak():
    """Una accion nueva rompe la racha y el turno continua con normalidad."""
    script = [
        {"calls": [READ], "text": ""},        # productivo
        {"calls": [READ_SAME], "text": ""},   # racha 1 -> nudge
        {"calls": [OTHER_READ], "text": ""},  # productivo -> racha 0
        {"calls": [READ_SAME], "text": ""},   # racha 1 otra vez
        {"calls": [], "text": "Terminado."},
    ]

    result, _reasoning, _skills, events = _run(script)

    assert result["steps_used"] == 5, "no debe cortarse: solo hubo pasos aislados"
    assert result["success"] is True
    # dos rachas de longitud 1, ninguna llego al limite
    assert all(e["streak"] == 1 for e in events)


def test_promise_closed_turn_is_not_cached_as_skill():
    """Un turno cerrado en promesa deja una secuencia incompleta.

    Cachearla en SkillMemory hacia que el siguiente intento replicara el mismo
    bucle de re-verificacion.
    """
    promise = "Let me verify the fix by reading the file again."
    script = [
        {"calls": [READ], "text": ""},
        {"calls": [], "text": promise},
        {"calls": [], "text": promise},
        {"calls": [], "text": promise},
    ]

    result, _reasoning, skills, _events = _run(script)

    assert skills.successes == [], (
        "un turno que cierra en promesa no puede cachearse como skill"
    )
    assert skills.failures
    assert result["steps_used"] <= len(script)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
