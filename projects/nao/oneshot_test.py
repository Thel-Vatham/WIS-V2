
import sys
sys.path.insert(0, r"C:\naoqi_sdk\pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649\lib")
try:
    from naoqi import ALProxy
    print("QI_IMPORT_OK")
except Exception as e:
    print("QI_IMPORT_FAIL:", repr(e))
    sys.exit(2)

try:
    tts = ALProxy("ALTextToSpeech", "172.20.10.9", 9559)
    print("CONNECTED")
    tts.setLanguage("Spanish")
    print("LANG_SET_SPANISH")
    tts.say("Hola, soy WIS. Estoy listo para ensenar.")
    print("SAY_OK")
except Exception as e:
    print("NAO_FAIL:", repr(e))
    sys.exit(3)
print("ONESHOT_DONE")
