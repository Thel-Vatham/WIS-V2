# -*- coding: utf-8 -*-
"""Regression tests for the desktop process subsystem.

The whole `desktop` process engine was dead code, reachable only through a
broken import, so three advertised actions failed 100% of the time and the
agent retried them until the turn budget was gone:

    from .process import ProcessManager   # ProcessManager does not exist

The real class is `ProcessOps` (abilities/pc/process.py), with a different
surface:

    ProcessOps.list(name_filter, limit) -> list[dict]   (NOT .list_processes())
    ProcessOps.kill(pid)                -> str          (positional, NOT .kill(pid=, name=))
    ProcessOps.kill_by_name(name)       -> str
    no `wait_for` method at all.

These tests pin the corrected contract, including the self-protection guard:
`kill_process` must refuse to terminate WIS itself. That guard matters because
this fix is what makes the kill path reachable for the first time.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from abilities.pc.advanced_desktop_ability import (
    AdvancedDesktopAbility,
    _protected_pids,
)
from abilities.pc.process import ProcessOps


# --------------------------------------------------------------------------- #
#  Engine construction: the broken import must be gone
# --------------------------------------------------------------------------- #
def test_process_engine_imports_and_constructs():
    """The lazy accessor must resolve ProcessOps, not a non-existent name."""
    ability = AdvancedDesktopAbility()
    engine = ability.proc
    assert engine is not None, (
        "el motor de procesos no se pudo instanciar (import roto -> None)"
    )
    assert isinstance(engine, ProcessOps)


def test_no_reference_to_the_phantom_class_in_the_module():
    """`ProcessManager` must not be referenced anywhere anymore."""
    import abilities.pc.advanced_desktop_ability as mod

    source = open(mod.__file__, "r", encoding="utf-8").read()
    # The name may appear in prose/comments explaining the historical bug,
    # but never as an import target.
    assert "from .process import ProcessManager" not in source
    assert "from .process import ProcessOps" in source


# --------------------------------------------------------------------------- #
#  list_processes
# --------------------------------------------------------------------------- #
def test_processops_list_accepts_filter_and_limit():
    """list() must support filtering; it used to be a bare no-arg call."""
    rows = ProcessOps.list(name_filter="", limit=None)
    assert isinstance(rows, list)
    if rows:
        assert {"pid", "name"} <= set(rows[0].keys())

    limited = ProcessOps.list(limit=3)
    assert len(limited) <= 3


def test_list_processes_action_reports_success():
    ability = AdvancedDesktopAbility()
    result = asyncio.run(ability.execute("list_processes", {"limit": 5}))
    assert result["success"] is True, result
    assert len(result["data"]) <= 5


def test_list_processes_filter_matches_only_matching_names():
    ability = AdvancedDesktopAbility()
    result = asyncio.run(
        ability.execute("list_processes", {"filter_name": "python", "limit": 20})
    )
    assert result["success"] is True
    for proc in result["data"]:
        assert "python" in str(proc["name"]).lower()


def test_list_is_not_truncated_to_40_before_filtering():
    """Filtering must see the whole process table.

    The old code did `procs[:40]` before any filtering, so a name match outside
    the first 40 PIDs was unreachable for both filtering and wait_for_process.
    """
    everything = ProcessOps.list(limit=None)
    capped = ProcessOps.list(limit=40)
    if len(everything) > 40:
        assert len(capped) == 40
        assert len(everything) > len(capped)


# --------------------------------------------------------------------------- #
#  wait_for_process (was calling a method that does not exist)
# --------------------------------------------------------------------------- #
def test_wait_for_process_finds_current_process():
    """A process that certainly exists must be found."""
    me = "python"
    result = asyncio.run(
        AdvancedDesktopAbility().execute(
            "wait_for_process", {"name": me, "timeout": 8}
        )
    )
    assert result["success"] is True, result
    assert result["data"], "esperaba al menos un proceso coincidente"


def test_wait_for_process_times_out_gracefully():
    result = asyncio.run(
        AdvancedDesktopAbility().execute(
            "wait_for_process", {"name": "zzz-proceso-inexistente-zzz", "timeout": 1}
        )
    )
    assert result["success"] is False
    assert "no aparecio" in result["message"]


# --------------------------------------------------------------------------- #
#  kill_process: self-protection + malformed input
# --------------------------------------------------------------------------- #
def test_kill_process_refuses_to_kill_wis_itself():
    """Killing WIS's own PID must be blocked, never attempted."""
    result = asyncio.run(
        AdvancedDesktopAbility().execute("kill_process", {"pid": os.getpid()})
    )
    assert result["success"] is False
    assert result["data"]["blocked_by"] == "self_protection"
    # The process running the test is obviously still alive.
    assert os.getpid() in _protected_pids()


def test_kill_process_rejects_malformed_pid():
    result = asyncio.run(
        AdvancedDesktopAbility().execute("kill_process", {"pid": "not-a-pid"})
    )
    assert result["success"] is False
    assert "invalido" in result["message"].lower()


def test_kill_process_requires_pid_or_name():
    result = asyncio.run(AdvancedDesktopAbility().execute("kill_process", {}))
    assert result["success"] is False
    assert "pid" in result["message"].lower() or "name" in result["message"].lower()


def test_protected_pids_includes_self():
    assert os.getpid() in _protected_pids()
