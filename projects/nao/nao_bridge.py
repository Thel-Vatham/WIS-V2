# -*- coding: utf-8 -*-
"""
WIS NAO Bridge (Python 2.7)
===========================
Long-lived worker that loads the pynaoqi SDK and exposes NAO control
over a JSON-per-line stdin/stdout protocol.

Run by the Python 3.11 WIS ability `nao_robot`. Do NOT run under Python 3.
"""

from __future__ import print_function

import json
import sys
import time
import threading
import base64

try:
    from naoqi import ALProxy
except Exception as exc:  # noqa: BLE001
    print(json.dumps({"event": "error", "error": "naoqi_import_failed: %s" % exc}))
    sys.stdout.flush()
    sys.exit(1)

DEFAULT_IP = "172.20.10.9"
DEFAULT_PORT = 9559

# Vocabulario por defecto del reconocedor.
#
# IMPORTANTE: ALSpeechRecognition NO hace dictado libre, es un detector de
# palabras clave. Todo lo que no figure aqui NO se reconocera nunca. La lista
# cubre el modo profesor de jardin: saludos, cortesia, numeros, colores y
# ordenes de aula. Sin acentos a proposito: el motor normaliza el lexicon
# ("como estas" se reconoce y se devuelve como "Como estas").
ASR_VOCABULARY = [
    # Saludos y despedidas
    "hola", "buenos dias", "buenas tardes", "adios", "hasta luego", "hasta pronto", "chao",
    # Cortesia y afirmaciones
    "si", "no", "por favor", "gracias", "de nada", "perdon", "disculpa", "vale", "claro", "esta bien",
    # Conversacion e identidad
    "como estas", "muy bien", "bien", "mal", "que tal", "quien eres", "como te llamas", "me llamo", "cuantos anos tienes",
    # Acciones y juegos
    "vamos a jugar", "juguemos", "vamos a aprender", "vamos a cantar", "canta", "canta una cancion",
    "baila", "cuentame un cuento", "cuentame una historia", "dime un chiste",
    "saluda", "camina", "para", "ven aqui", "sientate", "levantate", "da una vuelta",
    # Numeros
    "cero", "uno", "dos", "tres", "cuatro", "cinco",
    "seis", "siete", "ocho", "nueve", "diez",
    # Colores
    "rojo", "azul", "verde", "amarillo", "blanco", "negro", "rosa", "naranja", "morado",
    # Conceptos espaciales y tamanos
    "grande", "pequeno", "arriba", "abajo", "cerca", "lejos",
    # Animales
    "perro", "gato", "leon", "elefante", "pajaro", "mono", "jirafa", "oso", "vaca", "caballo", "dinosaurio",
    # Aula, personas y emociones
    "maestra", "maestro", "profesor", "profesora", "amiguitos", "amigos", "escuela", "jardin",
    "feliz", "triste", "alegre", "sorpresa",
    # Instrucciones de clase y dudas
    "escucha", "silencio", "mira", "ayuda", "no entiendo", "otra vez", "que hora es", "estoy listo",
]


def _json_safe(value):
    """Coerce non-serializable naoqi objects (Event, ALProxy, etc.) to strings."""
    try:
        return str(value)
    except Exception:  # noqa: BLE001
        return repr(value)


_PY2 = sys.version_info[0] == 2

if _PY2:

    def _text(value, default=""):
        """Devuelve un `str` nativo (bytes) para la capa SWIG de naoqi.

        CAUSA RAIZ de los fallos en vivo de speak/posture/set_language:
            ALTextToSpeech::say
            Call argument number 0 conversion failure from Void to String.

        pynaoqi corre en Python 2 y sus typemaps SWIG NO aceptan `unicode`,
        pero `json.loads()` devuelve SIEMPRE `unicode`. Por eso todo argumento
        de texto debe re-codificarse a bytes utf-8 antes de tocar un ALProxy.
        """
        if value is None:
            return default
        if isinstance(value, str):
            return value
        if isinstance(value, unicode):  # noqa: F821  (solo existe en py2)
            return value.encode("utf-8")
        return str(value)

    def _utext(value, default=u""):
        """Devuelve `unicode` para que json.dumps emita UTF-8 y no mojibake.

        ALMemory devuelve los textos del ASR como bytes utf-8 (p.ej.
        'C\\xc3\\xb3mo est\\xc3\\xa1s'). Si se pasan tal cual a json.dumps, cada
        byte se escapa por separado ("C\\u00c3\\u00b3mo") y el panel muestra
        "CÃ³mo" en lugar de "Cómo".
        """
        if value is None:
            return default
        if isinstance(value, unicode):  # noqa: F821
            return value
        if isinstance(value, str):
            try:
                return value.decode("utf-8")
            except Exception:  # noqa: BLE001
                return value.decode("latin-1")
        try:
            return unicode(value)  # noqa: F821
        except Exception:  # noqa: BLE001
            return default

else:

    def _text(value, default=""):
        """Variante py3 (usada por el test offline con el stub de naoqi)."""
        if value is None:
            return default
        return value if isinstance(value, str) else str(value)

    def _utext(value, default=""):
        """Variante py3 de `_utext`."""
        if value is None:
            return default
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except Exception:  # noqa: BLE001
                return value.decode("latin-1")
        return value if isinstance(value, str) else str(value)


def _text_list(values):
    """Convierte una secuencia a lista de `str` nativos."""
    if not values:
        return []
    return [_text(v) for v in values]


def _parse_color(value, default=0xFFFFFF):
    """Accept 0xRRGGBB ints, '0xRRGGBB' / '#RRGGBB' / 'RRGGBB' strings.

    ALLeds.fadeRGB() requires an INT. The dispatcher passes whatever string
    the LLM produced (e.g. "0xff0000"), so without this coercion every LED
    command fails with a naoqi type error.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text.startswith("#"):
        text = text[1:]
    if text.startswith("0x"):
        text = text[2:]
    try:
        return int(text, 16)
    except (TypeError, ValueError):
        return default


def _parse_led_name(value, default="AllLeds"):
    text = _text(value).strip()
    return text or default


def _best_asr_hypothesis(data):
    """Extrae la hipotesis mas probable de la clave `WordRecognized`.

    ALMemory la expone como una lista plana: [palabra1, conf1, palabra2, conf2,
    ...] ordenada por probabilidad, pero el orden NO es fiable entre llamadas,
    asi que se elige por confianza.

    Con word-spotting activo (el modo util para conversacion) las coincidencias
    parciales llegan envueltas en marcadores, p.ej. "<...> hola <...>". Se
    limpian para dejar "hola".

    Devuelve (texto, confianza) o None si no hay nada legible.
    """
    if not data or not isinstance(data, (list, tuple)):
        return None
    best_word = u""
    best_conf = 0.0
    for i in range(0, len(data) - 1, 2):
        word = _utext(data[i]).replace("<...>", u" ").strip()
        word = u" ".join(word.split())
        try:
            conf = float(data[i + 1])
        except (TypeError, ValueError):
            continue
        if not word or conf <= best_conf:
            continue
        best_word, best_conf = word, conf
    if not best_word:
        return None
    return best_word, best_conf


def out(obj):
    sys.stdout.write(json.dumps(obj, default=_json_safe) + "\n")
    sys.stdout.flush()


class NAO(object):
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.tts = None
        self.motion = None
        # NOTA: estos proxies NO pueden llamarse self.leds / self.posture.
        # Los metodos leds() y posture() de esta clase quedaban sombreados por
        # el atributo de instancia y el dispatch (nao.leds(...), nao.posture(...))
        # fallaba con "object is not callable". Por eso llevan sufijo _svc.
        self.posture_svc = None
        self.leds_svc = None
        self.video = None
        self.memory = None
        self.battery_svc = None
        self.asr = None
        self.audio = None
        self.audio_svc = None
        self.animated_speech = None
        self.behavior = None
        self.sonar = None
        self.errors = {}
        self.connected = False
        self._mic_energy_enabled = False
        self._kg_thread = None
        self._kg_running = False

    def _proxy_safe(self, name):
        """Crea un ALProxy aislando el fallo: un servicio caido no debe tumbar el resto.

        Antes, si el robot no estaba accesible, la PRIMERA linea de connect()
        lanzaba y NINGUN proxy quedaba asignado. El bridge seguia respondiendo
        "ready" y el panel parecia conectado, pero todo comando devolvia
        errores opacos del tipo "'NoneType' object has no attribute ...".
        """
        try:
            return ALProxy(name, self.ip, self.port), None
        except Exception as exc:  # noqa: BLE001
            return None, "%s: %s" % (name, exc)

    def connect(self):
        """Conecta cada servicio por separado y devuelve un diagnostico real."""
        errors = {}

        # Servicios criticos: sin ellos el panel no sirve de nada.
        self.tts, errors["ALTextToSpeech"] = self._proxy_safe("ALTextToSpeech")
        self.motion, errors["ALMotion"] = self._proxy_safe("ALMotion")
        self.posture_svc, errors["ALRobotPosture"] = self._proxy_safe("ALRobotPosture")
        self.leds_svc, errors["ALLeds"] = self._proxy_safe("ALLeds")
        self.memory, errors["ALMemory"] = self._proxy_safe("ALMemory")
        self.battery_svc, errors["ALBattery"] = self._proxy_safe("ALBattery")
        self.audio_svc, errors["ALAudioDevice"] = self._proxy_safe("ALAudioDevice")
        self.audio = self.audio_svc

        # Servicios opcionales: su ausencia es normal segun la version de NAOqi,
        # asi que se guardan aparte y NO cuentan para decidir si hay conexion.
        optional_errors = {}
        self.animated_speech, optional_errors["ALAnimatedSpeech"] = self._proxy_safe("ALAnimatedSpeech")
        self.behavior, optional_errors["ALBehaviorManager"] = self._proxy_safe("ALBehaviorManager")
        self.video, optional_errors["ALVideoDevice"] = self._proxy_safe("ALVideoDevice")
        self.asr, optional_errors["ALSpeechRecognition"] = self._proxy_safe("ALSpeechRecognition")
        self.sonar, optional_errors["ALSonar"] = self._proxy_safe("ALSonar")
        if self.sonar is not None:
            try:
                self.sonar.subscribe("wis_nao")
            except Exception as exc:  # noqa: BLE001
                self.sonar = None
                optional_errors["ALSonar"] = "ALSonar.subscribe: %s" % exc

        errors = dict((k, v) for k, v in errors.items() if v)
        optional_errors = dict((k, v) for k, v in optional_errors.items() if v)

        self.errors = errors
        self.connected = self.tts is not None
        return {
            "connected": self.connected,
            "missing": sorted(errors.keys()),
            "optional_missing": sorted(optional_errors.keys()),
            "errors": errors,
        }

    # ------------------------------------------------------------------ #
    def speak(self, text, language="Spanish"):
        try:
            self.tts.setLanguage(_text(language, "Spanish"))
        except Exception:  # noqa: BLE001
            pass
        self.tts.say(_text(text))
        return {"success": True, "said": text, "language": _text(language)}

    def set_language(self, language):
        self.tts.setLanguage(_text(language, "Spanish"))
        return {"success": True, "language": _text(language)}

    def set_volume(self, level):
        """Set the robot speaker output volume (0-100) via ALAudioDevice."""
        if not self.audio_svc:
            return {"success": False, "error": self._svc_error("ALAudioDevice", "no_audio_service")}
        try:
            lvl = int(float(level))
        except Exception:  # noqa: BLE001
            return {"success": False, "error": "invalid_level"}
        if lvl < 0:
            lvl = 0
        if lvl > 100:
            lvl = 100
        self.audio_svc.setOutputVolume(lvl)
        return {"success": True, "volume": lvl}

    def get_volume(self):
        """Read the robot speaker output volume (0-100)."""
        if not self.audio_svc:
            return {"success": False, "error": self._svc_error("ALAudioDevice", "no_audio_service")}
        try:
            lvl = int(self.audio_svc.getOutputVolume())
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": "get_failed: %s" % exc}
        return {"success": True, "volume": lvl}

    # ------------------------------------------------------------------ #
    #  Microphones: "are NAO's ears actually hearing me?"
    # ------------------------------------------------------------------ #
    MIC_MEMORY_KEYS = {
        "front": "Device/SubDeviceList/Microphone/Front/Energy/Sensor/Value",
        "rear": "Device/SubDeviceList/Microphone/Rear/Energy/Sensor/Value",
        "left": "Device/SubDeviceList/Microphone/Left/Energy/Sensor/Value",
        "right": "Device/SubDeviceList/Microphone/Right/Energy/Sensor/Value",
    }

    def _audio_proxy(self):
        """Devuelve un proxy ALAudioDevice usable, o None si no hay."""
        return self.audio_svc or self.audio

    def _svc_error(self, name, fallback=None):
        """Motivo real por el que un servicio no esta disponible."""
        err = (self.errors or {}).get(name)
        if err:
            return err
        if fallback:
            return fallback
        return "%s_unavailable" % name.lower()

    def _mic_energies_via_audio(self):
        """Energia de las 4 capsulas via ALAudioDevice (via canonica NAOqi)."""
        audio = self._audio_proxy()
        if audio is None:
            raise RuntimeError(self._svc_error("ALAudioDevice", "no_audio_service"))
        if not self._mic_energy_enabled:
            # Sin esto, get*MicEnergy() devuelve siempre 0 en la mayoria de firmwares.
            try:
                audio.enableEnergyComputation()
            except Exception:  # noqa: BLE001
                pass
            self._mic_energy_enabled = True
        return {
            "front": float(audio.getFrontMicEnergy()),
            "rear": float(audio.getRearMicEnergy()),
            "left": float(audio.getLeftMicEnergy()),
            "right": float(audio.getRightMicEnergy()),
        }

    def _mic_energies_via_memory(self):
        """Fallback: lee las energias directamente desde ALMemory."""
        out_ = {}
        for name, key in self.MIC_MEMORY_KEYS.items():
            out_[name] = float(self.memory.getData(_text(key)))
        return out_

    def get_mic_level(self, reference=8000.0, threshold=0.05):
        """Nivel de los microfonos, para saber si NAO realmente esta oyendo.

        Devuelve la energia cruda de las 4 capsulas, un `level` normalizado
        0..1 respecto a `reference` y `hearing`, que es True cuando alguna
        capsula supera `threshold` (fraccion de la referencia).
        """
        try:
            ref = float(reference)
        except Exception:  # noqa: BLE001
            ref = 8000.0
        if ref <= 0:
            ref = 8000.0
        try:
            thresh = float(threshold)
        except Exception:  # noqa: BLE001
            thresh = 0.05

        source = "audio_device"
        try:
            energies = self._mic_energies_via_audio()
        except Exception as exc:  # noqa: BLE001
            try:
                energies = self._mic_energies_via_memory()
                source = "almemory"
            except Exception as exc2:  # noqa: BLE001
                return {
                    "success": False,
                    "error": "mic_read_failed: %s / %s" % (exc, exc2),
                    "source": "none",
                }

        peak = max(energies.values())
        level = peak / ref
        if level < 0.0:
            level = 0.0
        if level > 1.0:
            level = 1.0
        return {
            "success": True,
            "source": source,
            "energy": energies,
            "peak": peak,
            "reference": ref,
            "level": level,
            "hearing": peak >= (ref * thresh),
        }

    def move(self, x, y, theta):
        self.motion.moveTo(float(x), float(y), float(theta))
        return {"success": True}

    def stop_move(self):
        self.motion.stopMove()
        return {"success": True}

    def posture(self, name):
        name = _text(name, "Stand")
        # wakeUp() es necesario: goToPosture falla si los motores estan rigidos.
        try:
            self.motion.wakeUp()
        except Exception:  # noqa: BLE001
            pass
        self.posture_svc.goToPosture(name, 0.6)
        return {"success": True, "posture": name}

    def set_angles(self, names, angles, speed=0.2):
        self.motion.setAngles(_text_list(names), angles, float(speed))
        return {"success": True}

    def leds(self, color, led="AllLeds"):
        self.leds_svc.fadeRGB(_parse_led_name(led), _parse_color(color), 0.3)
        return {"success": True, "color": _parse_color(color), "led": _parse_led_name(led)}

    def leds_off(self):
        self.leds_svc.fadeRGB("AllLeds", 0x000000, 0.3)
        return {"success": True}

    def battery(self):
        return {"success": True, "percent": self.battery_svc.getBatteryCharge()}

    def capture(self):
        if not self.video:
            return {"success": False, "error": "no_video_service"}
        name = "wis_cam"
        try:
            self.video.unsubscribe(name)
        except Exception:  # noqa: BLE001
            pass
        handle = self.video.subscribeCamera(name, 0, 2, 11, 5)
        img = self.video.getImageRemote(handle)
        self.video.unsubscribe(handle)
        if not img:
            return {"success": False, "error": "no_image"}
        return {
            "success": True,
            "width": img[0],
            "height": img[1],
            "data_len": len(img[6]),
        }

    def _asr_live(self):
        """Return a live ALSpeechRecognition proxy, re-creating it if the
        cached handle is stale. The robot-side service can be destroyed
        (e.g. after a failed init), which makes every call on the old
        handle raise 'module destroyed'. Re-acquiring fixes that.

        Solo se usa `pause(True)` como sonda: la version antigua llamaba
        tambien a `pause(False)`, que ENCENDIA el microfono como efecto
        colateral de un simple chequeo de salud.
        """
        if self.asr is not None:
            try:
                self.asr.pause(True)
                return self.asr
            except Exception:  # noqa: BLE001
                pass
        self.asr, _err = self._proxy_safe("ALSpeechRecognition")
        return self.asr

    # Nombre del cliente de suscripcion del motor ASR. NAOqi admite varias
    # suscripciones, pero el bridge solo necesita una a la vez.
    ASR_CLIENT = "wis_listen"

    def listen(self, timeout=6.0, language="Spanish", vocabulary=None,
               word_spotting=True, min_confidence=0.4):
        """Escucha una locucion y devuelve el texto reconocido.

        CAUSA RAIZ de que NAO "no escuchara" (dos fallos independientes):

        1. `self.memory.subscriber("WordRecognized")` esta ROTO en este build
           de NAOqi: lanza siempre
               "Conversion from o(class boost::shared_ptr<qi::GenericObject>)
                to m(class AL::ALValue) failed"
           sin importar el estado del motor. El bridge la llamaba en cada
           `listen`, asi que el reconocimiento jamas arrancaba.
           `memory.getData("WordRecognized")` si funciona -> se hace polling.

        2. Faltaba `asr.subscribe(cliente)`. ALSpeechRecognition NO procesa
           audio hasta que alguien se suscribe; con solo `pause(False)` el
           motor quedaba "encendido" pero sordo.

        Ademas, `setLanguage`/`setVocabulary` solo son validos con el motor
        PAUSADO; si no, NAOqi responde
            "You need to stop or pause the ASR engine to be able to make this call".
        """
        asr = self._asr_live()
        if not asr:
            return {"success": False, "error": "no_asr_service"}

        try:
            timeout = max(0.0, float(timeout))
        except (TypeError, ValueError):
            timeout = 6.0
        try:
            min_confidence = float(min_confidence)
        except (TypeError, ValueError):
            min_confidence = 0.4

        vocab = vocabulary if vocabulary else ASR_VOCABULARY
        vocab_warning = None
        best_word, best_conf = u"", 0.0

        # Un resultado viejo en ALMemory se devolveria como si fuese nuevo.
        try:
            self.memory.insertData("WordRecognized", [])
        except Exception:  # noqa: BLE001
            pass

        try:
            try:
                asr.pause(True)
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "error": "asr_module_destroyed",
                        "detail": str(exc)}

            try:
                asr.setLanguage(_text(language, "Spanish"))
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "error": "asr_set_language_failed",
                        "detail": str(exc)}

            if vocab:
                try:
                    asr.setVocabulary(_text_list(vocab), bool(word_spotting))
                except Exception as exc:  # noqa: BLE001
                    # El vocabulario es opcional: con la gramatica por defecto
                    # la escucha sigue operativa, solo reconoce menos palabras.
                    vocab_warning = str(exc)

            # Una suscripcion anterior colgada impide volver a arrancar.
            try:
                asr.unsubscribe(self.ASR_CLIENT)
            except Exception:  # noqa: BLE001
                pass
            asr.subscribe(self.ASR_CLIENT)
            asr.pause(False)

            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    data = self.memory.getData("WordRecognized")
                except Exception:  # noqa: BLE001
                    data = None
                cand = _best_asr_hypothesis(data)
                if cand and cand[1] > best_conf:
                    best_word, best_conf = cand
                if best_word and best_conf >= min_confidence:
                    break
                time.sleep(0.15)
        finally:
            try:
                asr.pause(True)
            except Exception:  # noqa: BLE001
                pass
            try:
                asr.unsubscribe(self.ASR_CLIENT)
            except Exception:  # noqa: BLE001
                pass

        result = {
            "success": True,
            "text": _utext(best_word),
            "confidence": round(best_conf, 3),
            "language": _utext(language),
            "matched": bool(best_word) and best_conf >= min_confidence,
        }
        if vocab_warning:
            result["vocabulary_warning"] = vocab_warning
        return result

    # ------------------------------------------------------------------ #
    def animated_say(self, text, language="Spanish"):
        if not self.animated_speech:
            return {"success": False, "error": "no_animated_speech"}
        try:
            self.tts.setLanguage(_text(language, "Spanish"))
        except Exception:
            pass
        self.animated_speech.say(_text(text))
        return {"success": True, "said": text}

    def get_joints(self):
        names = self.motion.getBodyNames("Body")
        angles = self.motion.getAngles("Body", True)
        return {"success": True, "joints": dict(zip(names, angles))}

    def set_stiffness(self, name, stiffness):
        self.motion.setStiffnesses(_text(name, "Body"), float(stiffness))
        return {"success": True}

    def get_memory_key(self, key):
        try:
            val = self.memory.getData(_text(key))
            return {"success": True, "value": val}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_memory_key(self, key, value):
        self.memory.insertData(_text(key), value)
        return {"success": True}

    def get_sensors(self):
        try:
            # Tactile
            head_f = self.memory.getData("Device/SubDeviceList/Head/Touch/Front/Sensor/Value")
            head_m = self.memory.getData("Device/SubDeviceList/Head/Touch/Middle/Sensor/Value")
            head_r = self.memory.getData("Device/SubDeviceList/Head/Touch/Rear/Sensor/Value")
            l_hand = self.memory.getData("Device/SubDeviceList/LHand/Touch/Back/Sensor/Value")
            r_hand = self.memory.getData("Device/SubDeviceList/RHand/Touch/Back/Sensor/Value")
            
            # Sonar
            sonar_l = self.memory.getData("Device/SubDeviceList/US/Left/Sensor/Value")
            sonar_r = self.memory.getData("Device/SubDeviceList/US/Right/Sensor/Value")
            
            # Accel
            acc_x = self.memory.getData("Device/SubDeviceList/InertialSensor/AccelerometerX/Sensor/Value")
            acc_y = self.memory.getData("Device/SubDeviceList/InertialSensor/AccelerometerY/Sensor/Value")
            acc_z = self.memory.getData("Device/SubDeviceList/InertialSensor/AccelerometerZ/Sensor/Value")
            
            return {
                "success": True,
                "tactile": {"head_front": head_f, "head_middle": head_m, "head_rear": head_r, "l_hand": l_hand, "r_hand": r_hand},
                "sonar": {"left": sonar_l, "right": sonar_r},
                "accelerometer": {"x": acc_x, "y": acc_y, "z": acc_z}
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_temperature(self, joint="Body"):
        if joint == "Body":
            names = self.motion.getBodyNames("Body")
        else:
            names = [_text(joint)]
        temps = []
        for n in names:
            key = "Device/SubDeviceList/%s/Temperature/Sensor/Value" % n
            try:
                temps.append(self.memory.getData(key))
            except Exception:
                # Sensor de temperatura no disponible para esta articulacion; se reporta 0.
                temps.append(0)
        return {"success": True, "temperatures": dict(zip(names, temps))}

    def capture_b64(self, resolution=1):
        """Captura un frame y lo devuelve en base64 (pixeles CRUDOS RGB).

        OJO: esta build de NAOqi NO sabe entregar JPEG. Se comprobo en el robot:
        colorSpace=21 (kJpegColorSpace) devuelve 320*240*2 bytes en 2 capas, es
        decir YUV422, NO un JPEG. Por eso aqui se devuelven los pixeles crudos
        de colorSpace=11 y la conversion a JPEG la hace el host (panel_server)
        con Pillow. El campo se llama `image_raw_b64` a proposito: antes se
        enviaba crudo bajo el nombre `image_b64` y el navegador, que esperaba
        un JPEG real, no mostraba nada.
        """
        # resolution: 0=QQVGA, 1=QVGA, 2=VGA
        if not self.video:
            return {"success": False, "error": self._svc_error("ALVideoDevice", "no_video_service")}
        name = "wis_cam_b64"
        try:
            self.video.unsubscribe(name)
        except Exception:
            pass
        handle = self.video.subscribeCamera(name, 0, resolution, 11, 5)
        try:
            img = self.video.getImageRemote(handle)
        finally:
            try:
                self.video.unsubscribe(handle)
            except Exception:
                pass
        if not img:
            return {"success": False, "error": "no_image"}
        width, height, layers = img[0], img[1], img[2]
        img_data = img[6]
        if not img_data:
            return {"success": False, "error": "empty_frame"}
        b64 = base64.b64encode(bytearray(img_data)).decode('ascii')
        return {
            "success": True,
            "width": width,
            "height": height,
            "layers": layers,
            "encoding": "raw_rgb",
            "image_raw_b64": b64,
        }

    def list_behaviors(self):
        if not self.behavior: return {"success": False, "error": "no_behavior_mgr"}
        return {"success": True, "behaviors": self.behavior.getInstalledBehaviors()}

    def run_behavior(self, name):
        if not self.behavior: return {"success": False, "error": "no_behavior_mgr"}
        self.behavior.runBehavior(_text(name))
        return {"success": True}

    def stop_behavior(self, name):
        if not self.behavior: return {"success": False, "error": "no_behavior_mgr"}
        self.behavior.stopBehavior(_text(name))
        return {"success": True}

    # ------------------------------------------------------------------ #
    #  Autonomous kindergarten-teacher mode
    # ------------------------------------------------------------------ #
    def kindergarten_start(self, topic=""):
        if self._kg_running:
            return {"success": True, "already": True}
        self._kg_running = True
        self._kg_thread = threading.Thread(target=self._kg_loop, args=(topic,))
        self._kg_thread.daemon = True
        self._kg_thread.start()
        return {"success": True, "started": True}

    def kindergarten_stop(self):
        self._kg_running = False
        return {"success": True, "stopped": True}

    def _kg_loop(self, topic):
        self.leds_svc.fadeRGB("FaceLeds", 0x66CCFF, 0.5)
        self.posture_svc.goToPosture("Stand", 0.6)
        self.speak(
            "Hola ninos y ninas. Soy WIS, su maestra. Vamos a aprender juntos.",
            "Spanish",
        )
        while self._kg_running:
            time.sleep(1)
        self.leds_svc.fadeRGB("AllLeds", 0x000000, 0.5)
        self.speak("Hasta luego, amigos.", "Spanish")


def main():
    ip = DEFAULT_IP
    port = DEFAULT_PORT
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--ip" and i + 1 < len(args):
            ip = args[i + 1]
        if a == "--port" and i + 1 < len(args):
            port = int(args[i + 1])

    nao = NAO(ip, port)
    try:
        diag = nao.connect()
        if diag["connected"]:
            out({
                "event": "ready", "connected": True, "ip": ip, "port": port,
                "optional_missing": diag["optional_missing"],
            })
        else:
            # Antes esto se reportaba como conectado y el panel parecia OK
            # mientras todo comando fallaba con 'NoneType' object has no ...
            out({
                "event": "ready", "connected": False, "ip": ip, "port": port,
                "error": "nao_unreachable",
                "missing": diag["missing"],
                "errors": diag["errors"],
            })
    except Exception as exc:  # noqa: BLE001
        out({"event": "ready", "connected": False, "error": str(exc)})

    for line in iter(sys.stdin.readline, ""):
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:  # noqa: BLE001
            out({"success": False, "error": "bad_json"})
            continue
        action = msg.get("action")
        p = msg.get("params", {}) or {}
        if action == "quit":
            out({"success": True, "bye": True})
            break
        # Diagnostico explicito: evita fallos opacos tipo 'NoneType' object.
        if action == "diag":
            out({
                "success": True,
                "connected": getattr(nao, "connected", False),
                "missing": sorted((nao.errors or {}).keys()),
                "errors": nao.errors or {},
                "ip": nao.ip,
                "port": nao.port,
            })
            continue
        try:
            if action == "speak":
                res = nao.speak(p.get("text", ""), p.get("language", "Spanish"))
            elif action == "set_language":
                res = nao.set_language(p.get("language", "Spanish"))
            elif action == "move":
                res = nao.move(p.get("x", 0), p.get("y", 0), p.get("theta", 0))
            elif action == "walk_to":
                res = nao.move(p.get("x", 0), p.get("y", 0), p.get("theta", 0))
            elif action == "stop_move":
                res = nao.stop_move()
            elif action == "posture":
                res = nao.posture(p.get("name", "Stand"))
            elif action == "set_angles":
                res = nao.set_angles(p.get("names", []), p.get("angles", []), p.get("speed", 0.2))
            elif action == "leds":
                res = nao.leds(p.get("color", "0xffffff"), p.get("led", "AllLeds"))
            elif action == "leds_off":
                res = nao.leds_off()
            elif action == "battery":
                res = nao.battery()
            elif action == "set_volume":
                res = nao.set_volume(p.get("level", 50))
            elif action == "get_volume":
                res = nao.get_volume()
            elif action == "get_mic_level":
                res = nao.get_mic_level(
                    p.get("reference", 8000.0), p.get("threshold", 0.05)
                )
            elif action == "capture":
                res = nao.capture()
            elif action == "capture_b64":
                res = nao.capture_b64(p.get("resolution", 1))
            elif action == "animated_say":
                res = nao.animated_say(p.get("text", ""), p.get("language", "Spanish"))
            elif action == "get_joints":
                res = nao.get_joints()
            elif action == "set_stiffness":
                res = nao.set_stiffness(p.get("name", "Body"), p.get("stiffness", 1.0))
            elif action == "get_memory_key":
                res = nao.get_memory_key(p.get("key", ""))
            elif action == "set_memory_key":
                res = nao.set_memory_key(p.get("key", ""), p.get("value", 0))
            elif action == "get_sensors":
                res = nao.get_sensors()
            elif action == "get_temperature":
                res = nao.get_temperature(p.get("joint", "Body"))
            elif action == "list_behaviors":
                res = nao.list_behaviors()
            elif action == "run_behavior":
                res = nao.run_behavior(p.get("name", ""))
            elif action == "stop_behavior":
                res = nao.stop_behavior(p.get("name", ""))
            elif action == "listen":
                res = nao.listen(
                    p.get("timeout", 6.0),
                    p.get("language", "Spanish"),
                    p.get("vocabulary"),
                    p.get("word_spotting", True),
                    p.get("min_confidence", 0.4),
                )
            elif action == "kindergarten_start":
                res = nao.kindergarten_start(p.get("topic", ""))
            elif action == "kindergarten_stop":
                res = nao.kindergarten_stop()
            else:
                res = {"success": False, "error": "unknown_action: %s" % action}
        except Exception as exc:  # noqa: BLE001
            res = {"success": False, "error": str(exc)}
        out(res)


if __name__ == "__main__":
    main()
