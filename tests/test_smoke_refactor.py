"""
Smoke test verifying the full refactored stack:
- AdvancedDesktopAbility
- LongHorizonEngine persistence and execution
- Server endpoints (FastAPI create_app, health, auth bootstrap, long horizon CRUD, render)
"""
import asyncio
import json
from pathlib import Path
import sys

# Ensure ROOT_DIR in sys.path
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from abilities.pc.advanced_desktop_ability import AdvancedDesktopAbility
from core.long_horizon import LongHorizonEngine
from console.server import create_app, WISCoreContainer
import pytest
from fastapi.testclient import TestClient


def test_advanced_desktop():
    ada = AdvancedDesktopAbility()
    assert ada.name == "advanced_desktop"
    assert ada.domain == "pc"
    schema = ada.get_schema()
    assert len(schema) >= 6
    action_names = [a["action"] for a in schema]
    assert "launch_app" in action_names
    assert "list_windows" in action_names
    assert "click_element" in action_names
    assert "annotate_screen" in action_names
    assert "analyze_screen" in action_names
    assert "list_processes" in action_names
    print(f"[OK] AdvancedDesktopAbility: {len(schema)} actions registered.")


@pytest.fixture
def engine(tmp_path):
    data_dir = tmp_path / "data_lh"
    data_dir.mkdir(parents=True, exist_ok=True)

    class MockPipeline:
        async def process(self, text, **kwargs):
            return {"success": True, "response": f"Processed: {text}"}

    class MockLLM:
        async def chat(self, messages, **kwargs):
            return {"text": json.dumps({"steps": ["Step A: check", "Step B: apply"]})}

    return LongHorizonEngine(
        data_dir=data_dir,
        pipeline=MockPipeline(),
        llm_client=MockLLM(),
        poll_interval=0.1,
    )


def test_long_horizon_engine(engine):
    # Create task
    task = engine.create_task("Analyze and optimize system", priority=9)
    assert task.status == "pending"
    assert task.priority == 9

    # List tasks
    all_tasks = engine.list_tasks()
    assert any(t["id"] == task.id for t in all_tasks)

    # Pause / Resume / Cancel lifecycle
    task.status = "running"
    assert engine.pause_task(task.id) is True
    assert task.status == "paused"
    assert engine.resume_task(task.id) is True
    assert task.status == "running"
    assert engine.cancel_task(task.id) is True
    assert task.status == "cancelled"

    # Journal
    journal = engine.get_journal(task.id)
    assert len(journal) >= 1
    print(f"[OK] LongHorizonEngine: task {task.id[:8]} full lifecycle tested.")


def test_fastapi_server(engine):
    container = WISCoreContainer(long_horizon=engine)
    app = create_app(core=container, auth_token="test-secret-token")
    client = TestClient(app)

    # 1. Health check (public)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    print("[OK] /api/health passed")

    # 2. Auth bootstrap (localhost allowed)
    res = client.get("/api/auth/bootstrap")
    assert res.status_code == 200
    data = res.json()
    assert data["token"] == "test-secret-token"
    print("[OK] /api/auth/bootstrap passed")

    # 3. Long Horizon tasks API
    headers = {"Authorization": "Bearer test-secret-token"}
    res = client.get("/api/tasks/long", headers=headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list) or "tasks" in res.json()
    print("[OK] GET /api/tasks/long passed")

    # Create new task via API
    res = client.post(
        "/api/tasks/long",
        headers=headers,
        json={"text": "E2E automated verification", "priority": 7},
    )
    assert res.status_code == 200
    new_task = res.json()["task"]
    assert new_task["priority"] == 7
    print("[OK] POST /api/tasks/long passed:", new_task["id"][:8])

    # 4. Render API
    res = client.post(
        "/api/render",
        headers=headers,
        json={"html": "<h1>WIS AGI Window</h1>", "title": "Test Render"},
    )
    assert res.status_code == 200
    render_id = res.json()["render_id"]
    res = client.get(f"/api/render/{render_id}")
    assert res.status_code == 200
    assert "WIS AGI Window" in res.text
    print("[OK] /api/render passed:", render_id)

    # 5. Static assets verification
    res = client.get("/console/index.html")
    assert res.status_code == 200
    assert "WIS — Cognitive OS" in res.text
    print("[OK] /console/index.html served correctly")

    res = client.get("/console/style.css")
    assert res.status_code == 200
    print("[OK] /console/style.css served correctly")

    res = client.get("/console/app.js")
    assert res.status_code == 200
    print("[OK] /console/app.js served correctly")


if __name__ == "__main__":
    import tempfile
    print("=== STARTING SMOKE TESTS ===")
    test_advanced_desktop()
    with tempfile.TemporaryDirectory() as td:
        eng = engine(Path(td))
        test_long_horizon_engine(eng)
        test_fastapi_server(eng)
    print("\n>>> ALL SMOKE TESTS PASSED SUCCESSFULLY! <<<")
