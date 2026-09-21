/* =========================================================
   WIS System Dashboard — Frontend Logic
   Real-time CPU / RAM charts + process table + log stream
   ========================================================= */

const MAX_POINTS = 60;
const POLL_MS = 2000;

// ---------- Chart setup (lightweight canvas charts) ----------
function makeChart(canvas, color) {
  const ctx = canvas.getContext("2d");
  const data = [];

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function push(v) {
    data.push(v);
    if (data.length > MAX_POINTS) data.shift();
    draw();
  }

  function draw() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);

    // grid
    ctx.strokeStyle = "rgba(255,255,255,0.06)";
    ctx.lineWidth = 1;
    for (let i = 1; i < 4; i++) {
      const y = (h / 4) * i;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    if (data.length < 2) return;

    const step = w / (MAX_POINTS - 1);

    // filled area
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, color + "55");
    grad.addColorStop(1, color + "00");

    ctx.beginPath();
    ctx.moveTo(0, h);
    data.forEach((v, i) => {
      const x = i * step;
      const y = h - (v / 100) * h;
      ctx.lineTo(x, y);
    });
    ctx.lineTo((data.length - 1) * step, h);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // line
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = i * step;
      const y = h - (v / 100) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.stroke();

    // head dot
    const lx = (data.length - 1) * step;
    const ly = h - (data[data.length - 1] / 100) * h;
    ctx.beginPath();
    ctx.arc(lx, ly, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  }

  window.addEventListener("resize", () => { resize(); draw(); });
  resize();
  return { push, resize };
}

const cpuChart = makeChart(document.getElementById("cpu-chart"), "#22d3ee");
const ramChart = makeChart(document.getElementById("ram-chart"), "#a78bfa");

// ---------- Helpers ----------
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function setBar(id, pct) {
  const el = document.getElementById(id);
  if (el) el.style.width = Math.min(100, Math.max(0, pct)) + "%";
}

function fmtBytes(b) {
  if (b === null || b === undefined) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return b.toFixed(1) + " " + u[i];
}

function fmtUptime(sec) {
  if (sec === null || sec === undefined) return "—";
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}

// ---------- Data fetchers ----------
async function fetchStats() {
  try {
    const r = await fetch("/api/stats");
    const d = await r.json();
    if (!d.ok) return;

    // CPU
    setText("cpu-value", d.cpu.percent.toFixed(1) + "%");
    setBar("cpu-bar", d.cpu.percent);
    cpuChart.push(d.cpu.percent);
    setText("cpu-cores", d.cpu.cores + " cores");
    setText("cpu-freq", d.cpu.freq_mhz ? d.cpu.freq_mhz.toFixed(0) + " MHz" : "—");

    // RAM
    setText("ram-value", d.memory.percent.toFixed(1) + "%");
    setBar("ram-bar", d.memory.percent);
    ramChart.push(d.memory.percent);
    setText("ram-used", fmtBytes(d.memory.used));
    setText("ram-total", fmtBytes(d.memory.total));

    // Disk
    setText("disk-value", d.disk.percent.toFixed(1) + "%");
    setBar("disk-bar", d.disk.percent);
    setText("disk-used", fmtBytes(d.disk.used) + " / " + fmtBytes(d.disk.total));

    // Meta
    setText("uptime", fmtUptime(d.uptime_seconds));
    setText("proc-count", d.processes_total);
    setText("last-update", new Date().toLocaleTimeString());
  } catch (e) {
    console.warn("stats fetch failed", e);
  }
}

async function fetchProcesses() {
  try {
    const r = await fetch("/api/processes?limit=12");
    const d = await r.json();
    if (!d.ok) return;
    const tbody = document.getElementById("proc-body");
    tbody.innerHTML = "";
    d.processes.forEach(p => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${p.pid}</td>
        <td class="pname">${p.name}</td>
        <td>${p.cpu.toFixed(1)}%</td>
        <td>${fmtBytes(p.memory)}</td>
        <td>${p.status}</td>`;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.warn("process fetch failed", e);
  }
}

// ---------- Log streaming (SSE) ----------
function startLogStream() {
  const box = document.getElementById("log-box");
  const src = new EventSource("/api/logs/stream");

  src.onmessage = (ev) => {
    const line = ev.data;
    const div = document.createElement("div");
    div.className = "log-line";
    if (/ERROR|FAIL|Exception/i.test(line)) div.classList.add("log-error");
    else if (/WARN/i.test(line)) div.classList.add("log-warn");
    else if (/OK|SUCCESS|INFO/i.test(line)) div.classList.add("log-ok");
    div.textContent = line;
    box.appendChild(div);
    while (box.childNodes.length > 300) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  };

  src.onerror = () => {
    console.warn("log stream error, retrying...");
  };
}

// ---------- Init ----------
function init() {
  fetchStats();
  fetchProcesses();
  startLogStream();
  setInterval(fetchStats, POLL_MS);
  setInterval(fetchProcesses, POLL_MS * 2);
}

document.addEventListener("DOMContentLoaded", init);
