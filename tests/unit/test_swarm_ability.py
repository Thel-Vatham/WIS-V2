"""
Tests for SwarmAbility — wires core/swarm.py (SwarmCoordinator) into the registry.
"""
from __future__ import annotations

import pytest

from abilities.swarm import SwarmAbility
from core.swarm import SwarmCoordinator


@pytest.fixture(autouse=True)
def _reset_swarm():
    SwarmCoordinator.reset()
    yield
    SwarmCoordinator.reset()


def test_swarm_schema():
    ab = SwarmAbility()
    assert ab.name == "swarm"
    actions = [s["action"] for s in ab.get_schema()]
    for expected in ("broadcast", "inbox", "claim_task", "status", "lock_file", "unlock_file"):
        assert expected in actions


@pytest.mark.asyncio
async def test_swarm_broadcast_and_inbox():
    ab = SwarmAbility()
    await ab.execute("broadcast", {"topic": "plans", "message": "hello swarm", "sender_id": "a1"})
    res = await ab.execute("inbox", {"topic": "plans"})
    assert res["success"] is True
    assert any(b["message"] == "hello swarm" for b in res["data"])


@pytest.mark.asyncio
async def test_swarm_claim_task_is_atomic():
    ab = SwarmAbility()
    first = await ab.execute("claim_task", {"task_key": "build-auth", "agent_id": "a1"})
    second = await ab.execute("claim_task", {"task_key": "build-auth", "agent_id": "a2"})
    assert first["success"] is True
    assert second["success"] is False  # already claimed -> no duplicate work


@pytest.mark.asyncio
async def test_swarm_lock_file_and_release():
    ab = SwarmAbility()
    lock = await ab.execute("lock_file", {"path": "src/app.py", "agent_id": "a1"})
    assert lock["success"] is True
    held = await ab.execute("locked_files", {})
    # The lock manager normalizes to an absolute path; assert on the filename
    # and holder rather than the exact key.
    assert held["data"] and any("app.py" in k for k in held["data"])
    assert list(held["data"].values()) == ["a1"]
    await ab.execute("unlock_file", {"path": "src/app.py", "agent_id": "a1"})
    held2 = await ab.execute("locked_files", {})
    assert held2["data"] == {}
