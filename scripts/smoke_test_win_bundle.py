from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    base = repo_root / "dist" / "markview" / "_internal"
    qt_bin = base / "PyQt6" / "Qt6" / "bin"

    if not qt_bin.is_dir():
        raise SystemExit(f"Missing Qt bin directory: {qt_bin}")

    os.environ["PATH"] = str(qt_bin) + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(str(qt_bin))
    sys.path.insert(0, str(base))

    from PyQt6.QtWebChannel import QWebChannel
    from PyQt6.QtWebEngineCore import QWebEnginePage
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    print("Bundle smoke test OK")
    print("QWebChannel:", QWebChannel)
    print("QWebEnginePage:", QWebEnginePage)
    print("QWebEngineView:", QWebEngineView)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
