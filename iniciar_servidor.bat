@echo off
title WIS Core Server [Modo Persistente]
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ===================================================
echo     W I S  v3.0 - Servidor de Consola Web
echo ===================================================
echo.

set "PY_BIN="
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_BIN=%~dp0venv\Scripts\python.exe"
) else (
    set "PY_BIN=python"
)

echo Iniciando servidor backend continuo...
echo Puedes abrir la consola web en: http://127.0.0.1:7777/console/
echo.
echo Presiona Ctrl+C en esta ventana para detener el servidor.
echo ===================================================
echo.

"!PY_BIN!" main.py --server

pause
