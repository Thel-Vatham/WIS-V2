# 🛠️ WIS v3.0 — Matriz de Habilidades y Capacidades

El ecosistema de habilidades de WIS consta de **19 habilidades activas** agrupadas por dominios funcionales. Todas heredan de la clase base abstracta `Ability` ([abilities/registry.py](file:///d:/WIS/abilities/registry.py)), exponiendo esquemas estandarizados conformes a la especificación de herramientas de función de OpenAI.

---

## 📊 Resumen de Habilidades

| Habilidad | Dominio | Módulo de Origen | Descripción Clave |
|---|---|---|---|
| **`code_tools`** | PC / Desarrollo | `abilities/pc/code_ability.py` | Ejecución Python, refactor AST y TDD |
| **`desktop`** | PC / Sistema | `abilities/pc/desktop_ability.py` | Control de ventanas DWM, procesos y apps |
| **`filesystem`** | PC / Almacenamiento | `abilities/pc/filesystem_ability.py` | Operaciones de archivos atómicas y sandboxing |
| **`shell_comm`** | PC / Shell | `abilities/pc/filesystem_ability.py` | Ejecución PowerShell asíncrona segura |
| **`screen_vision`** | PC / Visión | `abilities/pc/screen_ability.py` | OCR y Set-of-Marks (SOM) en pantalla |
| **`advanced_desktop`**| PC / Integrado | `abilities/pc/advanced_desktop_ability.py` | Orquestador multi-motor de escritorio |
| **`serial_comm`** | Hardware / IoT | `abilities/serial_comm.py` | Conexión UART/RS232 con ACK empírico |
| **`mqtt_comm`** | Hardware / IoT | `abilities/mqtt_comm.py` | Cliente MQTT con QoS y telemetría |
| **`toolchain`** | Hardware / Firmware | `abilities/toolchain.py` | PlatformIO, Arduino-CLI y esptool |
| **`browser`** | Web / Navegación | `abilities/browser.py` | Automatización Chromium con Playwright |
| **`web_search`** | Web / Búsqueda | `abilities/web_search.py` | Motor DuckDuckGo sin credenciales |
| **`vision`** | Percepción | `abilities/vision.py` | Reconocimiento de imágenes y cámaras |
| **`voice`** | Interfaz Humana | `abilities/voice.py` | Síntesis Kokoro-82M ONNX TTS local |
| **`listen`** | Interfaz Humana | `abilities/listen.py` | Reconocimiento de voz STT por micrófono |
| **`system`** | Sistema Operativo | `abilities/system_ability.py` | Métricas de CPU/RAM, timers y audio |
| **`knowledge`** | Memoria | `abilities/knowledge_ability.py` | Búsqueda y gestión de hechos en SQLite |
| **`file_manager`** | Utilidades | `abilities/file_manager.py` | Exploración estructurada de directorios |
| **`builder`** | Meta-Programación | `abilities/builder.py` | Síntesis de nuevas habilidades en caliente |
| **`discovery`** | Auto-Exploración | `abilities/discovery.py` | Inspección de herramientas y puertos activos |

---

## 🔍 Detalle Técnico por Dominio

### 1. Dominio de Desarrollo y Automatización de PC (Herencia AVRORA)

#### `code_tools` (`abilities/pc/code_ability.py`)
- **Acciones:**
  - `run_code(code, timeout)`: Ejecuta fragmentos de código Python en un subproceso aislado capturando stdout y stderr.
  - `inspect_symbols(file_path)`: Parsea el AST del archivo indicado y devuelve clases, métodos, funciones y firmas.
  - `rename_symbol(file_path, old_name, new_name)`: Realiza refactorización segura a nivel de sintaxis AST (evita reemplazos accidentales de texto).
  - `wrap_try_except(file_path, target_function)`: Envuelve funciones en bloques de captura de excepciones estructurados.
  - `run_tdd_cycle(test_file, impl_file)`: Ejecuta ciclo TDD (Rojo-Verde-Refactor) con reportes de cobertura.

#### `desktop` (`abilities/pc/desktop_ability.py`)
- **Acciones:**
  - `list_windows()`: Lista ventanas visibles con IDs de ventana (HWND), títulos y estado de foco.
  - `focus_window(title_or_hwnd)`: Lleva una ventana específica al primer plano (DWM aware).
  - `snap_window(hwnd, position)`: Organiza ventanas en cuadrícula (izq, der, maximizar, minimizar).
  - `kill_process(pid_or_name)`: Termina procesos con verificación posterior de desalojo en memoria.
  - `launch_app(name, args)`: Arranca ejecutables del sistema o accesos directos registrados.

#### `filesystem` & `shell_comm` (`abilities/pc/filesystem_ability.py`)
- **Acciones Filesystem:**
  - `read_file(path, lines_range)`: Lectura paginada para archivos grandes.
  - `write_file_atomic(path, content)`: Escritura con archivo temporal intermedio para evitar corrupción por caídas abruptas.
  - `find_files(pattern, root_dir)`: Búsqueda rápida por glob o regex recursivo.
- **Acciones Shell:**
  - `exec_powershell(command, timeout_s, cwd)`: Ejecuta comandos PowerShell nativos bajo Windows con captura de código de salida y timeouts estrictos.

#### `screen_vision` (`abilities/pc/screen_ability.py`)
- **Acciones:**
  - `capture_screen(bounding_box)`: Captura captura de pantalla en formato optimizado para el LLM.
  - `som_annotate(image_path)`: Ejecuta el algoritmo Set-of-Marks (detecta elementos clickeables, botones y cajas de texto, superponiendo números identificadores).
  - `ocr_read(image_path)`: Extrae texto en pantalla mediante RapidOCR ONNX de alta velocidad sin dependencias de GPU.

---

### 2. Dominio de Hardware e Ingeniería de Firmware

#### `serial_comm` (`abilities/serial_comm.py`)
- **Acciones:**
  - `list_ports()`: Detecta puertos COM físicos o virtuales con VID, PID y descripción del fabricante.
  - `connect(port, baudrate, timeout)`: Abre conexión serie asíncrona.
  - `write(port, data, await_ack)`: Envía cadenas de control o bytes a MCUs (Arduino, ESP32, STM32), verificando recepción con timeout configurable.
  - `read(port, timeout)`: Lee del buffer circular de entrada serie.

#### `mqtt_comm` (`abilities/mqtt_comm.py`)
- **Acciones:**
  - `connect_broker(host, port, client_id)`: Establece conexión con el broker MQTT local o remoto.
  - `publish(topic, mensaje, qos)`: Publica comandos o telemetría con soporte de QoS 0, 1 y 2.
  - `subscribe(topic)`: Escucha eventos de sensores y los redirige al `EventBus` interno.

#### `toolchain` (`abilities/toolchain.py`)
- **Acciones:**
  - `check_tools()`: Verifica disponibilidad de PlatformIO (`pio`), `arduino-cli`, `esptool` y `git`.
  - `compile(project_dir, board)`: Compila firmware generando binarios `.bin` o `.hex` verificados en disco.
  - `flash(project_dir, port, board)`: Transfiere el firmware compilado a la placa conectada con verificación de reinicio.

---

### 3. Dominio Web y Navegación

#### `browser` (`abilities/browser.py`)
- Motor basado en **Playwright Chromium**:
  - `navigate(url)`: Abre páginas web locales o remotas.
  - `click(selector)`, `type(selector, text)`: Interacción precisa con el DOM.
  - `screenshot(path)`: Captura gráfica de páginas web y paneles de control.
  - `extract_text()`: Limpieza de texto y extracción de contenido principal eliminando anuncios y scripts.

#### `web_search` (`abilities/web_search.py`)
- Búsquedas rápidas en la web sin requerir API keys de pago:
  - `search(query, max_results)`: Recupera títulos, URLs y snippets directos de DuckDuckGo.

---

### 4. Dominio de Percepción, Voz y Utilidades

#### `voice` & `listen`
- **Voice (`Kokoro-82M ONNX`):** Genera voz en inglés de calidad ultra-realista de forma 100% local en CPU sin latencia de red.
- **Listen:** Captura audio del micrófono y lo procesa mediante STT para control por voz manos libres.

#### `system` & `knowledge`
- **System:** Monitorización en tiempo real de consumo de RAM, núcleos de CPU, espacio en disco, control de volumen maestro de Windows (`pycaw`) y alarmas.
- **Knowledge:** Base de datos relacional mnemónica para almacenar credenciales locales, diagramas de pines, notas de ingeniería y preferencias del desarrollador.
