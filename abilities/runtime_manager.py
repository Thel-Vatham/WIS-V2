"""
WIS Runtime Manager — Multi-Interpreter Isolated Environment Engine.
====================================================================
WIS puede ejecutar codigo en CUALQUIER runtime sin contaminar su propio entorno.

Soporta:
  - Python: cualquier version (2.7, 3.8, 3.11, etc.) con venv aislado
  - Node.js: cualquier version con carpeta node_modules propia
  - C / C++: compilacion con gcc/g++/msvc y ejecucion
  - Java: compilacion javac + ejecucion
  - Bash / PowerShell: scripts de shell
  - Rust, Go (si estan instalados)

Flujo principal:
  1. detect_runtime(path)  -> analiza el proyecto y devuelve el runtime necesario
  2. create_env(...)       -> crea un entorno aislado para ese runtime
  3. run_in_env(...)       -> ejecuta codigo/scripts en ese entorno
  4. install_deps(...)     -> instala dependencias en el entorno correcto
  5. list_envs()           -> lista todos los entornos gestionados
  6. destroy_env(...)      -> elimina un entorno cuando ya no se necesita
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from abilities.base import Ability

logger = logging.getLogger("wis.abilities.runtime_manager")

# ── Directorio base para todos los entornos aislados de WIS ────────────────────
_ENVS_DIR = Path("Data") / "runtime_envs"

# ── Mapa de extensiones / archivos -> runtime sugerido ─────────────────────────
_MANIFEST_HINTS = {
    "package.json":         "node",
    "requirements.txt":     "python",
    "pyproject.toml":       "python",
    "setup.py":             "python",
    "Pipfile":              "python",
    "CMakeLists.txt":       "cpp",
    "Makefile":             "cpp",
    "pom.xml":              "java",
    "build.gradle":         "java",
    "Cargo.toml":           "rust",
    "go.mod":               "go",
    "tsconfig.json":        "node",
    "Gemfile":              "ruby",
    "composer.json":        "php",
}

_EXT_HINTS = {
    ".py":   "python",
    ".js":   "node",
    ".ts":   "node",
    ".cpp":  "cpp",
    ".cc":   "cpp",
    ".c":    "cpp",
    ".java": "java",
    ".rs":   "rust",
    ".go":   "go",
    ".sh":   "bash",
    ".ps1":  "powershell",
    ".rb":   "ruby",
    ".php":  "php",
}


class RuntimeManager(Ability):
    """Multi-interpreter isolated environment engine for WIS."""

    @property
    def name(self) -> str:
        return "runtime_manager"

    @property
    def description(self) -> str:
        return (
            "Multi-interpreter manager. Creates isolated execution environments for any "
            "programming language or runtime: Python (any version), Node.js, C/C++, Java, "
            "Rust, Go, Bash, PowerShell. "
            "Actions: detect_runtime, create_env, run_in_env, install_deps, "
            "list_envs, destroy_env, run_auto (auto-detect + run)."
        )

    @property
    def domain(self) -> str:
        return "pc"

    def get_schema(self) -> list:
        return [
            {
                "action": "detect_runtime",
                "description": (
                    "Analyze a project directory or file and return the required runtime, "
                    "version hints, and dependency files found."
                ),
                "params": {"path": "Directory or file path to analyze"}
            },
            {
                "action": "create_env",
                "description": (
                    "Create an isolated environment for a runtime. "
                    "For Python: creates a venv with the specified Python version. "
                    "For Node: creates a directory with its own node_modules. "
                    "For C++/Java: validates the compiler is available."
                ),
                "params": {
                    "env_name": "Unique name for this environment (e.g. 'myproject_py311')",
                    "runtime": "Runtime type: python | node | cpp | java | rust | go | bash",
                    "version": "Optional version hint: '3.11', '2.7', '18', etc.",
                }
            },
            {
                "action": "install_deps",
                "description": "Install dependencies into an isolated environment.",
                "params": {
                    "env_name": "Environment name created with create_env",
                    "deps_file": "Path to deps file: requirements.txt, package.json, etc. (optional)",
                    "packages": "List of package names to install directly (optional)",
                }
            },
            {
                "action": "run_in_env",
                "description": (
                    "Execute code or a script inside a specific isolated environment. "
                    "Provide either 'code' (inline) or 'script_path' (file)."
                ),
                "params": {
                    "env_name": "Environment name",
                    "code": "Inline code to execute (optional)",
                    "script_path": "Path to script file to run (optional)",
                    "args": "List of command-line arguments (optional)",
                    "cwd": "Working directory for execution (optional)",
                    "timeout": "Max seconds to run (default 60)",
                }
            },
            {
                "action": "run_auto",
                "description": (
                    "Auto-detect the runtime from a file/directory, create env if needed, "
                    "install deps, and run. One-shot convenience action."
                ),
                "params": {
                    "path": "File or project directory to run",
                    "args": "Extra command-line args (optional)",
                    "timeout": "Max seconds (default 120)",
                    "version": "Force a specific runtime version (optional)",
                }
            },
            {
                "action": "list_envs",
                "description": "List all managed runtime environments with their status.",
                "params": {}
            },
            {
                "action": "list_runtimes",
                "description": "Detect and list all interpreters/compilers installed on this system.",
                "params": {}
            },
            {
                "action": "destroy_env",
                "description": "Delete an isolated environment to free disk space.",
                "params": {"env_name": "Environment name to delete"}
            },
        ]

    async def execute(self, action: str, params: dict) -> dict:
        a = (action or "").lower().strip()
        try:
            if a == "detect_runtime":
                return await asyncio.to_thread(self._detect_runtime, params)
            if a == "create_env":
                return await self._create_env(params)
            if a == "install_deps":
                return await self._install_deps(params)
            if a == "run_in_env":
                return await self._run_in_env(params)
            if a == "run_auto":
                return await self._run_auto(params)
            if a == "list_envs":
                return await asyncio.to_thread(self._list_envs, params)
            if a == "list_runtimes":
                return await asyncio.to_thread(self._list_runtimes, params)
            if a == "destroy_env":
                return await asyncio.to_thread(self._destroy_env, params)
            return {"success": False, "message": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception("RuntimeManager error in %s", action)
            return {"success": False, "message": str(e)}

    # ── Env root ──────────────────────────────────────────────────────────────────

    def _env_root(self, env_name: str) -> Path:
        root = Path(os.getcwd()) / _ENVS_DIR / env_name
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _env_meta(self, env_name: str) -> dict:
        meta_file = Path(os.getcwd()) / _ENVS_DIR / env_name / ".wis_env_meta.json"
        if meta_file.exists():
            try:
                return json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_env_meta(self, env_name: str, meta: dict) -> None:
        meta_file = Path(os.getcwd()) / _ENVS_DIR / env_name / ".wis_env_meta.json"
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # ── detect_runtime ────────────────────────────────────────────────────────────

    def _detect_runtime(self, params: dict) -> dict:
        path = Path(params.get("path", "."))
        detected = {"runtime": None, "version": None, "confidence": "low", "hints": []}

        if path.is_file():
            ext = path.suffix.lower()
            if ext in _EXT_HINTS:
                detected["runtime"] = _EXT_HINTS[ext]
                detected["confidence"] = "high"
                detected["hints"].append(f"File extension {ext}")
            # Check Python shebang / version specifier
            if ext == ".py":
                try:
                    first_lines = path.read_text(encoding="utf-8", errors="replace")[:500]
                    if "python2" in first_lines or "python 2" in first_lines.lower():
                        detected["version"] = "2.7"
                        detected["hints"].append("Shebang/comment suggests Python 2")
                    m = re.search(r"python_requires\s*=\s*['\"]([^'\"]+)['\"]", first_lines)
                    if m:
                        detected["version"] = m.group(1)
                        detected["hints"].append(f"python_requires={m.group(1)}")
                except Exception:
                    pass
            return {"success": True, "data": detected, "message": self._fmt_detection(detected)}

        if path.is_dir():
            files = {f.name for f in path.iterdir() if f.is_file()}
            # Priority scan
            for manifest, runtime in _MANIFEST_HINTS.items():
                if manifest in files:
                    detected["runtime"] = runtime
                    detected["confidence"] = "high"
                    detected["hints"].append(f"Found {manifest}")
                    break

            # Try to detect version from manifest content
            if detected["runtime"] == "python":
                # Check setup.py or pyproject.toml for python_requires
                for fname in ("pyproject.toml", "setup.py", "setup.cfg", ".python-version"):
                    fp = path / fname
                    if fp.exists():
                        try:
                            content = fp.read_text(encoding="utf-8", errors="replace")
                            m = re.search(r"python_requires['\"]?\s*[=:]\s*['\"]([^'\"]+)['\"]", content)
                            if m:
                                detected["version"] = m.group(1)
                                detected["hints"].append(f"{fname}: python_requires={m.group(1)}")
                            if fname == ".python-version":
                                detected["version"] = content.strip()
                                detected["hints"].append(f".python-version: {content.strip()}")
                        except Exception:
                            pass

            if detected["runtime"] == "node":
                pkg = path / "package.json"
                if pkg.exists():
                    try:
                        data = json.loads(pkg.read_text(encoding="utf-8"))
                        engines = data.get("engines", {})
                        if "node" in engines:
                            detected["version"] = engines["node"]
                            detected["hints"].append(f"package.json engines.node={engines['node']}")
                    except Exception:
                        pass

            # Count file types as secondary signal
            if not detected["runtime"]:
                counts: dict[str, int] = {}
                for f in path.rglob("*"):
                    if f.is_file() and f.suffix in _EXT_HINTS:
                        rt = _EXT_HINTS[f.suffix]
                        counts[rt] = counts.get(rt, 0) + 1
                if counts:
                    best = max(counts, key=lambda k: counts[k])
                    detected["runtime"] = best
                    detected["confidence"] = "medium"
                    detected["hints"].append(f"Majority file type: {best} ({counts[best]} files)")

            return {"success": True, "data": detected, "message": self._fmt_detection(detected)}

        return {"success": False, "message": f"Path not found: {path}"}

    def _fmt_detection(self, d: dict) -> str:
        rt = d.get("runtime") or "unknown"
        ver = d.get("version") or "any"
        conf = d.get("confidence", "low")
        hints = "\n  - ".join(d.get("hints", []))
        return f"Runtime: {rt} (version: {ver}, confidence: {conf})\nHints:\n  - {hints}"

    # ── create_env ────────────────────────────────────────────────────────────────

    async def _create_env(self, params: dict) -> dict:
        env_name = params.get("env_name", "")
        runtime = (params.get("runtime", "") or "").lower()
        version = params.get("version", "")

        if not env_name:
            return {"success": False, "message": "env_name required"}
        if not runtime:
            return {"success": False, "message": "runtime required (python|node|cpp|java|rust|go|bash)"}

        env_root = self._env_root(env_name)

        if runtime == "python":
            return await self._create_python_env(env_name, env_root, version)
        if runtime == "node":
            return await asyncio.to_thread(self._create_node_env, env_name, env_root, version)
        if runtime in ("cpp", "c"):
            return await asyncio.to_thread(self._create_cpp_env, env_name, env_root)
        if runtime == "java":
            return await asyncio.to_thread(self._create_java_env, env_name, env_root)
        if runtime == "rust":
            return await asyncio.to_thread(self._create_rust_env, env_name, env_root)
        if runtime == "go":
            return await asyncio.to_thread(self._create_go_env, env_name, env_root)
        if runtime in ("bash", "powershell", "shell"):
            self._save_env_meta(env_name, {"runtime": runtime, "version": version, "env_root": str(env_root)})
            return {"success": True, "message": f"Shell env '{env_name}' ({runtime}) ready at {env_root}"}

        return {"success": False, "message": f"Unsupported runtime: {runtime}"}

    async def _create_python_env(self, env_name: str, env_root: Path, version: str) -> dict:
        """Create an isolated Python venv for the requested version."""
        python_exe = self._find_python(version)
        if not python_exe:
            return {
                "success": False,
                "message": (
                    f"Python {version or 'any'} not found. "
                    f"Install it or use the Python Launcher (py.exe). "
                    f"Available: {self._find_all_pythons()}"
                )
            }

        venv_path = env_root / "venv"
        if venv_path.exists():
            self._save_env_meta(env_name, {
                "runtime": "python", "version": version,
                "python_exe": python_exe,
                "venv_path": str(venv_path),
                "env_root": str(env_root),
            })
            return {"success": True, "message": f"Python env '{env_name}' already exists at {venv_path}"}

        try:
            proc = await asyncio.create_subprocess_exec(
                python_exe, "-m", "venv", str(venv_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                return {"success": False, "message": f"venv creation failed:\n{stderr.decode(errors='replace')}"}

            # Upgrade pip in the new venv
            pip = venv_path / "Scripts" / "pip.exe"
            if pip.exists():
                proc2 = await asyncio.create_subprocess_exec(
                    str(pip), "install", "--upgrade", "pip", "--quiet",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc2.communicate(), timeout=60)

            self._save_env_meta(env_name, {
                "runtime": "python",
                "version": version or self._get_python_version(python_exe),
                "python_exe": python_exe,
                "venv_path": str(venv_path),
                "env_root": str(env_root),
            })
            return {
                "success": True,
                "message": f"Python env '{env_name}' created at {venv_path}\nInterpreter: {python_exe}"
            }
        except asyncio.TimeoutError:
            return {"success": False, "message": "venv creation timed out"}

    def _create_node_env(self, env_name: str, env_root: Path, version: str) -> dict:
        """Create an isolated Node.js project environment."""
        node_exe = shutil.which("node")
        npm_exe = shutil.which("npm")
        if not node_exe:
            return {"success": False, "message": "node not found in PATH. Install Node.js."}
        pkg_json = env_root / "package.json"
        if not pkg_json.exists():
            pkg_json.write_text(json.dumps({
                "name": env_name,
                "version": "1.0.0",
                "private": True,
                "description": f"WIS isolated Node.js environment: {env_name}",
            }, indent=2), encoding="utf-8")
        self._save_env_meta(env_name, {
            "runtime": "node",
            "version": version or self._get_cmd_version(node_exe),
            "node_exe": node_exe,
            "npm_exe": npm_exe or "",
            "env_root": str(env_root),
        })
        return {"success": True, "message": f"Node.js env '{env_name}' ready at {env_root}\nNode: {node_exe}"}

    def _create_cpp_env(self, env_name: str, env_root: Path) -> dict:
        """Verify C/C++ compiler availability."""
        compiler = shutil.which("g++") or shutil.which("gcc") or shutil.which("cl")
        if not compiler:
            return {
                "success": False,
                "message": "No C/C++ compiler found (g++, gcc, cl). Install MinGW or MSVC."
            }
        (env_root / "src").mkdir(exist_ok=True)
        (env_root / "build").mkdir(exist_ok=True)
        self._save_env_meta(env_name, {
            "runtime": "cpp",
            "compiler": compiler,
            "env_root": str(env_root),
        })
        return {"success": True, "message": f"C++ env '{env_name}' ready. Compiler: {compiler}"}

    def _create_java_env(self, env_name: str, env_root: Path) -> dict:
        """Verify Java availability."""
        javac = shutil.which("javac")
        java = shutil.which("java")
        if not java:
            return {"success": False, "message": "java not found. Install JDK."}
        (env_root / "src").mkdir(exist_ok=True)
        (env_root / "classes").mkdir(exist_ok=True)
        self._save_env_meta(env_name, {
            "runtime": "java",
            "java_exe": java,
            "javac_exe": javac or "",
            "env_root": str(env_root),
        })
        return {"success": True, "message": f"Java env '{env_name}' ready. JRE: {java}"}

    def _create_rust_env(self, env_name: str, env_root: Path) -> dict:
        cargo = shutil.which("cargo")
        if not cargo:
            return {"success": False, "message": "cargo not found. Install Rust: https://rustup.rs"}
        self._save_env_meta(env_name, {"runtime": "rust", "cargo_exe": cargo, "env_root": str(env_root)})
        return {"success": True, "message": f"Rust env '{env_name}' ready. Cargo: {cargo}"}

    def _create_go_env(self, env_name: str, env_root: Path) -> dict:
        go = shutil.which("go")
        if not go:
            return {"success": False, "message": "go not found. Install Go: https://golang.org"}
        self._save_env_meta(env_name, {"runtime": "go", "go_exe": go, "env_root": str(env_root)})
        return {"success": True, "message": f"Go env '{env_name}' ready. Go: {go}"}

    # ── install_deps ──────────────────────────────────────────────────────────────

    async def _install_deps(self, params: dict) -> dict:
        env_name = params.get("env_name", "")
        deps_file = params.get("deps_file", "")
        packages = params.get("packages", [])
        if not env_name:
            return {"success": False, "message": "env_name required"}

        meta = self._env_meta(env_name)
        runtime = meta.get("runtime", "")

        if runtime == "python":
            venv_path = Path(meta.get("venv_path", ""))
            pip = venv_path / "Scripts" / "pip.exe"
            if not pip.exists():
                pip = venv_path / "bin" / "pip"
            if not pip.exists():
                return {"success": False, "message": f"pip not found in {venv_path}"}

            cmds = []
            if deps_file:
                cmds.append([str(pip), "install", "-r", deps_file, "--quiet"])
            for pkg in (packages if isinstance(packages, list) else [packages]):
                cmds.append([str(pip), "install", pkg, "--quiet"])

            results = []
            for cmd in cmds:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
                msg = stdout.decode(errors="replace") + stderr.decode(errors="replace")
                results.append(f"{'OK' if proc.returncode == 0 else 'FAIL'}: {' '.join(cmd[2:])}\n{msg}")

            return {"success": True, "message": "\n".join(results)}

        if runtime == "node":
            env_root = Path(meta.get("env_root", ""))
            npm = meta.get("npm_exe") or shutil.which("npm") or "npm"
            cmds = []
            if deps_file:
                cmds.append([npm, "install", "--prefix", str(env_root)])
            for pkg in (packages if isinstance(packages, list) else [packages]):
                cmds.append([npm, "install", pkg, "--prefix", str(env_root), "--save"])

            results = []
            for cmd in cmds:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    cwd=str(env_root),
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
                msg = stdout.decode(errors="replace") + stderr.decode(errors="replace")
                results.append(f"npm: {msg}")
            return {"success": True, "message": "\n".join(results)}

        return {"success": False, "message": f"Dependency install not supported for runtime: {runtime}"}

    # ── run_in_env ────────────────────────────────────────────────────────────────

    async def _run_in_env(self, params: dict) -> dict:
        env_name = params.get("env_name", "")
        code = params.get("code", "")
        script_path = params.get("script_path", "")
        args = params.get("args", [])
        cwd = params.get("cwd") or os.getcwd()
        timeout = int(params.get("timeout", 60))

        if not env_name:
            return {"success": False, "message": "env_name required"}

        meta = self._env_meta(env_name)
        if not meta:
            return {"success": False, "message": f"Environment '{env_name}' not found. Create it first with create_env."}

        runtime = meta.get("runtime", "")

        if runtime == "python":
            return await self._run_python(meta, code, script_path, args, cwd, timeout)
        if runtime == "node":
            return await self._run_node(meta, code, script_path, args, cwd, timeout)
        if runtime in ("cpp", "c"):
            return await self._run_cpp(meta, code, script_path, args, cwd, timeout)
        if runtime == "java":
            return await self._run_java(meta, code, script_path, args, cwd, timeout)
        if runtime in ("bash", "shell"):
            return await self._run_shell(code or script_path, args, cwd, timeout, shell="bash")
        if runtime == "powershell":
            return await self._run_shell(code or script_path, args, cwd, timeout, shell="powershell")
        if runtime == "rust":
            return await self._run_rust(meta, code, script_path, args, cwd, timeout)
        if runtime == "go":
            return await self._run_go(meta, code, script_path, args, cwd, timeout)

        return {"success": False, "message": f"Unsupported runtime: {runtime}"}

    async def _run_python(self, meta: dict, code: str, script: str, args: list, cwd: str, timeout: int) -> dict:
        venv = Path(meta["venv_path"])
        py = venv / "Scripts" / "python.exe"
        if not py.exists():
            py = venv / "bin" / "python"

        import tempfile, os as _os
        tmp_file = None
        try:
            if code and not script:
                tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
                tmp.write(code)
                tmp.close()
                tmp_file = tmp.name
                script = tmp_file

            cmd = [str(py), script] + (args if isinstance(args, list) else [])
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            ok = proc.returncode == 0
            return {"success": ok, "data": {"stdout": out, "stderr": err, "returncode": proc.returncode},
                    "message": out + (("\nSTDERR:\n" + err) if err else "")}
        except asyncio.TimeoutError:
            return {"success": False, "message": f"Execution timed out after {timeout}s"}
        finally:
            if tmp_file:
                try:
                    _os.unlink(tmp_file)
                except Exception:
                    pass

    async def _run_node(self, meta: dict, code: str, script: str, args: list, cwd: str, timeout: int) -> dict:
        node = meta.get("node_exe") or shutil.which("node")
        env_root = Path(meta["env_root"])

        import tempfile, os as _os
        tmp_file = None
        try:
            if code and not script:
                tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False, encoding="utf-8")
                tmp.write(code)
                tmp.close()
                tmp_file = tmp.name
                script = tmp_file

            env = {**os.environ, "NODE_PATH": str(env_root / "node_modules")}
            cmd = [node, script] + (args if isinstance(args, list) else [])
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            ok = proc.returncode == 0
            return {"success": ok, "data": {"stdout": out, "stderr": err}, "message": out + err}
        except asyncio.TimeoutError:
            return {"success": False, "message": f"Timed out after {timeout}s"}
        finally:
            if tmp_file:
                try:
                    _os.unlink(tmp_file)
                except Exception:
                    pass

    async def _run_cpp(self, meta: dict, code: str, script: str, args: list, cwd: str, timeout: int) -> dict:
        compiler = meta.get("compiler") or shutil.which("g++") or shutil.which("gcc")
        env_root = Path(meta["env_root"])

        import tempfile, os as _os
        src_file = None
        out_exe = str(env_root / "build" / "output.exe")
        try:
            if code and not script:
                tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False, encoding="utf-8")
                tmp.write(code)
                tmp.close()
                src_file = tmp.name
                script = src_file

            # Compile
            compile_proc = await asyncio.create_subprocess_exec(
                compiler, script, "-o", out_exe, "-std=c++17",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            cout, cerr = await asyncio.wait_for(compile_proc.communicate(), timeout=30)
            if compile_proc.returncode != 0:
                return {"success": False,
                        "message": f"Compilation failed:\n{cerr.decode(errors='replace')}"}

            # Run
            run_proc = await asyncio.create_subprocess_exec(
                out_exe, *((args if isinstance(args, list) else [])),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(run_proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            ok = run_proc.returncode == 0
            return {"success": ok, "data": {"stdout": out, "stderr": err},
                    "message": f"[Compiled OK]\n{out}" + (f"\nSTDERR:\n{err}" if err else "")}
        except asyncio.TimeoutError:
            return {"success": False, "message": f"Timed out after {timeout}s"}
        finally:
            if src_file:
                try:
                    _os.unlink(src_file)
                except Exception:
                    pass

    async def _run_java(self, meta: dict, code: str, script: str, args: list, cwd: str, timeout: int) -> dict:
        java = meta.get("java_exe") or shutil.which("java")
        javac = meta.get("javac_exe") or shutil.which("javac")
        env_root = Path(meta["env_root"])

        import tempfile, os as _os
        src_file = None
        try:
            if code and not script:
                # Extract class name from code
                m = re.search(r"public\s+class\s+(\w+)", code)
                class_name = m.group(1) if m else "Main"
                src_file = str(env_root / "src" / f"{class_name}.java")
                Path(src_file).write_text(code, encoding="utf-8")
                script = src_file

            if javac:
                classes_dir = str(env_root / "classes")
                compile_proc = await asyncio.create_subprocess_exec(
                    javac, script, "-d", classes_dir,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                cout, cerr = await asyncio.wait_for(compile_proc.communicate(), timeout=30)
                if compile_proc.returncode != 0:
                    return {"success": False, "message": f"Compilation failed:\n{cerr.decode(errors='replace')}"}

                # Extract class name from file
                class_name = Path(script).stem
                run_proc = await asyncio.create_subprocess_exec(
                    java, "-cp", classes_dir, class_name,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )
            else:
                # Direct run if .jar or no javac available
                run_proc = await asyncio.create_subprocess_exec(
                    java, "-jar", script,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )

            stdout, stderr = await asyncio.wait_for(run_proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            ok = run_proc.returncode == 0
            return {"success": ok, "data": {"stdout": out, "stderr": err}, "message": out + err}
        except asyncio.TimeoutError:
            return {"success": False, "message": f"Timed out after {timeout}s"}

    async def _run_shell(self, script: str, args: list, cwd: str, timeout: int, shell: str) -> dict:
        if shell == "powershell":
            cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File" if Path(script).exists() else "-Command", script]
        else:
            bash = shutil.which("bash") or shutil.which("sh")
            if not bash:
                return {"success": False, "message": "bash/sh not found"}
            cmd = [bash, script] if Path(script).exists() else [bash, "-c", script]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            ok = proc.returncode == 0
            return {"success": ok, "data": {"stdout": out, "stderr": err}, "message": out + err}
        except asyncio.TimeoutError:
            return {"success": False, "message": f"Timed out after {timeout}s"}

    async def _run_rust(self, meta: dict, code: str, script: str, args: list, cwd: str, timeout: int) -> dict:
        cargo = meta.get("cargo_exe") or shutil.which("cargo")
        env_root = Path(meta["env_root"])
        if code and not script:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False, encoding="utf-8", dir=env_root)
            tmp.write(code)
            tmp.close()
            script = tmp.name
        try:
            proc = await asyncio.create_subprocess_exec(
                "rustc", script, "-o", str(env_root / "output"),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            cout, cerr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                return {"success": False, "message": f"Rust compile failed:\n{cerr.decode(errors='replace')}"}
            run_proc = await asyncio.create_subprocess_exec(
                str(env_root / "output"),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(run_proc.communicate(), timeout=timeout)
            return {"success": run_proc.returncode == 0,
                    "message": stdout.decode(errors="replace") + stderr.decode(errors="replace")}
        except asyncio.TimeoutError:
            return {"success": False, "message": f"Timed out after {timeout}s"}

    async def _run_go(self, meta: dict, code: str, script: str, args: list, cwd: str, timeout: int) -> dict:
        go = meta.get("go_exe") or shutil.which("go")
        env_root = Path(meta["env_root"])
        if code and not script:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False, encoding="utf-8", dir=env_root)
            tmp.write(code)
            tmp.close()
            script = tmp.name
        try:
            proc = await asyncio.create_subprocess_exec(
                go, "run", script,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {"success": proc.returncode == 0,
                    "message": stdout.decode(errors="replace") + stderr.decode(errors="replace")}
        except asyncio.TimeoutError:
            return {"success": False, "message": f"Timed out after {timeout}s"}

    # ── run_auto ──────────────────────────────────────────────────────────────────

    async def _run_auto(self, params: dict) -> dict:
        path = Path(params.get("path", ""))
        version = params.get("version", "")
        args = params.get("args", [])
        timeout = int(params.get("timeout", 120))

        # 1. Detect
        detect = self._detect_runtime({"path": str(path)})
        if not detect["success"]:
            return detect
        info = detect["data"]
        runtime = info.get("runtime")
        if not runtime:
            return {"success": False, "message": f"Could not detect runtime for: {path}\n{detect['message']}"}

        # 2. Create env
        env_name = f"auto_{path.stem}_{runtime}"
        create = await self._create_env({
            "env_name": env_name,
            "runtime": runtime,
            "version": version or info.get("version", ""),
        })

        # 3. Install deps if manifest found
        if runtime == "python":
            for req in ("requirements.txt", "Pipfile"):
                req_path = (path if path.is_dir() else path.parent) / req
                if req_path.exists():
                    await self._install_deps({"env_name": env_name, "deps_file": str(req_path)})
                    break
        elif runtime == "node":
            pkg = (path if path.is_dir() else path.parent) / "package.json"
            if pkg.exists():
                await self._install_deps({"env_name": env_name, "deps_file": str(pkg)})

        # 4. Run
        script = str(path) if path.is_file() else ""
        return await self._run_in_env({
            "env_name": env_name,
            "script_path": script,
            "args": args,
            "cwd": str(path.parent if path.is_file() else path),
            "timeout": timeout,
        })

    # ── list_envs ─────────────────────────────────────────────────────────────────

    def _list_envs(self, params: dict) -> dict:
        envs_root = Path(os.getcwd()) / _ENVS_DIR
        if not envs_root.exists():
            return {"success": True, "data": [], "message": "No environments created yet."}
        envs = []
        for d in sorted(envs_root.iterdir()):
            if d.is_dir():
                meta = self._env_meta(d.name)
                runtime = meta.get("runtime", "unknown")
                version = meta.get("version", "")
                size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                envs.append({
                    "name": d.name,
                    "runtime": runtime,
                    "version": version,
                    "size_mb": round(size / 1_048_576, 1),
                    "path": str(d),
                })
        lines = [f"  {e['name']} [{e['runtime']} {e['version']}] — {e['size_mb']} MB" for e in envs]
        return {"success": True, "data": envs, "message": f"Managed environments ({len(envs)}):\n" + "\n".join(lines)}

    # ── list_runtimes ─────────────────────────────────────────────────────────────

    def _list_runtimes(self, params: dict) -> dict:
        found = {}

        # Python versions — check py launcher and common paths
        pythons = self._find_all_pythons()
        if pythons:
            found["python"] = pythons

        # Node
        node = shutil.which("node")
        if node:
            found["node"] = {"exe": node, "version": self._get_cmd_version(node)}

        # npm
        npm = shutil.which("npm")
        if npm:
            found["npm"] = {"exe": npm, "version": self._get_cmd_version(npm, ["--version"])}

        # Java
        java = shutil.which("java")
        if java:
            found["java"] = {"exe": java, "version": self._get_cmd_version(java, ["-version"])}

        # C++
        for compiler in ("g++", "gcc", "cl"):
            exe = shutil.which(compiler)
            if exe:
                found[f"c++/{compiler}"] = {"exe": exe, "version": self._get_cmd_version(exe, ["--version"])}
                break

        # Rust
        cargo = shutil.which("cargo")
        if cargo:
            found["rust/cargo"] = {"exe": cargo, "version": self._get_cmd_version(cargo, ["--version"])}

        # Go
        go = shutil.which("go")
        if go:
            found["go"] = {"exe": go, "version": self._get_cmd_version(go, ["version"])}

        # PowerShell
        ps = shutil.which("pwsh") or shutil.which("powershell")
        if ps:
            found["powershell"] = {"exe": ps}

        lines = []
        for name, info in found.items():
            if isinstance(info, dict):
                ver = info.get("version", "")
                exe = info.get("exe", "")
                lines.append(f"  ✅ {name:<20} {ver}  [{exe}]")
            elif isinstance(info, list):
                for item in info:
                    lines.append(f"  ✅ {name:<20} {item.get('version','')}  [{item.get('exe','')}]")

        msg = f"Installed runtimes ({len(found)}):\n" + "\n".join(lines)
        return {"success": True, "data": found, "message": msg}

    # ── destroy_env ───────────────────────────────────────────────────────────────

    def _destroy_env(self, params: dict) -> dict:
        env_name = params.get("env_name", "")
        if not env_name:
            return {"success": False, "message": "env_name required"}
        env_path = Path(os.getcwd()) / _ENVS_DIR / env_name
        if not env_path.exists():
            return {"success": False, "message": f"Environment '{env_name}' not found"}
        shutil.rmtree(env_path)
        return {"success": True, "message": f"Environment '{env_name}' deleted."}

    # ── Helpers ───────────────────────────────────────────────────────────────────

    def _find_python(self, version: str) -> str | None:
        """Find a Python executable matching the requested version."""
        # WIS venv first (only for "same version" or no version specified)
        wis_py = Path(os.getcwd()) / "venv" / "Scripts" / "python.exe"
        wis_ver = self._get_python_version(str(wis_py)) if wis_py.exists() else ""

        if not version or wis_ver.startswith(version):
            if wis_py.exists():
                return str(wis_py)

        # Python 2.7
        if version and version.startswith("2"):
            for p in [r"C:\Python27\python.exe", r"C:\Python27\python27.exe"]:
                if Path(p).exists():
                    return p

        # py.exe launcher (Windows Python Launcher)
        py_launcher = shutil.which("py")
        if py_launcher and version:
            major = version.split(".")[0]
            minor = version.split(".")[1] if "." in version else ""
            flag = f"-{major}.{minor}" if minor else f"-{major}"
            try:
                result = subprocess.run(
                    [py_launcher, flag, "--version"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return f"{py_launcher} {flag}"
            except Exception:
                pass

        # Search PATH for python, python3, python3.X
        for name in ("python3", "python", f"python{version}", f"python{version.replace('.', '')}"[:10]):
            exe = shutil.which(name)
            if exe:
                ver = self._get_python_version(exe)
                if not version or ver.startswith(version):
                    return exe

        # Last resort: scan common install dirs
        for prefix in (r"C:\Python", r"C:\Users\nicol\AppData\Local\Programs\Python\Python"):
            for suffix in ("", "3", "38", "39", "310", "311", "312", "27"):
                p = Path(f"{prefix}{suffix}") / "python.exe"
                if p.exists():
                    ver = self._get_python_version(str(p))
                    if not version or ver.startswith(version):
                        return str(p)

        return None

    def _find_all_pythons(self) -> list:
        found = []
        candidates = []
        # Common install paths
        for d in Path("C:\\").glob("Python*"):
            candidates.append(d / "python.exe")
        for d in Path("C:\\Users\\nicol\\AppData\\Local\\Programs\\Python").glob("Python*"):
            candidates.append(d / "python.exe")
        wis_py = Path(os.getcwd()) / "venv" / "Scripts" / "python.exe"
        candidates.append(wis_py)

        seen = set()
        for c in candidates:
            if c.exists() and str(c) not in seen:
                seen.add(str(c))
                ver = self._get_python_version(str(c))
                found.append({"exe": str(c), "version": ver})
        return found

    def _get_python_version(self, exe: str) -> str:
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
            out = (r.stdout + r.stderr).strip()
            m = re.search(r"Python (\d+\.\d+\.\d+)", out)
            return m.group(1) if m else out
        except Exception:
            return "unknown"

    def _get_cmd_version(self, exe: str, args: list | None = None) -> str:
        try:
            cmd = [exe] + (args or ["--version"])
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return (r.stdout + r.stderr).strip().split("\n")[0]
        except Exception:
            return "unknown"
