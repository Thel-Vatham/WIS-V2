"""
Autonomous Kindergarten Teacher Mode for NAO (Python 3.11)
Integrates NAO perception, host & robot audio listening, with WIS LLM logic to act autonomously.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

try:
    from core.llm_client import LLMClient
except ImportError:
    LLMClient = None

try:
    from abilities.listen import ListenAbility
except ImportError:
    ListenAbility = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("autonomous_nao")

NAO_API = "http://localhost:7860/api/nao"

SYSTEM_PROMPT = """You are WIS, an AI living inside a NAO robot acting as a kindergarten teacher.
Your personality is warm, playful, and educational.
A child or teacher has just spoken to you.
You must respond with:
1. 'speech': What you will say out loud (in Spanish). Keep it friendly, clear, max 2 short sentences.
2. 'gesture': A posture/gesture to adopt (StandInit, Sit, Crouch, Rest)
3. 'emotion_color': A hex color for your LED eyes (e.g. 0x00FF00 for happy green, 0x66CCFF for calm blue, 0xFFAA00 for warm yellow)
Respond ONLY in valid JSON.
Example:
{"speech": "¡Hola amiguitos! Bienvenidos a nuestra clase de hoy. ¿A qué les gustaría jugar?", "gesture": "StandInit", "emotion_color": 0x66CCFF}
"""

# Global listen ability instance for PC microphone
_pc_listener: Optional[ListenAbility] = None

def get_pc_listener(lang: str = "es-ES") -> Optional[ListenAbility]:
    global _pc_listener
    if _pc_listener is None and ListenAbility is not None:
        try:
            _pc_listener = ListenAbility(language=lang)
        except Exception as e:
            logger.warning(f"Could not initialize ListenAbility: {e}")
    return _pc_listener


async def api_call(action: str, params: dict = None, api_base: str = NAO_API) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{api_base}/{action}", json=params or {})
            if res.status_code == 200:
                return res.json()
            return {"success": False, "status_code": res.status_code}
    except Exception as e:
        logger.debug(f"NAO API ({action}) unavailable: {e}")
        return {"success": False, "error": str(e)}


async def listen_for_speech(mic_mode: str = "pc", timeout: float = 5.0, language: str = "es-ES", api_base: str = NAO_API) -> str:
    """Escucha la voz del usuario/niño mediante la fuente de audio seleccionada.
    
    mic_mode:
      - 'pc': Micrófono del ordenador con reconocimiento continuo en español (Google STT / Faster-Whisper).
      - 'nao': Micrófono integrado en la cabeza del robot NAO (vía API / ALSpeechRecognition).
      - 'both' o 'auto': Intenta primero el micrófono del PC; si no detecta nada, consulta el de NAO.
      - 'cli': Entrada manual por teclado (ideal para pruebas silenciosas o de desarrollo).
    """
    heard = ""

    # Modo 1: CLI (teclado)
    if mic_mode == "cli":
        print("\n" + "=" * 50)
        print("[MIC-CLI] Escribe lo que dice el nino/usuario (o Enter para silencio):")
        try:
            user_text = await asyncio.to_thread(input, "[NINO]: ")
            return user_text.strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    # Modo 2: Microfono del PC (alta precision en espanol)
    if mic_mode in ("pc", "both", "auto"):
        listener = get_pc_listener(language)
        if listener:
            logger.info("[MIC-PC] Escuchando por microfono local del PC (%.1fs en %s)... Habla ahora!", timeout, language)
            try:
                res = await asyncio.to_thread(listener._listen_once, {"timeout": timeout, "language": language})
                if res.get("success") and res.get("data", {}).get("text"):
                    heard = res["data"]["text"].strip()
                    logger.info("[OK] Transcrito desde microfono PC: '%s'", heard)
                    return heard
            except Exception as exc:
                logger.warning(f"Fallo en escucha de microfono PC: {exc}")

    # Modo 3: Microfono integrado de NAO (cabeza del robot)
    if (mic_mode in ("nao", "both", "auto")) and not heard:
        logger.info("[NAO-MIC] Escuchando por los microfonos de NAO (%.1fs)...", timeout)
        nao_lang = "Spanish" if "es" in language.lower() else "English"
        res = await api_call("listen", {"timeout": timeout, "language": nao_lang}, api_base=api_base)
        if res.get("success") and res.get("text"):
            heard = res["text"].strip()
            logger.info("[OK] Reconocido desde microfonos de NAO: '%s'", heard)
            return heard

    return heard


async def get_wis_response(text: str) -> dict:
    """Envia el texto capturado al cerebro LLM de WIS y obtiene la respuesta estructurada."""
    if not LLMClient:
        return {
            "speech": f"Hola! Escuche que dijiste: {text}. Que interesante!",
            "gesture": "StandInit",
            "emotion_color": 0x66CCFF
        }
        
    try:
        settings_path = ROOT_DIR / "config" / "settings.json"
        settings = {}
        if settings_path.exists():
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        
        llm_cfg = settings.get("llm", {})
        api_key = llm_cfg.get("api_key", "")
        if not api_key:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
            
        base_url = llm_cfg.get("base_url", "https://api.deepseek.com")
        model = llm_cfg.get("model", "deepseek-chat")

        llm = LLMClient(
            base_url=base_url,
            api_key=api_key,
            model=model
        )
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ]
        
        logger.info(f"[THINK] WIS razonando sobre: '{text}'...")
        chat_res = await llm.chat(messages, temperature=0.7)
        response = chat_res.get("text", "")
        resp_json = response.strip()
        if "```json" in resp_json:
            resp_json = resp_json.split("```json")[1].split("```")[0].strip()
        elif "```" in resp_json:
            resp_json = resp_json.split("```")[1].split("```")[0].strip()
        
        data = json.loads(resp_json)
        return {
            "speech": data.get("speech", "Que bien! Sigamos aprendiendo juntos."),
            "gesture": data.get("gesture", "StandInit"),
            "emotion_color": int(data.get("emotion_color", 0x66CCFF))
        }
    except Exception as e:
        logger.error(f"LLM Error ({e}). Usando respuesta pedagogica de respaldo.")
        return {
            "speech": f"Que lindo lo que dijiste! Vamos a jugar y aprender mucho.",
            "gesture": "StandInit",
            "emotion_color": 0x66CCFF
        }


async def autonomous_loop(mic_mode: str = "pc", timeout: float = 5.0, language: str = "es-ES", api_base: str = NAO_API):
    print("\n" + "=" * 60)
    print("[WIS] Autonomous Kindergarten Teacher")
    print(f"[AUDIO] Fuente: {mic_mode.upper()} | Idioma: {language} | Timeout: {timeout}s")
    print("=" * 60 + "\n")
    
    # Inicializacion del robot (si esta conectado)
    await api_call("leds", {"color": 0x66CCFF}, api_base=api_base)
    await api_call("posture", {"name": "StandInit"}, api_base=api_base)
    await api_call("animated_say", {"text": "Modo maestro de jardin activado! Estoy listo para escuchar.", "language": "Spanish"}, api_base=api_base)
    
    idle_time = 0
    
    try:
        while True:
            # 1. Escuchar activamente
            logger.info("[LISTEN] Escuchando a los ninos...")
            await api_call("leds", {"color": 0x00FF00}, api_base=api_base) # Verde = escuchando
            
            heard_text = await listen_for_speech(mic_mode=mic_mode, timeout=timeout, language=language, api_base=api_base)
            
            if heard_text:
                idle_time = 0
                logger.info(f"[VOZ] Nino dijo: '{heard_text}'")
                await api_call("leds", {"color": 0x0000FF}, api_base=api_base) # Azul = pensando
                
                # 2. Razonar con WIS LLM
                plan = await get_wis_response(heard_text)
                logger.info(f"[PLAN] {plan}")
                
                # 3. Responder con voz y gestos
                await api_call("leds", {"color": plan["emotion_color"]}, api_base=api_base)
                await api_call("posture", {"name": plan["gesture"]}, api_base=api_base)
                say_res = await api_call("animated_say", {"text": plan["speech"], "language": "Spanish"}, api_base=api_base)
                if not say_res.get("success"):
                    print(f"\n[WIS Maestro dice]: \"{plan['speech']}\"\n")
                
            else:
                idle_time += 1
                logger.debug("No se detecto voz en este intervalo.")
                await api_call("leds", {"color": 0x444444}, api_base=api_base) # Blanco tenue = idle
                
                # Comportamiento autonomo si no hay actividad
                if idle_time == 6:  # ~30s sin voz
                    logger.info("Comportamiento de invitacion al juego activado...")
                    msg = "Hay alguien por ahi? Tengo muchas ganas de cantar o jugar."
                    await api_call("animated_say", {"text": msg, "language": "Spanish"}, api_base=api_base)
                    print(f"\n[WIS Autonomo]: \"{msg}\"\n")
                elif idle_time > 12:
                    logger.info("Descanso por inactividad prolongada...")
                    msg = "Voy a descansar un ratito. Llamame cuando quieras jugar."
                    await api_call("animated_say", {"text": msg, "language": "Spanish"}, api_base=api_base)
                    await api_call("posture", {"name": "Crouch"}, api_base=api_base)
                    await api_call("set_stiffness", {"name": "Body", "stiffness": 0.0}, api_base=api_base)
                    await api_call("leds_off", api_base=api_base)
                    break
            
            await asyncio.sleep(0.5)
            
    except KeyboardInterrupt:
        logger.info("Deteniendo modo maestro de jardin...")
    except Exception as e:
        logger.error(f"Error en el bucle autonomo: {e}", exc_info=True)
    finally:
        await api_call("leds_off", api_base=api_base)
        await api_call("posture", {"name": "Sit"}, api_base=api_base)
        logger.info("Modo autonomo finalizado con exito.")


def main():
    parser = argparse.ArgumentParser(description="WIS Autonomous Kindergarten Teacher for NAO")
    parser.add_argument(
        "--mic",
        choices=["pc", "nao", "both", "cli"],
        default="pc",
        help="Fuente del micrófono: 'pc' (micrófono del PC con STT en español, recomendado), 'nao' (micrófono del robot), 'both' (ambos), o 'cli' (teclado)"
    )
    parser.add_argument("--timeout", type=float, default=5.0, help="Tiempo de escucha por turno en segundos (default: 5.0)")
    parser.add_argument("--lang", default="es-ES", help="Código de idioma de reconocimiento (default: es-ES)")
    parser.add_argument("--api", default=NAO_API, help=f"URL base de la API de NAO (default: {NAO_API})")
    args = parser.parse_args()

    asyncio.run(autonomous_loop(mic_mode=args.mic, timeout=args.timeout, language=args.lang, api_base=args.api))


if __name__ == "__main__":
    main()
