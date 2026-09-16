
# -*- coding: utf-8 -*-
import sys, time
try:
    from naoqi import ALProxy
except Exception as e:
    print("IMPORT_FAIL: %s" % e); sys.exit(2)

IP, PORT = "172.20.10.9", 9559
try:
    tts = ALProxy("ALTextToSpeech", IP, PORT)
    motion = ALProxy("ALMotion", IP, PORT)
    posture = ALProxy("ALRobotPosture", IP, PORT)
    leds = ALProxy("ALLeds", IP, PORT)
except Exception as e:
    print("CONNECT_FAIL: %s" % e); sys.exit(3)

print("CONNECTED")

try:
    tts.setLanguage("Spanish")
    print("LANG_SET: Spanish")
except Exception as e:
    print("LANG_WARN: %s" % e)

try:
    motion.wakeUp(); posture.goToPosture("StandInit", 0.5)
    print("POSTURE_OK")
except Exception as e:
    print("POSTURE_WARN: %s" % e)

try:
    leds.fadeRGB("FaceLeds", 0x00CCFF, 0.5)
    leds.fadeRGB("EarLeds",  0x00CCFF, 0.5)
    print("LEDS_OK")
except Exception as e:
    print("LEDS_WARN: %s" % e)

msg = ("Hola, ni\u00f1os y ni\u00f1as. Buenos d\u00edas. "
       "Yo soy WIS, y hoy voy a ser su maestra de k\u00ednder. "
       "Vamos a aprender y a jugar juntos. \u00bfEst\u00e1n listos?")
try:
    tts.say(msg)
    print("SPEAK_OK")
except Exception as e:
    print("SPEAK_FAIL: %s" % e)

try:
    motion.angleInterpolationWithSpeed(
        "RArm", [1.0, 0.2, 1.0], 0.5)  # simple wave
    print("WAVE_OK")
except Exception as e:
    print("WAVE_WARN: %s" % e)

print("POSSESSION_DONE")
sys.exit(0)
