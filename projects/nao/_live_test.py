
import subprocess, json, os, sys, time

BRIDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nao_bridge.py")

env = dict(os.environ)
env["PYTHONPATH"] = r"C:\Users\nicol\OneDrive\Documentos\NAO\pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649\lib"
env["PYTHONIOENCODING"] = "utf-8"

p = subprocess.Popen([r"C:\Python27\python.exe", BRIDGE],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT, env=env, bufsize=1)

def send(obj):
    p.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
    p.stdin.flush()

def readline(t=15):
    end = time.time() + t
    while time.time() < end:
        line = p.stdout.readline()
        if line:
            return line.decode("utf-8", "replace").strip()
    return None

# 1. connect
send({"cmd": "connect", "ip": "172.20.10.9", "port": 9559})
print("CONNECT:", readline())

# 2. set language Spanish
send({"cmd": "set_language", "language": "Spanish"})
print("LANG:", readline())

# 3. speak
send({"cmd": "speak", "text": "Hola, soy WIS. La conexion funciona."})
print("SPEAK:", readline())

# 4. battery
send({"cmd": "battery"})
print("BATTERY:", readline())

send({"cmd": "quit"})
try:
    p.wait(timeout=5)
except Exception:
    p.kill()
print("EXITCODE:", p.returncode)
