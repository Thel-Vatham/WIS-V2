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
        this.btnCancel = this.element.querySelector('[action="cancel"]');
        this.btnMic = this.element.querySelector('[action="mic"]');
        this.btnUpload = this.element.querySelector('[action="upload"]');
        this.btnSend = this.element.querySelector('[action="send"]');
        this.btnMinimize = this.element.querySelector('[action="minimize"]');
        this.btnClose = this.element.querySelector('[action="close"]');

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
            { cmd: "/port",          args: "<num>",             desc: "Levanta un micro-servidor HTTP estatico en la carpeta" },
            { cmd: "/git",           args: "<mensaje>",        desc: "Hace add, commit y push del codigo automaticamente" },
            { cmd: "/build",         args: "",                  desc: "Detecta e invoca el comando de build o install del proyecto" },
            { cmd: "/reboot",        args: "",                  desc: "Limpia la memoria a corto plazo del LLM en esta sesion" },
            { cmd: "/goal",          args: "<desc>",            desc: "Lanza un worker en background para un objetivo largo" },
            { cmd: "/proactividad",  args: "<on|off>",          desc: "Enciende o apaga el motor proactivo" },
            { cmd: "/ping",          args: "<ip>",              desc: "Verifica latencia contra una IP local o remota" },
            { cmd: "/list",          args: "",                  desc: "Lista los archivos del proyecto actual" },
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

class TerminalManager {
    constructor() {
        this.instances = new Map();
        this.activeSessionId = "main";
        this.grid = document.getElementById("terminal-grid");
        this.dock = document.getElementById("terminal-dock");
        this.template = document.getElementById("terminal-template");
        
        this.btnNewTerm = document.getElementById("btn-new-term");
        this.btnNewTerm.addEventListener("click", () => {
            const name = prompt("Ingrese el nombre del proyecto o terminal:", this.generateId());
            if (name && name.trim()) {
                this.createTerminal(name.trim().replace(/\s+/g, '-'));
            }
        });
        
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

    setActive(sessionId) {
        if (this.instances.has(sessionId)) {
            this.activeSessionId = sessionId;
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
                return true; // Successfully restored
            }
        } catch(e) {}
        return false;
    }

    async restorePersistentState() {
        try {
            const res = await fetch("/api/sessions", { headers: getAuthHeaders() });
            if (!res.ok) return [];
            // Project sessions stay in the tree and are opened on demand.
            // Startup must contain only the transient main console.
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
        
        // Fallback: Return first one in grid, or default
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
        
        const tab = this.dock.querySelector(`[data-session-id="${sid}"]`);
        if (tab) tab.remove();

        this.instances.delete(sid);
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
        
        const tab = this.dock.querySelector(`[data-session-id="${oldSid}"]`);
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
            
            const tab = document.createElement("div");
            tab.className = "terminal-tab";
            tab.dataset.sessionId = sid;
            tab.textContent = sid;
            
            tab.draggable = true;
            tab.addEventListener("dragstart", (e) => {
                e.dataTransfer.setData("text/plain", sid);
            });
            
            tab.addEventListener("click", () => {
                this.restoreToGrid(sid);
            });
            
            this.dock.insertBefore(tab, this.btnNewTerm);
            this.updateGridSplit();
        }
    }

    restoreToGrid(sid) {
        const inst = this.instances.get(sid);
        if (!inst) return;
        
        if (inst.element.parentNode !== this.grid) {
            const tab = this.dock.querySelector(`[data-session-id="${sid}"]`);
            if (tab) tab.remove();
            
            this.grid.appendChild(inst.element);
            this.updateGridSplit();
        }
    }

    updateGridSplit() {
        const count = this.grid.children.length;
        if (count > 2) {
            this.grid.classList.add("split-col");
        } else {
            this.grid.classList.remove("split-col");
        }
    }
}

window.TerminalManager = TerminalManager;
