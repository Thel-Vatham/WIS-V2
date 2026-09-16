"""
WIS Worker Process — Isolated Execution Engine for true parallelism.
=====================================================================
Spawns an isolated `ActionPipeline` in a completely separate OS process.
All logs from this process are written to a dedicated log file to prevent
console overlapping. Result is written to an output JSON file.
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Fix path to allow importing core modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pipeline import ActionPipeline
from core.reasoning import ReasoningEngine
from core.skill_memory import SkillMemory
from abilities.registry import AbilityRegistry
from core.task_store import TaskStore


def setup_isolated_logging(log_file: str):
    """Redirige todo el logging a un archivo exclusivo para no estorbar en consola."""
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    # File handler
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Redirect stdout/stderr strictly to file to avoid console interleaving
    sys.stdout = open(log_file, "a", encoding="utf-8")
    sys.stderr = open(log_file, "a", encoding="utf-8")


async def main():
    parser = argparse.ArgumentParser(description="WIS Isolated Worker")
    parser.add_argument("--task-id", required=True, help="ID of the task")
    parser.add_argument("--text", required=True, help="Instruction text to execute")
    parser.add_argument("--log", required=True, help="Path to write the isolated logs")
    parser.add_argument("--session-id", default="default", help="Cognitive session owning the task")
    
    args = parser.parse_args()
    
    # 1. Setup isolated logging
    setup_isolated_logging(args.log)
    logging.info(f"=== Worker started for task {args.task_id} ===")
    logging.info(f"Task: {args.text}")
    
    # 2. Initialize Core Dependencies
    logging.info("Initializing dependencies...")
    
    from core.memory import Memory
    from core.identity import Identity
    from core.llm_client import LLMClient
    from core.task_store import TaskStore
    
    db_path = Path(os.getcwd()) / "Data" / "wis_tasks.db"
    identity_path = Path(os.getcwd()) / "config" / "identity.md"
    
    # Check for env vars
    base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "deepseek-chat")
    
    nexus = LLMClient(base_url=base_url, api_key=api_key, model=model)
    persona = Identity(identity_path=identity_path)
    
    # Actually use memory db path for Memory, but task store has its own path now
    memory_db = Path(os.getcwd()) / "Data" / "wis_memory.db"
    mnemonic = Memory(db_path=memory_db)
    
    reasoning = ReasoningEngine(llm_client=nexus, identity=persona, memory=mnemonic)
    
    from core.skill_memory import SkillMemory
    task_store = TaskStore(db_path=db_path)
    skill_memory = SkillMemory(db_path=memory_db)

    from core.hardware_memory import HardwareMemory
    from core.safety import SafetyPolicy
    
    hw_vault = HardwareMemory(db_path=memory_db)
    aegis = SafetyPolicy(mode="secure")

    logging.info("Loading AbilityRegistry (including DevAgent, PC Agent, etc.)...")
    # Actually, we can use the helper from main.py if we want all the config loaded
    import main
    registry = AbilityRegistry()
    main._register_default_abilities(registry, {}, hw_vault)
    
    logging.info("Initializing ActionPipeline...")
    pipeline = ActionPipeline(
        reasoning=reasoning,
        skill_memory=skill_memory,
        abilities=registry,
        safety=aegis,
        hardware_memory=hw_vault,
        max_steps=200
    )
    
    # 3. Execute
    logging.info("Starting pipeline processing...")
    try:
        result = await pipeline.process(args.text, session_id=args.session_id)
        logging.info("Pipeline completed successfully.")
        
        response_text = result.get("response", "")
        if not response_text and result.get("results"):
            first_result = result["results"][0]
            response_text = str(first_result.get("output", ""))[:500]
            
        task_store.update_task(
            args.task_id,
            status="done" if result.get("success", False) else "failed",
            result=response_text or "Completado",
            error=result.get("error") if not result.get("success", False) else None
        )
    except Exception as e:
        logging.exception("Pipeline crashed.")
        task_store.update_task(
            args.task_id,
            status="failed",
            error=str(e)
        )
        
    logging.info("=== Worker finished ===")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
