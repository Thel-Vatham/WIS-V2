@echo off
setlocal EnableDelayedExpansion
title WIS — Instalador Automatico Completo
color 0B
chcp 65001 >nul 2>&1

echo.
echo  ╔═══════════════════════════════════════════════════════════════╗
echo  ║          WIS — WISDOM INTEGRATED SYSTEM v3.0                 ║
echo  ║          Instalador Automatico — 100%% sin intervencion       ║
echo  ╚═══════════════════════════════════════════════════════════════╝
echo.

set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
echo  📁 Directorio del proyecto: %PROJECT_ROOT%
echo.

:: ─────────────────────────────────────────────────────────────────
::  PASO 1 — Visual C++ Redistributable
::  (requerido por: kokoro-onnx, opencv-python, ctransformers)
:: ─────────────────────────────────────────────────────────────────
echo [1/8] Verificando Visual C++ Redistributable...

set "VCREDIST_OK=0"
reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" /v Installed >nul 2>&1 && set "VCREDIST_OK=1"
if "!VCREDIST_OK!"=="0" reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" /v Installed >nul 2>&1 && set "VCREDIST_OK=1"

if "!VCREDIST_OK!"=="1" (
    echo     ✔ Visual C++ Redistributable ya instalado
) else (
    echo     ⬇ Descargando e instalando Visual C++ Redistributable 2022...
    set "VCREDIST=%TEMP%\vc_redist_x64.exe"
    powershell -NoProfile -NonInteractive -Command ^
        "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://aka.ms/vs/17/release/vc_redist.x64.exe','!VCREDIST!')"
    if exist "!VCREDIST!" (
        "!VCREDIST!" /install /quiet /norestart
        echo     ✔ Visual C++ Redistributable instalado
    ) else (
        echo     ⚠ No se pudo descargar VC++ Redist. Continuando...
    )
)
echo.

:: ─────────────────────────────────────────────────────────────────
::  PASO 2 — Python >= 3.10
:: ─────────────────────────────────────────────────────────────────
echo [2/8] Verificando Python 3.10+...

set "PYTHON_OK=0"
set "PYTHON_EXE="

for /f "tokens=*" %%p in ('where python 2^>nul') do (
    if "!PYTHON_EXE!"=="" set "PYTHON_EXE=%%p"
)

if "!PYTHON_EXE!"=="" (
    for %%d in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
        "C:\Python310\python.exe"
        "C:\Program Files\Python313\python.exe"
        "C:\Program Files\Python312\python.exe"
    ) do (
        if exist %%d if "!PYTHON_EXE!"=="" set "PYTHON_EXE=%%~d"
    )
)

if not "!PYTHON_EXE!"=="" (
    for /f "tokens=2 delims= " %%v in ('"!PYTHON_EXE!" --version') do set "PY_VER=%%v"
    for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
        set "PY_MAJOR=%%a" & set "PY_MINOR=%%b"
    )
    if !PY_MAJOR! GEQ 3 if !PY_MINOR! GEQ 10 (
        echo     ✔ Python !PY_VER! detectado
        set "PYTHON_OK=1"
    )
    if "!PYTHON_OK!"=="0" echo     ⚠ Python !PY_VER! demasiado antiguo ^(se requiere ^>= 3.10^)
)

if "!PYTHON_OK!"=="0" (
    echo     ⬇ Descargando Python 3.12.10...
    set "PY_INSTALLER=%TEMP%\python312_setup.exe"
    powershell -NoProfile -NonInteractive -Command ^
        "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe','!PY_INSTALLER!')"
    if not exist "!PY_INSTALLER!" (
        echo  ❌ ERROR: No se pudo descargar Python.
        pause & exit /b 1
    )
    echo       Instalando silenciosamente...
    "!PY_INSTALLER!" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_doc=0 Include_launcher=1 Include_pip=1
    if errorlevel 1 (echo  ❌ ERROR: Instalacion de Python fallo. & pause & exit /b 1)
    for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "PATH=%%b;!PATH!"
    for /f "tokens=*" %%p in ('where python 2^>nul') do if "!PYTHON_EXE!"=="" set "PYTHON_EXE=%%p"
    if "!PYTHON_EXE!"=="" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    echo     ✔ Python 3.12.10 instalado
)
echo.

:: ─────────────────────────────────────────────────────────────────
::  PASO 3 — Entorno virtual
:: ─────────────────────────────────────────────────────────────────
echo [3/8] Creando entorno virtual (venv)...
cd /d "%PROJECT_ROOT%"

if exist "venv\Scripts\activate.bat" (
    echo     ✔ Entorno virtual ya existe
) else (
    "!PYTHON_EXE!" -m venv venv
    if errorlevel 1 (echo  ❌ ERROR: No se pudo crear el entorno virtual. & pause & exit /b 1)
    echo     ✔ Entorno virtual creado en venv\
)

set "VENV_PYTHON=%PROJECT_ROOT%\venv\Scripts\python.exe"
set "VENV_PIP=%PROJECT_ROOT%\venv\Scripts\pip.exe"
call "%PROJECT_ROOT%\venv\Scripts\activate.bat"
echo.

:: ─────────────────────────────────────────────────────────────────
::  PASO 4 — Actualizar pip + wheel + setuptools
:: ─────────────────────────────────────────────────────────────────
echo [4/8] Actualizando pip, wheel y setuptools...
"!VENV_PYTHON!" -m pip install --upgrade pip setuptools wheel --quiet
echo     ✔ Herramientas base actualizadas
echo.

:: ─────────────────────────────────────────────────────────────────
::  PASO 5 — PyAudio (requiere binario pre-compilado)
::  ctransformers en Windows puede ser complicado — instalamos primero
:: ─────────────────────────────────────────────────────────────────
echo [5/8] Pre-instalando paquetes con binarios nativos...

:: PyAudio — instalacion limpia de binarios de audio
"!VENV_PIP!" install "PyAudio" --quiet 2>nul
"!VENV_PYTHON!" -c "import pyaudio" 2>nul
if errorlevel 1 (
    "!VENV_PIP!" install pipwin --quiet 2>nul
    "!VENV_PYTHON!" -c "import pipwin; pipwin.install('pyaudio')" 2>nul
)
"!VENV_PYTHON!" -c "import pyaudio" 2>nul
if errorlevel 1 (
    echo     ⚠ PyAudio no pudo instalarse automaticamente. Voz STT puede no funcionar.
    echo       Instala manualmente: pip install PyAudio
) else (
    echo     ✔ PyAudio instalado correctamente
)

:: ctransformers — motor de inferencia local GGUF (CPU)
echo       Instalando ctransformers ^(motor LLM local^)...
"!VENV_PIP!" install ctransformers --quiet 2>nul || echo     ⚠ ctransformers: instalacion parcial ^(opcional^)
echo.

:: ─────────────────────────────────────────────────────────────────
::  PASO 6 — Instalar todas las dependencias
:: ─────────────────────────────────────────────────────────────────
echo [6/8] Instalando dependencias desde requirements.txt...
echo       ^(Puede tardar 5-15 minutos^)
echo.
"!VENV_PIP!" install -r "%PROJECT_ROOT%\requirements.txt"
if errorlevel 1 (
    echo.
    echo  ⚠ Algunos paquetes fallaron. Instalando criticos individualmente...
    "!VENV_PIP!" install fastapi "uvicorn[standard]" python-multipart httpx pywebview numpy pillow psutil
    "!VENV_PIP!" install duckduckgo-search requests kokoro-onnx soundfile SpeechRecognition
    "!VENV_PIP!" install opencv-python playwright pyautogui pyperclip comtypes pycaw
    "!VENV_PIP!" install uiautomation pywin32 paho-mqtt pyserial fastembed faiss-cpu lxml rapidocr-onnxruntime
    "!VENV_PIP!" install pytest pytest-asyncio
    echo.
    echo  ⚠ Revisa errores arriba. Algunos paquetes opcionales pueden faltar.
) else (
    echo     ✔ Todas las dependencias instaladas
)
echo.

:: ─────────────────────────────────────────────────────────────────
::  PASO 7 — Playwright Chromium (web automation)
:: ─────────────────────────────────────────────────────────────────
echo [7/8] Instalando navegador Chromium para Playwright...
echo       ^(~150 MB — puede tardar unos minutos^)
"!VENV_PYTHON!" -m playwright install chromium
if errorlevel 1 (
    echo  ⚠ Chromium no instalado. Ejecuta manualmente:
    echo    venv\Scripts\python -m playwright install chromium
) else (
    echo     ✔ Chromium de Playwright instalado
)
echo.

:: ─────────────────────────────────────────────────────────────────
::  PASO 8 — Configuracion inicial
:: ─────────────────────────────────────────────────────────────────
echo [8/8] Configuracion inicial...

:: Crear carpeta Data si no existe
if not exist "%PROJECT_ROOT%\Data" (
    mkdir "%PROJECT_ROOT%\Data"
    echo     ✔ Carpeta Data\ creada
)

:: Copiar Keys.env desde template si no existe
if not exist "%PROJECT_ROOT%\Keys.env" (
    if exist "%PROJECT_ROOT%\Keys.env.template" (
        copy "%PROJECT_ROOT%\Keys.env.template" "%PROJECT_ROOT%\Keys.env" >nul
        echo     ✔ Keys.env creado desde template
    )
) else (
    echo     ✔ Keys.env ya existe
)
echo.

:: ─────────────────────────────────────────────────────────────────
::  VERIFICACION FINAL
:: ─────────────────────────────────────────────────────────────────
echo  ═══════════════════════════════════════════════════════════════
echo   VERIFICACION FINAL DEL ENTORNO WIS
echo  ═══════════════════════════════════════════════════════════════
echo.

set "PYTHONIOENCODING=utf-8"

"!VENV_PYTHON!" --version 2>nul && echo   ✅ Python: OK || echo   ❌ Python: ERROR
"!VENV_PYTHON!" -c "import fastapi; print('  ✅ fastapi:', fastapi.__version__)"  2>nul || echo   ❌ fastapi: NO INSTALADO
"!VENV_PYTHON!" -c "import uvicorn; print('  ✅ uvicorn: OK')"                    2>nul || echo   ❌ uvicorn: NO INSTALADO
"!VENV_PYTHON!" -c "import numpy; print('  ✅ numpy:', numpy.__version__)"        2>nul || echo   ❌ numpy: NO INSTALADO
"!VENV_PYTHON!" -c "import cv2; print('  ✅ opencv: OK')"                         2>nul || echo   ⚠ opencv: no disponible
"!VENV_PYTHON!" -c "import pyautogui; print('  ✅ pyautogui: OK')"                2>nul || echo   ⚠ pyautogui: no disponible
"!VENV_PYTHON!" -c "import serial; print('  ✅ pyserial: OK')"                    2>nul || echo   ⚠ pyserial: no disponible
"!VENV_PYTHON!" -c "import paho.mqtt.client; print('  ✅ paho-mqtt: OK')"         2>nul || echo   ⚠ paho-mqtt: no disponible
"!VENV_PYTHON!" -c "import playwright; print('  ✅ playwright: OK')"              2>nul || echo   ⚠ playwright: no disponible
"!VENV_PYTHON!" -c "import speech_recognition; print('  ✅ SpeechRecognition: OK')" 2>nul || echo   ⚠ SpeechRecognition: no disponible
"!VENV_PYTHON!" -c "import fastembed; print('  ✅ fastembed: OK')"                2>nul || echo   ⚠ fastembed: no disponible
"!VENV_PYTHON!" -c "import faiss; print('  ✅ faiss-cpu: OK')"                    2>nul || echo   ⚠ faiss-cpu: no disponible
"!VENV_PYTHON!" -c "import lxml; print('  ✅ lxml: OK')"                         2>nul || echo   ⚠ lxml: no disponible
"!VENV_PYTHON!" -c "import pywebview; print('  ✅ pywebview: OK')"                2>nul || echo   ⚠ pywebview: no disponible
"!VENV_PYTHON!" -c "import ctransformers; print('  ✅ ctransformers: OK')"       2>nul || echo   ⚠ ctransformers: no disponible
"!VENV_PYTHON!" -c "import rapidocr_onnxruntime; print('  ✅ rapidocr: OK')"      2>nul || echo   ⚠ rapidocr: no disponible
"!VENV_PYTHON!" -c "import kokoro_onnx; print('  ✅ kokoro-onnx: OK')"            2>nul || echo   ⚠ kokoro-onnx: no disponible

echo.
if exist "%PROJECT_ROOT%\Keys.env" (
    echo   ✅ Keys.env: OK
) else (
    echo   ❌ Keys.env: AUSENTE — copia Keys.env.template a Keys.env y agrega tu API key
)
if exist "%PROJECT_ROOT%\Data" (
    echo   ✅ Carpeta Data\: OK
) else (
    echo   ⚠ Carpeta Data\: pendiente ^(se crea al primer arranque^)
)

echo.
echo  ╔═══════════════════════════════════════════════════════════════╗
echo  ║   ✅  WIS v3.0 instalado y listo.                            ║
echo  ║                                                               ║
echo  ║   IMPORTANTE: Edita Keys.env y pon tu API key:               ║
echo  ║   DEEPSEEK_API_KEY=sk-tu-clave-aqui                          ║
echo  ║                                                               ║
echo  ║   PARA INICIAR WIS:                                           ║
echo  ║   Modo Web Console:   venv\Scripts\python main.py --server   ║
echo  ║   Modo CLI:           venv\Scripts\python main.py --cli      ║
echo  ║   Abrir en browser:   http://localhost:7777                  ║
echo  ║                                                               ║
echo  ║   Modo mock hardware: venv\Scripts\python mock_server.py     ║
echo  ║   Tests:              venv\Scripts\python -m pytest tests\   ║
echo  ╚═══════════════════════════════════════════════════════════════╝
echo.
pause
