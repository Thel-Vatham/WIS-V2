# Live Camera — Detección de objetos en vivo

Detector de objetos multi-clase sobre la webcam, con ventana en vivo, cajas
etiquetadas y anuncios por voz. Es el proyecto que alimenta la detección de
visión que antes vivía suelta en la raíz como `object_detector/`.

## Modelos disponibles

| Modelo | Clases | Cuándo se usa |
|---|---|---|
| **YOLOv4-tiny (COCO-80)** | 80 — incluye `cell phone`, `bottle`, `cup`, `person`, `chair`, `dog`… | **Recomendado.** Detecta varios objetos a la vez, incluidos objetos pequeños. |
| MobileNet-SSD (VOC-20) | 20 — `person`, `bottle`, `chair`… (**no** tiene `cell phone`) | Legado. Sólo objetos grandes y evidentes. |

> El viejo MobileNet-SSD VOC-20 fue justamente el motivo por el que "sólo
> detectaba la persona": su lista de clases no incluye teléfono ni bolígrafo, y
> con umbral 0.5 se queda con un único objeto dominante. YOLOv4-tiny lo resuelve.

## Requisitos importantes

Este proyecto trae **su propio entorno virtual** con **OpenCV 4.14**, porque el
venv principal de WIS usa **OpenCV 5.0**, que eliminó `readNetFromDarknet` y
`readNetFromCaffe`. Por eso el detector debe correr con **su** venv:

```powershell
Projects\live_camera\venv\Scripts\python.exe
```

## Uso

### Detector en vivo (YOLOv4-tiny, recomendado)
```powershell
cd Projects\live_camera
venv\Scripts\python.exe live_detector.py
```

Controles:
- `Q` / `ESC` → salir
- `S` → guardar una captura anotada en `snapshots/`
- `ESPACIO` → pausar / reanudar

### Otras variantes
| Comando | Qué hace |
|---|---|
| `venv\Scripts\python.exe detector.py` | Detección sobre una foto capturada (MobileNet-SSD). |
| `venv\Scripts\python.exe live_detector_ssd_v1.py` | Versión antigua del detector en vivo (MobileNet-SSD). |
| `venv\Scripts\python.exe detector_lite.py` | Detección de rostros con Haar cascades (no necesita modelos externos). |

## Archivos

| Archivo | Qué es |
|---|---|
| `live_detector.py` | **Detector en vivo principal.** YOLOv4-tiny COCO-80, NMS, tracking, lista de objetos en pantalla y voz opcional en español. |
| `detector.py` | Detector sobre imagen capturada (MobileNet-SSD + Caffe). |
| `detector_lite.py` | Detección de rostros con cascadas Haar. |
| `live_detector_ssd_v1.py` | Versión previa del detector en vivo (MobileNet-SSD). |
| `yolov4-tiny.cfg` / `.weights` / `coco.names` | Modelo YOLOv4-tiny y sus 80 clases. |
| `MobileNetSSD_deploy.prototxt` / `.caffemodel` | Modelo MobileNet-SSD (legado). |
| `ssd_mobilenet*.onnx` | Modelos ONNX de prueba (**truncados/corruptos**, no usables). |
| `_cap.py` | Captura un frame de la webcam a `live_frame.png`. |
| `_validate.py` | Verifica que el modelo Caffe carga y detecta. |
| `_probe.py` / `_verify_yolo.py` / `_selftest_v2.py` | Utilidades de diagnóstico. |
| `snapshots/` | Capturas anotadas guardadas con `S`. |

Todos los scripts resuelven sus modelos de forma **relativa a su propia
ubicación**, así que la carpeta se puede mover sin romperlos.

## Relación con el núcleo de WIS

`abilities/vision.py` es una habilidad **del núcleo** (se carga siempre y sirve
para analizar pantalla/imagen), y necesita el modelo YOLO. Para no acoplar el
núcleo a este proyecto, WIS guarda su **propia copia** de los assets en:

```
models/detection/yolov4-tiny.cfg | .weights | coco.names
```

Así, si borras o mueves este proyecto, la visión del núcleo sigue funcionando.
