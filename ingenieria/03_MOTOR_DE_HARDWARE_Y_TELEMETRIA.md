# 🔌 WIS v3.0 — Motor de Hardware y Telemetría

WIS incorpora una capa de abstracción de hardware diseñada para interactuar de forma segura y en tiempo real con microcontroladores, sensores IoT y periféricos industriales. A diferencia de un chatbot convencional, WIS posee memoria topológica de hardware y verificación empírica de estados físicos.

---

## 1. Memoria Topológica de Hardware (`HardwareMemory`)

Ubicada en `Data/wis_hardware.db`, gestiona tres tablas relacionales primarias:

### A. `devices` (El Device Graph)
Registra cada dispositivo físico conectado o conocido en la topología:
- `id`: Identificador único (ej. `esp32_gateway_01`).
- `name`: Nombre descriptivo (ej. `ESP32 DevKit v1`).
- `device_type`: MCU, SENSOR, ACTUATOR, RELAY, CAMERA, POWER_METER.
- `interface`: `serial`, `mqtt`, `i2c`, `spi`, `ble`.
- `connection_info`: JSON con puerto (`COM4`), baudrate (`115200`), topic MQTT, dirección I2C.
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

Implementado en [abilities/serial_comm.py](file:///d:/WIS/abilities/serial_comm.py):

### Arquitectura de Buffer y Verificación
1. **Detección Automática:** Escanea el bus USB buscando descriptores USB-UART (CH340, CP2102, FTDI).
2. **Buffer Circular Asíncrono:** Un hilo de lectura continuo almacena las líneas recibidas en una cola no bloqueante de memoria, evitando pérdida de caracteres durante ráfagas de telemetría.
3. **ACK Físico Obligatorio:** Al enviar un comando (ej. `SET_RELAY 1`), el pipeline no asume éxito hasta que el microcontrolador responde con el patrón esperado (`ACK`, `OK` o echo correspondiente) dentro de un timeout estricto.

---

## 3. Arquitectura MQTT e Ingesta de Telemetría

Implementado en [abilities/mqtt_comm.py](file:///d:/WIS/abilities/mqtt_comm.py) y [core/telemetry.py](file:///d:/WIS/core/telemetry.py):

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

Implementado en [abilities/toolchain.py](file:///d:/WIS/abilities/toolchain.py):
- **PlatformIO (`pio`):** Compilación desatendida mediante CLI de proyectos PlatformIO (`pio run`).
- **Arduino CLI (`arduino-cli`):** Compilación y subida a placas clásicas (Arduino Uno, Mega, Nano).
- **ESPTool (`esptool.py`):** Flasheo a bajo nivel de microcontroladores Espressif (ESP8266, ESP32-S2/S3/C3), lectura de MAC, borrado de flash (`erase_flash`) y lectura de tablas de particiones.

### Verificación de Artefactos de Compilación
WIS inspecciona el sistema de archivos tras la compilación:
- Comprueba que el archivo `.hex`, `.bin` o `.elf` haya sido creado en el timestamp del comando actual.
- Valida que el tamaño del binario sea mayor a cero y no sobrepase el tamaño máximo de la memoria flash declarada en el Device Graph.

---

## 5. Servidor de Simulación de Hardware (`mock_server.py`)

Para entornos de desarrollo o CI/CD donde no hay microcontroladores conectados físicamente, WIS incluye un simulador integral en [mock_server.py](file:///d:/WIS/mock_server.py):
- Crea puertos serie virtuales emulados con respuestas programadas (`OK`, `READY`, lecturas de temperatura senoidales).
- Emula un broker MQTT local con simulación de pérdida de paquetes y latencia de red.
- Permite validar la suite completa de pruebas de hardware sin riesgo de dañar placas reales.
