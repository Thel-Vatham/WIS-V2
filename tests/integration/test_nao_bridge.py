# -*- coding: utf-8 -*-
"""Regression tests for the NAO bridge (offline: no robot, no Python 2.7 needed).

These lock in three real defects that were found and fixed:

D6-a  Method shadowing.
      `self.leds = ALProxy("ALLeds", ...)` and `self.posture = ALProxy(...)`
      shadowed the `leds()` / `posture()` methods of the same class, so
      `nao.leds(...)` raised "object is not callable". The proxies are now
      `leds_svc` / `posture_svc`.

D6-b  unicode rejected by the pynaoqi SWIG layer.
      Running against the real robot, speak/posture/set_language failed with:
          ALTextToSpeech::say
          Call argument number 0 conversion failure from Void to String.
      `json.loads()` always yields `unicode` in Python 2 and the naoqi typemaps
      reject it; text arguments must be re-encoded to utf-8 native `str`.

D6-c  Non-serializable parameters aborted whole commands.
      WIS injects internal params (events, sessions); `json.dumps` raised
      "Object of type Event is not JSON serializable" and `_send` returned
      `write_failed: ...` without ever reaching the robot.

The bridge is exercised as a real subprocess with a stub `naoqi` module on
PYTHONPATH, so the JSON protocol itself is covered too.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NAO_DIR = REPO_ROOT / "projects" / "nao"
BRIDGE = NAO_DIR / "nao_bridge.py"
STUB = NAO_DIR / "_stub_naoqi"
OFFLINE_TEST = NAO_DIR / "_offline_test.py"
AUDIT_SCRIPT = NAO_DIR / "_audit_shadowing.py"
PY27 = Path(r"C:\Python27\python.exe")

pytestmark = pytest.mark.skipif(
    not BRIDGE.is_file(), reason="NAO bridge not present in this checkout"
)


def _run(args, env_extra=None, timeout=180):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        args,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# --------------------------------------------------------------------------- #
#  D6-a: shadowing
# --------------------------------------------------------------------------- #
def test_no_method_shadowing_in_bridge():
    """Instance attributes must not shadow class methods (D6-a)."""
    assert AUDIT_SCRIPT.is_file(), "audit script missing"

    source = BRIDGE.read_text(encoding="utf-8")
    assert "self.leds_svc" in source, "leds proxy must be named leds_svc"
    assert "self.posture_svc" in source, "posture proxy must be named posture_svc"
    # The shadowing assignments must be gone.
    assert "self.leds = None" not in source
    assert "self.posture = None" not in source

    proc = _run([sys.executable, str(AUDIT_SCRIPT)])
    assert proc.returncode == 0, (
        "shadowing audit failed:\n%s\n%s" % (proc.stdout, proc.stderr)
    )
    assert "sin shadowing" in proc.stdout


def test_bridge_exposes_leds_and_posture_methods():
    """Static check: the dispatch targets must be class methods, not proxies."""
    import ast

    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"), str(BRIDGE))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "NAO":
            methods = {
                n.name for n in node.body if isinstance(n, ast.FunctionDef)
            }
            assert "leds" in methods
            assert "posture" in methods
            return
    pytest.fail("class NAO not found in bridge")


# --------------------------------------------------------------------------- #
#  D6-b: unicode -> native str (root cause of the live failures)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not PY27.is_file(), reason="Python 2.7 not installed")
def test_text_coerces_unicode_to_native_str_under_py2():
    """Under Python 2, _text(unicode) must return a byte `str` (D6-b)."""
    snippet = (
        "import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); "
        "import nao_bridge as b; "
        "u = u'ni\\u00f1os y ni\\u00f1as'; "
        "r = b._text(u); "
        "assert isinstance(r, str) and not isinstance(r, unicode), "
        "'expected byte str, got %%r' %% type(r); "
        "assert r == u.encode('utf-8'), 'utf-8 mismatch'; "
        "assert b._text(None) == ''; "
        "assert b._text(u'Stand') == 'Stand'; "
        "print('OK')"
    ) % (str(STUB), str(NAO_DIR))

    proc = _run([str(PY27), "-c", snippet])
    assert proc.returncode == 0, (
        "unicode coercion failed under py2:\n%s\n%s" % (proc.stdout, proc.stderr)
    )
    assert "OK" in proc.stdout


def test_bridge_source_guards_text_arguments():
    """All text arguments reaching an ALProxy must go through _text()."""
    source = BRIDGE.read_text(encoding="utf-8")
    for expected in (
        "self.tts.say(_text(text))",
        "self.tts.setLanguage(_text(language",
        "self.posture_svc.goToPosture(name, 0.6)",
        "self.motion.setAngles(_text_list(names)",
        "self.behavior.runBehavior(_text(name))",
        "self.memory.getData(_text(key))",
    ):
        assert expected in source, "missing text coercion: %s" % expected


# --------------------------------------------------------------------------- #
#  Schema drift: every bridge action must be announced to the LLM
# --------------------------------------------------------------------------- #
def _bridge_dispatch_actions():
    """Extract the action names handled by the bridge's dispatch loop."""
    import ast

    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"), str(BRIDGE))
    actions = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        if not (isinstance(left, ast.Name) and left.id == "action"):
            continue
        if not isinstance(node.ops[0], ast.Eq):
            continue
        comp = node.comparators[0]
        if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
            actions.add(comp.value)
    return actions


def test_every_bridge_action_is_declared_in_schema():
    """Actions the bridge implements must be visible to the agent.

    A command the LLM cannot see in the tool schema is a command the agent
    never calls, which shows up as "WIS is not executing the actions".
    """
    from abilities.nao_robot import NAORobotAbility

    implemented = _bridge_dispatch_actions()
    assert implemented, "could not extract any action from the bridge"

    declared = {entry["action"] for entry in NAORobotAbility().get_schema()}

    # `quit` is a transport-level command, and `connect` is handled inside the
    # ability (it restarts the bridge) rather than by the bridge dispatch.
    implemented -= {"quit"}

    missing = sorted(implemented - declared)
    assert not missing, (
        "bridge implements actions that are NOT declared in get_schema(), "
        "so the agent cannot call them: %s" % missing
    )


def test_schema_has_no_phantom_actions():
    """Declared actions must actually be routed somewhere (bridge or ability)."""
    from abilities.nao_robot import NAORobotAbility

    # `connect` and `status` are answered by the ability itself, without a
    # round-trip to the bridge (see NAORobotAbility.execute).
    handled_in_process = {"connect", "status"}
    implemented = _bridge_dispatch_actions() | handled_in_process
    declared = {entry["action"] for entry in NAORobotAbility().get_schema()}

    phantom = sorted(declared - implemented)
    assert not phantom, (
        "get_schema() advertises actions nobody handles: %s" % phantom
    )


# --------------------------------------------------------------------------- #
#  D6-c: parameter sanitization in the ability
# --------------------------------------------------------------------------- #
def test_jsonable_sanitizes_unserializable_params():
    """_jsonable must degrade odd values instead of raising (D6-c)."""
    from abilities.nao_robot import _jsonable

    class Event(object):
        def __repr__(self):
            return "<Event object at 0x0>"

    payload = {
        "text": "hola",
        "event": Event(),
        "nested": {"evt": Event(), "n": 3},
        "items": [1, Event()],
        "none": None,
        "flag": True,
    }
    clean = _jsonable(payload)
    # Must be serializable now, even though the raw dict was not.
    encoded = json.dumps(clean)
    assert "hola" in encoded
    assert clean["nested"]["n"] == 3
    assert clean["none"] is None
    assert clean["flag"] is True
    assert isinstance(clean["event"], str)

    # Sanity: the raw payload really would have exploded.
    with pytest.raises(TypeError):
        json.dumps(payload)


# --------------------------------------------------------------------------- #
#  Protocol: end-to-end against the stub naoqi
# --------------------------------------------------------------------------- #
def test_offline_protocol_suite_passes_under_current_interpreter():
    """Run the full offline bridge protocol test (py3 side)."""
    assert OFFLINE_TEST.is_file(), "offline test missing"
    proc = _run([sys.executable, str(OFFLINE_TEST)], timeout=240)
    assert proc.returncode == 0, (
        "offline bridge test failed:\n%s\n%s" % (proc.stdout, proc.stderr)
    )
    assert "passed" in proc.stdout


@pytest.mark.skipif(not PY27.is_file(), reason="Python 2.7 not installed")
def test_offline_protocol_suite_passes_under_py2():
    """Run the same offline suite with the interpreter the robot actually uses."""
    proc = _run([str(PY27), str(OFFLINE_TEST)], timeout=240)
    assert proc.returncode == 0, (
        "offline bridge test failed under py2:\n%s\n%s" % (proc.stdout, proc.stderr)
    )
    assert "passed" in proc.stdout


# --------------------------------------------------------------------------- #
#  Full WIS path: ability -> _send (jsonable) -> bridge subprocess
# --------------------------------------------------------------------------- #
def test_ability_end_to_end_against_stub_bridge(monkeypatch):
    """Drive NAORobotAbility exactly like WIS does, but with the stub naoqi.

    This covers the whole chain the user exercises from the console:
        pipeline -> nao_robot.execute() -> _send() -> bridge -> JSON reply
    """
    import asyncio

    import abilities.nao_robot as nao_robot

    # Route the ability at the stub instead of the py2 SDK.
    monkeypatch.setattr(nao_robot, "PY27", sys.executable)

    def fake_env(_self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(STUB)
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    monkeypatch.setattr(nao_robot.NAORobotAbility, "_env", fake_env)

    ability = nao_robot.NAORobotAbility()

    async def scenario():
        out = {}
        # connect is handled in-process: it (re)starts the bridge.
        out["connect"] = await ability.execute("connect", {"ip": "127.0.0.1"})
        # A non-serializable param used to abort the command with write_failed.
        out["speak"] = await ability.execute(
            "speak",
            {"text": "hola", "_cancel_event": object(), "_session_id": "default"},
        )
        out["battery"] = await ability.execute("battery", {})
        out["leds"] = await ability.execute(
            "leds", {"color": "#12AB34", "led": "FaceLeds"}
        )
        out["posture"] = await ability.execute("posture", {"name": "Stand"})
        out["status"] = await ability.execute("status", {})
        return out

    try:
        result = asyncio.run(scenario())
    finally:
        ability._stop_bridge()

    assert result["connect"]["success"] is True, result["connect"]

    assert result["speak"]["success"] is True, result["speak"]
    assert result["speak"]["said"] == "hola"

    assert result["battery"]["success"] is True, result["battery"]
    assert result["battery"]["percent"] == 87

    assert result["leds"]["success"] is True, result["leds"]
    assert result["leds"]["color"] == 0x12AB34, result["leds"]

    assert result["posture"]["success"] is True, result["posture"]
    assert result["posture"]["posture"] == "Stand"

    assert result["status"]["success"] is True

    # No error path may have produced a serialization/write failure.
    for key, rep in result.items():
        assert "write_failed" not in str(rep.get("error", "")), (key, rep)
        assert "encode_failed" not in str(rep.get("error", "")), (key, rep)
