# 📦 Manual de Instalación y Despliegue de WIS v2.0

Este documento describe los requisitos, métodos de instalación y configuración de claves para poner en marcha el sistema cognitivo **WIS** en entornos Windows.

---

## 📋 Requisitos del Sistema

- **Sistema Operativo:** Windows 10 / 11 (64-bit).
- **Python:** Versión 3.10, 3.11 o 3.12 (recomendado Python 3.11 o 3.12).
- **Visual C++ Redistributable 2022 (x64):** Indispensable para librerías nativas de audio (`soundfile`, `kokoro-onnx`) y visión (`opencv-python`).
- **Memoria RAM:** Mínimo 8 GB (Recomendado 16 GB).
- **Espacio en Disco:** ~3.5 GB libres (incluyendo librerías y navegador Playwright Chromium).

---

## ⚡ Métodos de Instalación

Existen 3 formas de instalar WIS dependiendo de tu entorno:

### Método 1: Instalación Automática Completa (`instalar.bat`)
> **Recomendado para PCs limpias o nuevas.**

Doble clic en [instalar.bat](file:///d:/WIS/instalar.bat) o ejecútalo en CMD / PowerShell:
```bat
instalar.bat
```
**Este script se encarga de todo de forma 100% desatendida:**
1. Detecta y descarga automáticamente el instalador de Visual C++ Redistributable si falta en el sistema.
2. Comprueba si Python 3.10+ existe; de no ser así, descarga e instala Python 3.12 silenciosamente.
3. Genera el entorno virtual `venv\`.
4. Instala librerías complejas con binarios nativos (`PyAudio`, `ctransformers`).
5. Instala las 54 dependencias desde `requirements.txt`.
6. Descarga el navegador Chromium de Playwright para automatización web.
7. Crea las carpetas de datos `Data/` y genera la plantilla `Keys.env`.

---

### Método 2: Instalación Rápida con Python Previo (`setup.bat`)
> **Ideal si ya tienes Python 3.10+ instalado en tu máquina.**

Doble clic en [setup.bat](file:///d:/WIS/setup.bat) o ejecútalo en PowerShell:
```bat
setup.bat
```
**Qué realiza:**
1. Crea el entorno virtual `venv\` en el directorio raíz.
2. Prepara la carpeta `Data/` y copia `Keys.env.template` a `Keys.env`.
3. Actualiza `pip` e instala todas las dependencias de `requirements.txt`.
4. Descarga los binarios de Chromium de Playwright.

---

### Método 3: Instalación Manual (PowerShell Paso a Paso)

Si prefieres realizar el proceso comando por comando:

```powershell
# 1. Posicionarse en la carpeta del proyecto
cd D:\WIS

# 2. Crear entorno virtual
python -m venv venv

# 3. Actualizar herramientas base
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel

# 4. Instalar todas las dependencias
venv\Scripts\pip.exe install -r requirements.txt

# 5. Instalar navegador Chromium para Playwright
venv\Scripts\python.exe -m playwright install chromium

# 6. Crear carpetas de runtime
if (-not (Test-Path Data)) { New-Item -ItemType Directory -Path Data }
if (-not (Test-Path Keys.env)) { Copy-Item Keys.env.template Keys.env }
```

---

## 🔑 Configuración de Claves de API (`Keys.env`)

WIS requiere acceso a un proveedor de LLM para su razonamiento agéntico.

Abre el archivo [Keys.env](file:///d:/WIS/Keys.env) generado en la raíz del proyecto y agrega tus claves:

### Opción A: DeepSeek (Recomendado — Alta velocidad y bajo costo)
```env
DEEPSEEK_API_KEY=sk-tu-clave-real-aqui
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

### Opción B: OpenRouter (Múltiples modelos: Claude, GPT-4o, Llama 3)
```env
OPENROUTER_API_KEY=sk-or-v1-tu-clave-real-aqui
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=deepseek/deepseek-chat
```

### Opción C: ZhipuAI / GLM
```env
ZHIPUAI_API_KEY=tu-clave-zhipu-aqui
```

---

## 🚀 Formas de Iniciar WIS

Elige el modo de ejecución que mejor se adapte a tu flujo de trabajo:

### 1. Modo Consola AGI Nativa (Experiencia Gráfica Completa)
Abre la ventana nativa pywebview acelerada por GPU, con scanlines CRT, barra de arrastre y motor multi-ventana:
```powershell
venv\Scripts\python.exe main.py
```

### 2. Modo Servidor Web (Acceso por Navegador)
Arranca el backend FastAPI y permite abrir la interfaz en cualquier navegador:
```powershell
venv\Scripts\python.exe main.py --server
```
Accede desde tu navegador en:  
👉 **`http://localhost:7777`** (o `http://localhost:8770/console/`)

### 3. Modo CLI (Terminal Pura / Servidores sin pantalla)
Interacción directa por línea de comandos sin abrir navegador ni ventanas:
```powershell
venv\Scripts\python.exe main.py --cli
```

---

## 🛠️ Diagnóstico y Solución de Problemas Frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| `HTTP 401 Unauthorized: Your api key: ****aqui is invalid` | Clave de API no configurada en `Keys.env`. | Abre `Keys.env` y reemplaza el texto de plantilla por tu clave real de DeepSeek u OpenRouter. |
| `cannot import name 'ScreenMarker'` | Discrepancia de nombre en motor SoM. | Ya resuelto en v2.0 mediante alias automático `ScreenMarker = DesktopSoM`. |
| `Playwright Host unreachable / Chromium missing` | Binarios del navegador no descargados. | Ejecuta `venv\Scripts\python.exe -m playwright install chromium`. |
| Error al compilar `PyAudio` | Falta Visual C++ o encabezados portaudio. | Ejecuta `instalar.bat` o descarga el wheel precompilado con `pip install PyAudio`. |
| `Local LLM generation failed: access violation` | Incompatibilidad de instrucciones AVX en ctransformers en Windows. | Se activa automáticamente cuando la clave de API remota falla; al configurar tu clave real en `Keys.env`, el sistema usará la nube con respuesta instantánea. |
