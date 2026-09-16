# ⚙️ WIS v3.0 — Operaciones, Despliegue y Mantenimiento

Este documento constituye el **Manual de Operaciones y Runbook** de WIS v3.0 para entornos Windows en producción, laboratorio de desarrollo y bancos de prueba de hardware.

---

## 1. Despliegue Rápido Automatizado ([instalar.bat](file:///d:/WIS/instalar.bat))

El repositorio incluye un script de instalación desatendido de 8 pasos que no requiere intervención humana:

```cmd
:: Desde la consola de Windows o doble clic:
instalar.bat
```

### ¿Qué ejecuta `instalar.bat` automáticamente?
1. **Visual C++ Redistributable 2022:** Comprueba en el registro de Windows si está presente; si falta, descarga silenciosamente el instalador oficial de Microsoft y lo aplica sin reiniciar.
2. **Python 3.10+:** Escanea la máquina en busca de intérpretes válidos; si no existe o es inferior a 3.10, descarga e instala silenciosamente Python 3.12.10 y añade las variables de entorno al usuario.
3. **Entorno Virtual (`venv`):** Crea el entorno virtual en `d:\WIS\venv\` si no existe.
4. **Herramientas Base:** Actualiza `pip`, `setuptools` y `wheel`.
5. **Binarios Nativos de Audio e Inferencia:** Instala `PyAudio` y `ctransformers` (motor GGUF de CPU).
6. **Dependencias del Ecosistema:** Instala todos los paquetes de `requirements.txt` (incluyendo `faiss-cpu`, `lxml`, `rapidocr-onnxruntime`, `fastapi`, `pywebview`, etc.).
7. **Navegador Chromium de Playwright:** Descarga los binarios de Chromium para la automatización web headless.
8. **Estructura de Datos y Credenciales:** Inicializa la carpeta `Data/` y genera `Keys.env` a partir de `Keys.env.template`.

---

## 2. Configuración de Credenciales (`Keys.env`)

WIS requiere configurar al menos un proveedor de LLM en el archivo `Keys.env`:

```env
# =============================================================================
# WIS v3.0 - Variables de Entorno y Claves de API
# =============================================================================

# --- Proveedor Primario (Recomendado: DeepSeek V3) ---
DEEPSEEK_API_KEY=sk-tu-clave-aqui
DEEPSEEK_BASE_URL=https://api.deepseek.com

# --- Proveedores Opcionales / Fallback ---
OPENROUTER_API_KEY=
ZHIPUAI_API_KEY=
OPENAI_API_KEY=

# --- Configuración de Red del Servidor ---
WIS_SERVER_HOST=127.0.0.1
WIS_SERVER_PORT=7777
WIS_CONSOLE_AUTH_TOKEN=auto_generate_if_empty

# --- Broker MQTT (Para laboratorio de Hardware) ---
MQTT_BROKER_HOST=127.0.0.1
MQTT_BROKER_PORT=1883
```

---

## 3. Modo 100% Offline / CPU Local

WIS puede funcionar de manera autónoma sin conexión a Internet:
1. Asegúrate de que el modelo local exista en `models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf`.
2. En `config/settings.json`, establece:
   ```json
   {
     "llm": {
       "provider": "local",
       "local_model_path": "models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
     }
   }
   ```
3. El FastPath (Path 0), los embeddings locales de MiniLM (Path 1), el caché FAISS (Path 2) y la síntesis de voz Kokoro-82M seguirán operando a máxima velocidad sin tocar servidores externos.

---

## 4. Ejecución del Sistema

### Modo A: Interfaz de Escritorio Nativa (Recomendado)
```powershell
python main.py
```
Abre la consola en una ventana PyWebView nativa con aceleración gráfica y paleta oscura.

### Modo B: Servidor Web Standalone
```powershell
python main.py --server
```
Inicia el backend en `http://127.0.0.1:7777/console/`. Ideal para conectarse desde navegadores externos o monitores secundarios.

### Modo C: Terminal CLI Puro
```powershell
python main.py --cli
```
Sesión interactiva en la consola de comandos de PowerShell/cmd para depuración directa sin interfaz gráfica.

---

## 5. Ejecución del Banco de Pruebas Automatizadas

Para validar la integridad completa del sistema tras una modificación:

```powershell
# Ejecución completa de todos los tests (unidad e integración):
python -m pytest tests/ -v

# Ejecución rápida de la prueba de humo del stack completo:
python -m pytest tests/test_smoke_refactor.py -v

# Ejecución con cobertura:
python -m pytest --cov=core --cov=abilities tests/
```

Todos los 34 tests del sistema deben pasar en verde (`34 passed`).

---

## 6. Guía de Diagnóstico y Resolución de Problemas (Troubleshooting)

| Síntoma | Causa Probable | Solución |
|---|---|---|
| **`Error 403 Forbidden` en `/api/auth/bootstrap`** | Solicitud desde IP remota o User-Agent no local | El endpoint solo acepta conexiones loopback (`127.0.0.1`, `localhost`). Para clientes remotos, obtén el token desde la consola de arranque y pásalo en el header `Authorization: Bearer <token>`. |
| **`Port 7777 is already in use`** | Instancia previa de WIS no finalizada | Ejecuta en PowerShell: `Get-NetTCPConnection -LocalPort 7777 \| Select-Object -ExpandProperty OwningProcess \| Stop-Process -Force`. |
| **`SerialException: Access is denied` en puerto COM** | El puerto está abierto por el Monitor Serie de Arduino o PuTTY | Cierra cualquier otro software que esté bloqueando el puerto serie antes de conectar WIS. |
| **`pywebview` falla al arrancar la ventana** | Falta el runtime WebView2 de Microsoft | `main.py` detecta el fallo automáticamente y levanta el servidor web abriendo el navegador por defecto. Para tener la ventana nativa, instala el [WebView2 Evergreen Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/). |
| **Voz TTS no reproduce sonido** | El dispositivo de salida de audio predeterminado cambió | Verifica que el servicio de audio de Windows esté activo. Kokoro-82M generará el archivo WAV de todos modos en `Data/` y la consola web lo reproducirá por el navegador. |
