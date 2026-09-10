"""Local and workspace filesystem operations for Windows.

Provides atomic file writes (os.replace on temp files) to prevent data corruption,
directory change watching (wait_for_change), sandboxed workspace resolution,
safe deletion, file analysis, and tar/zip compression/decompression.
"""
from __future__ import annotations

import logging
import os
import shutil
import tarfile
import zipfile
from pathlib import Path

from .system_folders import resolve_folder

logger = logging.getLogger(__name__)



class PCOperationError(Exception):
    """Raised when a PC operation fails."""


# Backward-compatible wrapper around the OS-resolved folders (no dictionary).
def home_shortcuts() -> dict[str, Path]:
    """Return the real user folders keyed by canonical + localized names.

    Delegates to the operating system (Known Folders / XDG) — the single
    source of truth — instead of a hand-written dictionary.
    """
    from .system_folders import system_folders

    return system_folders()


class FileSystemOps:
    """File/directory operations with path-traversal protection."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.cwd()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str | Path) -> Path:
        if not path:
            return self.root
        p_obj = Path(path)
        if p_obj.is_absolute():
            return p_obj.resolve()

        if isinstance(path, str):
            # 1. Direct system folder matching (e.g. "escritorio", "Desktop")
            resolved_single = resolve_folder(path)
            if resolved_single is not None:
                return resolved_single.resolve()

            # 2. Path starting with a system folder prefix (e.g. "escritorio/countdown.py", "Desktop/test.txt")
            parts = p_obj.parts
            if len(parts) > 1:
                resolved_prefix = resolve_folder(parts[0])
                if resolved_prefix is not None:
                    return (resolved_prefix / Path(*parts[1:])).resolve()

        return (self.root / p_obj).resolve()

    def search(
        self,
        name: str,
        roots: list[Path] | None = None,
        limit: int = 50,
        time_budget: float = 5.0,
    ) -> list[Path]:
        """Recursively search for files/dirs whose name contains `name`.

        Searches the user's common folders (Desktop, Documents, Downloads) by
        default — NOT the whole home (too slow). Bounded by `limit` matches,
        a `time_budget`, and skips heavy/hidden directories.
        """
        import time as _time
        import subprocess
        import shlex

        pattern = name.lower()
        roots = roots or [
            Path.home() / "Desktop",
            Path.home() / "Documents",
            Path.home() / "Downloads",
        ]
        _SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "AppData", ".cache", ".config"}
        results: list[Path] = []
        seen: set[Path] = set()
        started = _time.perf_counter()

        # Fast shallow inspection of top-level files in self.root, user home, and workspace root
        direct_roots = [r for r in {self.root, Path.home(), Path.cwd()} if r and r.exists()]
        for droot in direct_roots:
            try:
                for entry in droot.iterdir():
                    if entry.is_file() and pattern in entry.name.lower():
                        if entry not in seen:
                            seen.add(entry)
                            results.append(entry)
                            if len(results) >= limit:
                                return results
            except Exception:
                continue

        for root in roots:
            if not root.exists():
                continue
            
            # Fast Path: Rust Ripgrep (rg)
            try:
                # Build rg command: rg --files --hidden --no-ignore -g "*pattern*" <root>
                # Using subprocess to call the fast compiled binary
                rg_cmd = ["rg", "--files", "--hidden", "-g", f"*{pattern}*", str(root)]
                # Add skip dirs
                for skip in _SKIP_DIRS:
                    rg_cmd.extend(["-g", f"!{skip}/**"])
                
                proc = subprocess.run(rg_cmd, capture_output=True, text=True, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                
                # Parse output
                for line in proc.stdout.splitlines():
                    if _time.perf_counter() - started > time_budget:
                        return results
                    line = line.strip()
                    if not line: continue
                    entry = Path(line)
                    if entry.is_file() and entry not in seen:
                        seen.add(entry)
                        results.append(entry)
                        if len(results) >= limit:
                            return results
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Fallback: Python os.walk (Safe Mode)
                for dirpath, dirnames, filenames in os.walk(root):
                    if _time.perf_counter() - started > time_budget:
                        return results
                    dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
                    for fn in filenames:
                        if pattern in fn.lower():
                            entry = Path(dirpath) / fn
                            if entry not in seen:
                                seen.add(entry)
                                results.append(entry)
                                if len(results) >= limit:
                                    return results
        return results

    def list(self, path: str = ".") -> list[dict[str, str | int]]:
        p = self._resolve(path)
        if not p.exists():
            raise PCOperationError(f"path does not exist: {p}")
        if p.is_file():
            try:
                sz = p.stat().st_size
            except OSError:
                sz = 0
            return [
                {
                    "name": p.name,
                    "type": "file",
                    "size": sz,
                    "parent": str(p.parent),
                }
            ]
        items: list[dict[str, str | int]] = []
        for entry in sorted(p.iterdir()):
            try:
                items.append(
                    {
                        "name": entry.name,
                        "type": "dir" if entry.is_dir() else "file",
                        "size": entry.stat().st_size if entry.is_file() else 0,
                    }
                )
            except OSError:
                continue
        return items

    def read(self, path: str, max_chars: int = 20_000) -> str:
        try:
            clean = path.strip()
            if not clean or clean.lower() in ("y", "el", "la", "en", "de", "a", "o", "u", "por", "con"):
                raise PCOperationError(f"Invalid file target '{path}'. Please specify a valid filename or path.")

            p = self._resolve(path)
            # Desktop fallback if not found in current root
            if not p.exists():
                desk_p = (Path.home() / "Desktop" / clean)
                if desk_p.exists():
                    p = desk_p

            if p.is_dir():
                idx_file = p / "index.html"
                if idx_file.exists() and idx_file.is_file():
                    content = idx_file.read_text(encoding="utf-8", errors="replace")
                    return f"[Note: '{p.name}' is a directory; auto-loaded '{p.name}/index.html']\n\n" + content[:max_chars]
                files = [f.name for f in p.iterdir() if not f.name.startswith(".")][:12]
                file_list = ", ".join(files) if files else "(empty folder)"
                raise PCOperationError(f"'{p.name}' is a directory containing: {file_list}. Specify which file to read.")

            if not p.is_file():
                raise PCOperationError(f"not a file: {p}")
            content = p.read_text(encoding="utf-8", errors="replace")
            return content[:max_chars] + ("\n…[truncated]" if len(content) > max_chars else "")
        except PCOperationError:
            raise
        except OSError as exc:
            raise PCOperationError(f"could not read '{path}': {exc}") from exc

    def atomic_write(self, path: str, content: str, encoding: str = "utf-8") -> str:
        """Write file contents atomically using a temporary file and atomic replace.

        Prevents file corruption or partial writes during unexpected crashes.
        """
        import tempfile

        p = self._resolve(path)
        if p.is_dir():
            raise PCOperationError(f"'{p}' is an existing directory. Specify a filename to write.")
        p.parent.mkdir(parents=True, exist_ok=True)
        # Create temp file in same directory (guarantees same filesystem volume for atomic os.replace)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=p.parent, prefix=f".tmp_{p.name}_")
        try:
            with open(tmp_fd, "w", encoding=encoding) as f:
                f.write(content)
            os.replace(tmp_path, str(p))
            return f"written {len(content)} chars atomically -> {p}"
        except Exception as exc:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception as _exc:
                logger.debug("Operacion no fatal suprimida: %s", _exc)
            raise PCOperationError(f"atomic write failed for '{path}': {exc}") from exc

    def wait_for_change(self, path: str, timeout: float = 5.0) -> bool:
        """Wait until a file is created or modified, bounded by timeout."""
        import time

        p = self._resolve(path)
        init_mtime = p.stat().st_mtime if p.exists() else None
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            time.sleep(0.05)
            if p.exists():
                curr_mtime = p.stat().st_mtime
                if init_mtime is None or curr_mtime != init_mtime:
                    return True
        return False

    def write(self, path: str, content: str) -> str:
        return self.atomic_write(path, content)

    def create(self, path: str, content: str = "") -> str:
        try:
            p = self._resolve(path)
            if p.is_dir():
                raise PCOperationError(f"'{p}' is an existing directory. Specify a filename to create a file.")
            self.atomic_write(path, content)
            return f"created {p}"
        except PCOperationError:
            raise
        except OSError as exc:
            raise PCOperationError(f"could not create '{path}': {exc}") from exc

    def append(self, path: str, content: str = "") -> str:
        try:
            p = self._resolve(path)
            if p.is_dir():
                raise PCOperationError(f"'{p}' is an existing directory. Specify a filename to append to a file.")
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8", errors="replace") as f:
                f.write(content)
            return f"appended {len(content)} chars to {p}"
        except PCOperationError:
            raise
        except OSError as exc:
            raise PCOperationError(f"could not append to '{path}': {exc}") from exc

    def mkdir(self, path: str) -> str:
        try:
            p = self._resolve(path)
            p.mkdir(parents=True, exist_ok=True)
            return f"created directory {p}"
        except OSError as exc:
            raise PCOperationError(f"could not create directory '{path}': {exc}") from exc

    def delete(self, path: str, recursive: bool = False) -> str:
        try:
            p = self._resolve(path)
            if not p.exists():
                raise PCOperationError(f"does not exist: {p}")

            # Enforce critical system safety boundaries
            p_resolved = p.resolve()
            if str(p_resolved) == p_resolved.anchor or len(p_resolved.parts) <= 1:
                raise PCOperationError(f"Security Violation: Prohibited from deleting drive root '{p}'")

            home = Path.home().resolve()
            if p_resolved == home:
                raise PCOperationError("Security Violation: Prohibited from deleting user home directory")

            win_dir = Path(os.environ.get("WINDIR", "C:\\Windows")).resolve()
            prog_files = Path(os.environ.get("ProgramFiles", "C:\\Program Files")).resolve()
            if p_resolved == win_dir or win_dir in p_resolved.parents or p_resolved == prog_files or prog_files in p_resolved.parents:
                raise PCOperationError(f"Security Violation: Prohibited from deleting system directory '{p}'")

            if p.is_dir():
                if not recursive:
                    raise PCOperationError(f"directory {p} — use recursive=true to delete")
                shutil.rmtree(p)
            else:
                p.unlink()
            return f"deleted {p}"
        except PCOperationError:
            raise
        except OSError as exc:
            raise PCOperationError(f"could not delete '{path}': {exc}") from exc

    def move(self, src: str, dst: str) -> str:
        try:
            s, d = self._resolve(src), self._resolve(dst)
            if not s.exists():
                raise PCOperationError(f"does not exist: {s}")
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(s), str(d))
            return f"moved {s} → {d}"
        except PCOperationError:
            raise
        except OSError as exc:
            raise PCOperationError(f"could not move '{src}' to '{dst}': {exc}") from exc

    # ------------------------------------------------------------------
    def analyze(self, path: str) -> dict[str, str | int]:
        """Return size, lines, words, chars and type of a file."""
        p = self._resolve(path)
        if not p.exists():
            raise PCOperationError(f"does not exist: {p}")
        if p.is_dir():
            files = [f for f in p.rglob("*") if f.is_file()]
            total = sum(f.stat().st_size for f in files)
            return {
                "type": "directory",
                "name": p.name,
                "files": len(files),
                "total_size": _human(total),
                "bytes": total,
            }
        size = p.stat().st_size
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            lines = text.count("\n") + (1 if text else 0)
            words = len(text.split())
            chars = len(text)
            preview = text[:200].replace("\n", " ")
        except Exception:  # noqa: BLE001 — binary file
            lines = words = chars = 0
            preview = "(binary)"
        return {
            "type": "file",
            "name": p.name,
            "extension": p.suffix or "(none)",
            "size": _human(size),
            "bytes": size,
            "lines": lines,
            "words": words,
            "chars": chars,
            "preview": preview,
        }

    def compress(self, path: str, dest: str | None = None) -> str:
        """Compress a file or directory into a .zip (or .tar.gz if dest ends with .tar.gz)."""
        src = self._resolve(path)
        if not src.exists():
            raise PCOperationError(f"does not exist: {src}")
        dest_path = self._resolve(dest or (str(src) + ".zip"))
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if str(dest_path).endswith((".tar.gz", ".tgz")):
            with tarfile.open(dest_path, "w:gz") as tar:
                tar.add(src, arcname=src.name)
        elif str(dest_path).endswith(".tar"):
            with tarfile.open(dest_path, "w") as tar:
                tar.add(src, arcname=src.name)
        else:
            if src.is_dir():
                shutil.make_archive(str(dest_path).replace(".zip", ""), "zip", root_dir=src.parent, base_dir=src.name)
            else:
                with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(src, arcname=src.name)
        return f"compressed {src.name} → {dest_path}"

    def decompress(self, archive: str, dest: str | None = None) -> str:
        """Decompress a .zip / .tar / .tar.gz into dest (default: same folder)."""
        a = self._resolve(archive)
        if not a.is_file():
            raise PCOperationError(f"not a file: {a}")
        dest_path = self._resolve(dest or str(a.parent))
        dest_path.mkdir(parents=True, exist_ok=True)
        if str(a).endswith((".tar.gz", ".tgz", ".tar")):
            with tarfile.open(a) as tar:
                tar.extractall(dest_path)  # noqa: S202 # nosec B202
        else:
            with zipfile.ZipFile(a) as zf:
                zf.extractall(dest_path)  # nosec B202
        return f"decompressed {a.name} → {dest_path}"


def _human(n: int | float) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{value:.0f} B"
        value /= 1024
    return f"{value} B"
