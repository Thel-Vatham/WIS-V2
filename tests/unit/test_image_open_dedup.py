from unittest.mock import patch

import pytest

from abilities.system import SystemAbility


@pytest.mark.asyncio
async def test_same_image_open_is_deduplicated():
    ability = SystemAbility(mode="autonomous")
    command = 'start "" "C:\\Temp\\photo.png"'

    with patch("abilities.system.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = ""
        run.return_value.stderr = ""

        first = await ability.execute("execute_shell", {"command": command})
        second = await ability.execute("execute_shell", {"command": command})

    assert first["success"] is True
    assert second["success"] is True
    assert second["data"]["skipped"] is True
    assert run.call_count == 1