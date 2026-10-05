"""
Tests that the Red-Green-Commit TDD cycle is a real, wired capability.
"""
from __future__ import annotations

import pytest

from abilities.pc.code_ability import CodeToolsAbility
from abilities.pc.tdd_runner import run_tdd_cycle


def test_code_tools_exposes_tdd_cycle_action():
    ab = CodeToolsAbility()
    actions = [s["action"] for s in ab.get_schema()]
    assert "tdd_cycle" in actions


def test_tdd_cycle_full_red_green_commit(tmp_path):
    target = "greeter.py"
    test = "test_greeter.py"
    test_code = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
        "from greeter import greet\n\n"
        "def test_greet():\n"
        "    assert greet('wis') == 'hello wis'\n"
    )
    impl = "def greet(name):\n    return 'hello ' + name\n"

    result = run_tdd_cycle(
        target_file=target,
        test_file=test,
        test_code=test_code,
        implementation_code=impl,
        host_root=tmp_path,
    )
    assert result["success"] is True
    assert result["phase"] == "completed"
    assert result["red_phase"] == "test_failed_as_expected"
    # Committed to host only after green.
    assert (tmp_path / target).exists()
    assert (tmp_path / test).exists()
    assert (tmp_path / target).read_text() == impl


def test_tdd_cycle_refuses_env_files(tmp_path):
    with pytest.raises(PermissionError):
        run_tdd_cycle(
            target_file=".env",
            test_file="test_x.py",
            test_code="",
            implementation_code="",
            host_root=tmp_path,
        )
