import time
import threading
import logging
import requests
import pyaudio
import speech_recognition as sr
import keyboard
from typing import Optional

from core.event_bus import event_bus

logger = logging.getLogger("wis.core.ptt")

class PTTService:
    """Push-To-Talk global background service."""
    
    def __init__(self, host: str, port: int, token: str, hotkey: str = "f9"):
        self.host = host
        self.port = port
        self.token = token
        self.hotkey = hotkey
        
        self._recording = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._recognizer = sr.Recognizer()
        
    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="PTTService")
        self._thread.start()
        logger.info(f"PTT Service started. Hold '{self.hotkey}' to talk.")
        
    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            
    def _run_loop(self):
        pa = pyaudio.PyAudio()
        chunk = 1024
        format = pyaudio.paInt16
        channels = 1
        rate = 16000
        
        while not self._stop_event.is_set():
            try:
                is_pressed = keyboard.is_pressed(self.hotkey)
            except Exception as e:
                logger.error("Keyboard hook failed (requires admin?): %s", e)
                time.sleep(5)
                continue
                
            if is_pressed:
                if not self._recording:
                    self._recording = True
                    event_bus.emit("ptt.started", {})
                    
                    frames = []
                    stream = None
                    try:
                        stream = pa.open(format=format, channels=channels, rate=rate, input=True, frames_per_buffer=chunk)
                        while keyboard.is_pressed(self.hotkey) and not self._stop_event.is_set():
                            data = stream.read(chunk, exception_on_overflow=False)
                            frames.append(data)
                    except Exception as exc:
                        logger.error("Audio recording error: %s", exc)
                        # Evitar spam de logs si falla mientras se mantiene presionada la tecla
                        while keyboard.is_pressed(self.hotkey) and not self._stop_event.is_set():
                            time.sleep(0.1)
                    finally:
                        if stream:
                            stream.stop_stream()
                            stream.close()
                    
                    self._recording = False
                    event_bus.emit("ptt.stopped", {})
                    
                    if frames:
                        # Process audio in a separate thread to immediately free the PTT loop
                        raw_data = b"".join(frames)
                        sample_width = pa.get_sample_size(format)
                        threading.Thread(target=self._process_audio, args=(raw_data, rate, sample_width), daemon=True).start()
            else:
                time.sleep(0.05)
                
        pa.terminate()

    def _process_audio(self, raw_data: bytes, rate: int, width: int):
        audio_data = sr.AudioData(raw_data, rate, width)
        try:
            logger.info("PTT: Transcribing audio...")
            text = self._recognizer.recognize_google(audio_data, language="es-ES")
            logger.info(f"PTT Recognized: {text}")
            
            if text.strip():
                url = f"http://{self.host}:{self.port}/api/chat"
                headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
                try:
                    requests.post(url, json={"message": text}, headers=headers, timeout=60.0)
                except Exception as e:
                    logger.error("Failed to POST PTT message: %s", e)
                    
        except sr.UnknownValueError:
            logger.debug("PTT: Could not understand audio")
        except sr.RequestError as e:
            logger.error("PTT: STT service error: %s", e)
        except Exception as e:
            logger.exception("PTT: Unexpected error: %s", e)
