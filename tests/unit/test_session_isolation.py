from pathlib import Path

from core.memory import Memory, _is_contaminating_turn
from core.task_store import TaskStore


def test_memory_session_rename_survives_reload(tmp_path: Path):
    db_path = tmp_path / "memory.db"
    memory = Memory(db_path=db_path)
    memory.remember("mensaje privado", "respuesta privada", session_id="main")
    memory.rename_session("main", "paper")
    memory.close()

    restored = Memory(db_path=db_path)
    assert restored.get_history("main") == []
    assert restored.get_history("paper") == [
        {"role": "user", "content": "mensaje privado"},
        {"role": "assistant", "content": "respuesta privada"},
    ]
    restored.close()


def test_task_store_tracks_session_and_process_metadata(tmp_path: Path):
    store = TaskStore(db_path=tmp_path / "tasks.db")
    task = store.create_task("trabajo aislado", session_id="paper")
    store.update_task(task["id"], pid=1234, attempts=1)

    saved = store.get_task(task["id"])
    assert saved["session_id"] == "paper"
    assert saved["pid"] == 1234
    assert saved["attempts"] == 1
    store.close()


def test_default_session_persists_across_reload(tmp_path: Path):
    """La consola principal ('default') debe sobrevivir a un reinicio de WIS."""
    db_path = tmp_path / "memory.db"
    memory = Memory(db_path=db_path)
    memory.remember("set a countdown until 5pm", "Done.", session_id="default")
    memory.close()

    restored = Memory(db_path=db_path)
    assert restored.get_history("default") == [
        {"role": "user", "content": "set a countdown until 5pm"},
        {"role": "assistant", "content": "Done."},
    ]
    restored.close()


def test_recall_is_scoped_to_session(tmp_path: Path):
    """recall() no debe filtrar memoria de una sesion a otra."""
    db_path = tmp_path / "memory.db"
    memory = Memory(db_path=db_path)
    for i in range(70):
        memory.remember(f"alpha project secret marker {i}", "ok", session_id="alpha")
    memory.remember("beta unrelated question", "ok", session_id="beta")

    assert memory.recall("alpha project secret marker", top_k=5, session_id="beta") == []

    own = memory.recall("alpha project secret marker", top_k=5, session_id="alpha")
    assert own, "recall debe alcanzar turnos antiguos de su propia sesion"
    assert all("alpha project secret marker" in item["user_input"] for item in own)
    memory.close()


def test_status_symbols_do_not_contaminate_turns():
    """Un ✅ o un ⚠ dentro de una respuesta tecnica no debe borrar el turno."""
    assert not _is_contaminating_turn(
        "can you set reminders?",
        "Done ✅\n\n⚠ Timers do not survive a reboot.",
    )


def test_emoji_dominated_turns_are_filtered():
    """Un turno dominado por emojis si debe descartarse del contexto."""
    assert _is_contaminating_turn("look at this", "🎉🎊🥳🎈🎁✨🎇🎆")


def test_pipeline_persists_every_session():
    """El pipeline ya no excluye 'main'/'default' de la memoria episodica."""
    from core.pipeline import ActionPipeline

    assert ActionPipeline._persistent_session("default") is True
    assert ActionPipeline._persistent_session("main") is True
    assert ActionPipeline._persistent_session("paper") is True
    assert ActionPipeline._persistent_session("") is False