"""Innate shell abilities and safety policy matrix for AVRORA.

Defines the command catalog, PendingAction confirmation wrappers,
explicit destructive action classification (DESTRUCTIVE_ACTIONS),
and 0-token monosyllabic fast-path dialog acts.

AVRORA operates the PC as its native language — NOT as external skills.
These abilities cover: read, analyze, compress, decompress, delete, install,
uninstall. Successful operations are memorized through procedural memory so
AVRORA learns the commands it actually uses (digital-twin behavior), instead
of pretending to "know" every shell command.

Safety model:
- read / analyze / compress / decompress → safe, execute immediately
- delete / install / uninstall            → destructive, require confirmation
  (returned as a PendingAction, executed only on explicit confirmation)
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..memory.procedural import ProceduralMemory
from .filesystem import FileSystemOps, PCOperationError
from .shell import ShellOps

if TYPE_CHECKING:  # pragma: no cover
    from .workspace_env import WorkspaceEnv


@dataclass(frozen=True)
class PendingAction:
    """An operation awaiting explicit user confirmation before execution."""

    description: str
    executor: Callable[[], str]


# Explicit safety policy matrix: operations requiring human confirmation before execution
DESTRUCTIVE_ACTIONS = frozenset(
    {
        "pc_delete",
        "delete",
        "uninstall",
        "kill_tree",
        "kill_process",
        "shutdown",
        "restart",
        "wipe_memory",
        "clear_database",
    }
)


def is_destructive_action(action_name: str) -> bool:
    """Return True if an action is destructive and requires a PendingAction confirmation."""
    clean = action_name.strip().lower()
    return clean in DESTRUCTIVE_ACTIONS or any(d in clean for d in ("delete", "uninstall", "shutdown", "restart"))


# Standard dialog act polarity for 0-token immediate fast-path confirmation.
_AFFIRMATIVE_ACTS = frozenset(
    {
        "yes", "y", "sí", "si", "confirm", "confirma", "confirmed", "do it",
        "proceed", "adelante", "dale", "go ahead", "ok", "okay", "continue",
        "claro", "por supuesto", "afirmativo",
    }
)
_NEGATIVE_ACTS = frozenset(
    {
        "no", "n", "cancel", "cancela", "cancelar", "stop", "abort", "abortar",
        "negativo", "detén", "deten", "para",
    }
)


def _first_word(text: str) -> str:
    """First token with punctuation stripped, e.g. 'si,' -> 'si'."""
    tokens = text.strip().lower().split()
    if not tokens:
        return ""
    return tokens[0].strip(".,;:!?¿¡\"'()[]{}")


def is_confirmation(text: str) -> bool:
    """Classify affirmative dialog act ('si, borralo', 'yes please', 'dale')."""
    lowered = text.strip().lower()
    if lowered in _AFFIRMATIVE_ACTS:
        return True
    first = _first_word(text)
    # Multi-letter leading words only, so 'y'/'n' never hijack a sentence.
    return len(first) >= 2 and first in _AFFIRMATIVE_ACTS


def is_cancellation(text: str) -> bool:
    """Classify negative dialog act ('no, no borres', 'cancel that', 'abortar')."""
    lowered = text.strip().lower()
    if lowered in _NEGATIVE_ACTS:
        return True
    first = _first_word(text)
    return len(first) >= 2 and first in _NEGATIVE_ACTS


class ShellCatalog:
    """Catalog of AVRORA's innate PC abilities."""

    def __init__(
        self,
        *,
        fs: FileSystemOps | None = None,
        shell: ShellOps | None = None,
        procedural: ProceduralMemory | None = None,
        workspace_env: WorkspaceEnv | None = None,
    ) -> None:
        self.fs = fs or FileSystemOps()
        self.shell = shell or ShellOps()
        self.procedural = procedural
        self.workspace_env = workspace_env

    # ------------------------------------------------------------------
    def _remember(self, name: str, steps: str) -> None:
        if self.procedural is not None:
            self.procedural.add(name, steps)

    # -- safe operations (no confirmation) -------------------------------
    def read(self, path: str) -> str:
        content = self.fs.read(path)
        self._remember("read_file", f"read {path}")
        return content

    def analyze(self, path: str) -> str:
        info = self.fs.analyze(path)
        self._remember("analyze_file", f"analyze {path}")
        lines = [f"[pc] analysis of {path}:"]
        for key, value in info.items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)

    def compress(self, path: str, dest: str | None = None) -> str:
        out = self.fs.compress(path, dest)
        self._remember("compress", f"compress {path}")
        return f"[pc] {out}"

    def decompress(self, archive: str, dest: str | None = None) -> str:
        out = self.fs.decompress(archive, dest)
        self._remember("decompress", f"decompress {archive}")
        return f"[pc] {out}"

    # -- destructive operations (require confirmation) --------------------
    def delete(self, path: str, recursive: bool = False) -> str:
        out = self.fs.delete(path, recursive=recursive)
        self._remember("delete", f"delete {path}")
        return f"[pc] {out}"

    def install(self, package: str, manager: str = "auto") -> str:
        m = manager.lower()
        if (m in ("pip", "auto") or not m) and self.workspace_env is not None:
            out = self.workspace_env.install(package, manager)
            self._remember("install", f"install {package} in workspace_env")
            return out
        command = _package_command(manager, "install", package)
        out = self.shell.run(command, timeout=600)
        self._remember("install", f"install {package} via {manager}")
        return f"[pc] installed {package}: {out}"

    def uninstall(self, package: str, manager: str = "auto") -> str:
        m = manager.lower()
        if (m in ("pip", "auto") or not m) and self.workspace_env is not None:
            out = self.workspace_env.uninstall(package, manager)
            self._remember("uninstall", f"uninstall {package} from workspace_env")
            return out
        command = _package_command(manager, "uninstall", package)
        out = self.shell.run(command, timeout=600)
        self._remember("uninstall", f"uninstall {package} via {manager}")
        return f"[pc] uninstalled {package}: {out}"


def _package_command(manager: str, action: str, package: str) -> str:
    m = manager.lower()
    if m == "pip":
        return f'python -m pip {action} "{package}"'
    if m == "npm":
        return f"npm {action} {package}"
    if m in ("winget", "auto"):
        return f'winget {action} "{package}"'
    raise PCOperationError(f"unknown package manager: {manager}")
