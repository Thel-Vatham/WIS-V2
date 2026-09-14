# PTT Feature Task List

- `[x]` 1. Instalar la librería `keyboard` y actualizar `requirements.txt`.
- `[x]` 2. Modificar `console/web/app.js` para renderizar el input del usuario usando el evento `pipeline.input_received`.
- `[x]` 3. Modificar `console/web/app.js` (y el HTML/CSS si es necesario) para mostrar un indicador visual cuando PTT esté activo (`ptt.started` / `ptt.stopped`).
- `[x]` 4. Crear el servicio de escucha global en `core/ptt.py` usando `keyboard` y `pyaudio`/`speech_recognition`.
- `[x]` 5. Modificar `main.py` para arrancar el servicio PTT si está habilitado y pasarle la configuración del servidor.
- `[ ]` 6. Validar que la voz se reconoce y se envía al servidor cuando se mantiene presionado F9.
