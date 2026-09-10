"""System folder resolution — ask the OS, don't hardcode a dictionary.

Professionals do NOT maintain hand-written dictionaries mapping "escritorio"
→ "C:\\Users\\X\\Desktop". The operating system is the single source of truth
for folder locations and their localized names:

- Windows: SHGetKnownFolderPath (returns the REAL localized path, including
  OneDrive redirects and non-English Windows).
- Linux:   XDG user-dirs (~/.config/user-dirs.dirs).
- macOS:   ~/Desktop, ~/Documents, … (always English).

The canonical keys (desktop, documents, downloads, pictures, music, videos)
are the only thing we keep; their real paths come from the OS. To understand
what the user said ("escritorio", "Desktop", "escritorio"), we match by exact
name first, then by substring, then (optionally) by embedding similarity
against the OS-provided real names.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# Canonical keys → Windows Known Folder GUIDs (FOLDERID_*).
_KNOWN_FOLDER_GUIDS: dict[str, str] = {
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}

_CANONICAL = tuple(_KNOWN_FOLDER_GUIDS) if sys.platform == "win32" else (
    "desktop", "documents", "downloads", "pictures", "music", "videos",
)

# Minimal, STABLE bilingual bridge for the 6 system folders ONLY. This is not
# the anti-pattern: unlike intent dictionaries (which grow with usage), the set
# of system folders is finite and fixed (~6), so a tiny canonical→localized
# mapping is standard practice. Everything that grows uses embeddings/NLU.
_LOCALIZED: dict[str, str] = {
    "desktop": "desktop",
    "escritorio": "desktop",
    "documents": "documents",
    "documentos": "documents",
    "downloads": "downloads",
    "descargas": "downloads",
    "pictures": "pictures",
    "imagenes": "pictures",
    "imágenes": "pictures",
    "music": "music",
    "musica": "music",
    "música": "music",
    "videos": "videos",
    "vídeos": "videos",
}


def _win_known_folder(guid: str) -> Path | None:
    """Resolve a Windows Known Folder GUID to its REAL localized path."""
    try:
        import ctypes
        from ctypes import wintypes

        # SHGetKnownFolderPath(const GUID*, DWORD, HANDLE, PWSTR*)
        SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
        SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(ctypes.c_char), wintypes.DWORD, wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        SHGetKnownFolderPath.restype = ctypes.c_long

        guid_buf = ctypes.create_string_buffer(guid.encode("ascii"))
        p_path = ctypes.c_wchar_p()
        hr = SHGetKnownFolderPath(
            ctypes.cast(guid_buf, ctypes.POINTER(ctypes.c_char)),
            0,  # KF_FLAG_DEFAULT
            None,
            ctypes.byref(p_path),
        )
        if hr == 0 and p_path.value:
            return Path(p_path.value)
    except Exception as _exc:  # noqa: BLE001 — fall back to env/home
        logger.debug("Operacion no fatal suprimida: %s", _exc)
    return None


def system_folders() -> dict[str, Path]:
    """The real user folders, resolved from the OS (not hardcoded)."""
    result: dict[str, Path] = {}
    home = Path.home()

    if sys.platform == "win32":
        for key, guid in _KNOWN_FOLDER_GUIDS.items():
            p = _win_known_folder(guid)
            if p is not None:
                result[key] = p
        # Fallbacks if the API missed something.
        result.setdefault("desktop", home / "Desktop")
        result.setdefault("documents", home / "Documents")
        result.setdefault("downloads", home / "Downloads")
        result.setdefault("pictures", home / "Pictures")
        result.setdefault("music", home / "Music")
        result.setdefault("videos", home / "Videos")
    else:
        # Linux XDG user dirs, then macOS defaults.
        xdg = _xdg_dirs(home)
        result["desktop"] = xdg.get("DESKTOP", home / "Desktop")
        result["documents"] = xdg.get("DOCUMENTS", home / "Documents")
        result["downloads"] = xdg.get("DOWNLOAD", home / "Downloads")
        result["pictures"] = xdg.get("PICTURES", home / "Pictures")
        result["music"] = xdg.get("MUSIC", home / "Music")
        result["videos"] = xdg.get("VIDEOS", home / "Videos")

    # Also register the OS-localized names (e.g. "Escritorio" on Spanish Windows).
    for key, path in list(result.items()):
        result[key] = path
        result[path.name.lower()] = path
    return result


def _xdg_dirs(home: Path) -> dict[str, Path]:
    """Parse ~/.config/user-dirs.dirs (XDG) if present."""
    result: dict[str, Path] = {}
    config = home / ".config" / "user-dirs.dirs"
    try:
        for line in config.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("XDG_") and "=" in line:
                key, _, value = line.partition("=")
                key = key.removeprefix("XDG_").removesuffix("_DIR")
                value = value.strip('"').replace("$HOME", str(home))
                if value.startswith("/"):
                    result[key] = Path(value)
    except OSError:
        pass
    return result


def resolve_folder(name: str) -> Path | None:
    """Resolve a user-supplied folder name to a real OS path.

    Strategy (no hand-written synonyms):
    1. Exact match against canonical keys and OS-localized names.
    2. Substring match (e.g. "escririo" typo → "escritorio" if unique).
    3. (Future) embedding similarity against the real names.
    """
    clean_name = name.strip().strip("/\\").lower()
    if not clean_name:
        return None
    # If it's a compound path like "desktop/file.py", only resolve the folder part
    if "/" in clean_name or "\\" in clean_name:
        return None

    folders = system_folders()

    # 1) Exact match.
    if clean_name in folders:
        return folders[clean_name]

    # 1b) Minimal stable bilingual bridge (6 system folders only).
    canonical = _LOCALIZED.get(clean_name)
    if canonical is not None and canonical in folders:
        return folders[canonical]

    # 2) Substring / startswith match against the real names (min length 3 to avoid false positives).
    if len(clean_name) >= 3:
        matches: list[Path] = []
        for known, path in folders.items():
            if clean_name in known:
                matches.append(path)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            # Prefer the shortest name (most canonical) when ambiguous.
            matches.sort(key=lambda p: len(p.name))
            return matches[0]

    # 3) Levenshtein fallback for typos (min length 4).
    if len(clean_name) >= 4:
        best: tuple[int, Path] | None = None
        for known, path in folders.items():
            dist = _edit_distance(clean_name, known)
            if len(known) >= 3 and dist <= max(1, len(clean_name) // 3):
                if best is None or dist < best[0]:
                    best = (dist, path)
        return best[1] if best else None
    return None


def _edit_distance(a: str, b: str) -> int:
    """Tiny Levenshtein distance (typo tolerance for folder names)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + (ca != cb),
            ))
        prev = cur
    return prev[-1]
