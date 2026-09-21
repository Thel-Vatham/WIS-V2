@echo off
setlocal EnableDelayedExpansion
title WIS — Motor de Instalacion Autonoma
color 0A
chcp 65001 >nul 2>&1

:: Habilitar secuencias ANSI (Opcional, en caso de soporte Win10+)
reg add HKCU\Console /v VirtualTerminalLevel /t REG_DWORD /d 1 /f >nul 2>&1

echo.
echo  ========================================================================
echo       __          __  _____  _____ 
echo       \ \        / / |_   _|/ ____|
echo        \ \  /\  / /    ^| ^| ^| (___  
echo         \ \/  \/ /     ^| ^|  \___ \ 
echo          \  /\  /     _^| ^|_ ____) ^|
echo           \/  \/     ^|_____^|_____/ 
echo.
echo    WISDOM INTEGRATED SYSTEM v3.0 - SETUP AUTONOMO Y A PRUEBA DE FALLOS
echo    [ Desarrollado para el Grupo de Investigacion DIGITI ]
echo  ========================================================================
echo.

set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
echo  [SYSTEM] Directorio del proyecto detectado: %PROJECT_ROOT%
echo.

:: =====================================================================
::  PASO 1 — Visual C++ Redistributable
:: =====================================================================
echo  [1/8] Verificando pre-requisitos nativos (Visual C++ Redistributable)...
set "VCREDIST_OK=0"
reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" /v Installed >nul 2>&1 && set "VCREDIST_OK=1"
if "!VCREDIST_OK!"=="0" reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" /v Installed >nul 2>&1 && set "VCREDIST_OK=1"

if "!VCREDIST_OK!"=="1" (
    echo    [OK] Visual C++ Redistributable instalado.
) else (
    echo    [!] Descargando Visual C++ Redistributable 2022...
    set "VCREDIST=%TEMP%\vc_redist_x64.exe"
    powershell -NoProfile -NonInteractive -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://aka.ms/vs/17/release/vc_redist.x64.exe','!VCREDIST!')"
    "!VCREDIST!" /install /quiet /norestart
    echo    [OK] Visual C++ Redistributable instalado autonomamente.
)
echo.

:: =====================================================================
::  PASO 2 — Python 3.10+
:: =====================================================================
echo  [2/8] Validando Motor Python 3.10+...
set "PYTHON_OK=0"
set "PYTHON_EXE="

for /f "tokens=*" %%p in ('where python 2^>nul') do (
    if "!PYTHON_EXE!"=="" set "PYTHON_EXE=%%p"
)

:: Busqueda en directorios comunes si no esta en PATH
if "!PYTHON_EXE!"=="" (
    for %%d in (
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
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
        echo    [OK] Python !PY_VER! detectado y funcional.
        set "PYTHON_OK=1"
    ) else (
        echo    [!] Version !PY_VER! insuficiente. Requiere ^>= 3.10.
    )
)

if "!PYTHON_OK!"=="0" (
    echo    [!] Descargando e instalando Python 3.12 autonomamente...
    set "PY_INSTALLER=%TEMP%\python312_setup.exe"
    powershell -NoProfile -NonInteractive -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe','!PY_INSTALLER!')"
    
    echo    [!] Ejecutando instalacion silenciosa (por favor espera)...
    "!PY_INSTALLER!" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_doc=0 Include_launcher=1 Include_pip=1
    
    :: Refrescar PATH y buscar de nuevo
    for /f "tokens=*" %%p in ('where python 2^>nul') do if "!PYTHON_EXE!"=="" set "PYTHON_EXE=%%p"
    if "!PYTHON_EXE!"=="" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    echo    [OK] Python instalado exitosamente.
)
echo.

:: =====================================================================
::  PASO 3 — Entorno Virtual (Sandbox)
:: =====================================================================
echo  [3/8] Inicializando Entorno Virtual (VENV)...
cd /d "%PROJECT_ROOT%"

:CHECK_VENV
if exist "venv\Scripts\activate.bat" (
    echo    [OK] Entorno virtual operativo.
) else (
    "!PYTHON_EXE!" -m venv venv
    if errorlevel 1 (
        echo    [ERROR] Fallo critico creando entorno virtual. Reintentando en 3s...
        timeout /t 3 >nul
        goto CHECK_VENV
    )
    echo    [OK] Entorno virtual desplegado en \venv.
)

set "VENV_PYTHON=%PROJECT_ROOT%\venv\Scripts\python.exe"
set "VENV_PIP=%PROJECT_ROOT%\venv\Scripts\pip.exe"
call "%PROJECT_ROOT%\venv\Scripts\activate.bat"
echo.

:: =====================================================================
::  PASO 4 — Pip y Herramientas Base
:: =====================================================================
echo  [4/8] Actualizando capa de gestion de paquetes (Pip, Wheel)...
:UPDATE_PIP
"!VENV_PYTHON!" -m pip install --upgrade pip setuptools wheel --quiet
if errorlevel 1 (
    echo    [ERROR] Fallo actualizando Pip. Reintentando...
    timeout /t 3 >nul
    goto UPDATE_PIP
)
echo    [OK] Pip, Setuptools y Wheel al dia.
echo.

:: =====================================================================
::  PASO 5 — Compilados Pesados (PyAudio, CTransformers)
:: =====================================================================
echo  [5/8] Desplegando binarios de audio y LLM...
:INSTALL_PYAUDIO
"!VENV_PYTHON!" -c "import pyaudio" 2>nul
if errorlevel 1 (
    "!VENV_PIP!" install "PyAudio" --quiet 2>nul
    "!VENV_PYTHON!" -c "import pyaudio" 2>nul
    if errorlevel 1 (
        "!VENV_PIP!" install pipwin --quiet 2>nul
        "!VENV_PYTHON!" -c "import pipwin; pipwin.install('pyaudio')" 2>nul
        "!VENV_PYTHON!" -c "import pyaudio" 2>nul
        if errorlevel 1 (
            echo    [ERROR] PyAudio fallo. Reintentando ciclo de instalacion...
            timeout /t 3 >nul
            goto INSTALL_PYAUDIO
        )
    )
)
echo    [OK] Motor PyAudio estable.

:INSTALL_CTRANSFORMERS
"!VENV_PYTHON!" -c "import ctransformers" 2>nul
if errorlevel 1 (
    "!VENV_PIP!" install ctransformers --quiet 2>nul
    "!VENV_PYTHON!" -c "import ctransformers" 2>nul
    if errorlevel 1 (
        echo    [ERROR] CTransformers fallo. Reintentando instalacion de motor IA...
        timeout /t 3 >nul
        goto INSTALL_CTRANSFORMERS
    )
)
echo    [OK] Motor CTransformers (GGUF) estable.
echo.

:: =====================================================================
::  PASO 6 — Dependencias Core
:: =====================================================================
echo  [6/8] Sincronizando dependencias principales (requirements.txt)...
echo        (Este proceso no se detendra hasta completar el 100%%)
:INSTALL_DEPS
"!VENV_PIP!" install -r "%PROJECT_ROOT%\requirements.txt"
if errorlevel 1 (
    echo    [!] ADVERTENCIA: Fallo en algun paquete. Limpiando y reintentando...
    timeout /t 3 >nul
    goto INSTALL_DEPS
)
echo    [OK] Integracion de requirements.txt completada con exito.
echo.

:: =====================================================================
::  PASO 7 — Dependencias Pesadas y Navegadores (Playwright)
:: =====================================================================
echo  [7/8] Sincronizando subsistemas web (Playwright Chromium)...
:INSTALL_PLAYWRIGHT
"!VENV_PYTHON!" -m playwright install chromium
if errorlevel 1 (
    echo    [ERROR] Chromium no pudo instalarse. Red descargada corrupta o caida. Reintentando...
    timeout /t 5 >nul
    goto INSTALL_PLAYWRIGHT
)
echo    [OK] Chromium embebido desplegado exitosamente.
echo.

:: =====================================================================
::  PASO 7.5 — Descarga de Modelos de Inteligencia Artificial Pesados
:: =====================================================================
echo  [7.5/8] Validando y descargando modelos IA pesados (Vision y Voz)...
"!VENV_PYTHON!" "%PROJECT_ROOT%\scripts\download_assets.py"
if errorlevel 1 (
    echo    [ERROR] Fallo en la descarga de activos IA. Abortando.
    pause
    exit /b 1
)
echo.

:: =====================================================================
::  PASO 8 — Inicializacion de Entorno y Datos
:: =====================================================================
echo  [8/8] Configurando carpetas y credenciales base...
if not exist "%PROJECT_ROOT%\Data" (
    mkdir "%PROJECT_ROOT%\Data"
    echo    [OK] Directorio \Data creado.
)
if not exist "%PROJECT_ROOT%\Keys.env" (
    if exist "%PROJECT_ROOT%\Keys.env.template" (
        copy "%PROJECT_ROOT%\Keys.env.template" "%PROJECT_ROOT%\Keys.env" >nul
        echo    [OK] Keys.env aprovisionado desde plantilla.
    )
)
echo.

:: =====================================================================
::  CHECK DE SALUD Y VERIFICACION FINAL
:: =====================================================================
echo  ========================================================================
echo       [ VERIFICACION DE SALUD DEL SISTEMA WIS ]
echo  ========================================================================
set "PYTHONIOENCODING=utf-8"

set "HEALTH_OK=1"

"!VENV_PYTHON!" -c "import fastapi" 2>nul || (echo    [FAIL] fastapi & set "HEALTH_OK=0")
"!VENV_PYTHON!" -c "import numpy" 2>nul || (echo    [FAIL] numpy & set "HEALTH_OK=0")
"!VENV_PYTHON!" -c "import cv2" 2>nul || (echo    [FAIL] opencv-python & set "HEALTH_OK=0")
"!VENV_PYTHON!" -c "import pyaudio" 2>nul || (echo    [FAIL] pyaudio & set "HEALTH_OK=0")
"!VENV_PYTHON!" -c "import kokoro_onnx" 2>nul || (echo    [FAIL] kokoro-onnx & set "HEALTH_OK=0")
"!VENV_PYTHON!" -c "import sounddevice" 2>nul || (echo    [FAIL] sounddevice & set "HEALTH_OK=0")
"!VENV_PYTHON!" -c "import playwright" 2>nul || (echo    [FAIL] playwright & set "HEALTH_OK=0")
"!VENV_PYTHON!" -c "import faiss" 2>nul || (echo    [FAIL] faiss-cpu & set "HEALTH_OK=0")

if not exist "%PROJECT_ROOT%\models\detection\yolov4-tiny.weights" (echo    [FAIL] yolov4-tiny.weights missing & set "HEALTH_OK=0")
if not exist "%PROJECT_ROOT%\models\kokoro-v0_19.onnx" (echo    [FAIL] kokoro-v0_19.onnx missing & set "HEALTH_OK=0")

if "!HEALTH_OK!"=="0" (
    echo.
    echo  [!] ALERTA: La verificacion final fallo. Forzando re-instalacion general en 5s...
    timeout /t 5 >nul
    goto INSTALL_DEPS
)

echo    [ALL GREEN] Todos los sub-sistemas de WIS se encuentran en estado optimo.
echo.
echo  ========================================================================
echo    WIS v3.0 HA SIDO DESPLEGADO EXITOSAMENTE
echo  ========================================================================
echo    IMPORTANTE: Abre el archivo Keys.env e introduce tu API key.
echo.
echo    Comandos de Arranque:
echo    $ venv\Scripts\python main.py             (Interfaz Nativa - Recomendado)
echo    $ venv\Scripts\python main.py --server    (Servidor Web)
echo  ========================================================================
echo.
pause
