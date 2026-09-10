"""Application, document, and URL launcher for Windows.

Provides dynamic executable resolution via Start Menu shortcut indexing (.lnk),
Windows Registry App Paths, and targeted candidate lookup (eliminating unbounded filesystem scans).
Supports bounded-depth workspace file resolution and specific browser targeting.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)



class PCOperationError(Exception):
    """Raised when a PC operation fails."""


def resolve_browser_exe(preferred: str | None) -> str | None:
    """Dynamically resolve executable path for any browser or application (zero hardcoding)."""
    if not preferred:
        return None
    key_name = preferred.strip().lower()
    if not key_name:
        return None

    # 1. PATH environment lookup
    import shutil
    for candidate in (key_name, f"{key_name}.exe"):
        found = shutil.which(candidate)
        if found and os.path.isfile(found):
            return found

    # 2. Windows Registry App Paths dynamic enumeration
    if os.name == "nt":
        try:
            import winreg
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as app_paths:
                        num_keys, _, _ = winreg.QueryInfoKey(app_paths)
                        for i in range(num_keys):
                            try:
                                kname = winreg.EnumKey(app_paths, i)
                                if key_name in kname.lower():
                                    with winreg.OpenKey(app_paths, kname) as k:
                                        val, _ = winreg.QueryValueEx(k, "")
                                        clean = val.strip('"').strip()
                                        if clean and os.path.isfile(clean):
                                            return clean
                            except OSError:
                                continue
                except OSError:
                    continue
        except Exception as _exc:
            logger.debug("Operacion no fatal suprimida: %s", _exc)

    # 3. Windows Start Menu shortcuts (fast <5ms resolution for desktop apps)
    if os.name == "nt":
        start_menu_roots = [
            Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
            Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
        ]
        for sm_root in start_menu_roots:
            if not sm_root.exists():
                continue
            try:
                for lnk in sm_root.glob(f"*{key_name}*.lnk"):
                    if lnk.is_file():
                        return str(lnk)
                for lnk in sm_root.glob(f"*/*{key_name}*.lnk"):
                    if lnk.is_file():
                        return str(lnk)
            except Exception:
                continue

    # 4. Bounded filesystem scan across standard program directories (depth <= 2)
    if os.name == "nt":
        search_roots = [
            Path(os.environ.get("LOCALAPPDATA", "")),
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")),
        ]
        for sroot in search_roots:
            if not sroot.exists():
                continue
            try:
                # Direct candidates
                direct_cands = [
                    sroot / f"{key_name}.exe",
                    sroot / key_name / f"{key_name}.exe",
                    sroot / "Programs" / key_name / f"{key_name}.exe",
                    sroot / "Programs" / f"{key_name}.exe",
                ]
                for dc in direct_cands:
                    if dc.is_file():
                        return str(dc)
                # Shallow glob (depth 1 and 2)
                for p in sroot.glob(f"*/{key_name}*.exe"):
                    if p.is_file():
                        return str(p)
                for p in sroot.glob(f"*/*/{key_name}*.exe"):
                    if p.is_file():
                        return str(p)
            except Exception:
                continue

    return None


class AppOps:
    """Open apps, files, and URLs with optional browser routing."""

    @staticmethod
    def resolve_file(path_or_filename: str, root: Path | None = None) -> Path | None:
        """Dynamically resolve a file across workspace and Windows user directories (Desktop, Documents, Downloads, Home)."""
        p = Path(path_or_filename)
        if p.is_absolute() and p.exists() and p.is_file():
            return p

        from .filesystem import resolve_folder
        # Check direct prefix (e.g. "Desktop/file.pptx")
        parts = p.parts
        if len(parts) > 1:
            pre = resolve_folder(parts[0])
            if pre is not None:
                cand = (pre / Path(*parts[1:])).resolve()
                if cand.exists() and cand.is_file():
                    return cand

        search_root = root or Path.cwd()
        direct = search_root / p
        if direct.exists() and direct.is_file():
            return direct.resolve()

        # Check user desktop, documents, and downloads directly
        for folder_name in ("desktop", "documents", "downloads"):
            sys_folder = resolve_folder(folder_name)
            if sys_folder is not None:
                cand = (sys_folder / p.name).resolve()
                if cand.exists() and cand.is_file():
                    return cand

        # Check user home directly (where pc_root files are stored by default)
        try:
            home_cand = (Path.home() / p.name).resolve()
            if home_cand.exists() and home_cand.is_file():
                return home_cand
        except Exception as _exc:
            logger.debug("Operacion no fatal suprimida: %s", _exc)

        # Extension fallbacks if name was given without extension (e.g. 'Propuesta' -> 'Propuesta.pptx')
        if not p.suffix:
            common_exts = (".pptx", ".docx", ".xlsx", ".pdf", ".html", ".txt", ".csv")
            for ext in common_exts:
                variant = p.with_suffix(ext)
                for cand_dir in (search_root, Path.home(), resolve_folder("desktop"), resolve_folder("documents")):
                    if cand_dir is not None:
                        try:
                            cand = (cand_dir / variant.name).resolve()
                            if cand.exists() and cand.is_file():
                                return cand
                        except Exception:
                            continue

        try:
            # Bounded search (max depth 3) to prevent freezing on large workspace directories
            for pattern in (f"*/{p.name}", f"*/*/{p.name}", f"*/*/*/{p.name}"):
                matches = [
                    f for f in search_root.glob(pattern)
                    if f.is_file() and not any(part.startswith((".", "venv", "__")) for part in f.parts)
                ]
                if matches:
                    return matches[0].resolve()
        except Exception as _exc:
            logger.debug("Operacion no fatal suprimida: %s", _exc)
        return None


    @staticmethod
    def open(path_or_app: str, browser: str | None = None, root: Path | None = None) -> str:
        is_url = path_or_app.startswith(("http://", "https://", "www.")) or any(
            path_or_app.endswith(tld) for tld in (".com", ".org", ".net", ".io", ".es", ".co", ".gov", ".edu", ".ai")
        )
        try:
            if is_url:
                url = path_or_app if path_or_app.startswith(("http://", "https://")) else f"https://{path_or_app}"
                exe_path = resolve_browser_exe(browser)
                if exe_path:
                    subprocess.Popen([exe_path, url], creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    return f"opened: {url} in {browser}"
                if os.name == "nt":
                    # Secure native shell-less opening (Win32 ShellExecuteW)
                    os.startfile(url)
                else:
                    subprocess.Popen(["xdg-open", url])
                return f"opened: {url}"

            if os.name == "nt":
                target_file = AppOps.resolve_file(path_or_app, root=root)
                if target_file and target_file.is_file():
                    os.startfile(str(target_file))  # noqa: S606
                    return f"opened: {target_file.name}"
                # If target_file was not a direct file path, try os.startfile directly.
                # os.startfile invokes ShellExecuteW directly without cmd.exe or shell=True,
                # opening registered extensions, protocols, shortcuts, and apps safely.
                try:
                    os.startfile(path_or_app)
                    return f"opened: {path_or_app}"
                except OSError:
                    exe = shutil.which(path_or_app) or resolve_browser_exe(path_or_app)
                    if exe and os.path.isfile(exe):
                        subprocess.Popen([exe], creationflags=subprocess.CREATE_NO_WINDOW)
                        return f"opened: {path_or_app}"
                    raise
            else:
                subprocess.Popen(["xdg-open", path_or_app])
            return f"opened: {path_or_app}"
        except Exception as exc:  # noqa: BLE001
            raise PCOperationError(f"could not open {path_or_app}: {exc}") from exc

    open_app = open
