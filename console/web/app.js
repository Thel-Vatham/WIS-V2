// ═══════════════════════════════════════════════════════════════════════════════
// WIS COGNITIVE OS — Hacker Terminal Console Client
// ═══════════════════════════════════════════════════════════════════════════════

const State = {
    token: "",
    ws: null,
    wsConnected: false,
    reconnectTimer: null,
    reconnectDelay: 1000,
    pyapi: null,

    // Layout
    rightW: 320,
    rightHidden: false,

    // Terminal
    isThinking: false,
    currentStreamMsg: null,
    currentStreamMessages: new Map(),
    // Render windows per session: sessionId -> Map(renderId -> window|url)
    renderWindows: new Map(),
    renderCounters: new Map(),
    ttsEnabled: localStorage.getItem("wis-tts") === "true",
    securityMode: "privileged",

    // Pending action requiring approval
    pendingApproval: null,

    // TTS Control
    currentTtsSession: 0,
    ttsInterrupted: false,
};

const LAYOUT = {
    MIN_W: 180,
    MAX_W: 520,
    DEFAULT_RIGHT_W: 320,
    STORAGE_KEY: "wis-layout-v2",
};

// ─── DOM References ───────────────────────────────────────────────
const Dom = {};

function cacheDom() {
    Dom.root = document.getElementById("wis-root");
    Dom.bootOverlay = document.getElementById("boot-overlay");
    Dom.bootLog = document.getElementById("boot-log");
    Dom.bootFill = document.getElementById("boot-fill");
    Dom.bootPct = document.getElementById("boot-pct");

    Dom.titlebar = document.getElementById("titlebar");
    Dom.wisOrb = document.getElementById("wis-orb");
    Dom.tbStatus = document.getElementById("tb-status");
    Dom.pillMode = document.getElementById("pill-mode");

    Dom.btnToggleRight = document.getElementById("btn-toggle-right");
    Dom.btnTts = document.getElementById("btn-tts");
    Dom.btnNewWindow = document.getElementById("btn-new-window");
    Dom.btnMinimize = document.getElementById("btn-minimize");
    Dom.btnMaximize = document.getElementById("btn-maximize");
    Dom.btnClose = document.getElementById("btn-close");

    Dom.workspace = document.getElementById("workspace");
    Dom.rightSidebar = document.getElementById("right-sidebar");
    Dom.resizerRight = document.getElementById("resizer-right");

    // Initialize Terminal Manager
    window.parseMarkdown = formatMarkdown;
    window.terminalManager = new TerminalManager();
    
    // Fallback file input if needed globally
    Dom.fileInput = document.getElementById("global-file-input");

    Dom.goalList = document.getElementById("goal-list");
    Dom.projectTree = document.getElementById("project-tree");
    Dom.btnRefreshProjects = document.getElementById("btn-refresh-projects");
    if (Dom.btnRefreshProjects) Dom.btnRefreshProjects.addEventListener("click", loadProjects);
    Dom.btnAddGoal = document.getElementById("btn-add-goal");
    Dom.lhTaskList = document.getElementById("lh-task-list");
    Dom.btnAddLhTask = document.getElementById("btn-add-lh-task");
    Dom.traceList = document.getElementById("trace-list");

    // Modals
    Dom.approvalModal = document.getElementById("approval-modal");
    Dom.approvalText = document.getElementById("approval-text");
    Dom.btnDeny = document.getElementById("btn-deny");
    Dom.btnAuthorize = document.getElementById("btn-authorize");

    Dom.goalModal = document.getElementById("goal-modal");
    Dom.goalInput = document.getElementById("goal-input");
    Dom.goalPriority = document.getElementById("goal-priority");
    Dom.goalPriorityVal = document.getElementById("goal-priority-val");
    Dom.btnGoalCancel = document.getElementById("btn-goal-cancel");
    Dom.btnGoalSubmit = document.getElementById("btn-goal-submit");

    Dom.lhModal = document.getElementById("lh-modal");
    Dom.lhTaskInput = document.getElementById("lh-task-input");
    Dom.lhPriority = document.getElementById("lh-priority");
    Dom.lhPriorityVal = document.getElementById("lh-priority-val");
    Dom.btnLhCancel = document.getElementById("btn-lh-cancel");
    Dom.btnLhSubmit = document.getElementById("btn-lh-submit");

    Dom.btnCloseRight = document.getElementById("btn-close-right");
}

function clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
}

// ═══════════════════════════════════════════════════════════════════
// LAYOUT & FULL-WIDTH CONSOLE (SHOW / HIDE / RESIZE)
// ═══════════════════════════════════════════════════════════════════

function persistLayout() {
    try {
        localStorage.setItem(LAYOUT.STORAGE_KEY, JSON.stringify({
            rightW: State.rightW,
            rightHidden: State.rightHidden,
        }));
    } catch (_) { }
}

function restoreLayout() {
    let saved = null;
    try {
        const raw = localStorage.getItem(LAYOUT.STORAGE_KEY);
        if (raw) saved = JSON.parse(raw);
    } catch (_) { }

    if (saved) {
        State.rightW = clamp(saved.rightW ?? LAYOUT.DEFAULT_RIGHT_W, LAYOUT.MIN_W, LAYOUT.MAX_W);
        State.rightHidden = !!saved.rightHidden;
    }
    applyLayout();
}

function applyLayout() {
    const root = document.documentElement;
    root.style.setProperty("--right-w", State.rightW + "px");

    if (Dom.workspace) {
        Dom.workspace.classList.toggle("right-hidden", State.rightHidden);
    }

    if (Dom.btnToggleRight) {
        Dom.btnToggleRight.classList.toggle("off", State.rightHidden);
        Dom.btnToggleRight.textContent = State.rightHidden ? "◀ Mostrar Der" : "Ocultar Der ▶";
    }

    if (Dom.btnToggleBoth) {
        Dom.btnToggleBoth.classList.toggle("active", State.rightHidden);
        Dom.btnToggleBoth.textContent = State.rightHidden ? "⛶ Restaurar" : "⛶ Consola 100%";
        Dom.btnToggleBoth.title = State.rightHidden
            ? "Restaurar panel derecho (Ctrl+\\)"
            : "Consola Completa al 100% (Ctrl+\\)";
    }
}

function toggleSidebar(side) {
    State.rightHidden = !State.rightHidden;
    applyLayout();
    persistLayout();
}

function toggleBothSidebars() {
    State.rightHidden = !State.rightHidden;
    applyLayout();
    persistLayout();
}

// ─── Resizer Drag Logic (Draggable Splitters) ─────────────────────

function initResizers() {
    bindResizer(Dom.resizerRight);
}

function bindResizer(handle) {
    if (!handle) return;
    let dragging = false;
    let startX = 0;
    let startW = 0;
    let rafId = null;
    let pendingW = 0;

    function onDown(e) {
        if (e.button !== undefined && e.button !== 0) return;
        dragging = true;
        startX = e.clientX;
        startW = Dom.rightSidebar ? Dom.rightSidebar.offsetWidth : 320;
        handle.classList.add("dragging");
        Dom.workspace.classList.add("dragging");
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        e.preventDefault();
    }

    function onMove(e) {
        if (!dragging) return;
        const dx = e.clientX - startX;
        let w = startW - dx;
        w = clamp(w, LAYOUT.MIN_W, LAYOUT.MAX_W);
        pendingW = Math.round(w);

        if (!rafId) {
            rafId = requestAnimationFrame(() => {
                rafId = null;
                document.documentElement.style.setProperty("--right-w", pendingW + "px");
            });
        }
    }

    function onUp() {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove("dragging");
        Dom.workspace.classList.remove("dragging");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        if (rafId) { cancelAnimationFrame(rafId); rafId = null; }

        State.rightW = pendingW || State.rightW;
        persistLayout();
    }

    handle.addEventListener("dblclick", () => {
        State.rightW = LAYOUT.DEFAULT_RIGHT_W;
        document.documentElement.style.setProperty("--right-w", LAYOUT.DEFAULT_RIGHT_W + "px");
        persistLayout();
    });

    handle.addEventListener("mousedown", onDown);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
}

// ─── Keyboard Shortcuts ───────────────────────────────────────────

function initKeyboardShortcuts() {
    document.addEventListener("keydown", (e) => {
        if (e.ctrlKey && (e.key === "]" || e.code === "BracketRight")) {
            e.preventDefault();
            toggleSidebar("right");
        } else if (e.ctrlKey && e.key === "\\") {
            e.preventDefault();
            toggleBothSidebars();
        }
    });
}

// ═══════════════════════════════════════════════════════════════════
// WINDOW CONTROLS (NATIVE DRAG & 8-EDGE RESIZE)
// ═══════════════════════════════════════════════════════════════════

function initWindowControls() {
    initPyWebViewBridge();
    initWindowDrag();
    initWindowResize();
    initWindowActionButtons();
}

function initPyWebViewBridge() {
    if (window.pywebview && window.pywebview.api) {
        State.pyapi = window.pywebview.api;
    } else {
        window.addEventListener("pywebviewready", () => {
            State.pyapi = window.pywebview.api;
        });
    }
}

function initWindowActionButtons() {
    if (Dom.btnMinimize) {
        Dom.btnMinimize.addEventListener("click", () => {
            if (State.pyapi && State.pyapi.minimize) State.pyapi.minimize();
        });
    }

    if (Dom.btnMaximize) {
        Dom.btnMaximize.addEventListener("click", () => {
            if (State.pyapi && State.pyapi.maximize) {
                State.pyapi.maximize();
            } else if (document.fullscreenElement) {
                document.exitFullscreen().catch(() => { });
            } else {
                document.documentElement.requestFullscreen().catch(() => { });
            }
        });
    }

    if (Dom.btnClose) {
        Dom.btnClose.addEventListener("click", () => {
            if (State.pyapi && State.pyapi.close_window) {
                State.pyapi.close_window();
            } else {
                window.close();
            }
        });
    }

    if (Dom.btnNewWindow) {
        Dom.btnNewWindow.addEventListener("click", () => {
            openNewRenderWindow();
        });
    }
}

// ─── Drag Window via Titlebar ─────────────────────────────────────

function initWindowDrag() {
    const bar = Dom.titlebar;
    if (!bar) return;

    let dragging = false;
    let startScreenX = 0, startScreenY = 0;
    let startWinX = 0, startWinY = 0;
    let rafId = null;
    let pendingX = 0, pendingY = 0;

    async function getRect() {
        if (State.pyapi && State.pyapi.get_window_rect) {
            try { return await State.pyapi.get_window_rect(); }
            catch (_) { return null; }
        }
        return null;
    }

    bar.addEventListener("mousedown", async (e) => {
        if (e.target.closest("button, .tb-btn, .hud-pill, input, textarea, a, .workspace, .sidebar, .panel, .terminal-pane, .resizer, .modal-overlay, .modal-card")) return;
        if (e.button !== 0) return;

        const rect = await getRect();
        if (!rect) return; // Browser mode or native handler active

        dragging = true;
        startScreenX = e.screenX;
        startScreenY = e.screenY;
        startWinX = rect.x;
        startWinY = rect.y;
        document.body.style.cursor = "move";
        e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        const dx = e.screenX - startScreenX;
        const dy = e.screenY - startScreenY;
        pendingX = Math.round(startWinX + dx);
        pendingY = Math.round(startWinY + dy);

        if (!rafId) {
            rafId = requestAnimationFrame(() => {
                rafId = null;
                if (State.pyapi && State.pyapi.move_window) {
                    State.pyapi.move_window(pendingX, pendingY);
                }
            });
        }
    });

    document.addEventListener("mouseup", () => {
        if (!dragging) return;
        dragging = false;
        document.body.style.cursor = "";
        if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    });
}

// ─── Resize Window via 8 Edge Handles ─────────────────────────────

function initWindowResize() {
    const handles = document.querySelectorAll(".win-resize");
    if (!handles.length) return;

    handles.forEach(h => {
        let dragging = false;
        let dir = "";
        let startScreenX = 0, startScreenY = 0;
        let startRect = null;
        let rafId = null;
        let pendingW = 0, pendingH = 0, pendingX = 0, pendingY = 0;

        async function getRect() {
            if (State.pyapi && State.pyapi.get_window_rect) {
                try { return await State.pyapi.get_window_rect(); }
                catch (_) { return null; }
            }
            return null;
        }

        h.addEventListener("mousedown", async (e) => {
            if (e.button !== 0) return;
            const rect = await getRect();
            if (!rect) return;

            dragging = true;
            dir = h.dataset.dir;
            startScreenX = e.screenX;
            startScreenY = e.screenY;
            startRect = rect;
            document.body.style.cursor = getComputedStyle(h).cursor;
            e.preventDefault();
            e.stopPropagation();
        });

        document.addEventListener("mousemove", (e) => {
            if (!dragging || !startRect) return;
            const dx = e.screenX - startScreenX;
            const dy = e.screenY - startScreenY;

            let x = startRect.x, y = startRect.y;
            let w = startRect.width, hgt = startRect.height;

            const MIN_W = 640, MIN_H = 420;

            if (dir.includes("e")) w = Math.max(MIN_W, startRect.width + dx);
            if (dir.includes("s")) hgt = Math.max(MIN_H, startRect.height + dy);
            if (dir.includes("w")) {
                const nw = Math.max(MIN_W, startRect.width - dx);
                x = startRect.x + (startRect.width - nw);
                w = nw;
            }
            if (dir.includes("n")) {
                const nh = Math.max(MIN_H, startRect.height - dy);
                y = startRect.y + (startRect.height - nh);
                hgt = nh;
            }

            pendingX = Math.round(x);
            pendingY = Math.round(y);
            pendingW = Math.round(w);
            pendingH = Math.round(hgt);

            if (!rafId) {
                rafId = requestAnimationFrame(() => {
                    rafId = null;
                    if (!State.pyapi) return;
                    if (State.pyapi.set_window_rect) {
                        State.pyapi.set_window_rect(pendingX, pendingY, pendingW, pendingH);
                    } else {
                        if (State.pyapi.move_window) State.pyapi.move_window(pendingX, pendingY);
                        if (State.pyapi.resize_window) State.pyapi.resize_window(pendingW, pendingH);
                    }
                });
            }
        });

        document.addEventListener("mouseup", () => {
            if (!dragging) return;
            dragging = false;
            document.body.style.cursor = "";
            if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
        });
    });
}

// ═══════════════════════════════════════════════════════════════════
// COLLAPSIBLE PANELS
// ═══════════════════════════════════════════════════════════════════

function initCollapsiblePanels() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem("wis-panel-state") || "{}"); } catch (_) { }
    document.querySelectorAll(".panel[data-collapsible]").forEach((panel, index) => {
        const key = panel.classList.contains("project-panel") ? "projects" : `panel-${index}`;
        if (saved[key]) panel.classList.add("collapsed");
        const header = panel.querySelector(".panel-hd");
        if (!header) return;
        header.querySelectorAll("button, input").forEach(el => {
            el.addEventListener("click", (e) => e.stopPropagation());
        });
        header.addEventListener("click", () => {
            panel.classList.toggle("collapsed");
            try {
                const state = JSON.parse(localStorage.getItem("wis-panel-state") || "{}");
                state[key] = panel.classList.contains("collapsed");
                localStorage.setItem("wis-panel-state", JSON.stringify(state));
            } catch (_) { }
        });
    });
}

// ═══════════════════════════════════════════════════════════════════
// WEBSOCKET & BACKEND COMMUNICATION
// ═══════════════════════════════════════════════════════════════════

async function fetchBootstrapToken() {
    try {
        const res = await fetch("/api/auth/bootstrap");
        if (res.ok) {
            const data = await res.json();
            if (data.token) {
                State.token = data.token;
                localStorage.setItem("wis-token", State.token);
                return;
            }
        }
    } catch (_) { }
    State.token = localStorage.getItem("wis-token") || "";
}

function getAuthHeaders() {
    const h = { "Content-Type": "application/json" };
    if (State.token) h["Authorization"] = "Bearer " + State.token;
    return h;
}

function initWebSocket() {
    if (State.ws) {
        try { State.ws.close(); } catch (_) { }
        State.ws = null;
    }

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    let wsUrl = `${protocol}//${location.host}/ws`;
    if (State.token) wsUrl += `?token=${encodeURIComponent(State.token)}`;

    try {
        State.ws = new WebSocket(wsUrl);
    } catch (e) {
        onWsError();
        return;
    }

    State.ws.onopen = () => {
        State.wsConnected = true;
        State.reconnectDelay = 1000;
        if (Dom.wisOrb) Dom.wisOrb.className = "wis-orb";
        if (Dom.tbStatus) {
            Dom.tbStatus.textContent = "SYSTEM ONLINE";
            Dom.tbStatus.className = "tb-center online";
        }
        if (window.terminalManager) {
            for (const sessionId of window.terminalManager.instances.keys()) {
                subscribeWebSocketSession(sessionId);
            }
        }
        refreshPanels();
    };

    State.ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleWsMessage(data);
        } catch (e) {
            console.error("WS Parse error", e);
        }
    };

    State.ws.onclose = () => {
        onWsDisconnect();
    };

    State.ws.onerror = () => {
        onWsError();
    };
}

function onWsDisconnect() {
    State.wsConnected = false;
    if (Dom.wisOrb) Dom.wisOrb.className = "wis-orb offline";
    if (Dom.tbStatus) {
        Dom.tbStatus.textContent = "OFFLINE / RECONNECTING";
        Dom.tbStatus.className = "tb-center offline";
    }

    clearTimeout(State.reconnectTimer);
    State.reconnectTimer = setTimeout(() => {
        State.reconnectDelay = Math.min(10000, State.reconnectDelay * 1.5);
        initWebSocket();
    }, State.reconnectDelay);
}

function onWsError() {
    onWsDisconnect();
}

function handleWsMessage(data) {
    if (data.type === "status") {
        if (data.state === "thinking") {
            setThinking(true, data.label || "WIS is reasoning...", data.session_id);
        } else if (data.state === "done") {
            setThinking(false, "", data.session_id);
            State.currentStreamMsg = null;
            State.currentStreamMessages.delete(data.session_id || window.terminalManager.activeSessionId);
        } else if (data.state === "error") {
            setThinking(false, "", data.session_id);
            appendSystemMessage("Error: " + (data.error || "Unknown"), data.session_id);
        } else if (data.state === "cancelled") {
            setThinking(false, "", data.session_id);
            State.currentStreamMsg = null;
            State.currentStreamMessages.delete(data.session_id || window.terminalManager.activeSessionId);
        }
    } else if (data.type === "chunk") {
        setThinking(false, "", data.session_id);
        appendStreamChunk(data.text || "", data.session_id);
    } else if (data.type === "response") {
        setThinking(false, "", data.session_id);
        // renderFullResponse(data);
        State.currentStreamMsg = null;
        State.currentStreamMessages.delete(data.session_id || window.terminalManager.activeSessionId);
    } else if (data.type === "event_bus") {
        handleBusEvent(data.event, data.data || {});
    }
}

function handleBusEvent(event, payload) {
    addTraceEntry(event, payload);

    if (event === "terminal.spawn_goal") {
        const sid = payload.session_id || window.terminalManager.generateId();
        const term = window.terminalManager.createTerminal(sid);
        term.appendSystemMessage("--- New Goal Spawned ---");
        return;
    }
    
    if (event === "ui.show_log") {
        const modal = document.getElementById("log-modal");
        const pre = document.getElementById("log-output");
        pre.textContent = payload.content || "Empty log.";
        modal.classList.remove("hidden");
        return;
    }
    
    if (event === "ui.open_file") {
        const path = payload.path;
        if (path) {
            window.open("/projects/" + path, "_blank");
        }
        return;
    }

    // Try to route to specific terminal if session_id is provided, otherwise fallback to active
    let targetTerm = null;
    if (payload.session_id) {
        targetTerm = window.terminalManager.getTerminal(payload.session_id);
    }
    const sessionEvent = Boolean(payload.session_id);

    if (event === "reasoning.token_chunk") {
        // Stream chunk rendering is currently not implemented for multi-terminal via WS, 
        // as REST SSE is used. We ignore it here or implement stream chunk routing later.
    } else if (event === "pipeline.input_received") {
        stopTtsAudio();
        // Do not appendUserMessage here because sendChatRequest already does it instantly.
        // This avoids duplication and blocking issues if WS is delayed.
    } else if (event === "pipeline.call_start") {
        if (sessionEvent && targetTerm) targetTerm.setThinking(true, "Executing: " + (payload.action || payload.skill) + "...");
    } else if (event === "pipeline.loop_step") {
        if (sessionEvent && targetTerm) targetTerm.setThinking(true, "Thinking (Step " + payload.step + ")...");
    } else if (event === "ptt.started") {
        stopTtsAudio();
        if (targetTerm) targetTerm.setThinking(true, "Listening (PTT active)...");
    } else if (event === "ptt.stopped") {
        if (targetTerm) targetTerm.setThinking(true, "Transcribing audio...");
    } else if (event === "telemetry.data" || event === "telemetry.threshold_triggered") {
        updateTelemetryCard(payload);
    } else if (event === "hardware.device_connected" || event === "hardware.graph_updated") {
        loadHardwareList();
    } else if (event === "security.mode_changed") {
        setSecurityModeUI(payload.mode);
    } else if (event === "security.clearance_requested") {
        showApprovalModal(payload);
    } else if (event.startsWith("goal.")) {
        loadGoals();
    } else if (event.startsWith("long_horizon.")) {
        loadLongHorizonTasks();
    } else if (event === "console.render_requested") {
        openRenderWindow(
            payload.html,
            payload.title || "WIS Render Engine",
            payload.width || 800,
            payload.height || 600,
            payload.session_id || window.terminalManager.activeSessionId,
            payload.render_id || null
        );
    } else if (event === "console.render_closed") {
        forgetRenderWindow(payload.render_id);
    }
}

// ═══════════════════════════════════════════════════════════════════
// WIS RENDER ENGINE — MULTI-WINDOW PER SESSION
// ═══════════════════════════════════════════════════════════════════

function nextRenderId(sessionId) {
    const count = (State.renderCounters.get(sessionId) || 0) + 1;
    State.renderCounters.set(sessionId, count);
    return `${sessionId}-view-${count}`;
}

/**
 * Opens (or updates) a render window owned by a session.
 * Omitting renderId always creates a new window, so a console can open
 * as many as it needs; passing an existing renderId refreshes that window.
 */
function openRenderWindow(html, title, width, height, sessionId, renderId = null) {
    const sid = sessionId || "default";
    const id = renderId || nextRenderId(sid);
    if (!State.renderWindows.has(sid)) State.renderWindows.set(sid, new Map());
    const sessionWindows = State.renderWindows.get(sid);

    // Native pywebview bridge: one real OS window per renderId.
    if (State.pyapi && State.pyapi.open_render_window) {
        State.pyapi.open_render_window(html, title, width, height, id);
        sessionWindows.set(id, { mode: "native" });
        return id;
    }

    // Browser fallback: reuse the existing tab by navigating it in place.
    fetch("/api/render", {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ html, title, width, height, render_id: id, session_id: sid }),
    }).then(res => res.json()).then(data => {
        if (!data.url) return;
        const existing = sessionWindows.get(id);
        if (existing && existing.window && !existing.window.closed) {
            existing.window.location.replace(data.url);
            existing.window.focus();
            return;
        }
        const popup = window.open(data.url, "_blank", `width=${width},height=${height}`);
        sessionWindows.set(id, { mode: "browser", window: popup, url: data.url });
    }).catch(err => {
        appendSystemMessage("Render window error: " + err.message, sid);
    });
    return id;
}

function forgetRenderWindow(renderId) {
    if (!renderId) return;
    State.renderWindows.forEach(sessionWindows => sessionWindows.delete(renderId));
}

/** Closes every render window owned by a session. */
window.closeSessionRenderWindows = function (sessionId) {
    const sid = sessionId || window.terminalManager.activeSessionId;
    const sessionWindows = State.renderWindows.get(sid);
    if (!sessionWindows) return 0;
    let closed = 0;
    sessionWindows.forEach((entry, renderId) => {
        fetch(`/api/render/${encodeURIComponent(renderId)}`, {
            method: "DELETE",
            headers: getAuthHeaders(),
        }).catch(() => { });
        if (entry.mode === "browser" && entry.window && !entry.window.closed) {
            entry.window.close();
        }
        closed += 1;
    });
    sessionWindows.clear();
    return closed;
};

function subscribeWebSocketSession(sessionId) {
    if (State.ws && State.ws.readyState === WebSocket.OPEN && sessionId) {
        State.ws.send(JSON.stringify({ type: "subscribe_session", session_id: sessionId }));
    }
}

// ═══════════════════════════════════════════════════════════════════
// CHAT & TERMINAL RENDERING
// ═══════════════════════════════════════════════════════════════════

function setThinking(active, label = "WIS is reasoning...", sessionId = null) {
    // Legacy support for global thinking state (e.g. voice mic active)
    State.isThinking = active;
    if (Dom.wisOrb) {
        Dom.wisOrb.className = active ? "wis-orb thinking" : "wis-orb";
    }
    
    let term = null;
    if (sessionId) {
        term = window.terminalManager.getTerminal(sessionId);
    }
    if (!term) {
        term = window.terminalManager.getActiveTerminal();
    }
    if (term) term.setThinking(active, label);
}

function appendUserMessage(text, sessionId = null) {
    let term = sessionId ? window.terminalManager.getTerminal(sessionId) : window.terminalManager.getActiveTerminal();
    if (term) term.appendUserMessage(text);
}

function appendSystemMessage(text, sessionId = null) {
    let term = sessionId ? window.terminalManager.getTerminal(sessionId) : window.terminalManager.getActiveTerminal();
    if (term) term.appendSystemMessage(text);
}

function appendStreamChunk(chunk, sessionId = null) {
    const streamKey = sessionId || window.terminalManager.activeSessionId;
    let streamMsg = State.currentStreamMessages.get(streamKey);
    const terminal = window.terminalManager.getTerminal(streamKey) || window.terminalManager.getActiveTerminal();
    if (!terminal) return;

    if (!streamMsg) {
        const el = document.createElement("div");
        el.className = "msg msg-wis";
        el.innerHTML = `
            <div class="msg-header">
                <span class="msg-author">WIS CORE</span>
                <span class="msg-time">${new Date().toLocaleTimeString()}</span>
            </div>
            <div class="msg-bubble"></div>
        `;
        terminal.output.appendChild(el);
        streamMsg = el.querySelector(".msg-bubble");
        State.currentStreamMessages.set(streamKey, streamMsg);
    }

    streamMsg.dataset.raw = (streamMsg.dataset.raw || "") + chunk;
    
    let displayRaw = streamMsg.dataset.raw;
    const jsonMatch = displayRaw.match(/(?:```(?:json)?\s*)?\{\s*"(?:tool_calls|calls)"\s*:/);
    if (jsonMatch) {
        displayRaw = displayRaw.substring(0, jsonMatch.index).trim();
    } else {
        const arrMatch = displayRaw.match(/(?:```(?:json)?\s*)?\[\s*\{\s*"(?:action|name|skill|type|command)"/);
        if (arrMatch) {
            displayRaw = displayRaw.substring(0, arrMatch.index).trim();
        }
    }
    
    streamMsg.innerHTML = formatMarkdown(displayRaw);
    terminal.scrollToBottom();
}

function renderFullResponse(data) {
    const text = data.response || "";
    const calls = data.calls || [];

    if (State.currentStreamMsg && State.currentStreamMsg.dataset.raw) {
        // Stream completed
        State.currentStreamMsg.innerHTML = formatMarkdown(text);
        // if (calls.length > 0) {
        //     renderCallsInBubble(State.currentStreamMsg, calls);
        // }
    } else {
        const el = document.createElement("div");
        el.className = "msg msg-wis";
        el.innerHTML = `
            <div class="msg-header">
                <span class="msg-author">WIS CORE</span>
                <span class="msg-time">${new Date().toLocaleTimeString()}</span>
            </div>
            <div class="msg-bubble">${formatMarkdown(text)}</div>
        `;
        const bubble = el.querySelector(".msg-bubble");
        // if (calls.length > 0) renderCallsInBubble(bubble, calls);
        Dom.terminalOutput.appendChild(el);
    }

    if (data.path && Dom.pillPath) {
        Dom.pillPath.textContent = data.path;
        Dom.pillPath.classList.remove("dim");
    }

    scrollTerminalToBottom();

    if (State.ttsEnabled && text) {
        playTtsAudio(text);
    }
}

function renderCallsInBubble(bubble, calls) {
    calls.forEach(call => {
        const card = document.createElement("div");
        card.className = "tool-card";
        const fnName = call.name || call.skill || "tool_call";
        const args = JSON.stringify(call.arguments || call.params || {}, null, 2);

        card.innerHTML = `
            <details>
                <summary class="tool-card-hd" style="cursor: pointer; list-style: none;">
                    <span class="tool-name">${escapeHtml(fnName)}</span>
                    <span class="tool-status success">COMPLETED</span>
                </summary>
                <div class="tool-body" style="margin-top: 8px;">${escapeHtml(args)}</div>
            </details>
        `;
        bubble.appendChild(card);
    });
}

function scrollTerminalToBottom() {
    // Handled by TerminalInstance
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function formatMarkdown(src) {
    const source = String(src || "");
    const blocks = [];
    const inlineCode = [];
    const stash = (html, target, prefix) => {
        const key = `\u0000MD${prefix}${target.length}\u0000`;
        target.push(html);
        return key;
    };

    let text = escapeHtml(source).replace(/```([a-zA-Z0-9_+.#-]*)\s*\n?([\s\S]*?)```/g, (_, lang, code) => {
        const label = lang ? `<span class="md-code-lang">${escapeHtml(lang)}</span>` : "";
        return stash(`<div class="md-code-block">${label}<pre><code>${code.trim()}</code></pre></div>`, blocks, "B");
    });
    text = text.replace(/`([^`\n]+)`/g, (_, code) => stash(`<code>${code}</code>`, inlineCode, "I"));

    const formatInline = (value) => value
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/__([^_]+)__/g, "<strong>$1</strong>")
        .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
        .replace(/_([^_\n]+)_/g, "<em>$1</em>")
        .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

    const lines = text.split("\n");
    const html = [];
    let listType = null;
    const closeList = () => {
        if (listType) html.push(`</${listType}>`);
        listType = null;
    };

    for (const rawLine of lines) {
        const line = rawLine.trimEnd();
        const heading = line.match(/^(#{1,3})\s+(.+)$/);
        const unordered = line.match(/^\s*[-*]\s+(.+)$/);
        const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);

        if (!line.trim()) {
            closeList();
            html.push('<div class="md-spacer"></div>');
        } else if (heading) {
            closeList();
            const level = heading[1].length;
            html.push(`<h${level}>${formatInline(heading[2])}</h${level}>`);
        } else if (unordered || ordered) {
            const nextType = unordered ? "ul" : "ol";
            if (listType !== nextType) {
                closeList();
                listType = nextType;
                html.push(`<${listType}>`);
            }
            html.push(`<li>${formatInline((unordered || ordered)[1])}</li>`);
        } else if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) {
            closeList();
            html.push('<hr>');
        } else if (/^>\s?/.test(line)) {
            closeList();
            html.push(`<blockquote>${formatInline(line.replace(/^>\s?/, ""))}</blockquote>`);
        } else {
            closeList();
            html.push(`<p>${formatInline(line)}</p>`);
        }
    }
    closeList();

    let out = html.join("");
    out = out.replace(/\u0000MD([BI])(\d+)\u0000/g, (_, kind, index) => {
        const position = Number(index);
        return kind === "B" ? (blocks[position] || "") : (inlineCode[position] || "");
    });
    return out;
}

// ─── Input Submission ─────────────────────────────────────────────

// Aborta el turno cognitivo EN EL SERVIDOR. Abortar el fetch solo corta la
// conexion HTTP: el turno seguia ejecutandose y la sesion quedaba bloqueada
// con "A cognitive turn is already running for this session."
window.cancelServerTurn = function(sessionId) {
    const sid = sessionId || "default";
    try {
        fetch("/api/cancel", {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ session_id: sid }),
            keepalive: true,
        }).catch(() => { /* la cancelacion es best-effort */ });
    } catch (e) { /* noop */ }
    try {
        if (window.ws && window.ws.readyState === WebSocket.OPEN) {
            window.ws.send(JSON.stringify({ type: "cancel", session_id: sid }));
        }
    } catch (e) { /* noop */ }
};

window.sendChatRequest = async function(text, terminalInstance) {
    if (!text || terminalInstance.isThinking) return;
    terminalInstance.cancelled = false;
    
    stopTtsAudio();
    terminalInstance.appendUserMessage(text); 
    terminalInstance.setThinking(true, "Dispatching intent...");
    
    // Setup AbortController for cancel button
    terminalInstance.abortController = new AbortController();
    
    try {
        const res = await fetch("/api/chat", {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ message: text, session_id: terminalInstance.sessionId }),
            signal: terminalInstance.abortController.signal
        });
        
        // If aborted during fetch
        if (!terminalInstance.abortController) return;
        terminalInstance.abortController = null;
        
        const data = await res.json();
        terminalInstance.setThinking(false);
        
        // Handle goal spawn event explicitly if path is goal
        if (data.path_used === "goal") {
            // terminal.spawn_goal event will be triggered via event bus or we can do it directly
            terminalInstance.appendSystemMessage("Goal Dispatched.");
        }
        
        if (data.response) {
            terminalInstance.appendAssistantMessage(data.response);
            if (State.ttsEnabled) {
                playTtsAudio(data.response);
            }
        }

        if (/^\/delete\s+/i.test(text) && terminalInstance.sessionId !== "main") {
            window.terminalManager.closeTerminal(terminalInstance.sessionId);
            loadProjects();
        }
        
        // Render tool calls
        if (data.calls && data.calls.length > 0) {
            let toolsHtml = `<details class="msg-tools-box">
                <summary>Tool activity (${data.calls.length})</summary>
                <div class="msg-tools-list">`;
            for (let i = 0; i < data.calls.length; i++) {
                const call = data.calls[i];
                const resObj = data.results && data.results[i] ? data.results[i] : { ok: true };
                const icon = resObj.ok ? "[OK]" : "[ERR]";
                const cname = resObj.ok ? "success" : "danger";
                
                toolsHtml += `<div class="msg-tool-item">
                    <span class="tool-icon ${cname}">${icon}</span>
                    <span class="tool-action">${call.action || call.name || "tool"}</span>
                </div>`;
            }
            toolsHtml += '</div></details>';
            
            const msg = document.createElement("div");
            msg.className = "msg msg-wis";
            msg.innerHTML = toolsHtml;
            terminalInstance.output.appendChild(msg);
            terminalInstance.scrollToBottom();
        }
    } catch(e) {
        if (e.name === 'AbortError') {
            // Handled by cancel button
            return;
        }
        terminalInstance.setThinking(false);
        terminalInstance.appendSystemMessage("REST Chat Error: " + e.message);
    }
}

// ─── Voice Input, Uploads & TTS ───────────────────────────────────

window.startVoiceInput = async function() {
    const term = window.terminalManager.getActiveTerminal();
    if (!term) return;
    
    term.appendSystemMessage("Listening to hardware microphone (5s)...");

    try {
        const res = await fetch("/api/listen", {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ language: "en-US", timeout: 5.0 }),
        });
        const data = await res.json();

        if (data.transcribed_text) {
            term.appendUserMessage(data.transcribed_text);
            if (data.response) {
                term.appendAssistantMessage(data.response);
                if (State.ttsEnabled) {
                    playTtsAudio(data.response);
                }
            }
        } else {
            term.appendSystemMessage(data.message || "No speech detected.");
        }
    } catch (e) {
        term.appendSystemMessage("Voice input error: " + e.message);
    }
}

async function uploadFile(file) {
    const term = window.terminalManager.getActiveTerminal();
    if (!file || !term) return;
    
    term.appendSystemMessage(`Uploading '${file.name}'...`);

    const formData = new FormData();
    formData.append("file", file);

    try {
        const h = {};
        if (State.token) h["Authorization"] = "Bearer " + State.token;
        const res = await fetch("/api/upload", {
            method: "POST",
            headers: h,
            body: formData,
        });
        const data = await res.json();
        if (data.success) {
            term.appendSystemMessage(`File saved: ${data.path}`);
            // Inform model directly via chat
            window.sendChatRequest(`Attached file: ${data.path} (${data.filename})`, term);
        } else {
            term.appendSystemMessage(`Upload failed: ${data.error || "Unknown"}`);
        }
    } catch (e) {
        term.appendSystemMessage(`Upload failed: ${e.message}`);
    }
}

async function fetchTtsBlob(sentence) {
    try {
        const res = await fetch("/api/tts", {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ text: sentence }),
        });
        if (res.ok) return await res.blob();
    } catch (_) { }
    return null;
}

function stopTtsAudio() {
    State.currentTtsSession++;
    if (State.currentAudio) {
        State.currentAudio.pause();
        State.currentAudio.currentTime = 0;
        State.currentAudio = null;
    }
}

async function playTtsAudio(text) {
    try {
        stopTtsAudio();
        const mySession = State.currentTtsSession;

        // WIS Rule: direct and concise. Only read the first relevant chunk (1 or 2 sentences max)
        let sentences = (text.match(/[^.!?\n]+(?:[.!?\n]+|$)/g) || [text])
            .map(s => s.trim()).filter(Boolean);
        
        if (sentences.length === 0) return;
        
        // Truncate to first 2 sentences for brevity if the message is long
        sentences = sentences.slice(0, 2);
        
        let nextBlobPromise = fetchTtsBlob(sentences[0]);
        
        for (let i = 0; i < sentences.length; i++) {
            if (State.currentTtsSession !== mySession) break;

            const blob = await nextBlobPromise;
            
            if (i + 1 < sentences.length && State.currentTtsSession === mySession) {
                nextBlobPromise = fetchTtsBlob(sentences[i+1]);
            }
            
            if (blob && State.currentTtsSession === mySession) {
                const url = URL.createObjectURL(blob);
                const audio = new Audio(url);
                State.currentAudio = audio;
                
                await new Promise(resolve => {
                    audio.onended = () => { State.currentAudio = null; resolve(); };
                    audio.onerror = () => { State.currentAudio = null; resolve(); };
                    audio.play().catch(resolve);
                });
            }
        }
    } catch (_) { }
}

// ═══════════════════════════════════════════════════════════════════
// SIDEBAR PANELS DATA STREAM
// ═══════════════════════════════════════════════════════════════════

async function refreshPanels() {
    loadProjects();
    loadTasks();
    loadSecurityMode();
}

async function loadHardwareList() {
    // Hardware graph panel removed from UI
}

async function loadProjects() {
    if (!Dom.projectTree) return;
    try {
        const res = await fetch("/api/projects", { headers: getAuthHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const projects = data.projects || [];
        if (!projects.length) {
            Dom.projectTree.innerHTML = `<div class="empty-state">No projects found</div>`;
            return;
        }
        Dom.projectTree.innerHTML = projects.map(project => `
            <button class="project-node" type="button" data-session-id="${escapeHtml(project.session_id)}">
                <span class="project-node-icon">▸</span>
                <span class="project-node-copy">
                    <span class="project-node-name">${escapeHtml(project.name)}</span>
                    <span class="project-node-meta">${project.has_history ? `${project.history_count} turns` : "New session"} · ${project.focused_count || 0} focused · ${project.trace_count || 0} trace</span>
                </span>
                <span class="project-node-status">${project.has_history ? "●" : "○"}</span>
            </button>
        `).join("");
        Dom.projectTree.querySelectorAll(".project-node").forEach(node => {
            node.addEventListener("click", () => openProjectSession(node.dataset.sessionId));
        });
    } catch (e) {
        Dom.projectTree.innerHTML = `<div class="empty-state">Projects unavailable</div>`;
        console.error("Projects sync error:", e);
    }
}

async function openProjectSession(sessionId) {
    if (!sessionId || !window.terminalManager) return;
    const terminal = await window.terminalManager.openSession(sessionId);
    window.terminalManager.instances.forEach(instance => {
        instance.element.classList.toggle("project-selected", instance === terminal);
    });
}

function updateTelemetryCard(data) {
    // Telemetry panel removed from UI
}

async function loadTasks() {
    try {
        const res = await fetch("/api/tasks", { headers: getAuthHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const tasks = (data.tasks || []).filter(task => task.status === "executing");

        if (Dom.goalList) {
            if (tasks.length === 0) {
                Dom.goalList.innerHTML = `<div class="empty-state">No active tasks</div>`;
                return;
            }
            Dom.goalList.innerHTML = tasks.map(g => {
                let statusColor = "var(--text-color)";
                if (g.status === "failed") statusColor = "var(--red)";
                if (g.status === "done") statusColor = "var(--green)";
                if (g.status === "executing") statusColor = "var(--cyan)";
                return `
                    <div class="item-card">
                        <div class="item-hd">
                            <span class="item-name">${escapeHtml(g.text)}</span>
                            <div style="display:flex; gap: 6px; align-items:center;">
                                <button class="mini-btn" onclick="window.viewTaskLogs('${g.id}')" title="View Logs">Logs</button>
                                <button class="mini-btn danger" onclick="window.deleteTask('${g.id}')" title="Kill Task">X</button>
                            </div>
                        </div>
                        <div class="item-meta" style="color:${statusColor}">${escapeHtml(g.status || "active")}</div>
                        <div class="item-meta" style="font-size:10px; margin-top:4px;">${escapeHtml(g.result || g.error || "")}</div>
                    </div>
                `;
            }).join("");
        }
    } catch (e) {
        console.error("Tasks sync error:", e);
    }
}

window.deleteTask = async function(taskId) {
    if (!confirm("Are you sure you want to stop and delete this task?")) return;
    try {
        const res = await fetch(`/api/tasks/${taskId}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });
        if (res.ok) {
            loadTasks();
        } else {
            console.error("Failed to delete task");
        }
    } catch (e) {
        console.error("Error deleting task:", e);
    }
};

let _logInterval = null;

window.viewTaskLogs = function(taskId) {
    const modal = document.getElementById("log-modal");
    const output = document.getElementById("log-output");
    if (!modal || !output) return;
    
    modal.classList.remove("hidden");
    output.textContent = "Loading logs...";
    
    // Fetch immediately
    const fetchLogs = async () => {
        try {
            const res = await fetch(`/api/tasks/${taskId}/logs`, { headers: getAuthHeaders() });
            if (res.ok) {
                const data = await res.json();
                const wasAtBottom = output.scrollHeight - output.scrollTop <= output.clientHeight + 20;
                output.textContent = data.logs || "No logs yet.";
                if (wasAtBottom) {
                    output.scrollTop = output.scrollHeight;
                }
            }
        } catch (e) {
            console.error("Log fetch error:", e);
        }
    };
    
    fetchLogs();
    
    // Poll every 2 seconds
    if (_logInterval) clearInterval(_logInterval);
    _logInterval = setInterval(fetchLogs, 2000);
    
    const closeBtn = document.getElementById("btn-log-close");
    if (closeBtn) {
        closeBtn.onclick = () => {
            modal.classList.add("hidden");
            if (_logInterval) clearInterval(_logInterval);
        };
    }
};

function addTraceEntry(event, data) {
    if (!Dom.traceList) return;

    const firstChild = Dom.traceList.firstElementChild;
    if (firstChild && firstChild.classList.contains("empty-state")) {
        Dom.traceList.innerHTML = "";
    }

    const item = document.createElement("div");
    item.className = "item-card";
    item.innerHTML = `
        <div class="item-hd">
            <span class="item-name" style="color:var(--cyan);font-size:10px">${escapeHtml(event)}</span>
            <span class="item-meta">${new Date().toLocaleTimeString()}</span>
        </div>
    `;

    Dom.traceList.insertBefore(item, Dom.traceList.firstChild);

    // Keep max 25 traces
    while (Dom.traceList.children.length > 25) {
        Dom.traceList.removeChild(Dom.traceList.lastChild);
    }
}

// ═══════════════════════════════════════════════════════════════════
// SECURITY & CLEARANCE MODAL
// ═══════════════════════════════════════════════════════════════════

async function loadSecurityMode() {
    try {
        const res = await fetch("/api/security/mode", { headers: getAuthHeaders() });
        if (res.ok) {
            const data = await res.json();
            setSecurityModeUI(data.mode);
        }
    } catch (_) { }
}

function setSecurityModeUI(mode) {
    State.securityMode = mode || "secure";
    if (Dom.pillMode) {
        Dom.pillMode.textContent = State.securityMode.toUpperCase();
        Dom.pillMode.className = "hud-pill hud-pill-btn " + (State.securityMode === "privileged" ? "yellow" : "green");
    }
}

async function toggleSecurityMode() {
    const nextMode = State.securityMode === "privileged" ? "secure" : "privileged";
    try {
        const res = await fetch("/api/security/mode", {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ mode: nextMode }),
        });
        if (res.ok) {
            const data = await res.json();
            setSecurityModeUI(data.mode);
            appendSystemMessage(`Security mode switched to [${data.mode.toUpperCase()}]`);
        }
    } catch (e) {
        appendSystemMessage("Failed to switch security mode: " + e.message);
    }
}

function showApprovalModal(data) {
    State.pendingApproval = data;
    if (Dom.approvalText) {
        Dom.approvalText.textContent = `Action: ${data.action || data.skill || "System execution"}\nTarget: ${JSON.stringify(data.params || {})}`;
    }
    if (Dom.approvalModal) Dom.approvalModal.classList.remove("hidden");
}

async function handleApproval(approved) {
    if (Dom.approvalModal) Dom.approvalModal.classList.add("hidden");
    const endpoint = approved ? "/api/approve" : "/api/deny";
    const sessionId = State.pendingApproval && State.pendingApproval.session_id ? State.pendingApproval.session_id : "default";
    try {
        await fetch(endpoint, { 
            method: "POST", 
            headers: getAuthHeaders(),
            body: JSON.stringify({ session_id: sessionId })
        });
        appendSystemMessage(approved ? "Security clearance AUTHORIZED." : "Security clearance DENIED.", sessionId);
    } catch (e) {
        appendSystemMessage("Clearance response error: " + e.message, sessionId);
    }
    State.pendingApproval = null;
}

// ═══════════════════════════════════════════════════════════════════
// GOALS & LONG HORIZON MODALS
// ═══════════════════════════════════════════════════════════════════

function initModals() {
    // Approval
    if (Dom.btnAuthorize) Dom.btnAuthorize.addEventListener("click", () => handleApproval(true));
    if (Dom.btnDeny) Dom.btnDeny.addEventListener("click", () => handleApproval(false));

    // Task Modal
    if (Dom.btnAddGoal) Dom.btnAddGoal.addEventListener("click", () => {
        Dom.goalInput.value = "";
        Dom.goalModal.classList.remove("hidden");
        Dom.goalInput.focus();
    });
    if (Dom.btnGoalCancel) Dom.btnGoalCancel.addEventListener("click", () => Dom.goalModal.classList.add("hidden"));
    if (Dom.goalPriority) {
        Dom.goalPriority.addEventListener("input", (e) => {
            Dom.goalPriorityVal.textContent = e.target.value;
        });
    }
    if (Dom.btnGoalSubmit) {
        Dom.btnGoalSubmit.addEventListener("click", async () => {
            const text = Dom.goalInput.value.trim();
            if (!text) return;
            const priority = parseInt(Dom.goalPriority.value, 10) || 5;
            Dom.goalModal.classList.add("hidden");
            try {
                await fetch("/api/tasks", {
                    method: "POST",
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ text, priority }),
                });
                loadTasks();
                appendSystemMessage(`Background task spawned: '${text}'`);
            } catch (e) {
                appendSystemMessage("Failed to create task: " + e.message);
            }
        });
    }
}

function openNewRenderWindow() {
    const sessionId = (window.terminalManager && window.terminalManager.activeSessionId) || "main";
    const html = `
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>WIS View · ${escapeHtml(sessionId)}</title>
            <style>
                body { background: #050508; color: #8b5cf6; font-family: monospace; padding: 20px; }
                h2 { color: #06b6d4; }
            </style>
        </head>
        <body>
            <h2>W·I·S AGI Viewport</h2>
            <p>Session: <strong>${escapeHtml(sessionId)}</strong></p>
            <p>Native pywebview multi-window render engine online.</p>
            <div id="clock"></div>
            <script>
                setInterval(() => {
                    document.getElementById('clock').textContent = new Date().toISOString();
                }, 1000);
            </script>
        </body>
        </html>
    `;

    // No renderId: every click opens an additional independent window.
    openRenderWindow(html, `WIS Render Engine · ${sessionId}`, 800, 600, sessionId);
}

// ═══════════════════════════════════════════════════════════════════
// BOOT SCREEN SEQUENCE
// ═══════════════════════════════════════════════════════════════════

function runBootSequence() {
    const steps = [
        { pct: 15, msg: "Initializing Cortex Reasoning Engine..." },
        { pct: 40, msg: "Connecting Hardware & Skill Vault..." },
        { pct: 70, msg: "Mounting AVRORA PC Automation Engine..." },
        { pct: 90, msg: "Establishing WebSocket Pipeline..." },
        { pct: 100, msg: "Cognitive OS v2.0 Ready." },
    ];

    let i = 0;
    function nextStep() {
        if (i < steps.length) {
            const s = steps[i++];
            if (Dom.bootFill) Dom.bootFill.style.width = s.pct + "%";
            if (Dom.bootPct) Dom.bootPct.textContent = s.pct + "%";
            if (Dom.bootLog) Dom.bootLog.textContent = "> " + s.msg;
            setTimeout(nextStep, 180);
        } else {
            setTimeout(() => {
                if (Dom.bootOverlay) Dom.bootOverlay.classList.add("fade-out");
                if (Dom.root) Dom.root.classList.remove("hidden");
                if (Dom.userInput) Dom.userInput.focus();
            }, 300);
        }
    }
    nextStep();
}

// ═══════════════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", async () => {
    cacheDom();
    restoreLayout();
    initResizers();
    initKeyboardShortcuts();
    initCollapsiblePanels();
    initWindowControls();
    initModals();

    // Toggle button handlers
    if (Dom.btnToggleRight) Dom.btnToggleRight.addEventListener("click", () => toggleSidebar("right"));
    if (Dom.btnCloseRight) Dom.btnCloseRight.addEventListener("click", () => toggleSidebar("right"));
    // Pill-mode button toggles security mode directly
    if (Dom.pillMode) Dom.pillMode.addEventListener("click", toggleSecurityMode);
    if (Dom.btnTts) {
        Dom.btnTts.classList.toggle("active", State.ttsEnabled);
        Dom.btnTts.addEventListener("click", () => {
            State.ttsEnabled = !State.ttsEnabled;
            localStorage.setItem("wis-tts", State.ttsEnabled);
            Dom.btnTts.classList.toggle("active", State.ttsEnabled);
            appendSystemMessage(`TTS Voice output ${State.ttsEnabled ? "ENABLED" : "DISABLED"}`);
        });
    }

    // Input handlers are now managed by TerminalManager per instance

    // Global File Upload Hook
    if (Dom.fileInput) {
        Dom.fileInput.addEventListener("change", (e) => {
            if (e.target.files && e.target.files[0]) {
                uploadFile(e.target.files[0]);
            }
        });
        window.triggerGlobalFileUpload = function() {
            Dom.fileInput.click();
        };
    }

    // Check if running in standalone popout window mode (?standalone=1&session=...)
    const urlParams = new URLSearchParams(window.location.search);
    const isStandalone = urlParams.get("standalone") === "1" || urlParams.get("standalone") === "true";
    const targetSession = urlParams.get("session") || "main";

    if (isStandalone) {
        document.body.classList.add("standalone-terminal");
        if (Dom.bootOverlay) Dom.bootOverlay.remove();
        if (Dom.root) Dom.root.classList.remove("hidden");
        document.title = `WIS · Terminal [${targetSession}]`;

        await fetchBootstrapToken();
        const term = window.terminalManager.createTerminal(targetSession);
        window.terminalManager.setActive(targetSession);
        initWebSocket();
        await term.restoreHistory();
        if (term.input) term.input.focus();
        return;
    }

    // Connect & boot (Normal Mode)
    await fetchBootstrapToken();
    window.terminalManager.createTerminal("main");
    await window.terminalManager.restorePersistentState();
    initWebSocket();
    runBootSequence();
});