# WIS - Wisdom Integrated System (v3.0)

<p align="center">
  <b>Living Autonomous Companion & Cognitive Operating System Core for Developers</b><br>
  <i>Deep ReAct Loop, AVRORA Developer Engine, Multi-Path Cognition, Hardware Topologies & Hacker Terminal</i>
</p>

> 📚 **Documentación de Ingeniería Completa:** Consulta la carpeta [`ingenieria/`](file:///d:/WIS/ingenieria/00_INDICE_Y_RESUMEN_EJECUTIVO.md) para acceder a los diagramas de arquitectura, matriz de 19 habilidades, protocolos de hardware y manual de despliegue.

---

## 🌟 Overview

**WIS (Wisdom Integrated System) v3.0** is an advanced cognitive operating system and autonomous AI neuro-system designed specifically for hardware and software developers.

---

## 🚀 Key Features

- 🧠 **Hybrid Cognitive Core & Multi-tier LLM Routing:**
  - Fast response reflex layer and episodic memory database (`wis_memory.db`).
  - Native support for Cloud LLMs (DeepSeek, OpenRouter, ZhipuAI) and Local CPU LLM inference (`ctransformers` / GGUF).
  - Autonomous goal decomposition and multi-step execution loop (`core/pipeline.py`, `core/goal_manager.py`).

- 🎙️ **High-Performance Voice & Audio Subsystem:**
  - Ultra-fast, natural speech synthesis powered by **Kokoro ONNX** (`abilities/voice.py`).
  - Voice recognition and transcription via **SpeechRecognition** & **Faster-Whisper** (`abilities/listen.py`).

- 👁️ **Vision & Desktop Automation:**
  - Screen capture, visual analysis, OCR, and GUI element recognition (`abilities/vision.py`).
  - Native Windows desktop automation using `pyautogui`, `uiautomation`, and audio control via `pycaw`.
  - Full headless/headed browser control using `Playwright` (`abilities/browser.py`).

- ⚡ **Hardware & IoT Protocol Suite:**
  - Real-time **Serial / UART** communications (`abilities/serial_comm.py`).
  - **MQTT** client for telemetry ingestion and IoT trigger evaluation (`abilities/mqtt_comm.py`, `core/telemetry.py`).

- 🛠️ **Self-Extension & Dynamic Abilities:**
  - Meta-programming ability builder (`abilities/builder.py`) and integration discovery (`abilities/discovery.py`).
  - Dynamic loading of custom user abilities (`abilities/custom/`).

- 💻 **Modern Web Console & Native Window:**
  - Interactive web interface served via FastAPI (`http://localhost:7777`).
  - Native desktop window support via `pywebview` (`console/web_view.py`).

---

## 📂 Project Architecture

```
WIS/
├── abilities/              # Modular ability plugins
│   ├── browser.py          # Playwright browser automation
│   ├── builder.py          # Meta-programming ability generator
│   ├── desktop.py          # Desktop control & OS management
│   ├── discovery.py        # Autonomous discovery engine
│   ├── file_manager.py     # Native filesystem operations
│   ├── knowledge.py        # Knowledge base & document query
│   ├── listen.py           # Speech-to-Text (STT) engine
│   ├── mqtt_comm.py        # MQTT IoT client
│   ├── registry.py         # Abilities registry & dispatcher
│   ├── serial_comm.py      # Serial/UART communication
│   ├── system.py           # System diagnostics & execution
│   ├── vision.py           # Computer vision & screen analysis
│   ├── voice.py            # Neural TTS engine (Kokoro ONNX)
│   └── web_search.py       # DuckDuckGo search integration
├── config/                 # Configurations & persona
│   ├── identity.md         # Persona directives & voice profile
│   └── settings.json       # System configurations
├── console/                # Web console server & UI
│   ├── web/                # Frontend (HTML, CSS, JS)
│   ├── server.py           # FastAPI backend server
│   └── web_view.py         # PyWebView desktop launcher
├── core/                   # Core cognitive OS architecture
│   ├── dependencies.py     # Auto-installer for dependencies
│   ├── event_bus.py        # Asynchronous event bus
│   ├── goal_manager.py     # Goal planner & subtask tracker
│   ├── identity.py         # Identity prompt manager
│   ├── llm_client.py       # Multi-model LLM router & Local CPU engine
│   ├── memory.py           # Episodic & semantic memory store
│   ├── pipeline.py         # Main cognition & execution pipeline
│   ├── proactivity.py      # Proactive trigger engine
│   ├── reasoning.py        # Planning & chain-of-thought engine
│   ├── safety.py           # Aegis safety & permission guardrails
│   ├── skill_memory.py     # Reflex skill & action cache
│   └── telemetry.py        # Real-time telemetry ingestion engine
├── Data/                   # Local databases and runtime state (git ignored)
├── Keys.env.template       # Environment keys template
├── main.py                 # Entry point (CLI & GUI server)
├── mock_server.py          # Testing & mock hardware server
├── requirements.txt        # Python dependency manifest
└── setup.bat               # Automated one-click Windows setup
```

---

## 📚 Documentación Técnica

- 🏛️ **[Arquitectura del Sistema](file:///d:/WIS/docs/ARQUITECTURA.md)**: Diagramas Mermaid, flujo ReAct, Long-Horizon daemon, AVRORA PC Engine y canal WebSocket.
- 📦 **[Manual de Instalación y Despliegue](file:///d:/WIS/docs/INSTALACION.md)**: Guía paso a paso, solución de problemas y configuración de proveedores LLM.

---

## ⚡ Quick Start (Windows)

### 1. Instalación Automática
Ejecuta el instalador desatendido de WIS v3.0 (verifica Python, entorno virtual y dependencias automáticamente):
```cmd
instalar.bat
```

### 2. Configurar Claves de API (`Keys.env`)
Edita `Keys.env` y coloca tu API key:
```env
DEEPSEEK_API_KEY=sk-tu-clave-aqui
```

### 3. Iniciar WIS

#### Modo Ventana Nativa AGI (Recomendado)
Abre la consola nativa frameless con aceleración gráfica y motor multi-ventana:
```powershell
venv\Scripts\python.exe main.py
```

#### Modo Servidor Web
Arranca el servidor FastAPI accesible desde el navegador:
```powershell
venv\Scripts\python.exe main.py --server
```
Acceso en el navegador: **`http://localhost:7777`**

#### Modo CLI (Terminal Pura)
```powershell
venv\Scripts\python.exe main.py --cli
```

---

## 🛡️ Safety & Security (Aegis)

WIS features built-in security profiles configured in `config/settings.json`:
- **Privileged Mode:** Full autonomous operation with security boundary checking.
- **Strict Mode:** Requires manual confirmation for sensitive actions (filesystem write/delete, shell execution).

---

## 📄 License

This project is developed for cognitive robotics, hardware integration, and autonomous assistance. All rights reserved.
