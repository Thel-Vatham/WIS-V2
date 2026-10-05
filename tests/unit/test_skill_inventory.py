"""
Unit tests for SkillInventory ("la piel"): always-on core pillars + honest
validation against the live registry.
"""
from __future__ import annotations

from abilities.base import Ability
from core.skill_inventory import CORE_PILLARS, SkillInventory, collect_registered


class _FakeAbility(Ability):
    def __init__(self, name: str, actions: list[str]) -> None:
        self._name = name
        self._actions = actions

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "fake"

    @property
    def domain(self) -> str:
        return "test"

    def get_schema(self) -> list:
        return [{"action": a, "description": "", "params": {}} for a in self._actions]

    async def execute(self, action: str, params: dict) -> dict:
        return {"success": True}


class _FakeRegistry:
    def __init__(self, abilities: list[_FakeAbility]) -> None:
        self._abilities = {a.name: a for a in abilities}

    def all(self) -> dict[str, _FakeAbility]:
        return self._abilities


def test_pillars_are_the_three_innate_capabilities():
    assert set(CORE_PILLARS.keys()) == {"pc", "web", "code"}


def test_collect_registered_builds_skill_action_identifiers():
    reg = _FakeRegistry([
        _FakeAbility("code_tools", ["code_view_file", "code_grep"]),
        _FakeAbility("web_search", ["search"]),
    ])
    ids = set(collect_registered(reg))
    assert "code_tools.code_view_file" in ids
    assert "code_tools.code_grep" in ids
    assert "web_search.search" in ids


def test_sync_persists_pillars_and_returns_missing(temp_db_path):
    inv = SkillInventory(db_path=temp_db_path)
    missing = inv.sync(["code_tools.code_view_file"])  # far fewer than required
    # Honest validation: the 'code' pillar has unregistered tools here.
    assert missing
    assert "code" in missing
    # All three pillars persisted to SQLite.
    assert set(inv.pillars()) == {"code", "pc", "web"}
    inv.close()


def test_sync_all_registered_reports_no_missing(temp_db_path):
    inv = SkillInventory(db_path=temp_db_path)
    full: list[str] = []
    for spec in CORE_PILLARS.values():
        full.extend(spec["tools"])
    assert inv.sync(full) == {}
    inv.close()


def test_text_renders_core_capabilities_block(temp_db_path):
    inv = SkillInventory(db_path=temp_db_path)
    inv.sync([])
    text = inv.text()
    assert "CORE CAPABILITIES" in text
    for pillar in ("code", "pc", "web"):
        assert pillar in text
    inv.close()


def test_phantom_tool_is_reported_not_silently_claimed(temp_db_path):
    """Guard: a declared pillar tool missing from the registry MUST be reported."""
    inv = SkillInventory(db_path=temp_db_path)
    # Register everything EXCEPT one code tool.
    full: list[str] = []
    for spec in CORE_PILLARS.values():
        for t in spec["tools"]:
            if t != "code_tools.tdd_cycle":
                full.append(t)
    missing = inv.sync(full)
    assert "code" in missing
    assert "code_tools.tdd_cycle" in missing["code"]
    inv.close()
