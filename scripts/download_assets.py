import os
import sys
import time
import requests
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"
DETECTION_DIR = MODELS_DIR / "detection"

ASSETS = [
    {
        "url": "https://github.com/AlexeyAB/darknet/releases/download/darknet_yolo_v4_pre/yolov4-tiny.weights",
        "dest": DETECTION_DIR / "yolov4-tiny.weights",
        "desc": "YOLOv4-Tiny Weights (Vision)"
    },
    {
        "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx",
        "dest": MODELS_DIR / "kokoro-v0_19.onnx",
        "desc": "Kokoro TTS Model (Voice)"
    },
    {
        "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.json",
        "dest": MODELS_DIR / "voices.json",
        "desc": "Kokoro Voices Profiles"
    }
]

def download_file(url: str, dest: Path, desc: str, retries: int = 3):
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    if dest.exists() and dest.stat().st_size > 1024:
        print(f"[OK] {desc} ya existe y parece valido ({dest.name}). Saltando...")
        return True

    print(f"\nDescargando {desc}...")
    print(f"URL: {url}")
    
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True, timeout=15) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                downloaded = 0
                
                with open(dest, 'wb') as f:
                    start_time = time.time()
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = downloaded / total_size * 100
                                mb_downloaded = downloaded / (1024 * 1024)
                                mb_total = total_size / (1024 * 1024)
                                print(f"\rProgreso: {percent:.1f}% ({mb_downloaded:.1f} MB / {mb_total:.1f} MB)", end="")
                print(f"\n[EXITO] {desc} descargado en {time.time() - start_time:.1f}s")
                return True
        except Exception as e:
            print(f"\n[ERROR] Intento {attempt}/{retries} fallo: {e}")
            if dest.exists():
                dest.unlink()
            time.sleep(2)
            
    print(f"[FAIL] No se pudo descargar {desc}.")
    return False

def main():
    print("=" * 60)
    print("  WIS v3.0 - Auto-Descarga de Modelos IA Pesados")
    print("=" * 60)
    
    success_all = True
    for asset in ASSETS:
        if not download_file(asset["url"], asset["dest"], asset["desc"]):
            success_all = False
            
    if not success_all:
        print("\n[ALERTA] Algunos modelos fallaron en descargar. Revisa tu conexion.")
        sys.exit(1)
        
    print("\n[TODOS LOS MODELOS] Descargas y validaciones completadas!")
    sys.exit(0)

if __name__ == "__main__":
    main()
