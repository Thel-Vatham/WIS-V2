# NAO Robot — Proyecto WIS

Control del robot **NAO** desde WIS. Proyecto aislado dentro de `Projects/`
(siguiendo la regla de `config/system/EXECUTION.md`: el código de usuario no
contamina la raíz de WIS).

## Cómo funciona

WIS corre en **Python 3.11**, pero el SDK de NAO (NAOqi) sólo existe para
**Python 2.7**. La solución es un **puente**:

```
WIS (Python 3.11)
   └── ability: abilities/nao_robot.py
         └── subprocess: C:\Python27\python.exe  →  nao_bridge.py
               └── NAOqi SDK (pynaoqi 2.8.6)  →  NAO por TCP/IP
```

- `nao_bridge.py` es un worker *long-lived* de Python 2.7 que habla
  **JSON por línea** sobre stdin/stdout. WIS le manda comandos y lee respuestas.
- La ability `nao_robot` lo encuentra automáticamente en esta carpeta
  (`Projects/nao/nao_bridge.py`), con respaldo en `nao/` y `old/nao/`.

## Requisitos

| Componente | Ruta / valor |
|---|---|
| Python 2.7 | `C:\Python27\python.exe` |
| SDK NAOqi | `C:\Users\nicol\OneDrive\Documentos\NAO\pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649\lib` |
| IP del robot (por defecto) | `172.20.10.9` |
| Puerto (por defecto) | `9559` |

## Archivos

| Archivo | Qué es |
|---|---|
| `nao_bridge.py` | **Puente principal.** Worker Python 2.7 con protocolo JSON por línea. Lo lanza WIS automáticamente. |
| `panel_server.py`| **Servidor web FastAPI (Python 3.11).** UI de control total y telemetría sobre WebSockets (puerto 7860). |
| `kindergarten_teacher.py` | **Modo Autónomo.** Conecta los sensores/micro de NAO con el LLM de WIS para actuar como profesor. |
| `panel/` | Carpeta con la interfaz web (HTML/JS/CSS). |
| `possess_wis.py` | Script de "toma de posesión": despierta el robot, postura `StandInit`, LEDs azules, habla en español y saluda. |
| `oneshot_test.py` | Prueba mínima: importa NAOqi, conecta, pone español y dice una frase. |
| `_live_test.py` | Prueba del puente de extremo a extremo (connect → set_language → speak → battery → quit). |

## Uso

### Desde WIS (recomendado)
En la consola de WIS, abre el proyecto **nao** y pídelo en lenguaje natural:

> Conecta al robot NAO y saluda en español

La ability `nao_robot` levanta el puente sola. Si el robot no responde,
revisa que esté encendido y en la misma red (IP en `abilities/nao_robot.py`).

### Panel Web y Control Total
Para abrir la interfaz de usuario completa (cámara, sensores, articulaciones):
```powershell
# Lanzar el servidor web (Python 3.11)
python projects\nao\panel_server.py
```
Luego abre en tu navegador: [http://localhost:7860](http://localhost:7860)

### Modo Autónomo "Profesor de Jardín"
Para que NAO opere autónomamente razonando mediante el pipeline LLM de WIS:
```powershell
python projects\nao\kindergarten_teacher.py
```
(Asegúrate de que `panel_server.py` esté corriendo primero, ya que usa su API REST).

### Pruebas directas (con el robot encendido)
```powershell
C:\Python27\python.exe Projects\nao\oneshot_test.py
```
Salida esperada: `QI_IMPORT_OK` → `CONNECTED` → `LANG_SET_SPANISH` → `SAY_OK` → `ONESHOT_DONE`.

```powershell
C:\Python27\python.exe Projects\nao\_live_test.py
```
Prueba el protocolo JSON del puente completo.

## Notas

- **No** ejecutes `nao_bridge.py` con Python 3: usa sintaxis y SDK de Python 2.7.
- El SDK NAOqi no se instala con pip; se usa vía `PYTHONPATH` (lo hace la ability).
- Si mueves la carpeta, la ability la reencuentra por ruta relativa al repo, pero
  `possess_wis.py` y `_live_test.py` resuelven el puente de forma **relativa a su
  propia ubicación**, así que seguirán funcionando.
