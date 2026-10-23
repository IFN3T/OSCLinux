"""Main OSCLinux application entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from osclinux_updater import Release, ReleaseUpdater, UpdateError


APP_NAME = "OSCLinux"
APP_VERSION = "0.1.0"
INSTALL_DIR = Path(__file__).resolve().parent


def _make_updater() -> ReleaseUpdater:
    return ReleaseUpdater(APP_VERSION)


def _apply_pending_update(updater: ReleaseUpdater) -> None:
    """Apply an accepted update before importing the Qt application code."""
    try:
        if updater.apply_pending(install_dir=INSTALL_DIR):
            os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
    except UpdateError as exc:
        print(f"Mise à jour précédente non appliquée : {exc}", file=sys.stderr)


def _run_update_check(updater: ReleaseUpdater) -> int:
    try:
        release = updater.check()
    except UpdateError as exc:
        print(f"Vérification impossible : {exc}", file=sys.stderr)
        return 2
    if release is None:
        print(f"OSCLinux {APP_VERSION} : aucune mise à jour disponible.")
    else:
        print(f"Mise à jour disponible : {release.version} — {release.title}")
        if release.notes:
            print(release.notes)
    return 0


def _run_qt_app(updater: ReleaseUpdater) -> int:
    try:
        from PySide6.QtCore import QObject, QThread, QTimer, Signal
        from PySide6.QtWidgets import (
            QApplication,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        print(
            "PySide6 n'est pas installé. Utilise .venv : python3 -m venv .venv && "
            "source .venv/bin/activate && python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 2

    class UpdateWorker(QObject):
        succeeded = Signal(object)
        failed = Signal(str)
        finished = Signal()

        def __init__(self, operation: str, release: Release | None = None) -> None:
            super().__init__()
            self.operation = operation
            self.release = release

        def run(self) -> None:
            try:
                if self.operation == "check":
                    self.succeeded.emit(updater.check())
                elif self.operation == "download" and self.release is not None:
                    updater.queue(self.release)
                    self.succeeded.emit(self.release)
                else:
                    raise UpdateError("Opération de mise à jour inconnue.")
            except UpdateError as exc:
                self.failed.emit(str(exc))
            except Exception as exc:  # Keep unexpected worker errors out of the Qt event loop.
                self.failed.emit(f"Erreur inattendue : {exc}")
            finally:
                self.finished.emit()

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
            self.setMinimumSize(520, 280)
            self._threads: list[QThread] = []

            title = QLabel("OSCLinux")
            title.setStyleSheet("font-size: 24px; font-weight: 600;")
            description = QLabel(
                "Programme principal prêt. Les connexions Spotify et VRChat OSC "
                "seront ajoutées sous forme de modules."
            )
            description.setWordWrap(True)
            self.status = QLabel("Vérification des mises à jour au démarrage…")
            self.status.setWordWrap(True)

            self.check_button = QPushButton("Vérifier les mises à jour")
            self.check_button.clicked.connect(self.check_updates)
            version_label = QLabel(f"Version {APP_VERSION}")

            footer = QHBoxLayout()
            footer.addWidget(version_label)
            footer.addStretch(1)
            footer.addWidget(self.check_button)
            layout = QVBoxLayout()
            layout.addWidget(title)
            layout.addWidget(description)
            layout.addStretch(1)
            layout.addWidget(self.status)
            layout.addLayout(footer)

            container = QWidget()
            container.setLayout(layout)
            self.setCentralWidget(container)
            QTimer.singleShot(350, self.check_updates)

        def _start_worker(self, worker: UpdateWorker, success_handler) -> None:
            thread = QThread(self)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.succeeded.connect(success_handler)
            worker.failed.connect(self._show_update_error)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda: self._discard_thread(thread))
            self._threads.append(thread)
            thread.start()

        def _discard_thread(self, thread: QThread) -> None:
            if thread in self._threads:
                self._threads.remove(thread)

        def check_updates(self) -> None:
            self.check_button.setEnabled(False)
            self.status.setText("Vérification de la dernière release stable…")
            self._start_worker(UpdateWorker("check"), self._check_finished)

        def _check_finished(self, result: object) -> None:
            self.check_button.setEnabled(True)
            if result is None:
                self.status.setText(f"OSCLinux {APP_VERSION} est à jour.")
                return
            if not isinstance(result, Release):
                self._show_update_error("Réponse de mise à jour invalide.")
                return
            release = result
            self.status.setText(f"Version {release.version} disponible.")
            dialog = QMessageBox(self)
            dialog.setWindowTitle("Mise à jour disponible")
            dialog.setIcon(QMessageBox.Icon.Information)
            dialog.setText(f"OSCLinux {release.version} est disponible.")
            if release.notes:
                dialog.setInformativeText(release.notes[:6000])
            dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            dialog.button(QMessageBox.StandardButton.Yes).setText("Télécharger")
            dialog.button(QMessageBox.StandardButton.No).setText("Plus tard")
            if dialog.exec() == QMessageBox.StandardButton.Yes:
                self._queue_update(release)

        def _queue_update(self, release: Release) -> None:
            self.check_button.setEnabled(False)
            self.status.setText(f"Téléchargement et vérification de la version {release.version}…")
            self._start_worker(UpdateWorker("download", release), self._download_finished)

        def _download_finished(self, result: object) -> None:
            self.check_button.setEnabled(True)
            if not isinstance(result, Release):
                self._show_update_error("La mise à jour n'a pas pu être préparée.")
                return
            self.status.setText(f"Version {result.version} prête. Fermez puis relancez OSCLinux pour l'appliquer.")
            QMessageBox.information(
                self,
                "Mise à jour préparée",
                f"OSCLinux {result.version} a été téléchargé et vérifié.\n"
                "Fermez puis relancez l'application pour appliquer la mise à jour.",
            )

        def _show_update_error(self, message: str) -> None:
            self.check_button.setEnabled(True)
            self.status.setText(f"Mise à jour indisponible : {message}")

    app = QApplication(sys.argv[:1])
    window = MainWindow()
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Programme principal OSCLinux")
    parser.add_argument("--version", action="store_true", help="Afficher la version installée")
    parser.add_argument("--check-updates", action="store_true", help="Vérifier les releases GitHub puis quitter")
    args = parser.parse_args(argv)

    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0

    updater = _make_updater()
    _apply_pending_update(updater)
    if args.check_updates:
        return _run_update_check(updater)
    return _run_qt_app(updater)


if __name__ == "__main__":
    raise SystemExit(main())
