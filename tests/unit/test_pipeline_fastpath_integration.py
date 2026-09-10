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
async def test_pipeline_skill_memory_cached_dispatch(hardware_memory: HardwareMemory):
    mock_reasoning = MagicMock(spec=ReasoningEngine)
    mock_reasoning.think = AsyncMock()
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

    # Consulta aprendida -> ejecutada directamente desde SkillMemory
    result = await pipeline.process("rutina sintetizada")
    assert result["path_used"] == "known"
    assert "Cached synthesis" in result["response"]
    # No llama al LLM porque ya fue probado y adquirido
    mock_reasoning.think.assert_not_called()
