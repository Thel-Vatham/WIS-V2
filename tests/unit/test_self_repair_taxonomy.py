"""Por que WIS no arreglaba sus propios defectos (y como se corrige).

Pregunta del usuario: "WIS es quien deberia solucionar esas cosas, porque no lo
hace?".

Evidencia en su propio codigo:

1. `FailureClassifier.classify` tenia como catch-all `HARDWARE_ERROR`. Cualquier
   fallo no reconocido se etiquetaba como averia de hardware, asi que WIS
   entendia "falla el mundo exterior" y nunca miraba su propia fuente.
2. El prompt de auto-reparacion era unico y solo decia: "consulta las tools y
   genera llamadas o parametros alternativos". Es decir, WIS SOLO tenia permiso
   para rodear el fallo, nunca para reparar el codigo.

Estas pruebas fijan la nueva taxonomia y la escalada del prompt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pipeline import _build_repair_prompt  # noqa: E402
from core.safety import FailureClassifier  # noqa: E402


# ── Taxonomia: un defecto de software NO es hardware ──────────────────────
@pytest.mark.parametrize(
    "error_text",
    [
        # El caso real del log: vision.py con OpenCV 5.
        "Deteccion multi-objeto no disponible: el modelo esta en "
        "D:\\WIS\\models\\detection, pero OpenCV 5.0.0 ya no incluye el "
        "importador Darknet (readNetFromDarknet).",
        "module 'cv2.dnn' has no attribute 'readNetFromDarknet'",
        "'SystemAbility' object has no attribute '_run_command_cancellable'",
        "ModuleNotFoundError: No module named 'torch'",
        "cannot import name 'ProcessManager' from 'abilities.pc.process'",
        "'NoneType' object has no attribute 'kill'",
        "Traceback (most recent call last):",
        "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
        "KeyError: 'app_name'",
        "error: Darknet importer has been removed",
    ],
)
def test_software_defects_are_classified_as_such(error_text: str):
    assert FailureClassifier.classify(error_text) == "SOFTWARE_DEFECT"


@pytest.mark.parametrize(
    "error_text",
    [
        "No se pudo capturar imagen (sin camara o dispositivo ocupado).",
        "No se encontro el dispositivo de camara",
        "serial port COM3 not available",
        "no se detecta ningun sensor USB",
    ],
)
def test_real_hardware_faults_still_report_hardware(error_text: str):
    assert FailureClassifier.classify(error_text) == "HARDWARE_ERROR"


@pytest.mark.parametrize(
    "error_text, expected",
    [
        ("Bloqueado por autoproteccion: cierra 'python.exe'", "SAFETY_BLOCK"),
        ("Timeout de 15.0s excedido.", "TIMEOUT"),
        ("invalid_call: missing action", "LLM_FORMAT_ERROR"),
        ("Connection failed: getaddrinfo failed", "NETWORK_ERROR"),
    ],
)
def test_existing_categories_are_preserved(error_text: str, expected: str):
    assert FailureClassifier.classify(error_text) == expected


def test_unknown_errors_are_not_blamed_on_hardware():
    """El catch-all ya no debe mentir diciendo que es hardware."""
    assert FailureClassifier.classify("algo raro paso") == "UNKNOWN_ERROR"


# ── Escalada del prompt de reparacion ─────────────────────────────────────
def test_software_defect_prompt_authorizes_repairing_own_source():
    prompt = _build_repair_prompt(
        "run the live camera", 2, "SOFTWARE_DEFECT", "module has no attribute x"
    )
    assert "DEFECT IN THE CODE" in prompt
    assert "repair the source code" in prompt
    # Debe indicar las tools reales de inspeccion y parcheo.
    assert "code_view_file" in prompt
    assert "code_replace_content" in prompt
    # Y exigir prueba de que el arreglo funciona.
    assert "Re-run the failed action" in prompt
    assert "not a hardware fault" in prompt


def test_non_software_failure_keeps_the_tool_selection_prompt():
    prompt = _build_repair_prompt("run x", 2, "TIMEOUT", "Timeout de 15s")
    assert "Generate alternative tool calls or parameters." in prompt
    assert "code_replace_content" not in prompt


def test_hardware_failure_does_not_authorize_code_changes():
    """Una averia real de hardware no debe invitar a tocar el codigo."""
    prompt = _build_repair_prompt("captura", 3, "HARDWARE_ERROR", "sin camara")
    assert "code_replace_content" not in prompt
    assert "Generate alternative tool calls or parameters." in prompt
