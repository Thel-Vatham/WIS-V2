"""Agentic Test-Driven Development (TDD) Orchestrator for AVRORA.

Executes a verifiable Red-Green-Commit engineering lifecycle:
1. Phase 1 (Red): Writes unit tests in an isolated Shadow Workspace and executes them.
   Verifies that the test properly fails or catches missing implementation.
2. Phase 2 (Green): Injects the implementation code in the Shadow Workspace and re-runs tests.
   Verifies that 100% of tests now pass.
3. Phase 3 (Commit): Atomically commits both the implementation and tests to the real project.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .shadow_workspace import ShadowWorkspace


class TDDError(Exception):
    """Raised when the TDD cycle cannot be fulfilled."""


def run_tdd_cycle(
    target_file: str,
    test_file: str,
    test_code: str,
    implementation_code: str,
    host_root: Path | None = None,
) -> dict[str, Any]:
    """Execute a complete Red-Green-Commit TDD cycle using Shadow Workspace."""
    base_root = (host_root or Path.cwd()).resolve()

    with ShadowWorkspace(host_root=base_root) as shadow:
        # Pre-stage existing implementation if any
        host_target = (base_root / target_file).resolve()
        if host_target.exists():
            shadow.stage_file(target_file)

        # -------------------------------------------------------------
        # 1. Red Phase: Stage tests before new implementation
        # -------------------------------------------------------------
        shadow.write_staged_file(test_file, test_code)

        # Run pytest inside the shadow workspace using the current python executable
        test_cmd = [sys.executable, "-m", "pytest", test_file, "-v"]
        red_result = shadow.run_staged_check(test_cmd)

        # In TDD, the test should fail if the new feature is not yet implemented
        red_phase_status = "test_failed_as_expected" if not red_result["success"] else "test_passed_unexpectedly"

        # -------------------------------------------------------------
        # 2. Green Phase: Stage implementation code
        # -------------------------------------------------------------
        shadow.write_staged_file(target_file, implementation_code)
        green_result = shadow.run_staged_check(test_cmd)

        if not green_result["success"]:
            return {
                "success": False,
                "phase": "green_failed",
                "message": "TDD Green phase failed: Tests did not pass with the new implementation.",
                "red_phase": red_phase_status,
                "green_stdout": green_result["stdout"],
                "green_stderr": green_result["stderr"],
                "diff": "",
            }

        # -------------------------------------------------------------
        # 3. Commit Phase: Tests passed 100% -> Commit both to host
        # -------------------------------------------------------------
        commit_res = shadow.commit_to_host()

        return {
            "success": True,
            "phase": "completed",
            "message": "TDD cycle successfully executed: Red -> Green -> Committed.",
            "red_phase": red_phase_status,
            "green_output": green_result["stdout"],
            "committed_files": commit_res.get("files", []),
            "diff": commit_res.get("diff", ""),
        }
