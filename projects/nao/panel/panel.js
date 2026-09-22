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

// Camera
let streamInterval = null;
async function captureImage() {
    const res = await apiCall('capture_b64', { resolution: 1 });
    if (res.success && res.image_b64) {
        document.getElementById('cam-placeholder').style.display = 'none';
        const img = document.getElementById('cam-img');
        img.style.display = 'block';
        img.src = 'data:image/jpeg;base64,' + res.image_b64;
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
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        document.getElementById('conn-dot').classList.add('connected');
        document.getElementById('conn-text').innerText = 'Connected';
    };

    ws.onclose = () => {
        document.getElementById('conn-dot').classList.remove('connected');
        document.getElementById('conn-text').innerText = 'Disconnected';
        setTimeout(connectWebSocket, 3000);
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        // Battery
        if (data.battery !== undefined) {
            const pct = Math.round(data.battery * 100);
            document.getElementById('batt-level').style.width = pct + '%';
            document.getElementById('batt-text').innerText = pct + '%';
            if (pct < 20) document.getElementById('batt-level').style.background = 'var(--danger)';
            else document.getElementById('batt-level').style.background = 'var(--success)';
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
connectWebSocket();
