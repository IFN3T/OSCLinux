"""Main OSCLinux application entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from osclinux.version import APP_NAME, APP_VERSION
from osclinux_updater import ReleaseUpdater, UpdateError

INSTALL_DIR = Path(__file__).resolve().parent


def _apply_pending_update() -> None:
    updater = ReleaseUpdater(APP_VERSION)
    try:
        if updater.apply_pending(install_dir=INSTALL_DIR):
            os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
    except UpdateError as exc:
        print(f"Mise à jour précédente non appliquée : {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Programme principal OSCLinux")
    parser.add_argument("--version", action="store_true", help="Afficher la version installée")
    args = parser.parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    _apply_pending_update()
    try:
        from PySide6.QtWidgets import QApplication
        from osclinux.window import MainWindow
    except ImportError:
        print(
            "PySide6 n'est pas installé. Active .venv puis lance : python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 2

    app = QApplication(sys.argv[:1])
    window = MainWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
