# 🔌 WIS v3.0 — Motor de Hardware y Telemetría

WIS incorpora una capa de abstracción de hardware diseñada para interactuar de forma segura y en tiempo real con microcontroladores, sensores IoT, plataformas robóticas humanoides (NAO) y vehículos aéreos no tripulados (drones). A diferencia de un chatbot convencional, WIS posee memoria topológica de hardware, verificación empírica de estados físicos y lazos sensoriales desacoplados.

---

## 1. Memoria Topológica de Hardware (`HardwareMemory`)

Ubicada en `Data/wis_hardware.db`, gestiona tres tablas relacionales primarias:

### A. `devices` (El Device Graph)
Registra cada dispositivo físico conectado o conocido en la topología:
- `id`: Identificador único (ej. `esp32_gateway_01`, `nao_robot_v5`).
- `name`: Nombre descriptivo (ej. `ESP32 DevKit v1`, `NAO Humanoid Primary`).
- `device_type`: MCU, SENSOR, ACTUATOR, RELAY, CAMERA, POWER_METER, ROBOT_HUMANOID, DRONE.
- `interface`: `serial`, `mqtt`, `i2c`, `spi`, `ble`, `tcp_socket`, `mavlink`.
- `connection_info`: JSON con puerto (`COM4`), baudrate (`115200`), topic MQTT, IP/Puerto TCP o enlace de telemetría.
- `status`: `connected`, `disconnected`, `error`.
- `last_seen`: Timestamp UNIX de última telemetría válida.

### B. `pinout_mappings`
Mapea la configuración funcional de cada pin del microcontrolador:
- `device_id`: Clave foránea al dispositivo.
- `pin_number`: Pin físico o GPIO (ej. `GPIO21`, `D4`).
- `label`: Etiqueta asignada por el usuario (ej. `SDA`, `LED_STATUS`, `DHT22_DATA`).
- `function`: `digital_in`, `digital_out`, `analog_in`, `pwm`, `i2c_sda`, `uart_rx`.
- `safe_range`: JSON con límites operacionales (ej. `{"voltage_max": 3.3, "current_ma": 12}`).

### C. `procedural_memory`
Registra secuencias de comandos pre-probadas y optimizadas:
- `command_signature`: Regex o descripción de la acción (ej. `flash_firmware_stm32`).
- `tool_sequence`: JSON con la cadena de llamadas probadas exitosamente.
- `success_count` / `fail_count`: Estadísticas empíricas de confiabilidad para ranking automático en Path 0 (FastPath).

---

## 2. Comunicaciones Serie (UART / RS232)

Implementado en `abilities/serial_comm.py`:

### Arquitectura de Buffer y Verificación
1. **Detección Automática:** Escanea el bus USB buscando descriptores USB-UART (CH340, CP2102, FTDI).
2. **Buffer Circular Asíncrono:** Un hilo de lectura continuo almacena las líneas recibidas en una cola no bloqueante de memoria, evitando pérdida de caracteres durante ráfagas de telemetría.
3. **ACK Físico Obligatorio:** Al enviar un comando (ej. `SET_RELAY 1`), el pipeline no asume éxito hasta que el microcontrolador responde con el patrón esperado (`ACK`, `OK` o echo correspondiente) dentro de un timeout estricto.

---

## 3. Arquitectura MQTT e Ingesta de Telemetría

Implementado en `abilities/mqtt_comm.py` y `core/telemetry.py`:

### Estructura de Tópicos
- **Telemetría de Sensores:** `wis/telemetry/{device_id}/{metric}` (ej. `wis/telemetry/esp32_01/temperature`).
- **Comandos a Actuadores:** `wis/command/{device_id}/{action}` (ej. `wis/command/relay_box/open`).
- **Estado de Dispositivos (LWT):** `wis/status/{device_id}` (`online` / `offline`).

### Evaluación de Umbrales en Tiempo Real
El `TelemetryEngine` ingesta las lecturas y las compara contra reglas configuradas en `config/settings.json`. Si una métrica excede un umbral seguro (ej. `temperature > 75°C` o `voltage < 3.0V`), dispara inmediatamente el evento:
```json
{
  "event": "telemetry.threshold_triggered",
  "device_id": "esp32_01",
  "metric": "temperature",
  "value": 78.4,
  "threshold": 75.0,
  "severity": "CRITICAL"
}
```
Este evento viaja por el `EventBus` y activa directamente el método `handle_autonomous_trigger` del `ActionPipeline`, ejecutando medidas correctivas sin intervención del operador.

---

## 4. Toolchains de Firmware (`toolchain`)

Implementado en `abilities/toolchain.py`:
- **PlatformIO (`pio`):** Compilación desatendida mediante CLI de proyectos PlatformIO (`pio run`).
- **Arduino CLI (`arduino-cli`):** Compilación y subida a placas clásicas (Arduino Uno, Mega, Nano).
- **ESPTool (`esptool.py`):** Flasheo a bajo nivel de microcontroladores Espressif (ESP8266, ESP32-S2/S3/C3), lectura de MAC, borrado de flash (`erase_flash`) y lectura de tablas de particiones.

### Verificación de Artefactos de Compilación
WIS inspecciona el sistema de archivos tras la compilación:
- Comprueba que el archivo `.hex`, `.bin` o `.elf` haya sido creado en el timestamp del comando actual.
- Valida que el tamaño del binario sea mayor a cero y no sobrepase el tamaño máximo de la memoria flash declarada en el Device Graph.

---

## 5. Servidor de Simulación de Hardware (`mock_server.py`)

Para entornos de desarrollo o CI/CD donde no hay microcontroladores conectados físicamente, WIS incluye un simulador integral en `mock_server.py`:
- Crea puertos serie virtuales emulados con respuestas programadas (`OK`, `READY`, lecturas de temperatura senoidales).
- Emula un broker MQTT local con simulación de pérdida de paquetes y latencia de red.
- Permite validar la suite completa de pruebas de hardware sin riesgo de dañar placas reales.

---

## 6. Robótica Física Avanzada y Percepción Sensorial en Tiempo Real (NAO & Drones)

WIS implementa una arquitectura híbrida de dos niveles para interactuar con sistemas ciber-físicos complejos:

```mermaid
graph TD
    subgraph Plano Cognitivo ["Plano Cognitivo (WIS Core)"]
        LLM["Razonamiento de Alto Nivel / LLM"]
        CRON["Cron Autónomo"]
        DEV["DevAgent / Meta-Programador"]
    end

    subgraph Plano Determinístico ["Plano Determinístico de Tiempo Real (Control Loops)"]
        VAD_LOOP["Hilo VAD / Audio Continuo (RMS Threshold)"]
        VISION_LOOP["Hilo OpenCV / Tracking Visual (30 FPS)"]
        PID_LOOP["Control de Estabilidad / Cinemática PID"]
    end

    subgraph Hardware Físico ["Hardware Físico / Actuadores"]
        NAO["Robot Humanoide NAO (Motores, TTS, Sensores táctiles)"]
        DRONE["Dron Autónomo (Controladora de Vuelo MAVLink/Betaflight)"]
    end

    Plano Cognitivo -->|Misiones, Metas y Parches de Código| Plano Determinístico
    Plano Determinístico -->|Eventos Filtrados y Disparadores| Plano Cognitivo
    Plano Determinístico <==>|Telemetría y Control Continuo (ms)| Hardware Físico
```

### A. Robot Humanoide NAO (`console/nao_api.py` y `projects/nao/`)
- **Control Cinemático Interpolado:** Comandos de ángulos articulares para cuello, brazos y postura con restricciones de seguridad de ángulo y velocidad máxima.
- **Bucle Sensorial Continuo (VAD):** Hilo en segundo plano que mide la energía acústica ambiental sin bloquear el servidor. Al detectar habla, despacha el evento cognitivo al pipeline para que el robot responda con naturalidad.
- **Comportamientos Autónomos:** Integración pedagógica y de interacción en `projects/nao/kindergarten_teacher.py`.

### B. Control de Vehículos Autónomos y Drones (Arquitectura de Misión Crítica)
- **Principio de Desacoplamiento de Seguridad:** El LLM **nunca** calcula loops PID a 100 Hz directamente (lo cual sería peligroso debido a la latencia de inferencia).
- En su lugar, WIS escribe, compila y despliega controladores de visión determinísticos en Python/C++ (ej. rastreo de objetos por color o detección de rostros con OpenCV a 30 FPS).
- El hilo determinístico envía ráfagas de control de actitud (`roll, pitch, yaw, throttle`) vía protocolo MAVLink o UART serie.
- **Mecanismo Fail-Safe:** Si WIS pierde la comunicación con el bucle o el sensor por más de 500 ms, el firmware del dron activa automáticamente la rutina de retorno a casa (RTH) o aterrizaje de emergencia programado.
