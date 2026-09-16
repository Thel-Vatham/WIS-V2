"""Smoke tests for the current WIS console and ability stack."""
from pathlib import Path
import sys

# Ensure ROOT_DIR in sys.path
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from abilities.pc.advanced_desktop_ability import AdvancedDesktopAbility
from console.server import create_app, WISCoreContainer
import pytest
from fastapi.testclient import TestClient


def test_advanced_desktop():
    ada = AdvancedDesktopAbility()
    assert ada.name in ("desktop", "advanced_desktop")
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


def test_fastapi_server():
    container = WISCoreContainer()
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

    # 3. Session API
    headers = {"Authorization": "Bearer test-secret-token"}
    res = client.get("/api/sessions", headers=headers)
    assert res.status_code == 200
    assert "sessions" in res.json()
    print("[OK] GET /api/sessions passed")

    res = client.get("/api/projects", headers=headers)
    assert res.status_code == 200
    assert "projects" in res.json()
    assert all("session_id" in project for project in res.json()["projects"])
    print("[OK] GET /api/projects passed")

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

    # 4b. A session can open many render windows
    first = client.post(
        "/api/render",
        headers=headers,
        json={"html": "<p>one</p>", "title": "A", "session_id": "main"},
    ).json()
    second = client.post(
        "/api/render",
        headers=headers,
        json={"html": "<p>two</p>", "title": "B", "session_id": "main"},
    ).json()
    assert first["render_id"] != second["render_id"]
    assert first["session_id"] == "main"
    assert client.get(f"/api/render/{second['render_id']}").text == "<p>two</p>"
    print("[OK] multiple render windows per session passed")

    # 4c. Reusing a render_id updates that window instead of creating another
    updated = client.post(
        "/api/render",
        headers=headers,
        json={"html": "<p>updated</p>", "title": "A2", "render_id": first["render_id"]},
    ).json()
    assert updated["render_id"] == first["render_id"]
    assert client.get(f"/api/render/{first['render_id']}").text == "<p>updated</p>"
    closed = client.delete(f"/api/render/{first['render_id']}", headers=headers).json()
    assert closed["closed"] is True
    assert client.get(f"/api/render/{first['render_id']}").status_code == 404
    print("[OK] idempotent render_id passed")

    # 5. Static assets verification
    res = client.get("/console/index.html")
    assert res.status_code == 200
    assert "WIS" in res.text
    print("[OK] /console/index.html served correctly")

    res = client.get("/console/style.css")
    assert res.status_code == 200
    print("[OK] /console/style.css served correctly")

    res = client.get("/console/app.js")
    assert res.status_code == 200
    print("[OK] /console/app.js served correctly")


if __name__ == "__main__":
    print("=== STARTING SMOKE TESTS ===")
    test_advanced_desktop()
    test_fastapi_server()
    print("\n>>> ALL SMOKE TESTS PASSED SUCCESSFULLY! <<<")
