"""
Unit tests for ActionPipeline pure-LLM agentic routing.
All queries go directly to the LLM ReAct loop unless synthesized into SkillMemory.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.pipeline import ActionPipeline
from core.hardware_memory import HardwareMemory
from core.skill_memory import SkillMemory
from core.reasoning import ReasoningEngine


@pytest.mark.asyncio
async def test_pipeline_queries_routed_to_llm(hardware_memory: HardwareMemory):
    # Registrar un dispositivo
    hardware_memory.register_device(
        device_id="stm32_board",
        name="STM32F4 Nucleo",
        interface="serial",
        port_or_address="COM8",
        baud_rate=115200,
    )

    mock_reasoning = MagicMock(spec=ReasoningEngine)
    mock_reasoning.think = AsyncMock(return_value={
        "text": "Checking devices via LLM reasoning.",
        "tool_calls": [],
    })
    mock_skill_mem = MagicMock(spec=SkillMemory)
    mock_skill_mem.lookup.return_value = None

    pipeline = ActionPipeline(
        reasoning=mock_reasoning,
        skill_memory=mock_skill_mem,
        hardware_memory=hardware_memory,
    )

    # Consulta que antes era interceptada por FastPath: ahora va 100% al LLM
    result = await pipeline.process("listar dispositivos")
    assert result["path_used"] == "new"
    assert result["success"] is True
    # ReasoningEngine SI debe ser llamado
    mock_reasoning.think.assert_called()


@pytest.mark.asyncio
async def test_pipeline_skill_memory_cached_hint(hardware_memory: HardwareMemory):
    mock_reasoning = MagicMock(spec=ReasoningEngine)
    mock_reasoning.think = AsyncMock(return_value={
        "text": "The cached skill is available as a hint.",
        "calls": [],
    })
    mock_skill_mem = MagicMock(spec=SkillMemory)
    # Simular una habilidad ya aprendida y sintetizada
    mock_skill_mem.lookup.return_value = {
        "response": "Cached synthesis executed instantly.",
        "calls": [],
    }

    pipeline = ActionPipeline(
        reasoning=mock_reasoning,
        skill_memory=mock_skill_mem,
        hardware_memory=hardware_memory,
    )

    # A learned skill is supplied as a hint to the current ReAct loop.
    result = await pipeline.process("rutina sintetizada")
    assert result["path_used"] == "new"
    mock_reasoning.think.assert_called()


@pytest.mark.asyncio
async def test_pipeline_deduplicates_repeated_side_effect_calls(hardware_memory: HardwareMemory):
    abilities = MagicMock()
    abilities.execute = AsyncMock(return_value={"success": True, "data": {"opened": True}})
    safety = MagicMock()
    safety.check.return_value = (True, "")
    safety.needs_approval.return_value = False

    pipeline = ActionPipeline(
        reasoning=MagicMock(spec=ReasoningEngine),
        skill_memory=MagicMock(spec=SkillMemory),
        abilities=abilities,
        safety=safety,
        hardware_memory=hardware_memory,
    )
    calls = [
        {"skill": "system", "action": "execute_shell", "params": {"command": "start photo.png"}},
        {"skill": "system", "action": "execute_shell", "params": {"command": "start photo.png"}},
    ]

    results, ok = await pipeline._execute_calls(calls, session_id="main", executed_calls=set())

    assert ok is True
    assert abilities.execute.await_count == 1
    assert results[1]["output"]["reason"] == "duplicate_call_in_request"


@pytest.mark.asyncio
async def test_pipeline_allows_retry_after_failed_call(hardware_memory: HardwareMemory):
    abilities = MagicMock()
    abilities.execute = AsyncMock(side_effect=[
        {"success": False, "error": "temporary failure"},
        {"success": True, "data": {"recovered": True}},
    ])
    safety = MagicMock()
    safety.check.return_value = (True, "")
    safety.needs_approval.return_value = False
    pipeline = ActionPipeline(
        reasoning=MagicMock(spec=ReasoningEngine),
        skill_memory=MagicMock(spec=SkillMemory),
        abilities=abilities,
        safety=safety,
        hardware_memory=hardware_memory,
    )
    call = {"skill": "system", "action": "execute_shell", "params": {"command": "echo retry"}}
    seen = set()

    first, first_ok = await pipeline._execute_calls([call], executed_calls=seen)
    second, second_ok = await pipeline._execute_calls([call], executed_calls=seen)

    assert first_ok is False
    assert second_ok is True
    assert first[0]["ok"] is False
    assert second[0]["ok"] is True
    assert abilities.execute.await_count == 2


@pytest.mark.asyncio
async def test_pipeline_stops_after_repeated_successful_turn(hardware_memory: HardwareMemory):
    call = {"skill": "system", "action": "execute_shell", "params": {"command": "start photo.png"}}
    reasoning = MagicMock(spec=ReasoningEngine)
    reasoning.think = AsyncMock(side_effect=[
        {"text": "", "calls": [call]},
        {"text": "", "calls": [call]},
        {"text": "should not reach this step", "calls": []},
    ])
    abilities = MagicMock()
    abilities.execute = AsyncMock(return_value={"success": True, "data": {"opened": True}})
    skill_memory = MagicMock(spec=SkillMemory)
    skill_memory.lookup.return_value = None
    safety = MagicMock()
    safety.check.return_value = (True, "")
    safety.needs_approval.return_value = False
    pipeline = ActionPipeline(
        reasoning=reasoning,
        skill_memory=skill_memory,
        abilities=abilities,
        safety=safety,
        max_steps=50,
        hardware_memory=hardware_memory,
    )

    result = await pipeline.process("open photo", session_id="main")

    assert reasoning.think.await_count == 2
    assert abilities.execute.await_count == 1
    assert result["steps_used"] == 2
