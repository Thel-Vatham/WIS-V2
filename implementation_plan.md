# Implementación de Push-to-Talk (PTT) Global con la tecla F9

Esta es la propuesta técnica para añadir la funcionalidad de Push-to-Talk global manteniendo presionada la tecla F9 en WIS.

## Resumen de Cambios

### 1. Dependencias
- Se agregará e instalará la librería `keyboard` (o `pynput`) en `requirements.txt` para capturar la tecla F9 globalmente en Windows, sin importar si WIS está en primer plano o en segundo plano.

### 2. Servicio Backend de PTT (`core/ptt.py`)
- Se creará un hilo (thread) de fondo que se iniciará automáticamente junto con el servidor WIS.
- **Flujo:**
  - Detecta cuándo se presiona y se mantiene `F9`.
  - Abre un flujo directo de `pyaudio` y graba fragmentos de audio a RAM.
  - Al soltar `F9`, detiene la grabación y utiliza `SpeechRecognition` para transcribir.
  - Envía el texto transcrito directamente a la API REST interna de WIS (`POST /api/chat`), lo cual inyecta tu voz al cerebro de forma segura y thread-safe.

### 3. Interfaz Gráfica (`console/web/app.js`)
- Actualmente, la burbuja de chat del usuario se dibuja en la pantalla *antes* de enviarse al servidor.
- Para que tu voz a través de F9 aparezca en la consola web de forma natural, modificaremos `app.js` para que escuche el evento `pipeline.input_received` que emite el backend.
- De esta manera, cualquier instrucción (sea por PTT, teclado o API) generará automáticamente su burbuja y se integrará en el flujo de la UI.
- Además, añadiremos notificaciones (eventos `ptt.started` y `ptt.stopped`) para mostrar un indicador visual de "Escuchando..." en la consola mientras mantengas presionado F9.

## Preguntas Abiertas para el Operador

> [!WARNING]
> La librería `keyboard` a veces requiere que la terminal (PowerShell o CMD) esté ejecutándose como Administrador para poder interceptar teclas a nivel global en Windows. Si no sueles ejecutar tu terminal como Admin, podríamos usar `pynput` que suele tener menos restricciones. ¿Estás de acuerdo en usar `keyboard` y asumir la ejecución como administrador si fuera necesario, o prefieres `pynput`?

Por favor, revisa el plan. Si estás de acuerdo, haz clic en **Proceed / Aprobar** y comenzaré la implementación y validación.
