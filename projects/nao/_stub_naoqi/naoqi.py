# -*- coding: utf-8 -*-
"""Fake `naoqi` module used to exercise nao_bridge.py without the real robot.

Put this directory first on PYTHONPATH and the bridge will import this instead
of the (Python 2.7-only) pynaoqi SDK. Every proxy records the calls it receives
so the tests can assert what the bridge actually did.

It also deliberately returns a NON-JSON-serializable object from a few methods
to reproduce the original failure:

    Object of type Event is not JSON serializable

Audio support: `ALAudioDevice` answers volume/microphone calls so the panel's
volume and mic-meter paths can be exercised. Set the environment variable
`NAO_STUB_MIC_ENERGY_BROKEN=1` to simulate a firmware without mic energy
computation, which forces the ALMemory fallback in nao_bridge.py.

ASR support: the stub reproduces the three rules of the REAL robot that made
NAO "deaf", so the offline test fails if the bridge regresses:
  1. `ALMemory.subscriber()` raises the real
     "Conversion from ... GenericObject ... to ... ALValue ... failed" error.
  2. `ALSpeechRecognition` publishes nothing until `subscribe()` is called.
  3. `setVocabulary()` only works while the engine is paused.
Set `NAO_STUB_ASR_SILENT=1` to simulate a silent room (no recognition at all).
"""

import os

CALLS = []

# Estado del motor de reconocimiento, en el proceso del bridge.
ASR_STATE = {
    "subscribed": None,
    "paused": None,
    "vocabulary": None,
    "word_recognized": [],
}

# Hipotesis que devolveria el motor tras una locucion correcta.
# Formato de ALMemory: [palabra1, conf1, palabra2, conf2, ...]
ASR_HYPOTHESES = ["Hola", 0.8852, "Ola", 0.7112]

# Error EXACTO de este build de NAOqi al construir el event subscriber.
ASR_GENERICOBJECT_ERROR = (
    "Conversion from o(class boost::shared_ptr<class qi::GenericObject>) "
    "to m(class AL::ALValue) failed "
)

# Energia "realista" por capsula cuando el robot si expone get*MicEnergy().
MIC_ENERGY = {
    "getFrontMicEnergy": 4200.0,
    "getRearMicEnergy": 3900.0,
    "getLeftMicEnergy": 4100.0,
    "getRightMicEnergy": 3800.0,
}

# Frame determinista y COHERENTE con sus dimensiones (4x2x3 = 24 bytes).
# Antes el stub decia 320x240 pero devolvia 24 bytes: esa incoherencia hacia
# que la ruta de camara nunca se ejercitara de verdad.
CAM_WIDTH = 4
CAM_HEIGHT = 2
CAM_LAYERS = 3
# Pixel 0 = rojo puro, pixel 1 = verde puro, pixel 2 = azul puro, resto 0.
CAM_FRAME = bytes(bytearray(
    [255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * (CAM_WIDTH * CAM_HEIGHT * 3 - 9)
))


class _Event(object):
    """Stand-in for naoqi's Event: not JSON serializable on purpose."""

    def __repr__(self):
        return "<Event object at 0x0>"


class ALProxy(object):
    def __init__(self, name, ip, port):
        self._name = name
        self._ip = ip
        self._port = port

    def __getattr__(self, method):
        def _recorder(*args, **kwargs):
            CALLS.append((self._name, method, args, kwargs))
            return self._result(method, args)

        return _recorder

    def _result(self, method, args):
        if self._name == "ALBattery":
            return 87
        if self._name == "ALAudioDevice":
            if method == "getOutputVolume":
                return 65
            if method == "setOutputVolume":
                return None
            if method in MIC_ENERGY:
                if os.environ.get("NAO_STUB_MIC_ENERGY_BROKEN"):
                    raise RuntimeError("mic_energy_unavailable")
                return MIC_ENERGY[method]
            if method == "enableEnergyComputation":
                return None
            return _Event()
        if self._name == "ALSpeechRecognition":
            if method == "pause":
                ASR_STATE["paused"] = bool(args[0]) if args else None
                return None
            if method == "setLanguage":
                return None
            if method == "setVocabulary":
                # El motor real rechaza el vocabulario si esta en marcha:
                #   "You need to stop or pause the ASR engine..."
                if not ASR_STATE["paused"]:
                    raise RuntimeError(
                        "ALSpeechRecognition::setVocabulary\n"
                        "\tAsrHybridNuance::xRemoveAllContext\n"
                        "\tYou need to stop or pause the ASR engine to be "
                        "able to make this call."
                    )
                ASR_STATE["vocabulary"] = args[0] if args else None
                return None
            if method == "subscribe":
                ASR_STATE["subscribed"] = args[0] if args else "anonymous"
                return None
            if method == "unsubscribe":
                ASR_STATE["subscribed"] = None
                return None
            if method == "getAvailableLanguages":
                return ["Chinese", "English", "Japanese", "Spanish"]
            return None
        if self._name == "ALMemory":
            key = args[0] if args else ""
            if method == "subscriber":
                # Fallo REAL de este build: el event subscriber de ALMemory no
                # se puede construir. Si el bridge vuelve a usarlo, el test
                # falla replica exacta del error de produccion.
                raise RuntimeError(ASR_GENERICOBJECT_ERROR)
            if key == "WordRecognized":
                if method == "insertData":
                    ASR_STATE["word_recognized"] = args[1] if len(args) > 1 else []
                    return None
                # Sin `subscribe` el robot esta literalmente sordo: el motor
                # no llega a procesar audio y ALMemory nunca se actualiza.
                if ASR_STATE["subscribed"] and not os.environ.get("NAO_STUB_ASR_SILENT"):
                    return list(ASR_HYPOTHESES)
                return list(ASR_STATE["word_recognized"])
            # Fallback del panel: energias leidas crudas desde ALMemory.
            if isinstance(key, str) and key.startswith("Device/SubDeviceList/Microphone/") \
                    and key.endswith("/Energy/Sensor/Value"):
                return 2400.0
            return 0.5
        if self._name == "ALMotion":
            if method == "getBodyNames":
                return ["HeadYaw", "HeadPitch", "LShoulderPitch"]
            if method == "getAngles":
                return [0.1, 0.2, 0.3]
            return _Event()  # <-- non-serializable on purpose
        if self._name == "ALVideoDevice":
            if method == "getImageRemote":
                return (CAM_WIDTH, CAM_HEIGHT, CAM_LAYERS, 0, 0, 0, CAM_FRAME)
            return 1
        if self._name == "ALBehaviorManager":
            if method == "getInstalledBehaviors":
                return ["wis-demo", _Event()]  # <-- non-serializable in a list
            return _Event()
        if self._name == "ALRobotPosture":
            if method == "getPostureList":
                return ["Stand", "Sit"]
            return _Event()
        if self._name == "ALLeds":
            return _Event()
        if self._name == "ALTextToSpeech":
            return _Event()
        return _Event()


def reset():
    del CALLS[:]
    ASR_STATE.update({
        "subscribed": None,
        "paused": None,
        "vocabulary": None,
        "word_recognized": [],
    })
