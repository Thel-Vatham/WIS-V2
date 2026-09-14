# 🖥️ WIS v3.0 — Interfaz Hacker y Servidor API

La interfaz de usuario de WIS v3.0 fue concebida como una **consola hacker / developer terminal** nativa. Reemplaza cualquier interfaz web genérica por un entorno de alta densidad informativa, estética cyberpunk monocromática con acentos neón y control estricto de seguridad.

---

## 1. Arquitectura de Presentación Dual

WIS permite dos modos de visualización utilizando la misma base de código:

1. **Modo Ventana Nativa de Escritorio (PyWebView):**
   - Ejecutado mediante `python main.py` (por defecto).
   - Crea una ventana acelerada por hardware de Windows mediante Webview2 (Chromium embebido).
   - Fondo negro puro (`#050505`) sin parpadeo blanco al arrancar.
   - Sin barras de título convencionales de Windows (frameless option).

2. **Modo Servidor Web Headless:**
   - Ejecutado mediante `python main.py --server`.
   - Levanta el servidor backend FastAPI en el puerto configurado (por defecto `7777`).
   - Accesible desde cualquier navegador en `http://127.0.0.1:7777/console/`.

---

## 2. Diseño Visual y Ergonomía Hacker (`console/web/`)

La interfaz está construida en **HTML5 semántico, CSS3 moderno y Vanilla JavaScript** (sin frameworks pesados tipo React ni dependencias externas lentas):
- **Tipografía:** Exclusivamente fuentes monoespaciadas (`Fira Code`, `JetBrains Mono`, `Consolas`).
- **Paleta de Colores:**
  - Fondo primario: `#050505` (Deep Black).
  - Paneles y tarjetas: `#0d0d0d` con bordes sutiles `#1f2428`.
  - Acentos de texto: `#00ff66` (Hacker Green) y `#00ffff` (Cyan Neon).
  - Alertas y seguridad: `#ff3366` (Crimson Warning).
- **Layout de 3 Columnas:**
  - **Columna Izquierda (Data Stream & Hardware):** Muestra el grafo de dispositivos activos en tiempo real, puertos COM abiertos y lecturas de telemetría continuas.
  - **Columna Central (Terminal Core):** Registro de conversación, streaming de tokens del LLM, visualización de bloques de código y salida de herramientas en vivo.
  - **Columna Derecha (Mission DAG & MetaCognition):** Estado de las metas del `GoalManager`, grafo de tareas de largo horizonte y visualizador del rastro del `MetaCognitive Verifier`.

---

## 3. Especificación de Endpoints del Servidor FastAPI (`console/server.py`)

### Endpoints Públicos y de Bootstrap
- `GET /api/health`: Comprobación rápida de estado del servidor (`{"status": "ok"}`).
- `GET /api/auth/bootstrap`: Entrega el token de sesión a clientes locales (loopback / testclient). Bloquea con `403 Forbidden` a cualquier origen remoto para prevenir ataques CSRF/SSRF.

### Endpoints de Cognición y Ejecución
- `POST /api/chat`:
  - Entrada: `{"message": "string", "session_id": "string"}`.
  - Respuesta: `StreamingResponse` (Event-Stream token a token) o JSON `{response, calls, path_used}`.
- `GET /api/state`: Retorna estadísticas de memoria mnemónica, hechos almacenados y habilidades activas.
- `GET /api/abilities`: Catálogo completo de esquemas JSON de las 19 habilidades disponibles.
- `GET /api/memory/facts`: Inspección de hechos aprendidos por el agente.

### Endpoints de Seguridad y Gobernanza (Aegis)
- `GET /api/security/mode`: Consulta el modo actual (`secure`, `privileged`).
- `POST /api/security/mode`: Cambia el nivel de privilegios y lo persiste en `config/settings.json`.
- `POST /api/approve`: El usuario confirma la ejecución de una acción retenida. Recibe `session_id` para desbloquear únicamente la terminal solicitante.
- `POST /api/deny`: El usuario rechaza la acción peligrosa para la terminal especificada en `session_id`, cancelando ese pipeline.

### Endpoints de Metas y Tareas de Largo Horizonte
- `POST /api/goals`: Crea una meta y descompone su plan en el `GoalManager`.
- `GET /api/goals`: Lista metas activas, progreso porcentual y estado de subtareas.
- `POST /api/tasks/long`: Inicia una tarea persistente en segundo plano en el `LongHorizonEngine`.
- `GET /api/tasks/long`: Lista tareas largas, estado (`pending`, `running`, `paused`, `done`, `cancelled`) y su journal.
- `POST /api/tasks/long/{task_id}/pause`: Pausa temporal de una tarea en background.
- `POST /api/tasks/long/{task_id}/resume`: Reanudación de la tarea pausada.
- `POST /api/tasks/long/{task_id}/cancel`: Cancelación definitiva.

### Endpoints Multimedia y Renderizado
- `POST /api/render`: Registra un fragmento HTML generado dinámicamente por WIS para ser renderizado en una ventana emergente nativa.
- `GET /api/render/{render_id}`: Devuelve el contenido HTML renderizado.
- `POST /api/upload`: Sube archivos, logs o capturas a `Data/uploads/`.
- `POST /api/tts`: Sintetiza texto a audio WAV mediante Kokoro-82M ONNX.
- `POST /api/listen`: Captura 5 segundos de audio del micrófono y los transcribe.

---

## 4. WebSocket en Tiempo Real (`/ws`)

El endpoint `/ws` establece un canal bidireccional de baja latencia:
- Los clientes autenticados reciben todas las emisiones del `EventBus` (`event_bus.subscribe("*")`).
- Se emiten eventos de latido (`heartbeat`), tokens en streaming (`llm.chunk`), llamadas a herramientas iniciadas (`tool.executing`), respuestas empíricas (`tool.result`) y alertas de telemetría de hardware (`telemetry.threshold_triggered`).
- **Enrutamiento por Sesión:** Todo evento originado por una interacción de terminal incluye un atributo `"session_id"`, permitiendo que el frontend asigne de forma precisa los indicadores de "Thinking..." y los outputs a la pestaña correcta sin bloquear el resto de la interfaz paralela.

---

## 5. Modal de Clearance de Seguridad (`[ SECURITY CLEARANCE REQUIRED ]`)

Cuando el `ActionPipeline` detecta una acción categorizada como de alto riesgo en modo seguro (por ejemplo: ejecución de un script destructivo, formateo de un disco, o flasheo directo de un microcontrolador conectado a maquinaria):
1. El pipeline **suspende la ejecución** de forma no bloqueante.
2. El servidor emite un evento `security.approval_required` vía WebSocket.
3. El frontend muestra un modal flotante con borde rojo neón y advertencia sonora con:
   - Nombre de la herramienta y acción solicitada.
   - Parámetros exactos que se van a ejecutar.
   - Diagnóstico del riesgo evaluado por Aegis.
   - Botones interactivos de `[ AUTHORIZE EXECUTION ]` y `[ ABORT ACTION ]`.
4. El operador decide si autoriza (`/api/approve`) o deniega (`/api/deny`).
