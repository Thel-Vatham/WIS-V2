// Navigation
const navBtns = document.querySelectorAll('.nav-btn');
const views = document.querySelectorAll('.view');

navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        navBtns.forEach(b => b.classList.remove('active'));
        views.forEach(v => v.classList.remove('active'));
        
        btn.classList.add('active');
        document.getElementById(btn.dataset.target).classList.add('active');
    });
});

// API config
const API_BASE = '/api/nao';
let ws;

async function apiCall(action, payload = {}) {
    try {
        const res = await fetch(`${API_BASE}/${action}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        return await res.json();
    } catch (e) {
        console.error("API error", e);
        return { success: false, error: e.toString() };
    }
}

// Actions
async function speak() {
    const text = document.getElementById('tts-text').value;
    const lang = document.getElementById('tts-lang').value;
    const anim = document.getElementById('tts-animated').checked;
    if (!text) return;
    
    if (anim) {
        await apiCall('animated_say', { text, language: lang });
    } else {
        await apiCall('speak', { text, language: lang });
    }
}

function setAngle(name, value) {
    apiCall('set_angles', { names: [name], angles: [parseFloat(value)], speed: 0.2 });
}

// ------------------------------------------------------------------ //
// Speaker volume
// ------------------------------------------------------------------ //
// Energia de microfono que el bridge toma como referencia para el 100%.
const MIC_REFERENCE = 8000;

let volTimer = null;
let volIgnoreUntil = 0;   // ignora el volumen que llega por WS mientras el usuario arrastra
let lastVolume = null;
let muted = false;
let restoreLevel = 50;

function setVolumeHint(msg, isError) {
    const el = document.getElementById('vol-hint');
    el.innerText = msg;
    el.classList.toggle('error', !!isError);
}

function renderVolume(pct) {
    if (typeof pct !== 'number' || isNaN(pct)) return;
    const val = Math.max(0, Math.min(100, Math.round(pct)));
    lastVolume = val;
    document.getElementById('vol-value').innerText = val + '%';
    if (Date.now() > volIgnoreUntil) {
        document.getElementById('vol-slider').value = val;
        muted = val === 0;
        updateMuteButton();
    }
}

function updateMuteButton() {
    document.getElementById('mute-btn').innerHTML = muted
        ? '<i class="fa-solid fa-volume-high"></i> Unmute'
        : '<i class="fa-solid fa-volume-xmark"></i> Mute';
}

function onVolumeInput(value) {
    const pct = parseInt(value, 10);
    document.getElementById('vol-value').innerText = pct + '%';
    volIgnoreUntil = Date.now() + 2500;
    clearTimeout(volTimer);
    volTimer = setTimeout(() => applyVolume(pct), 200);
}

async function applyVolume(pct) {
    const res = await apiCall('set_volume', { level: pct });
    if (!res.success) {
        setVolumeHint('No se pudo aplicar el volumen: ' + (res.error || 'error desconocido'), true);
        return;
    }
    lastVolume = res.volume;
    muted = res.volume === 0;
    updateMuteButton();
    document.getElementById('vol-value').innerText = res.volume + '%';
    document.getElementById('vol-slider').value = res.volume;
    setVolumeHint('Volumen aplicado: ' + res.volume + '%.', false);
}

async function toggleMute() {
    if (!muted) {
        if (typeof lastVolume === 'number' && lastVolume > 0) restoreLevel = lastVolume;
        await applyVolume(0);
        setVolumeHint('Silenciado. El robot sigue procesando audio, solo no habla.', false);
    } else {
        await applyVolume(restoreLevel || 50);
    }
}

async function refreshVolume() {
    const res = await apiCall('get_volume');
    if (res.success) {
        volIgnoreUntil = 0;
        renderVolume(res.volume);
        setVolumeHint('Volumen leido directamente de NAO.', false);
    } else {
        setVolumeHint('No se pudo leer el volumen: ' + (res.error || 'desconocido'), true);
    }
}

// ------------------------------------------------------------------ //
// Microphones
// ------------------------------------------------------------------ //
function setMicStatus(msg, kind) {
    const el = document.getElementById('mic-test-status');
    el.innerText = msg;
    el.classList.remove('error', 'ok');
    if (kind === 'fail') el.classList.add('error');
    if (kind === 'ok') el.classList.add('ok');
}

function renderMic(mic) {
    const pill = document.getElementById('mic-pill');
    const source = document.getElementById('mic-source');

    if (!mic || !mic.success) {
        pill.innerText = 'Sin datos';
        pill.className = 'pill';
        source.innerText = mic && mic.error ? mic.error : '';
        return;
    }

    const ref = mic.reference || MIC_REFERENCE;
    ['front', 'rear', 'left', 'right'].forEach(name => {
        const raw = (mic.energy && mic.energy[name]) || 0;
        const pct = Math.max(0, Math.min(100, (raw / ref) * 100));
        document.getElementById('mic-' + name).style.width = pct + '%';
        document.getElementById('mic-' + name + '-val').innerText = Math.round(raw);
    });

    const level = typeof mic.level === 'number' ? mic.level : 0;
    const pct = Math.round(level * 100);

    if (mic.hearing) {
        pill.innerText = 'Escuchando (' + pct + '%)';
        pill.className = 'pill ok';
    } else {
        pill.innerText = pct > 1 ? 'Sonido debil (' + pct + '%)' : 'En silencio';
        pill.className = 'pill idle';
    }
    source.innerText = 'via ' + (mic.source || '?');

    document.querySelectorAll('.mic-bar .meter').forEach(m => m.classList.toggle('active', mic.hearing));

    document.getElementById('mic-mini-fill').style.width = pct + '%';
    document.getElementById('mic-mini-text').innerText = pct <= 1 ? '--' : pct + '%';
    document.getElementById('mic-mini-icon').style.color = mic.hearing ? 'var(--success)' : 'var(--text-muted)';
}

let micTesting = false;
async function micTest() {
    if (micTesting) return;
    micTesting = true;
    const btn = document.getElementById('mic-test-btn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Probando...';
    try {
        setMicStatus('El robot va a pedirte una palabra y luego escuchara 6 segundos...', null);
        await apiCall('speak', { text: 'Di la palabra: hola', language: 'Spanish' });
        const res = await apiCall('listen', { timeout: 6, language: 'Spanish' });
        if (res.success && res.text) {
            setMicStatus('Te oi: "' + res.text + '". Los microfonos funcionan.', 'ok');
        } else if (res.success) {
            setMicStatus('No reconoci ninguna palabra. Di "hola" fuerte y cerca de la cabeza del robot (el vocabulario del test es: hola, si, no, gracias, maestro, ayuda, adios).', 'fail');
        } else {
            setMicStatus('Error: ' + (res.error || 'desconocido'), 'fail');
        }
    } finally {
        micTesting = false;
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-ear-listen"></i> Test hearing (6s)';
    }
}

// Camera
let streamInterval = null;
let camErrors = 0;

function setCamStatus(msg, isError) {
    const el = document.getElementById('cam-status');
    if (!el) return;
    el.innerText = msg || '';
    el.classList.toggle('error', !!isError);
}

async function captureImage() {
    const res = await apiCall('capture_b64', {
        resolution: 1,
        swap_rb: document.getElementById('cam-swap').checked,
        flip: document.getElementById('cam-flip').checked,
    });

    if (res.success && res.image_b64) {
        camErrors = 0;
        document.getElementById('cam-placeholder').style.display = 'none';
        const img = document.getElementById('cam-img');
        img.style.display = 'block';
        img.src = 'data:image/jpeg;base64,' + res.image_b64;
        setCamStatus('', false);
        return;
    }

    camErrors += 1;
    // No cortamos el stream al primer fallo, pero avisamos tras varios seguidos.
    if (camErrors >= 2) {
        setCamStatus('Sin imagen: ' + (res.error || 'error desconocido'), true);
    }
}

function toggleStream() {
    const btn = document.getElementById('stream-btn');
    if (streamInterval) {
        clearInterval(streamInterval);
        streamInterval = null;
        btn.innerHTML = '<i class="fa-solid fa-video"></i> Start Stream';
        btn.classList.remove('danger');
    } else {
        streamInterval = setInterval(captureImage, 1000);
        btn.innerHTML = '<i class="fa-solid fa-stop"></i> Stop Stream';
        btn.classList.add('danger');
    }
}

// Autonomous Mode Mock
let isAutoMode = false;
function startAutonomous() {
    isAutoMode = true;
    document.getElementById('btn-auto-start').style.display = 'none';
    document.getElementById('btn-auto-stop').style.display = 'inline-block';
    document.getElementById('brain-indicator').classList.add('active');
    document.getElementById('auto-state-text').innerText = 'Active - Listening...';
    apiCall('kindergarten_start', {});
}

function stopAutonomous() {
    isAutoMode = false;
    document.getElementById('btn-auto-stop').style.display = 'none';
    document.getElementById('btn-auto-start').style.display = 'inline-block';
    document.getElementById('brain-indicator').classList.remove('active');
    document.getElementById('auto-state-text').innerText = 'Idle';
    apiCall('kindergarten_stop', {});
}

// Telemetry WebSocket
// ------------------------------------------------------------------ //
// Connection state (panel vivo != robot alcanzable)
// ------------------------------------------------------------------ //
function renderConnection(bridge, bridgeAlive) {
    const dot = document.getElementById('conn-dot');
    const text = document.getElementById('conn-text');
    if (!bridge) return;

    if (bridgeAlive === false) {
        dot.classList.remove('connected');
        dot.style.background = 'var(--danger)';
        text.innerText = 'Bridge caido';
        text.title = bridge.error || 'el proceso del bridge no esta corriendo';
        return;
    }

    if (bridge.connected) {
        dot.classList.add('connected');
        dot.style.background = '';
        text.innerText = 'NAO conectado';
        text.title = 'IP ' + (bridge.ip || '');
        return;
    }

    dot.classList.remove('connected');
    dot.style.background = '';
    text.innerText = 'NAO no responde';
    const reason = bridge.error
        ? bridge.error
        : (bridge.missing && bridge.missing.length
            ? 'sin servicios: ' + bridge.missing.join(', ')
            : 'sin conexion');
    text.title = reason;
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        // El WebSocket solo prueba que el panel vive; el robot se confirma
        // cuando llega la telemetria con el estado real del bridge.
        document.getElementById('conn-text').innerText = 'Panel activo...';
    };

    ws.onclose = () => {
        document.getElementById('conn-dot').classList.remove('connected');
        document.getElementById('conn-text').innerText = 'Panel desconectado';
        setTimeout(connectWebSocket, 3000);
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        // Battery (el bridge puede entregar 0..1 o 0..100 segun firmware)
        if (data.battery !== undefined) {
            let pct = Number(data.battery) || 0;
            if (pct > 0 && pct <= 1.5) pct = pct * 100;
            pct = Math.max(0, Math.min(100, Math.round(pct)));
            document.getElementById('batt-level').style.width = pct + '%';
            document.getElementById('batt-text').innerText = pct + '%';
            if (pct < 20) document.getElementById('batt-level').style.background = 'var(--danger)';
            else document.getElementById('batt-level').style.background = 'var(--success)';
        }

        // Speaker volume
        if (data.volume !== null && data.volume !== undefined) {
            renderVolume(data.volume);
        }

        // Microphone energy
        if (data.mic) {
            renderMic(data.mic);
        }

        // Estado real de la conexion con el robot
        if (data.bridge) {
            renderConnection(data.bridge, data.bridge_alive);
        }

        // Sensors
        if (data.sensors && data.sensors.success) {
            const s = data.sensors;
            document.getElementById('val-sonar').innerText = `${s.sonar.left.toFixed(2)} / ${s.sonar.right.toFixed(2)}`;
            document.getElementById('val-head-touch').innerText = `${s.tactile.head_front} / ${s.tactile.head_middle} / ${s.tactile.head_rear}`;
            document.getElementById('val-hands-touch').innerText = `${s.tactile.l_hand} / ${s.tactile.r_hand}`;
            document.getElementById('val-accel').innerText = `${s.accelerometer.x.toFixed(2)} / ${s.accelerometer.y.toFixed(2)} / ${s.accelerometer.z.toFixed(2)}`;
        }
    };
}

// Init
updateMuteButton();
connectWebSocket();
refreshVolume();
