// console/web/terminal.js

class TerminalInstance {
    constructor(manager, sessionId, template) {
        this.manager = manager;
        this.sessionId = sessionId;
        this.isThinking = false;
        this.cancelled = false;
        this.currentAudio = null;
        this.ttsInterrupted = false;

        // Clone DOM
        this.element = template.content.cloneNode(true).firstElementChild;
        this.element.dataset.sessionId = sessionId;

        // Cache inner DOM
        this.header = this.element.querySelector(".terminal-header");
        this.title = this.element.querySelector(".terminal-title");
        this.output = this.element.querySelector(".terminal-output");
        this.thinkingRow = this.element.querySelector(".thinking-row");
        this.thinkingLabel = this.element.querySelector(".thinking-label");
        this.input = this.element.querySelector(".terminal-input");
        this.btnPopout = this.element.querySelector('[action="popout"]');
        this.btnFloat = this.element.querySelector('[action="float"]');
        this.btnCancel = this.element.querySelector('[action="cancel"]');
        this.btnMic = this.element.querySelector('[action="mic"]');
        this.btnUpload = this.element.querySelector('[action="upload"]');
        this.btnSend = this.element.querySelector('[action="send"]');
        this.btnMinimize = this.element.querySelector('[action="minimize"]');
        this.btnClose = this.element.querySelector('[action="close"]');
        this.isFloating = false;
        this._floatingDragInit = false;

        this.title.textContent = sessionId;

        // Setup Events
        this.setupEvents();
    }

    setupAutocomplete() {
        const COMMANDS = [
            { cmd: "/cd",            args: "<ruta>",           desc: "Cambia el directorio local de la consola" },
            { cmd: "/new",           args: "<nombre>",         desc: "Crea el proyecto en d:\\WIS\\Projects y hace cd" },
            { cmd: "/projects",      args: "",                  desc: "Lista las carpetas dentro de d:\\WIS\\Projects" },
            { cmd: "/stop",          args: "",                  desc: "Detiene los procesos de fondo vinculados a esta sesion" },
            { cmd: "/delete",        args: "<nombre>",         desc: "Borra el proyecto y detiene sus procesos" },
            { cmd: "/clear",         args: "",                  desc: "Limpia la pantalla visual localmente" },
            { cmd: "/help",          args: "",                  desc: "Lista todos los comandos disponibles" },
            { cmd: "/swarm",         args: "",                  desc: "Interroga el estado del enjambre de terminales" },
            { cmd: "/hw-scan",       args: "",                  desc: "Escanea puertos COM (serial) e IPs en red local" },
            { cmd: "/port",          args: "<num_opcional>",    desc: "Levanta un micro-servidor HTTP estatico en la carpeta" },
            { cmd: "/git",           args: "<msg_opcional>",    desc: "Hace add, commit y push del codigo automaticamente" },
            { cmd: "/build",         args: "",                  desc: "Detecta e invoca el comando de build o install del proyecto" },
            { cmd: "/reboot",        args: "",                  desc: "Limpia la memoria a corto plazo del LLM en esta sesion" },
            { cmd: "/goal",          args: "<desc>",            desc: "Lanza un worker en background para un objetivo largo" },
            { cmd: "/proactividad",  args: "<on|off>",          desc: "Enciende o apaga el motor proactivo" },
            { cmd: "/ping",          args: "<ip>",              desc: "Verifica latencia contra una IP local o remota" },
            { cmd: "/list",          args: "<ruta_opcional>",   desc: "Lista los archivos del proyecto o ruta especificada" },
            { cmd: "/run",           args: "<comando>",         desc: "Ejecuta y muestra el output en ventana modal" },
            { cmd: "/open",          args: "<archivo>",         desc: "Abre el archivo en una nueva pestana del navegador" },
            { cmd: "/sys",           args: "",                  desc: "Muestra la telemetria del SO Host (CPU, RAM, Discos)" },
            { cmd: "/focus",         args: "<archivo>",         desc: "Inyecta un archivo en la memoria transitoria" },
            { cmd: "/unfocus",       args: "<archivo>",         desc: "Quita un archivo de la memoria transitoria" },
            { cmd: "/context",       args: "",                  desc: "Muestra los archivos actualmente en memoria transitoria" },
            { cmd: "/clear-context", args: "",                  desc: "Limpia todos los archivos de la memoria transitoria" },
            { cmd: "/search",        args: "<texto>",           desc: "Buscador global en el proyecto actual" },
            { cmd: "/logs",          args: "",                  desc: "Abre el log maestro de WIS" },
            { cmd: "/ps",            args: "",                  desc: "Muestra tareas y agentes activos en Host" },
            { cmd: "/kill",          args: "<pid>",             desc: "Mata un proceso forzosamente" },
            { cmd: "/memory-map",    args: "",                  desc: "Dibuja el mapa de memoria actual del agente" },
            { cmd: "/why",           args: "",                  desc: "Muestra justificacion operacional del ultimo comando" },
            { cmd: "/trace",         args: "",                  desc: "Debugger agentivo del ciclo ReAct" },
            { cmd: "/undo",          args: "",                  desc: "Revierte la ultima operacion en el FS" },
            { cmd: "/speak",         args: "<texto>",           desc: "Sintetiza voz forzada omitiendo la red neuronal" }
        ];
        
        // Expose for /help command
        this._commands = COMMANDS;

        let selectedIndex = 0;
        const autocompletePopup = this.element.querySelector(".command-autocomplete");

        const updatePopup = () => {
            const val = this.input.value;
            if (!val.startsWith("/") || val.includes(" ")) {
                autocompletePopup.classList.add("hidden");
                return;
            }
            const query = val.toLowerCase();
            const matches = COMMANDS.filter(c => c.cmd.startsWith(query));
            
            if (matches.length === 0 || (matches.length === 1 && matches[0].cmd === val)) {
                autocompletePopup.classList.add("hidden");
                return;
            }

            autocompletePopup.innerHTML = "";
            matches.forEach((m, idx) => {
                const div = document.createElement("div");
                div.className = "ac-item" + (idx === selectedIndex ? " selected" : "");
                div.innerHTML = `<span class="ac-cmd">${m.cmd}</span><span class="ac-args">${m.args}</span><span class="ac-desc">${m.desc}</span>`;
                div.addEventListener("mousedown", (e) => {
                    e.preventDefault();
                    this.input.value = m.cmd + (m.args ? " " : "");
                    autocompletePopup.classList.add("hidden");
                    this.input.focus();
                });
                autocompletePopup.appendChild(div);
            });
            
            // Position popup above the input
            const rect = this.input.getBoundingClientRect();
            autocompletePopup.style.bottom = (window.innerHeight - rect.top + 6) + "px";
            autocompletePopup.style.left = rect.left + "px";
            autocompletePopup.classList.remove("hidden");
        };

        this.input.addEventListener("input", () => {
            selectedIndex = 0;
            updatePopup();
        });

        this.input.addEventListener("blur", () => {
            setTimeout(() => autocompletePopup.classList.add("hidden"), 150);
        });

        this.input.addEventListener("keydown", (e) => {
            if (autocompletePopup.classList.contains("hidden")) return;
            
            const items = autocompletePopup.querySelectorAll(".ac-item");
            if (e.key === "ArrowDown") {
                e.preventDefault();
                selectedIndex = (selectedIndex + 1) % items.length;
                updatePopup();
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                selectedIndex = (selectedIndex - 1 + items.length) % items.length;
                updatePopup();
            } else if (e.key === "Tab") {
                e.preventDefault();
                if (items[selectedIndex]) items[selectedIndex].dispatchEvent(new MouseEvent("mousedown"));
            } else if (e.key === "Escape") {
                autocompletePopup.classList.add("hidden");
            }
        });
    }

    setupEvents() {
        this.setupAutocomplete();

        this.title.addEventListener("dblclick", () => {
            const newName = prompt("Nuevo nombre para esta terminal:", this.sessionId);
            if (newName && newName.trim() && newName.trim() !== this.sessionId) {
                this.manager.renameTerminal(this.sessionId, newName.trim().replace(/\s+/g, '-'));
            }
        });

        this.input.addEventListener("keydown", (e) => {
            const autocompletePopup = this.element.querySelector(".command-autocomplete");
            if (!autocompletePopup.classList.contains("hidden") && 
                (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Tab" || e.key === "Escape")) {
                return; // Handled by autocomplete
            }
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                autocompletePopup.classList.add("hidden");
                
                // Client-side /clear
                if (this.input.value.trim() === "/clear") {
                    this.output.innerHTML = "";
                    this.input.value = "";
                    fetch("/api/sessions/" + encodeURIComponent(this.sessionId) + "/history", {
                        method: "DELETE",
                        headers: getAuthHeaders(),
                    });
                    return;
                }

                // Client-side /help
                if (this.input.value.trim() === "/help") {
                    this.input.value = "";
                    const lines = this._commands.map(c => 
                        `  ${c.cmd.padEnd(18)} ${c.args.padEnd(16)} ${c.desc}`
                    );
                    const helpText = "Comandos disponibles:\n\n" + lines.join("\n");
                    this.appendAssistantMessage("```\n" + helpText + "\n```");
                    return;
                }

                const deleteMatch = this.input.value.trim().match(/^\/delete(?:\s+(.+))?$/i);
                if (deleteMatch) {
                    const projectName = (deleteMatch[1] || this.sessionId).replace(/\s+--confirmed$/i, "").trim();
                    if (!projectName || !confirm(`Delete project '${projectName}' and all its history and context?`)) {
                        this.input.value = "";
                        return;
                    }
                    this.input.value = `/delete ${projectName} --confirmed`;
                }
                
                this.sendMessage();
            }
        });
        
        this.btnSend.addEventListener("click", () => this.sendMessage());
        
        this.btnMic.addEventListener("click", () => {
            if (window.startVoiceInput) window.startVoiceInput();
        });
        
        this.btnUpload.addEventListener("click", () => {
            if (window.triggerGlobalFileUpload) window.triggerGlobalFileUpload();
        });
        
        if (this.btnPopout) {
            this.btnPopout.addEventListener("click", () => {
                this.popoutToWindow();
            });
        }

        if (this.btnFloat) {
            this.btnFloat.addEventListener("click", () => {
                this.toggleFloat();
            });
        }

        this.btnMinimize.addEventListener("click", () => {
            this.manager.minimizeToDock(this.sessionId);
        });
        
        this.btnClose.addEventListener("click", () => {
            this.manager.closeTerminal(this.sessionId);
        });
        
        if (this.btnCancel) {
            this.btnCancel.addEventListener("click", () => {
                this.cancelled = true;
                if (this.abortController) {
                    this.abortController.abort();
                    this.abortController = null;
                }
                // El abort del fetch solo corta la conexion HTTP. Hay que
                // avisar al servidor para que detenga el turno cognitivo real;
                // si no, la sesion queda bloqueada hasta que termine solo.
                if (window.cancelServerTurn) window.cancelServerTurn(this.sessionId);
                this.setThinking(false);
                this.appendSystemMessage("Request cancelled by operator.");
            });
        }

        // Drag events for header
        this.header.addEventListener("dragstart", (e) => {
            if (this.isFloating) {
                e.preventDefault();
                return;
            }
            e.dataTransfer.setData("text/plain", this.sessionId);
            e.dataTransfer.effectAllowed = "move";
        });

        // Focus tracking
        this.element.addEventListener("mousedown", () => {
            this.manager.setActive(this.sessionId);
        });
        this.input.addEventListener("focus", () => {
            this.manager.setActive(this.sessionId);
        });
    }

    popoutToWindow() {
        const url = new URL(window.location.href);
        url.searchParams.set("session", this.sessionId);
        url.searchParams.set("standalone", "1");
        const win = window.open(
            url.toString(),
            "wis_term_" + this.sessionId.replace(/[^a-zA-Z0-9_-]/g, "_"),
            "width=960,height=650,resizable=yes,scrollbars=no,status=no"
        );
        if (win) {
            this.manager.markDetached(this.sessionId, true);
        }
    }

    toggleFloat() {
        this.isFloating = !this.isFloating;
        this.element.classList.toggle("is-floating", this.isFloating);
        if (this.isFloating) {
            if (this.btnFloat) {
                this.btnFloat.title = "Anclar nuevamente a la cuadrícula";
                this.btnFloat.classList.add("accent");
            }
            if (!this.element.style.top) {
                const w = Math.min(720, window.innerWidth - 40);
                const h = Math.min(520, window.innerHeight - 80);
                this.element.style.width = w + "px";
                this.element.style.height = h + "px";
                this.element.style.top = Math.max(50, (window.innerHeight - h) / 2) + "px";
                this.element.style.left = Math.max(50, (window.innerWidth - w) / 2) + "px";
            }
            this.initFloatingDrag();
        } else {
            if (this.btnFloat) {
                this.btnFloat.title = "Desanclar / Ventana flotante";
                this.btnFloat.classList.remove("accent");
            }
            this.element.style.position = "";
            this.element.style.top = "";
            this.element.style.left = "";
            this.element.style.width = "";
            this.element.style.height = "";
        }
        this.manager.updateGridSplit();
    }

    initFloatingDrag() {
        if (this._floatingDragInit) return;
        this._floatingDragInit = true;

        let isDragging = false;
        let startX = 0, startY = 0;
        let initialLeft = 0, initialTop = 0;

        this.header.addEventListener("mousedown", (e) => {
            if (!this.isFloating || e.target.closest("button") || e.target.closest("input") || e.target.closest("textarea")) return;
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            const rect = this.element.getBoundingClientRect();
            initialLeft = rect.left;
            initialTop = rect.top;
            e.preventDefault();

            const onMouseMove = (ev) => {
                if (!isDragging) return;
                const dx = ev.clientX - startX;
                const dy = ev.clientY - startY;
                const newLeft = Math.max(0, Math.min(window.innerWidth - 100, initialLeft + dx));
                const newTop = Math.max(0, Math.min(window.innerHeight - 50, initialTop + dy));
                this.element.style.left = newLeft + "px";
                this.element.style.top = newTop + "px";
            };

            const onMouseUp = () => {
                isDragging = false;
                document.removeEventListener("mousemove", onMouseMove);
                document.removeEventListener("mouseup", onMouseUp);
            };

            document.addEventListener("mousemove", onMouseMove);
            document.addEventListener("mouseup", onMouseUp);
        });
    }

    setThinking(active, label = "WIS is reasoning...") {
        if (active && this.cancelled) return;
        this.isThinking = active;
        this.thinkingLabel.textContent = label;
        if (active) {
            this.thinkingRow.classList.remove("hidden");
            this.input.disabled = true;
            this.btnSend.disabled = true;
        } else {
            this.thinkingRow.classList.add("hidden");
            this.input.disabled = false;
            this.btnSend.disabled = false;
            this.input.focus();
        }
    }

    appendSystemMessage(text) {
        const msg = document.createElement("div");
        msg.className = "msg msg-system";
        msg.innerHTML = `<span class="msg-sys-text">${text}</span>`;
        this.output.appendChild(msg);
        this.scrollToBottom();
    }

    appendUserMessage(text) {
        const msg = document.createElement("div");
        msg.className = "msg msg-user";
        msg.innerHTML = `<div class="msg-bubble">${text.replace(/</g, "&lt;")}</div>`;
        this.output.appendChild(msg);
        this.scrollToBottom();
    }

    appendAssistantMessage(text) {
        const msg = document.createElement("div");
        msg.className = "msg msg-wis";
        // Attempt to parse markdown if global function exists
        let content = window.parseMarkdown ? window.parseMarkdown(text) : text.replace(/</g, "&lt;");
        msg.innerHTML = `<div class="msg-bubble">${content}</div>`;
        this.output.appendChild(msg);
        this.scrollToBottom();
    }

    scrollToBottom() {
        requestAnimationFrame(() => {
            this.output.scrollTop = this.output.scrollHeight;
        });
    }

    async sendMessage() {
        const val = this.input.value.trim();
        if (!val || this.isThinking) return;
        this.input.value = "";
        
        if (window.sendChatRequest) {
            window.sendChatRequest(val, this);
        }
    }

    async restoreHistory() {
        if (this.output.childElementCount > 0) return;
        try {
            const res = await fetch(
                "/api/sessions/" + encodeURIComponent(this.sessionId) + "/history",
                { headers: getAuthHeaders() },
            );
            if (!res.ok) return;
            const data = await res.json();
            for (const message of data.history || []) {
                if (message.role === "user") this.appendUserMessage(message.content || "");
                if (message.role === "assistant") this.appendAssistantMessage(message.content || "");
            }
        } catch (e) {
            console.warn("Could not restore terminal history:", e);
        }
    }
}

const LAYOUT_META = {
    "1x1": { icon: "🗖", label: "1x1" },
    "1x2": { icon: "❚❚", label: "1x2" },
    "2x1": { icon: "〓", label: "2x1" },
    "2x2": { icon: "⊞", label: "2x2" },
    "3x3": { icon: "▤", label: "3x3" },
    "4x4": { icon: "▦", label: "4x4" },
    "auto": { icon: "❖", label: "Auto" },
};

class TerminalManager {
    constructor() {
        this.instances = new Map();
        this.activeSessionId = "main";
        this.grid = document.getElementById("terminal-grid");
        this.dock = document.getElementById("terminal-dock");
        this.tabsContainer = document.getElementById("terminal-dock-tabs") || this.dock;
        this.template = document.getElementById("terminal-template");
        
        this.layoutPickerBtn = document.getElementById("btn-layout-picker");
        this.layoutDropdown = document.getElementById("layout-dropdown");
        this.currentLayoutIcon = document.getElementById("current-layout-icon");
        this.currentLayoutLabel = document.getElementById("current-layout-label");
        this.currentLayout = localStorage.getItem("wis-terminal-layout") || "2x2";

        this.btnNewTerm = document.getElementById("btn-new-term");
        if (this.btnNewTerm) {
            this.btnNewTerm.addEventListener("click", () => {
                const name = prompt("Ingrese el nombre del proyecto o terminal:", this.generateId());
                if (name && name.trim()) {
                    this.createTerminal(name.trim().replace(/\s+/g, '-'));
                }
            });
        }

        this.initLayoutControls();
        this.applyLayout(this.currentLayout);
        
        // Dock drag drop zone
        this.dock.addEventListener("dragover", e => e.preventDefault());
        this.dock.addEventListener("drop", (e) => {
            e.preventDefault();
            const sid = e.dataTransfer.getData("text/plain");
            if (sid) this.minimizeToDock(sid);
        });

        // Grid drag drop zone
        this.grid.addEventListener("dragover", e => e.preventDefault());
        this.grid.addEventListener("drop", (e) => {
            e.preventDefault();
            const sid = e.dataTransfer.getData("text/plain");
            if (sid) this.restoreToGrid(sid);
        });
    }

    initLayoutControls() {
        if (this.layoutPickerBtn && this.layoutDropdown) {
            this.layoutPickerBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                this.layoutDropdown.classList.toggle("hidden");
            });

            document.addEventListener("click", (e) => {
                if (!e.target.closest("#layout-picker-wrapper")) {
                    this.layoutDropdown.classList.add("hidden");
                }
            });

            this.layoutDropdown.querySelectorAll(".layout-option").forEach(opt => {
                opt.addEventListener("click", () => {
                    const layout = opt.dataset.layout;
                    if (layout) {
                        this.setLayout(layout);
                    }
                    this.layoutDropdown.classList.add("hidden");
                });
            });
        }
    }

    setLayout(layoutName) {
        this.currentLayout = layoutName;
        localStorage.setItem("wis-terminal-layout", layoutName);
        this.applyLayout(layoutName);
    }

    applyLayout(layoutName) {
        if (!this.grid) return;
        const toRemove = [];
        this.grid.classList.forEach(cls => {
            if (cls.startsWith("layout-") || cls === "split-col") toRemove.push(cls);
        });
        toRemove.forEach(cls => this.grid.classList.remove(cls));

        this.grid.classList.add(`layout-${layoutName}`);

        if (this.layoutDropdown) {
            this.layoutDropdown.querySelectorAll(".layout-option").forEach(opt => {
                opt.classList.toggle("active", opt.dataset.layout === layoutName);
            });
        }

        const meta = LAYOUT_META[layoutName] || LAYOUT_META["2x2"];
        if (this.currentLayoutIcon) this.currentLayoutIcon.textContent = meta.icon;
        if (this.currentLayoutLabel) this.currentLayoutLabel.textContent = meta.label;

        this.updateGridSplit();
        this.updateActiveTerminalHighlight();
    }

    setActive(sessionId) {
        if (this.instances.has(sessionId)) {
            this.activeSessionId = sessionId;
            this.updateActiveTerminalHighlight();
        }
    }

    updateActiveTerminalHighlight() {
        for (const [sid, inst] of this.instances.entries()) {
            const isActive = (sid === this.activeSessionId);
            inst.element.classList.toggle("active-terminal", isActive);
            const tab = this.tabsContainer.querySelector(`[data-session-id="${sid}"]`);
            if (tab) tab.classList.toggle("active", isActive);
        }
    }

    upsertTab(sessionId) {
        let tab = this.tabsContainer.querySelector(`[data-session-id="${sessionId}"]`);
        if (!tab) {
            tab = document.createElement("div");
            tab.className = "terminal-tab";
            tab.dataset.sessionId = sessionId;
            tab.textContent = sessionId;
            
            tab.draggable = true;
            tab.addEventListener("dragstart", (e) => {
                e.dataTransfer.setData("text/plain", sessionId);
            });
            tab.addEventListener("click", () => {
                this.setActive(sessionId);
                this.restoreToGrid(sessionId);
                const inst = this.instances.get(sessionId);
                if (inst && inst.input) inst.input.focus();
            });
            this.tabsContainer.appendChild(tab);
        }
        if (this.activeSessionId === sessionId) {
            tab.classList.add("active");
        }
        return tab;
    }

    markDetached(sessionId, detached = true) {
        const tab = this.tabsContainer.querySelector(`[data-session-id="${sessionId}"]`);
        if (tab) {
            tab.classList.toggle("detached", detached);
            tab.textContent = detached ? `${sessionId} ⧉` : sessionId;
            tab.title = detached ? `${sessionId} (Ventana externa abierta)` : sessionId;
        }
    }

    saveState() {
        const ids = Array.from(this.instances.keys());
        localStorage.setItem("wis-terminals", JSON.stringify(ids));
    }
    
    restoreState() {
        try {
            const saved = JSON.parse(localStorage.getItem("wis-terminals"));
            if (Array.isArray(saved) && saved.length > 0) {
                for (const sid of saved) {
                    this.createTerminal(sid === "default" ? "main" : sid);
                }
                return true;
            }
        } catch(e) {}
        return false;
    }

    async restorePersistentState() {
        try {
            const res = await fetch("/api/sessions", { headers: getAuthHeaders() });
            if (!res.ok) return [];
            return (await res.json()).sessions || [];
        } catch (e) {
            console.warn("Could not restore persistent terminal sessions:", e);
            return [];
        }
    }

    generateId() {
        return "term-" + Math.random().toString(36).substring(2, 6);
    }

    createTerminal(customId = null) {
        const sid = customId || (this.instances.size === 0 ? "main" : this.generateId());
        if (this.instances.has(sid)) return this.instances.get(sid);
        
        const inst = new TerminalInstance(this, sid, this.template);
        this.instances.set(sid, inst);
        this.grid.appendChild(inst.element);
        this.upsertTab(sid);
        this.setActive(sid);
        this.updateGridSplit();
        this.saveState();
        if (window.subscribeWebSocketSession) window.subscribeWebSocketSession(sid);
        return inst;
    }

    getTerminal(sid) {
        return this.instances.get(sid);
    }

    getActiveTerminal() {
        if (this.instances.has(this.activeSessionId)) {
            const inst = this.instances.get(this.activeSessionId);
            if (inst.element.parentNode === this.grid) return inst;
        }
        for (let inst of this.instances.values()) {
            if (inst.element.parentNode === this.grid) {
                return inst;
            }
        }
        return this.instances.get("default");
    }

    async openSession(sessionId) {
        const terminal = this.createTerminal(sessionId);
        this.setActive(sessionId);
        this.restoreToGrid(sessionId);
        await terminal.restoreHistory();
        terminal.input.focus();
        return terminal;
    }

    closeTerminal(sid) {
        const inst = this.instances.get(sid);
        if (!inst) return;
        inst.element.remove();
        
        const tab = this.tabsContainer.querySelector(`[data-session-id="${sid}"]`);
        if (tab) tab.remove();

        this.instances.delete(sid);
        if (this.activeSessionId === sid) {
            const nextKey = this.instances.keys().next().value;
            if (nextKey) this.setActive(nextKey);
        }
        this.updateGridSplit();
        this.saveState();
    }

    renameTerminal(oldSid, newSid) {
        if (!this.instances.has(oldSid) || this.instances.has(newSid)) return;
        
        const inst = this.instances.get(oldSid);
        this.instances.delete(oldSid);
        this.instances.set(newSid, inst);
        
        inst.sessionId = newSid;
        inst.element.dataset.sessionId = newSid;
        inst.title.textContent = newSid;
        
        const tab = this.tabsContainer.querySelector(`[data-session-id="${oldSid}"]`);
        if (tab) {
            tab.dataset.sessionId = newSid;
            tab.textContent = newSid;
        }
        
        if (this.activeSessionId === oldSid) {
            this.activeSessionId = newSid;
        }
        
        this.saveState();
        if (window.ws && window.ws.readyState === WebSocket.OPEN) {
            window.ws.send(JSON.stringify({
                type: "rename_session",
                session_id: oldSid,
                new_id: newSid
            }));
        }
    }

    minimizeToDock(sid) {
        const inst = this.instances.get(sid);
        if (!inst) return;
        
        if (inst.element.parentNode === this.grid) {
            this.grid.removeChild(inst.element);
            const tab = this.upsertTab(sid);
            tab.classList.add("minimized");
            this.updateGridSplit();
        }
    }

    restoreToGrid(sid) {
        const inst = this.instances.get(sid);
        if (!inst) return;
        
        if (inst.element.parentNode !== this.grid) {
            this.grid.appendChild(inst.element);
            const tab = this.upsertTab(sid);
            tab.classList.remove("minimized");
            this.setActive(sid);
            this.updateGridSplit();
        }
    }

    updateGridSplit() {
        if (!this.grid) return;
        const visibleCount = Array.from(this.grid.children).filter(el => {
            return el.classList.contains("terminal-pane") && !el.classList.contains("is-floating");
        }).length;
        this.grid.dataset.count = visibleCount;
        
        const emptyState = document.getElementById("wis-empty-state");
        if (emptyState) {
            emptyState.classList.toggle("hidden", visibleCount > 0);
        }
    }
}

window.TerminalManager = TerminalManager;
