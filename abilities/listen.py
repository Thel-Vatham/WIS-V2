"""WIS Listen Ability - Speech-to-Text (STT) and microphone listening capability.

Permite al agente escuchar el microfono local del robot o procesar audio entrante.
Soporta speech_recognition / PyAudio si esta instalado, con fallback seguro.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from abilities.base import Ability

logger = logging.getLogger("wis.abilities.listen")

try:
    import speech_recognition as sr
    _SR_AVAILABLE = True
except ImportError:
    sr = None
    _SR_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    _WHISPER_AVAILABLE = True
except ImportError:
    _WHISPER_AVAILABLE = False


class ListenAbility(Ability):
    """Habilidad de escucha y reconocimiento de voz (STT)."""

    def __init__(self, language: str = "es-ES") -> None:
        self._language = language
        self._recognizer: Optional[Any] = None
        self._whisper_model: Optional[Any] = None
        if _SR_AVAILABLE:
            try:
                self._recognizer = sr.Recognizer()
            except Exception as exc:
                logger.warning("ListenAbility: could not initialize speech_recognition: %s", exc)

    @property
    def name(self) -> str:
        return "listen"

    @property
    def description(self) -> str:
        return "Listens to the microphone and transcribes user speech into text (STT in Spanish and other languages)."

    @property
    def domain(self) -> str:
        return "voice"

    async def execute(self, action: str, params: dict) -> dict:
        action = (action or "").lower().strip()

        if action in ("listen", "listen_once", "escuchar"):
            return self._listen_once(params)

        if action == "status":
            return {
                "success": True,
                "data": {
                    "available": _SR_AVAILABLE and self._recognizer is not None,
                    "engine": "speech_recognition (google + faster_whisper)" if _SR_AVAILABLE else "web_speech_fallback",
                    "whisper_available": _WHISPER_AVAILABLE,
                    "language": self._language,
                },
                "message": "Listen ability is operational.",
            }

        return {
            "success": False,
            "data": None,
            "message": f"Unrecognized listen action: '{action}'.",
        }

    def _transcribe_with_whisper(self, audio_data: Any, lang: str = "es") -> str:
        import io
        if not _WHISPER_AVAILABLE:
            return ""
        try:
            if self._whisper_model is None:
                logger.info("Loading faster-whisper tiny/base model for offline fallback...")
                self._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            wav_bytes = io.BytesIO(audio_data.get_wav_data())
            short_lang = lang.split("-")[0].lower() if "-" in lang else lang[:2].lower()
            segments, _ = self._whisper_model.transcribe(wav_bytes, language=short_lang)
            text = " ".join([seg.text.strip() for seg in segments if seg.text.strip()])
            return text.strip()
        except Exception as exc:
            logger.warning("ListenAbility: Whisper fallback failed: %s", exc)
            return ""

    def _listen_once(self, params: dict) -> dict:
        lang = str(params.get("language") or self._language)
        timeout = float(params.get("timeout", 5.0))

        if not _SR_AVAILABLE or self._recognizer is None:
            return {
                "success": False,
                "data": None,
                "message": "Microphone listening requires speech_recognition and pyaudio packages. Use Web Console audio input.",
            }

        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.4)
                logger.info("ListenAbility: Listening on microphone (timeout=%ss, lang=%s)...", timeout, lang)
                audio = self._recognizer.listen(source, timeout=timeout, phrase_time_limit=12.0)
                
                # 1. Intentar Google STT (rápido y muy preciso en español)
                text = ""
                try:
                    text = self._recognizer.recognize_google(audio, language=lang)
                except Exception as g_exc:
                    logger.info("ListenAbility: Google STT missed or offline (%s), trying Whisper fallback...", g_exc)
                    if _WHISPER_AVAILABLE:
                        text = self._transcribe_with_whisper(audio, lang=lang)

                if text:
                    return {
                        "success": True,
                        "data": {"text": text, "language": lang},
                        "message": f"Transcribed speech: '{text}'",
                    }
                else:
                    return {
                        "success": False,
                        "data": {"text": "", "language": lang},
                        "message": "No speech detected in audio.",
                    }
        except Exception as exc:
            logger.warning("ListenAbility: Speech recognition failed or timed out: %s", exc)
            return {
                "success": False,
                "data": None,
                "message": f"Could not recognize speech: {exc}",
            }

    def get_schema(self) -> list:
        return [
            {
                "action": "listen_once",
                "description": "Listens on the physical microphone for speech and transcribes it to text.",
                "params": {
                    "language": "str (e.g. 'es-ES' or 'en-US', default 'es-ES')",
                    "timeout": "float (seconds)",
                },
            },
            {
                "action": "status",
                "description": "Checks the status of the speech recognition engine.",
                "params": {},
            },
        ]
