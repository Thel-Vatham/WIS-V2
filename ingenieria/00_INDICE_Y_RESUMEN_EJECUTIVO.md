# 📑 WIS v3.0 — Carpeta de Ingeniería
## Índice Maestro y Resumen Ejecutivo del Sistema

**Wisdom Integrated System (WIS) v3.0** es un sistema operativo cognitivo y sistema nervioso agéntico diseñado específicamente para desarrolladores e ingenieros de hardware/software. WIS unifica razonamiento LLM de vanguardia, control nativo de sistemas operativos (Windows/DWM/PowerShell), visión por computadora (SOM/OCR), compilación y flasheo de microcontroladores (Serial/MQTT/PlatformIO), introspección de código mediante AST Knowledge Graph, control de robótica física con bucle sensorial continuo (VAD/NAO/Drones) y ejecución autónoma de tareas con cognición espontánea en segundo plano.

---

### 🗂️ Estructura del Proyecto

La raíz de WIS ha sido auditada, ampliada y depurada para contener estrictamente los subsistemas operativos de grado producción:

```
WIS-V2/
├── abilities/              # Catálogo de 21 habilidades nativas y dinámicas
│   ├── pc/                 # Motor de automatización PC de nivel SO (AVRORA)
│   │   ├── code_ability.py        # Intérprete Python, refactor AST, TDD runner
│   │   ├── desktop_ability.py     # Gestión de ventanas Win32, apps, procesos
│   │   ├── filesystem_ability.py  # Sandboxing, watcher de archivos, atomic writes
│   │   ├── screen_ability.py      # Visión SOM (Set-of-Marks) y OCR
│   │   └── advanced_desktop_ability.py # Orquestador de escritorio integrado
│   ├── browser.py          # Automatización web headless/headed (Playwright)
│   ├── builder.py          # Síntesis de nuevas habilidades dinámicas en caliente
│   ├── cron.py             # Motor de Vida Autónoma: Cron cognitivo y proactividad en background
│   ├── custom/             # Directorio para habilidades generadas en runtime
│   ├── dev_agent.py        # Meta-Programador AST, mapeo de arquitectura y grafo de código
│   ├── discovery.py        # Descubrimiento de APIs y schemas en caliente
│   ├── file_manager.py     # Exploración de árbol y archivos estructurados
│   ├── hardware_memory.py  # Device Graph y mapeo de pinouts SQLite
│   ├── knowledge_ability.py# Búsqueda y gestión de hechos en SQLite
│   ├── listen.py           # Reconocimiento de voz STT local/remoto
│   ├── mqtt_comm.py        # Cliente IoT MQTT con QoS 1/2 y telemetría
│   ├── registry.py         # Registro central de habilidades con hot-reload
│   ├── serial_comm.py      # Comunicación serie RS232/UART con ACK empírico
│   ├── system_ability.py   # Métricas SO (CPU, RAM, volúmenes, timers)
│   ├── toolchain.py        # PlatformIO, Arduino-CLI, esptool, git
│   ├── vision.py           # Análisis visual multimodelo y percepción de cámara
│   ├── voice.py            # Síntesis TTS Kokoro-82M ONNX (0ms cloud)
│   └── web_search.py       # Motor de búsqueda web sin API keys
│
├── config/                 # Configuración del sistema y gobernanza
│   ├── settings.json       # Parámetros de runtime, seguridad, modelos y puertos
│   └── system/             # Constitución cognitiva y reglas operativas
│       ├── CONSTITUTION.md # Mandatos éticos, de seguridad y preservación
│       ├── EXECUTION.md    # Protocolos de ejecución estricta
│       └── REFERENCE.md    # Manual de referencia rápida
│
├── console/                # Consola de Administración, Servidor Backend y Bridges
│   ├── hotreload.py        # Watcher y recargador dinámico de habilidades en runtime
│   ├── nao_api.py          # API de Robótica Física (NAO/Drones) con bucle sensorial VAD
│   ├── server.py           # Backend FastAPI (REST + WebSockets en tiempo real)
│   ├── web_view.py         # Ventana de escritorio nativa PyWebView frameless
│   ├── wis_expert.py       # Motor de auto-auditoría, asistencia técnica y diagnóstico
│   └── web/                # Frontend de interfaz avanzada (HTML5/CSS3/Vanilla JS)
│       ├── index.html      # Estructura terminal multi-sesión, side-panels y modal
│       ├── style.css       # Interfaz de alto contraste, orientada a ingeniería
│       ├── app.js          # Conexión WebSocket, streams de DAG y telemetría
│       └── terminal.js     # Gestor de terminales paralelas con memoria aislada
│
├── core/                   # Núcleo Cognitivo y Sistema Nervioso Agéntico
│   ├── event_bus.py        # Bus de eventos asíncrono pub/sub central
│   ├── goal_manager.py     # Gestor y planificador de metas operativas
│   ├── hardware_memory.py  # Base de datos relacional de hardware y pinouts
│   ├── llm_client.py       # Abstracción multimodelo (DeepSeek, OpenRouter, etc.)
│   ├── local_llm.py        # Motor LLM local offline para CPU (GGUF TinyLlama)
│   ├── long_horizon.py     # Motor de tareas largas en segundo plano con diario
│   ├── memory.py           # Memoria episódica, mnemónica y relacional compartida
│   ├── mission.py          # Planificador de misiones DAG (grafos de dependencias)
│   ├── pipeline.py         # ActionPipeline Pure-LLM con tool calling paralelo y SkillMemory
│   ├── proactivity.py      # Motor proactivo autónomo basado en reglas
│   ├── reasoning.py        # ReasoningEngine / Cortex con prompting estricto en inglés
│   ├── safety.py           # Políticas de Seguridad Estricta (Modos Secure y Privileged)
│   ├── skill_memory.py     # Memoria de secuencias exitosas (FAISS IndexFlatIP)
│   ├── skill_synthesizer.py# Meta-programador de nuevas habilidades con sandbox AST
│   ├── swarm.py            # Coordinador de enjambre multi-agente distribuido
│   ├── task_store.py       # Persistencia SQLite para metas y subtareas
│   ├── telemetry.py        # Motor de ingestión de telemetría y umbrales de alerta
│   └── verifier.py         # MetaCognitive Verifier (anti-alucinación post-síntesis)
│
├── Data/                   # Bases de datos SQLite y memoria persistente
│   ├── memory.db           # Grafo de código AST relacional y entidades de código
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
│   ├── 04_INTERFAZ_USUARIO_Y_API_SERVER.md
│   └── 05_OPERACIONES_DESPLIEGUE_Y_MANTENIMIENTO.md
│
├── models/                 # Modelos locales para inferencia en CPU
│   └── tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
│
├── projects/               # Proyectos de aplicación e integración física
│   └── nao/                # Integración robótica humanoide / control cinemático
│       ├── kindergarten_teacher.py # Agente de enseñanza y pedagogía interactiva
│       ├── nao_bridge.py   # Puente de cinemática, audio y visión con el robot
│       ├── panel_server.py # Servidor de panel táctil y telemetría del robot
│       └── panel/          # Interfaz web de control para operadores
│
├── tests/                  # Suite completa de pruebas automatizadas (109 tests validados)
│   ├── integration/        # Tests end-to-end (hardware synthesis, pipeline)
│   ├── unit/               # Tests unitarios por módulo (FastPath, SQLite, AST)
│   ├── test_smoke_refactor.py # Prueba de humo integral del stack
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

1. **[01. Arquitectura Cognitiva y Pipeline](01_ARQUITECTURA_COGNITIVA_Y_PIPELINE.md)**  
   Explica en detalle los caminos cognitivos (Path 1 al 2), la paralelización de llamadas con `asyncio.gather`, el Verificador Metacognitivo, el Motor de Vida Autónoma (`cron.py`), el Knowledge Graph AST de código y el Bucle Sensorial Continuo (VAD).

2. **[02. Matriz de Habilidades y Capacidades](02_MATRIZ_DE_HABILIDADES_Y_CAPACIDADES.md)**  
   Especificación formal de las 21 habilidades activas, sus acciones, esquemas de entrada/salida y políticas de seguridad del sistema.

3. **[03. Motor de Hardware y Telemetría](03_MOTOR_DE_HARDWARE_Y_TELEMETRIA.md)**  
   Detalles de los protocolos serie (UART/RS232), broker MQTT, grafo de dispositivos en SQLite, toolchains (PlatformIO/esptool), integración de robótica física (NAO) y control en tiempo real de drones/vehículos autónomos.

4. **[04. Interfaz de Usuario y API Server](04_INTERFAZ_USUARIO_Y_API_SERVER.md)**  
   Arquitectura visual del frontend avanzado, PyWebView frameless, endpoints REST de FastAPI, streams bidireccionales WebSocket, hot-reload dinámico de habilidades y soporte multi-consola distribuida con memoria compartida.

5. **[05. Operaciones, Despliegue y Mantenimiento](05_OPERACIONES_DESPLIEGUE_Y_MANTENIMIENTO.md)**  
   Manual de puesta en marcha, variables de entorno, configuración offline/local CPU, ejecución de tests de regresión (109 tests aprobados) y protocolos de mantenimiento.
