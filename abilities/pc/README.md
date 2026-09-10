# PC Control & Screen Vision Subsystem (`core/pc/`)

Provides native low-level interaction with Windows OS: GDI/DWM screen capture, CPU-based multimodal visual analysis, OCR, window management, audio/media control, file system manipulation, and process lifecycle management.

---

## 1. Components

| File | Capability |
| :--- | :--- |
| [`apps.py`](apps.py) | Dynamic application, browser, and file resolution with Start Menu indexing and bounded depth traversal. |
| [`process.py`](process.py) | High-speed native process inspection and termination via `psutil` with graceful `WM_CLOSE` and `taskkill` fallbacks. |
| [`gui_driver.py`](gui_driver.py) | UIAutomation, domain script injection (AutoCAD, Photoshop, LTspice), Win32 `SendInput`, and DirectInput hardware scan codes for 3D/CAD/Games. |
| [`window_tools.py`](window_tools.py) | Native Win32 (`ctypes.windll.user32`) window enumeration with DWM cloaked filtering, Per-Monitor DPI Awareness v2, window snapping, and monitor geometry. |
| [`media_tools.py`](media_tools.py) | System-wide GSMTC media playback metadata, Core Audio hardware master volume, and per-application audio session volume mixer (`IAudioSessionManager2`). |
| [`filesystem.py`](filesystem.py) | Workspace file operations: atomic file writes (`atomic_write`), directory change watcher (`wait_for_change`), bounded search, and tar/zip archives. |
| [`macros.py`](macros.py) | Multi-step macro routine engine (record, execute, and persist desktop automations in SQLite). |
| [`calendar_tools.py`](calendar_tools.py) | Natural language date normalization and SQLite event agenda management with reminder linking. |
| [`vision_engine.py`](vision_engine.py) | Multimodal CPU vision engine (<1.2s SLA): Zero-Shot CLIP ViT-B/32 ONNX, RapidOCR ONNX, and 64-bit perceptual screen diffing (dHash) cache (0.2 ms on static screens). |
| [`screen_vision.py`](screen_vision.py) | Native GDI BitBlt screen capture and GPU-accelerated window capture (`PrintWindow` with `PW_RENDERFULLCONTENT`). |
| [`shell.py`](shell.py) | Safe terminal execution in PowerShell/cmd with path space auto-quoting, execution timeouts, and real-time streaming execution (`run_streaming`). |
| [`commands.py`](commands.py) | Innate command catalog with explicit destructive action policy matrix (`DESTRUCTIVE_ACTIONS`) and 0-token monosyllabic fast-path. |
| [`excel_tools.py`](excel_tools.py) | Reading, writing, and structured table inspection of `.xlsx` and `.csv` workbooks. |
| [`pdf_tools.py`](pdf_tools.py) | Text, table, and metadata extraction from `.pdf` documents and report generation via ReportLab. |
| [`pptx_tools.py`](pptx_tools.py) | Automated presentation generator creating full `.pptx` slide decks from structured outlines. |
| [`word_tools.py`](word_tools.py) | Document builder for styled `.docx` reports and articles. |
| [`toast_notifications.py`](toast_notifications.py) | Native Windows 10/11 Action Center toast notifications (`AVRORA Notify`). |
| [`system_folders.py`](system_folders.py) | Dynamic Windows Known Folder resolution via Win32 `SHGetKnownFolderPath` (Desktop, Downloads, Documents, Pictures). |
| [`workspace_env.py`](workspace_env.py) | Local developer environment inspector (Git repositories, compilers, IDEs, and runtimes). |
| [`nl_commands.py`](nl_commands.py) | Tool dispatch surface for LLM function calling (`PCInterpreter`) and natural language mapping. |


