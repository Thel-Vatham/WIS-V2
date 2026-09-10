# 📑 WIS v3.0 — Carpeta de Ingeniería
## Índice Maestro y Resumen Ejecutivo del Sistema

**Wisdom Integrated System (WIS) v3.0** es un sistema operativo cognitivo y sistema nervioso agéntico diseñado específicamente para desarrolladores e ingenieros de hardware/software. WIS unifica razonamiento LLM de vanguardia, control nativo de sistemas operativos (Windows/DWM/PowerShell), visión por computadora (SOM/OCR), compilación y flasheo de microcontroladores (Serial/MQTT/PlatformIO) y ejecución autónoma de tareas de largo horizonte bajo una interfaz terminal hacker de alta densidad.

---

### 🗂️ Estructura del Proyecto y Carga Útil (Payload)

La raíz de WIS ha sido auditada y depurada para contener estrictamente los módulos operativos requeridos por el sistema:

```
D:\WIS\
├── abilities/              # Catálogo de 19 habilidades nativas y dinámicas
│   ├── pc/                 # Motor de automatización PC de nivel SO (AVRORA)
│   │   ├── code_ability.py        # Intérprete Python, refactor AST, TDD runner
│   │   ├── desktop_ability.py     # Gestión de ventanas Win32, apps, procesos
│   │   ├── filesystem_ability.py  # Sandboxing, watcher de archivos, atomic writes
│   │   ├── screen_ability.py      # Visión SOM (Set-of-Marks) y OCR
│   │   └── advanced_desktop_ability.py # Orquestador de escritorio integrado
│   ├── browser.py          # Automatización web headless/headed (Playwright)
│   ├── custom/             # Directorio para habilidades generadas en runtime
│   ├── discovery.py        # Descubrimiento de APIs y schemas en caliente
│   ├── hardware_memory.py  # Device Graph y mapeo de pinouts SQLite
│   ├── mqtt_comm.py        # Cliente IoT MQTT con QoS 1/2 y telemetría
│   ├── registry.py         # Registro central de habilidades con hot-reload
│   ├── serial_comm.py      # Comunicación serie RS232/UART con ACK empírico
│   ├── toolchain.py        # PlatformIO, Arduino-CLI, esptool, git
│   ├── voice.py            # Síntesis TTS Kokoro-82M ONNX (0ms cloud)
│   ├── listen.py           # Reconocimiento de voz STT local/remoto
│   ├── vision.py           # Análisis visual multimodelo
│   └── web_search.py       # Motor de búsqueda web sin API keys
│
├── config/                 # Configuración del sistema
│   └── settings.json       # Parámetros de runtime, seguridad, modelos y puertos
│
├── console/                # Consola Hacker y Servidor Backend
│   ├── server.py           # Backend FastAPI (REST + WebSockets en tiempo real)
│   ├── web_view.py         # Ventana de escritorio nativa PyWebView frameless
│   └── web/                # Frontend terminal hacker (HTML5/CSS3/Vanilla JS)
│       ├── index.html      # Estructura terminal, side-panels y modal de seguridad
│       ├── style.css       # Estética cyberpunk/CRT, fuentes monospace, neon
│       └── app.js          # Conexión WebSocket, streams de DAG y telemetría
│
├── core/                   # Núcleo Cognitivo y Sistema Nervioso Agéntico
│   ├── event_bus.py        # Bus de eventos asíncrono pub/sub central
│   ├── goal_manager.py     # Gestor y planificador de metas operativas
│   ├── hardware_memory.py  # Base de datos relacional de hardware y pinouts
│   ├── llm_client.py       # Abstracción multimodelo (DeepSeek, OpenRouter, etc.)
│   ├── local_llm.py        # Motor LLM local offline para CPU (GGUF TinyLlama)
│   ├── long_horizon.py     # Motor de tareas largas en segundo plano con diario
│   ├── memory.py           # Memoria episódica y mnemónica
│   ├── mission.py          # Planificador de misiones DAG (grafos de dependencias)
│   ├── pipeline.py         # ActionPipeline Pure-LLM con tool calling paralelo y SkillMemory
│   ├── proactivity.py      # Motor proactivo autónomo basado en reglas
│   ├── reasoning.py        # ReasoningEngine / Cortex con prompting estricto en inglés
│   ├── safety.py           # Aegis Safety Policy (Modos Secure y Privileged)
│   ├── skill_memory.py     # Memoria de secuencias exitosas (FAISS IndexFlatIP)
│   ├── skill_synthesizer.py# Meta-programador de nuevas habilidades con sandbox AST
│   ├── swarm.py            # Coordinador de enjambre multi-agente
│   ├── task_store.py       # Persistencia SQLite para metas y subtareas
│   ├── telemetry.py        # Motor de ingestión de telemetría y umbrales de alerta
│   └── verifier.py         # MetaCognitive Verifier (anti-alucinación post-síntesis)
│
├── Data/                   # Bases de datos SQLite y memoria persistente
│   ├── wis_memory.db       # Hechos y conversaciones persistidas
│   ├── wis_hardware.db     # Device graph, topología y registros pinout
│   ├── wis_skills.db       # Rutinas aprendidas e indexadas
│   ├── wis_tasks.db        # Metas y subtareas del GoalManager
│   └── uploads/            # Archivos temporales e imágenes analizadas
│
├── ingenieria/             # Dossier de ingeniería y especificación técnica
│   ├── 00_INDICE_Y_RESUMEN_EJECUTIVO.md
│   ├── 01_ARQUITECTURA_COGNITIVA_Y_PIPELINE.md
│   ├── 02_MATRIZ_DE_HABILIDADES_Y_CAPACIDADES.md
│   ├── 03_MOTOR_DE_HARDWARE_Y_TELEMETRIA.md
│   ├── 04_INTERFAZ_HACKER_Y_API_SERVER.md
│   └── 05_OPERACIONES_DESPLIEGUE_Y_MANTENIMIENTO.md
│
├── models/                 # Modelos locales para inferencia en CPU
│   └── tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
│
├── tests/                  # Suite completa de pruebas automatizadas (34 tests)
│   ├── integration/        # Tests end-to-end (hardware synthesis, pipeline)
│   ├── unit/               # Tests unitarios por módulo (FastPath, SQLite, AST)
│   ├── test_smoke_refactor.py # Prueba de humo integral del stack refactorizado
│   └── conftest.py         # Fixtures de pytest para entornos asíncronos
│
├── instalar.bat            # Instalador desatendido 100% automático para Windows
├── Keys.env                # Llaves de API y configuración de credenciales
├── Keys.env.template       # Plantilla de variables de entorno
├── main.py                 # Punto de entrada universal del sistema
├── mock_server.py          # Simulador de hardware (puertos COM virtuales y MQTT)
└── requirements.txt        # Especificación de dependencias de Python
```

---

### 🧭 Documentos de Ingeniería en esta Carpeta

1. **[01. Arquitectura Cognitiva y Pipeline](file:///d:/WIS/ingenieria/01_ARQUITECTURA_COGNITIVA_Y_PIPELINE.md)**  
   Explica en detalle los 4 caminos cognitivos (Path 0 al 3), la paralelización de llamadas con `asyncio.gather`, el Verificador Metacognitivo, el lazo cerrado de telemetría y el motor de misiones DAG.

2. **[02. Matriz de Habilidades y Capacidades](file:///d:/WIS/ingenieria/02_MATRIZ_DE_HABILIDADES_Y_CAPACIDADES.md)**  
   Especificación formal de las 19 habilidades activas, sus acciones, esquemas de entrada/salida y políticas de seguridad Aegis.

3. **[03. Motor de Hardware y Telemetría](file:///d:/WIS/ingenieria/03_MOTOR_DE_HARDWARE_Y_TELEMETRIA.md)**  
   Detalles de los protocolos serie (UART/RS232), broker MQTT, grafo de dispositivos en SQLite, toolchains (PlatformIO/esptool) y validación física de ejecución.

4. **[04. Interfaz Hacker y API Server](file:///d:/WIS/ingenieria/04_INTERFAZ_HACKER_Y_API_SERVER.md)**  
   Arquitectura visual del frontend terminal, PyWebView frameless, endpoints REST de FastAPI, streams bidireccionales WebSocket y modal de autorización de acciones críticas.

5. **[05. Operaciones, Despliegue y Mantenimiento](file:///d:/WIS/ingenieria/05_OPERACIONES_DESPLIEGUE_Y_MANTENIMIENTO.md)**  
   Manual de puesta en marcha, variables de entorno, configuración offline/local CPU, ejecución de tests de regresión y diagnóstico de problemas.
