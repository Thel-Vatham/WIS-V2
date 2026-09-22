"""
Autonomous Kindergarten Teacher Mode for NAO (Python 3.11)
Integrates NAO perception with WIS LLM logic to act autonomously.
"""
import asyncio
import httpx
import logging
import json
import time

# Attempt to load LLM settings from WIS config
import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

try:
    from core.llm_client import LLMClient
except ImportError:
    LLMClient = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("autonomous_nao")

NAO_API = "http://localhost:7860/api/nao"

SYSTEM_PROMPT = """You are WIS, an AI living inside a NAO robot acting as a kindergarten teacher.
Your personality is warm, playful, and educational.
A child has just spoken to you. 
You must respond with:
1. 'speech': What you will say out loud (in Spanish). Keep it short, max 2 sentences.
2. 'gesture': A posture/gesture to adopt (StandInit, Sit, Crouch, Rest)
3. 'emotion_color': A hex color for your LED eyes (e.g., 0x00FF00 for happy green, 0x0000FF for thinking blue)
Respond ONLY in valid JSON.
Example:
{"speech": "¡Hola amiguitos! Vamos a aprender mucho hoy.", "gesture": "StandInit", "emotion_color": 0x66CCFF}
"""

async def api_call(action: str, params: dict = None):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{NAO_API}/{action}", json=params or {})
            return res.json()
    except Exception as e:
        logger.error(f"API Error ({action}): {e}")
        return {"success": False}

async def get_wis_response(text: str) -> dict:
    if not LLMClient:
        return {
            "speech": f"Escuché que dijiste {text}, pero mi cerebro WIS no está conectado.",
            "gesture": "StandInit",
            "emotion_color": 0xFF0000
        }
        
    try:
        # Load settings
        settings_path = ROOT_DIR / "config" / "settings.json"
        with open(settings_path, 'r') as f:
            settings = json.load(f)
        
        llm_cfg = settings.get("llm", {})
        api_key = llm_cfg.get("api_key", "")
        if not api_key:
            import os
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            
        llm = LLMClient(
            base_url=llm_cfg.get("base_url", "https://api.deepseek.com"),
            api_key=api_key,
            model=llm_cfg.get("model", "deepseek-chat")
        )
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ]
        
        logger.info(f"Thinking about: {text}")
        response = await llm.complete(messages, temperature=0.7)
        # Parse JSON
        resp_json = response.strip()
        if resp_json.startswith("```json"):
            resp_json = resp_json.split("```json")[1].split("```")[0].strip()
        
        data = json.loads(resp_json)
        return {
            "speech": data.get("speech", "No sé qué decir."),
            "gesture": data.get("gesture", "StandInit"),
            "emotion_color": data.get("emotion_color", 0xFFFFFF)
        }
    except Exception as e:
        logger.error(f"LLM Error: {e}")
        return {
            "speech": "Oh no, mi cerebro está confundido.",
            "gesture": "StandInit",
            "emotion_color": 0xFF0000
        }

async def autonomous_loop():
    logger.info("Starting Autonomous Kindergarten Teacher Loop...")
    
    # Initialize
    await api_call("leds", {"color": 0x66CCFF})
    await api_call("posture", {"name": "StandInit"})
    await api_call("animated_say", {"text": "¡Modo maestro de jardín activado! Estoy listo.", "language": "Spanish"})
    
    idle_time = 0
    
    try:
        while True:
            # 1. Listen for voices/keywords
            logger.info("Listening...")
            await api_call("leds", {"color": 0x00FF00}) # Green = listening
            
            listen_res = await api_call("listen", {"timeout": 5.0, "language": "Spanish"})
            heard_text = listen_res.get("text", "") if listen_res else ""
            
            if heard_text:
                idle_time = 0
                logger.info(f"Heard: {heard_text}")
                await api_call("leds", {"color": 0x0000FF}) # Blue = thinking
                
                # 2. Reason with WIS LLM
                plan = await get_wis_response(heard_text)
                logger.info(f"WIS Plan: {plan}")
                
                # 3. Act
                await api_call("leds", {"color": plan["emotion_color"]})
                await api_call("posture", {"name": plan["gesture"]})
                await api_call("animated_say", {"text": plan["speech"], "language": "Spanish"})
                
            else:
                idle_time += 1
                logger.debug("No speech detected.")
                await api_call("leds", {"color": 0x444444}) # Dim white = idle
                
                # Autonomous Idle Behaviors
                if idle_time == 6:  # roughly 30 seconds idle
                    logger.info("Idle behavior triggered.")
                    await api_call("animated_say", {"text": "¿Hay alguien ahí? Tengo ganas de jugar.", "language": "Spanish"})
                elif idle_time > 12:
                    logger.info("Going to sleep due to inactivity.")
                    await api_call("animated_say", {"text": "Voy a descansar un ratito. Avísenme si me necesitan.", "language": "Spanish"})
                    await api_call("posture", {"name": "Crouch"})
                    await api_call("set_stiffness", {"name": "Body", "stiffness": 0.0})
                    await api_call("leds_off")
                    break # Stop loop
            
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Stopping autonomous mode...")
    except Exception as e:
        logger.error(f"Loop crashed: {e}")
    finally:
        await api_call("leds_off")
        await api_call("posture", {"name": "Sit"})
        logger.info("Autonomous mode ended.")

if __name__ == "__main__":
    asyncio.run(autonomous_loop())
