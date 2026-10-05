"""
Tests for BackgroundAbility — wires core/mission.py (TaskManager) into the registry.
"""
from __future__ import annotations

import time

import pytest

from abilities.background import BackgroundAbility


def test_background_schema():
    ab = BackgroundAbility()
    assert ab.name == "background"
    actions = [s["action"] for s in ab.get_schema()]
    for expected in ("run", "status", "kill", "list", "summary"):
        assert expected in actions


@pytest.mark.asyncio
async def test_background_run_and_status():
    ab = BackgroundAbility()
    res = await ab.execute("run", {"command": "echo hello_wis"})
    assert res["success"] is True
    job_id = res["data"]["job_id"]

    # Poll until done (fast command), bounded to avoid flakiness.
    status = None
    for _ in range(50):
        status = (await ab.execute("status", {"job_id": job_id}))["data"]
        if status.get("status") in ("done", "failed"):
            break
        time.sleep(0.1)

    assert status is not None
    assert status.get("status") == "done"
    assert "hello_wis" in (status.get("output") or "")


@pytest.mark.asyncio
async def test_background_list_includes_job():
    ab = BackgroundAbility()
    res = await ab.execute("run", {"command": "echo listed"})
    job_id = res["data"]["job_id"]
    lst = await ab.execute("list", {})
    assert any(j.get("job_id") == job_id for j in lst["data"])
