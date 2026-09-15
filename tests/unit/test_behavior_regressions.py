"""Regresiones de la validacion de comportamiento de WIS (2026-09-15).

D1 - `close_application` no puede matar el interprete que hospeda WIS.
     Incidente real: `taskkill /F /IM "python.exe"` mato a WIS a si mismo
     (log congelado a las 15:25:03, cero procesos vivos despues).
D2 - Una narracion sin tool calls ("I'll examine…") NO es una tarea terminada;
     debe reconocerse como turno estancado.
D3 - Los comandos compuestos (`cd X && ...`) no deben rechazarse como
     directorio inexistente.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from abilities.system import SystemAbility, _kills_wis_runtime  # noqa: E402
from core.pipeline import _announces_future_action  # noqa: E402


def _ability() -> SystemAbility:
    return SystemAbility()


# ── D1: autoproteccion ────────────────────────────────────────────────────
def test_close_application_blocks_generic_python():
    res = asyncio.run(_ability()._close_application({"app_name": "python", "force": True}))
    assert res["success"] is False
    assert res["data"]["blocked_by"] == "self_protection"
    assert "autoproteccion" in res["message"].lower()


def test_close_application_blocks_own_interpreter_name():
    own = Path(sys.executable).stem
    res = asyncio.run(_ability()._close_application({"app_name": own, "force": True}))
    assert res["success"] is False
    assert res["data"]["blocked_by"] == "self_protection"


def test_close_application_still_allows_unrelated_process_name():
    """Un nombre ajeno NO debe quedar bloqueado por autoproteccion."""
    res = asyncio.run(
        _ability()._close_application({"app_name": "wis_nonexistent_proc_xyz", "force": True})
    )
    assert res.get("data", {}).get("blocked_by") != "self_protection"


# ── D1-bis: el guard cubre TODAS las vias de ejecucion ────────────────────
# Incidente real: `close_application` estaba protegido, pero el agente esquivó
# el guard con `taskkill /F /IM python.exe /T` por la via de shell y volvió a
# matar a WIS. El guard ahora es transversal (shell, PowerShell y Python).
RUNTIME_IMAGE = Path(sys.executable).name   # p. ej. "python.exe"
RUNTIME_STEM = Path(sys.executable).stem    # p. ej. "python"


@pytest.mark.parametrize(
    "payload",
    [
        f"taskkill /F /IM {RUNTIME_IMAGE} /T",
        f'taskkill /F /IM "{RUNTIME_IMAGE}"',
        f"taskkill /F /IM {RUNTIME_IMAGE} /T 2>nul & echo DONE",
        f"Stop-Process -Name {RUNTIME_STEM} -Force",
        f'Stop-Process -Name "{RUNTIME_IMAGE}" -Force',
        f"pkill -f {RUNTIME_STEM}",
    ],
)
def test_kill_guard_detects_self_kill_by_image(payload: str):
    assert _kills_wis_runtime(payload), payload


def test_kill_guard_detects_self_kill_by_pid():
    assert _kills_wis_runtime(f"taskkill /F /PID {os.getpid()}")
    assert _kills_wis_runtime(f"Stop-Process -Id {os.getpid()} -Force")


def test_kill_guard_allows_unrelated_process():
    """Cerrar un proceso ajeno debe seguir permitido: no romper el uso legitimo."""
    assert _kills_wis_runtime("taskkill /F /IM CalculatorApp.exe") == ""
    assert _kills_wis_runtime("Stop-Process -Name notepad -Force") == ""
    assert _kills_wis_runtime("echo hola") == ""


def test_run_command_blocks_shell_self_kill():
    res = asyncio.run(_ability()._run_command({"command": f"taskkill /F /IM {RUNTIME_IMAGE} /T"}))
    assert res["success"] is False, res
    assert res["data"]["blocked_by"] == "self_protection"
    assert "autoproteccion" in res["message"].lower()


def test_run_command_still_allows_killing_unrelated_process():
    res = asyncio.run(
        _ability()._run_command({"command": "taskkill /F /IM wis_nonexistent_app_xyz.exe"})
    )
    assert res.get("data", {}).get("blocked_by") != "self_protection"


def test_execute_powershell_never_executes_self_kill():
    res = asyncio.run(
        _ability()._execute_powershell({"script": f"Stop-Process -Name {RUNTIME_STEM} -Force"})
    )
    # En modo 'safe' se bloquea por politica; en 'autonomous' por autoproteccion.
    assert res["success"] is False


def test_run_python_code_never_executes_self_kill():
    res = asyncio.run(
        _ability()._run_python_code(
            {"code": f"import os\nos.system('taskkill /F /IM {RUNTIME_IMAGE} /T')"}
        )
    )
    assert res["success"] is False


# ── D2: narracion vs. resultado final ─────────────────────────────────────
@pytest.mark.parametrize(
    "text",
    [
        "I'll examine the current render engine implementation to understand what needs improvement.",
        "Let me first check the current state of live_detector.py and validate it runs.",
        "Voy a revisar el detector en vivo.",
        "Ahora verifico el resultado.",
    ],
)
def test_detects_announced_but_unexecuted_action(text: str):
    assert _announces_future_action(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Listo. Detecte una botella y un telefono en el frame, con sus cajas dibujadas.",
        "The task is complete. The file is on disk (6398 bytes).",
        "Everything is working now. Let me know if you need anything else.",
        "I will not kill WIS's own runtime.",
        "No voy a cerrar el proceso que hospeda WIS.",
        # Oferta condicional (falso positivo real observado en vivo 16:06):
        "Give me that name or PID and I'll execute it immediately.",
        "If you tell me the exact PID, I'll close it.",
        "",
    ],
)
def test_does_not_flag_real_final_answers(text: str):
    assert _announces_future_action(text) is False


# ── D3: comandos compuestos con cd ────────────────────────────────────────
def test_compound_cd_command_runs_instead_of_being_rejected(tmp_path: Path):
    target = str(tmp_path)
    res = asyncio.run(
        _ability()._run_command(
            {"command": f'cd "{target}" && cd .', "_session_id": "test_chain"}
        )
    )
    assert "no existe" not in str(res.get("message", "")).lower()
    assert res.get("success") is True, res
    assert res["data"]["returncode"] == 0, res
