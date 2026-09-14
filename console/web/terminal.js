// console/web/terminal.js

class TerminalInstance {
    constructor(manager, sessionId, template) {
        this.manager = manager;
        this.sessionId = sessionId;
        this.isThinking = false;
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

    setupEvents() {
        this.input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
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
                if (this.abortController) {
                    this.abortController.abort();
                    this.abortController = null;
                }
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
}

class TerminalManager {
    constructor() {
        this.instances = new Map();
        this.activeSessionId = "default";
        this.grid = document.getElementById("terminal-grid");
        this.dock = document.getElementById("terminal-dock");
        this.template = document.getElementById("terminal-template");
        
        this.btnNewTerm = document.getElementById("btn-new-term");
        this.btnNewTerm.addEventListener("click", () => this.createTerminal());
        
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

    generateId() {
        return "term-" + Math.random().toString(36).substring(2, 6);
    }

    createTerminal(customId = null) {
        const sid = customId || (this.instances.size === 0 ? "default" : this.generateId());
        if (this.instances.has(sid)) return this.instances.get(sid);
        
        const inst = new TerminalInstance(this, sid, this.template);
        this.instances.set(sid, inst);
        this.grid.appendChild(inst.element);
        this.updateGridSplit();
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

    closeTerminal(sid) {
        const inst = this.instances.get(sid);
        if (!inst) return;
        inst.element.remove();
        
        const tab = this.dock.querySelector(`[data-session-id="${sid}"]`);
        if (tab) tab.remove();

        this.instances.delete(sid);
        this.updateGridSplit();
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
