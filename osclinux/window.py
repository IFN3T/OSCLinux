"""OSCLinux control center GUI."""

from __future__ import annotations

import os
import shlex
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QMimeData, QObject, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from osclinux.module_store import ModuleStore, ModuleStoreError
from osclinux.providers import ModuleDataProvider
from osclinux.settings import DEFAULTS, SETTINGS_PATH, load_settings, save_settings
from osclinux.osc import OscClient, VRChatListener
from osclinux.version import APP_NAME, APP_VERSION

DARK_STYLE = """
QMainWindow { background: #0d1425; color: #dce7ff; font-family: 'Noto Sans', 'DejaVu Sans', sans-serif; font-size: 13px; }
QWidget { color: #dce7ff; font-family: 'Noto Sans', 'DejaVu Sans', sans-serif; font-size: 13px; }
QFrame#sidebar { background: #0a1120; border-right: 1px solid #1c2a45; }
QFrame#topbar { background: #0d1425; border-bottom: 1px solid #1c2a45; }
QFrame#panel, QFrame#moduleCard { background: #111c31; border: 1px solid #263a5b; border-radius: 10px; }
QFrame#moduleCard[moduleEnabled="true"] { border: 1px solid #426cf3; }
QLabel#title { font-size: 22px; font-weight: 700; color: #f2f6ff; }
QLabel#pageTitle { font-size: 20px; font-weight: 700; color: #ecf2ff; }
QLabel#muted { color: #8fa6ce; }
QLabel#icon { background: #1a2a47; border-radius: 20px; padding: 7px; font-size: 22px; }
QPushButton { background: #1a2944; border: 1px solid #2d4266; border-radius: 7px; padding: 9px 13px; color: #dce7ff; }
QPushButton:hover { background: #263a60; border-color: #587df7; }
QPushButton#primary { background: #334ff0; border: 1px solid #536bff; font-weight: 700; }
QPushButton#primary:hover { background: #4560ff; }
QPushButton#danger { color: #ff9eae; }
QPushButton#storeAdd { background: #16834f; border-color: #22b970; color: white; font-size: 22px; font-weight: 700; }
QPushButton#storeAdd:hover { background: #1ba862; }
QPushButton#storeRemove { background: #3a2033; color: #ff9eae; font-size: 22px; font-weight: 700; }
QPushButton#storeUpdate { background: #20365d; color: #8fb4ff; font-size: 20px; font-weight: 700; }
QPushButton#nav { text-align: left; padding: 12px 14px; background: transparent; border: 0; color: #b4c5e7; }
QPushButton#nav:checked { background: #344ff0; color: white; font-weight: 700; }
QPushButton#nav:hover:!checked { background: #15233c; }
QLineEdit, QComboBox, QSpinBox, QTextEdit, QListWidget { background: #0c172a; border: 1px solid #293d60; border-radius: 6px; padding: 8px; selection-background-color: #344ff0; }
QComboBox::drop-down { border: 0; width: 24px; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator { border: 1px solid #50668c; border-radius: 4px; background: #111c31; }
QCheckBox::indicator:checked { background: #405bfa; border-color: #7387ff; }
QRadioButton::indicator { border: 1px solid #50668c; border-radius: 8px; background: #111c31; }
QRadioButton::indicator:checked { background: #526aff; border: 4px solid #b8c4ff; }
QScrollArea { border: 0; background: #0d1425; }
QStackedWidget { background: #0d1425; }
QScrollArea > QWidget { background: #0d1425; }
QAbstractScrollArea::viewport { background: #0d1425; }
QListWidget#timelineSources::item { background: #111c31; border: 1px solid #263a5b; border-radius: 8px; margin: 4px; padding: 8px; }
QListWidget#timelineSources::item:selected { background: #1b3157; border-color: #5974ff; }
QLabel { background: transparent; }
QTextEdit { color: #9db5dd; }
QStatusBar { color: #8fa6ce; border-top: 1px solid #1c2a45; }
QSlider::groove:horizontal { height: 5px; background: #283a5a; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: #5974ff; }
"""


class StatusBridge(QObject):
    packet = Signal(float)


class StoreBridge(QObject):
    completed = Signal(str, object, str)


class ModuleSourceList(QListWidget):
    def mimeData(self, items):
        mime = super().mimeData(items)
        if items:
            mime.setText(str(items[0].data(Qt.ItemDataRole.UserRole)))
        return mime


class TimelineWidget(QWidget):
    sequenceChanged = Signal(object)
    moduleSelected = Signal(str)

    def __init__(self, sequence: list[dict], names: dict[str, str], parent=None):
        super().__init__(parent)
        self.sequence = [dict(item) for item in sequence]
        self.names = names
        self.selected_id = ""
        self.drag_index = -1
        self.resize_index = -1
        self.press_x = 0
        self.setAcceptDrops(True)
        self.setMinimumHeight(145)
        self.setMouseTracking(True)
        self._update_width()

    def set_data(self, sequence: list[dict], names: dict[str, str]):
        self.sequence = [dict(item) for item in sequence]
        self.names = names
        self._update_width()
        self.update()

    def _update_width(self):
        total = sum(int(item.get("duration", 10)) for item in self.sequence)
        self.setMinimumWidth(max(900, 90 + total * 12))

    def _positions(self):
        x = 54
        result = []
        for item in self.sequence:
            width = max(24, int(item.get("duration", 10)) * 12)
            result.append((x, width))
            x += width
        return result

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0d1425"))
        positions = self._positions()
        total = sum(int(item.get("duration", 10)) for item in self.sequence)
        painter.setPen(QColor("#8fa6ce"))
        for second in range(0, total + 11, 5):
            x = 54 + second * 12
            painter.drawLine(x, 25, x, 43)
            painter.drawText(x - 12, 18, f"{second}s")
        painter.setPen(QColor("#263a5b"))
        painter.drawLine(54, 42, max(70, 54 + total * 12), 42)
        colors = ["#263d70", "#1c5360", "#593664", "#61501f", "#244e3b"]
        for index, (item, (x, width)) in enumerate(zip(self.sequence, positions)):
            selected = item["id"] == self.selected_id
            painter.setBrush(QColor(colors[index % len(colors)]))
            painter.setPen(QColor("#718eff") if selected else QColor("#3b5685"))
            painter.drawRoundedRect(x, 54, width - 4, 58, 7, 7)
            painter.setPen(QColor("#f2f6ff"))
            name = self.names.get(item["id"], item["id"])
            painter.drawText(x + 9, 78, painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, max(20, width - 25)))
            painter.setPen(QColor("#b8c8e6"))
            painter.drawText(x + 9, 99, f'{item.get("duration", 10)} s')
            painter.setPen(QColor("#91a8ce"))
            painter.drawLine(x + width - 7, 59, x + width - 7, 106)
        if not self.sequence:
            painter.setPen(QColor("#8fa6ce"))
            painter.drawText(54, 83, "Glissez ici les modules à planifier.")

    def _index_at(self, x):
        for index, (left, width) in enumerate(self._positions()):
            if left <= x <= left + width:
                return index
        return -1

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_x = int(event.position().x())
            self.drag_index = self._index_at(self.press_x)
            if self.drag_index >= 0:
                left, width = self._positions()[self.drag_index]
                self.resize_index = self.drag_index if self.press_x >= left + width - 13 else -1
                self.selected_id = self.sequence[self.drag_index]["id"]
                self.moduleSelected.emit(self.selected_id)
                self.update()

    def mouseMoveEvent(self, event):
        if self.resize_index >= 0 and event.buttons() & Qt.MouseButton.LeftButton:
            left, _ = self._positions()[self.resize_index]
            duration = max(2, min(120, round((event.position().x() - left) / 12)))
            self.sequence[self.resize_index]["duration"] = duration
            self._update_width()
            self.update()
        elif self.drag_index >= 0 and event.buttons() & Qt.MouseButton.LeftButton:
            if abs(int(event.position().x()) - self.press_x) >= QApplication.startDragDistance():
                item = self.sequence[self.drag_index]
                drag = QDrag(self)
                mime = QMimeData()
                mime.setText(item["id"])
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.MoveAction)
                self.drag_index = -1

    def mouseReleaseEvent(self, event):
        if self.resize_index >= 0:
            self.resize_index = -1
            self.sequenceChanged.emit([dict(item) for item in self.sequence])
        self.drag_index = -1

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        module_id = event.mimeData().text().strip()
        if not module_id:
            return
        existing = next((index for index, item in enumerate(self.sequence) if item["id"] == module_id), -1)
        if existing >= 0:
            item = self.sequence.pop(existing)
        else:
            item = {"id": module_id, "duration": 10}
        x = int(event.position().x())
        insert_at = len(self.sequence)
        for index, (left, width) in enumerate(self._positions()):
            if x < left + width // 2:
                insert_at = index
                break
        self.sequence.insert(insert_at, item)
        self.selected_id = module_id
        self._update_width()
        self.update()
        self.sequenceChanged.emit([dict(item) for item in self.sequence])
        self.moduleSelected.emit(module_id)
        event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.providers = ModuleDataProvider()
        self.osc = OscClient()
        self.listener: VRChatListener | None = None
        self.bridge = StatusBridge()
        self.bridge.packet.connect(self._heard_vrchat)
        self.running = False
        self.active_index = 0
        self.last_heard = 0.0
        self.log_lines: list[str] = []
        self.settings.setdefault("module_options", {})
        self.settings.setdefault("order", [])
        self.store = ModuleStore()
        self.catalog: list[dict] = []
        self._catalog_by_id: dict[str, dict] = {}
        self._pending_modules: set[str] = set()
        self.store_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="osclinux-store")
        self.store_bridge = StoreBridge()
        self.store_bridge.completed.connect(self._store_completed)
        self.nav_buttons: list[QPushButton] = []
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumSize(1120, 740)
        self.resize(1540, 980)
        self.setStyleSheet(DARK_STYLE)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_preview)
        self.refresh_timer.start(1000)
        self.cycle_timer = QTimer(self)
        self.cycle_timer.setSingleShot(True)
        self.cycle_timer.timeout.connect(self._send_next)
        self._build_ui()
        self.refresh_preview()
        self._append_log("OSCLinux est prêt. Aucun module n’est installé par défaut.")
        QTimer.singleShot(100, self.refresh_catalog)
        if self.settings["osc"].get("startup"):
            self._set_autostart(True, quiet=True)

    def _build_ui(self) -> None:
        root = QWidget()
        horizontal = QHBoxLayout(root)
        horizontal.setContentsMargins(0, 0, 0, 0)
        horizontal.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 18, 14, 16)
        brand = QLabel("◉  OSCLinux")
        brand.setObjectName("title")
        side.addWidget(brand)
        subtitle = QLabel("OSC Manager · Modules")
        subtitle.setObjectName("muted")
        side.addWidget(subtitle)
        side.addSpacing(22)
        nav_group = QButtonGroup(self)
        nav_group.setExclusive(True)
        for index, (text, icon) in enumerate([
            ("Modules", "▦"), ("Règle Temporelle", "◷"), ("Configuration OSC", "◉"), ("Apparence", "◈"),
            ("Paramètres généraux", "⚙"), ("Journal", "▤"),
        ]):
            button = QPushButton(f"{icon}   {text}")
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _checked=False, i=index: self.pages.setCurrentIndex(i))
            nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            side.addWidget(button)
        side.addStretch(1)
        brand_card = QFrame()
        brand_card.setObjectName("panel")
        bc = QVBoxLayout(brand_card)
        bc.addWidget(QLabel("VRCHAT OSC MANAGER"))
        bc.addWidget(QLabel(f"Version {APP_VERSION}"))
        bc.addWidget(QLabel("Linux · Session locale"))
        side.addWidget(brand_card)

        main_area = QWidget()
        main_v = QVBoxLayout(main_area)
        main_v.setContentsMargins(0, 0, 0, 0)
        main_v.setSpacing(0)
        topbar = QFrame()
        topbar.setObjectName("topbar")
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(20, 12, 20, 12)
        self.vrchat_state = QLabel("●  VRChat : non détecté")
        self.vrchat_state.setObjectName("muted")
        self.script_state = QLabel("●  Script : arrêté")
        self.script_state.setObjectName("muted")
        self.run_button = QPushButton("▶  Démarrer")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.toggle_script)
        top_layout.addStretch(1)
        top_layout.addWidget(self.vrchat_state)
        top_layout.addSpacing(18)
        top_layout.addWidget(self.script_state)
        top_layout.addSpacing(18)
        top_layout.addWidget(self.run_button)
        main_v.addWidget(topbar)

        self.pages = QStackedWidget()
        self.pages.setAutoFillBackground(True)
        pages_palette = self.pages.palette()
        pages_palette.setColor(QPalette.ColorRole.Window, QColor("#0d1425"))
        self.pages.setPalette(pages_palette)
        self.pages.addWidget(self._modules_page())
        self.pages.addWidget(self._temporal_page())
        self.pages.addWidget(self._osc_page())
        self.pages.addWidget(self._appearance_page())
        self.pages.addWidget(self._general_page())
        self.pages.addWidget(self._journal_page())
        main_v.addWidget(self.pages, 1)
        self.statusBar().showMessage(f"Configuration : {SETTINGS_PATH}")


        footer = QFrame()
        footer.setObjectName("topbar")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 10, 16, 10)
        reset = QPushButton("↺  Réinitialiser")
        reset.clicked.connect(self.reset_settings)
        save = QPushButton("▣  Enregistrer")
        save.setObjectName("primary")
        save.clicked.connect(self.save_all)
        quit_button = QPushButton("✕  Quitter")
        quit_button.clicked.connect(self.close)
        footer_layout.addStretch(1)
        footer_layout.addWidget(reset)
        footer_layout.addWidget(save)
        footer_layout.addWidget(quit_button)
        main_v.addWidget(footer)
        horizontal.addWidget(sidebar)
        horizontal.addWidget(main_area, 1)
        self.setCentralWidget(root)

    def _page_header(self, title: str, description: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        desc = QLabel(description)
        desc.setObjectName("muted")
        layout.addWidget(title_label)
        layout.addWidget(desc)
        return layout

    def _modules_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(12)
        header = QHBoxLayout()
        header.addLayout(self._page_header("Modules", "Catalogue des modules disponibles. Installez uniquement ceux dont vous avez besoin."), 1)
        self.refresh_catalog_button = QPushButton("↻  Actualiser le catalogue")
        self.refresh_catalog_button.clicked.connect(self.refresh_catalog)
        header.addWidget(self.refresh_catalog_button, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)
        self.catalog_status = QLabel("Chargement du catalogue…")
        self.catalog_status.setObjectName("muted")
        outer.addWidget(self.catalog_status)
        self.catalog_panel = QFrame()
        self.catalog_panel.setObjectName("panel")
        self.catalog_layout = QVBoxLayout(self.catalog_panel)
        self.catalog_layout.setContentsMargins(12, 12, 12, 12)
        self.catalog_layout.setSpacing(8)
        outer.addWidget(self.catalog_panel, 1)
        return self._scroll(page)

    def refresh_catalog(self) -> None:
        if not hasattr(self, "refresh_catalog_button"):
            return
        self.refresh_catalog_button.setEnabled(False)
        self.catalog_status.setText("Récupération du catalogue des modules…")
        future = self.store_executor.submit(self.store.fetch_catalog)
        def completed(result) -> None:
            try:
                catalog, online = result.result()
                self.store_bridge.completed.emit("catalog", (catalog, online), "")
            except Exception as exc:
                self.store_bridge.completed.emit("catalog", None, str(exc))
        future.add_done_callback(completed)

    def _render_catalog(self) -> None:
        while self.catalog_layout.count():
            item = self.catalog_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        installed = self.store.installed_versions()
        if not self.catalog:
            empty = QLabel("Aucun module disponible dans le catalogue.")
            empty.setObjectName("muted")
            self.catalog_layout.addWidget(empty)
        for entry in self.catalog:
            module_id = entry["id"]
            row = QFrame()
            row.setObjectName("moduleCard")
            row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(14, 10, 12, 10)
            row_layout.setSpacing(14)
            info = QVBoxLayout()
            name = QLabel(entry["name"])
            name.setStyleSheet("font-size:15px;font-weight:700")
            description = QLabel(entry["description"])
            description.setObjectName("muted")
            description.setWordWrap(True)
            metadata = QLabel(f"Version {entry['version']}  ·  Auteur : {entry['author']}")
            metadata.setObjectName("muted")
            info.addWidget(name)
            info.addWidget(description)
            info.addWidget(metadata)
            row_layout.addLayout(info, 1)
            installed_version = installed.get(module_id)
            is_installed = installed_version is not None
            if module_id in self._pending_modules:
                pending = QPushButton("…")
                pending.setEnabled(False)
                row_layout.addWidget(pending)
            elif not is_installed:
                add = QPushButton("＋")
                add.setObjectName("storeAdd")
                add.setToolTip("Installer ce module")
                add.setFixedSize(42, 40)
                add.clicked.connect(lambda _checked=False, mid=module_id: self._store_action("install", mid))
                row_layout.addWidget(add)
            else:
                remove = QPushButton("×")
                remove.setObjectName("storeRemove")
                remove.setToolTip("Désinstaller ce module")
                remove.setFixedSize(42, 40)
                remove.clicked.connect(lambda _checked=False, mid=module_id: self._store_action("uninstall", mid))
                manage = QPushButton("⚙")
                manage.setToolTip("Gérer les paramètres du module")
                manage.setFixedSize(42, 40)
                manage.clicked.connect(lambda _checked=False, item=entry: self._manage_module(item))
                row_layout.addWidget(remove)
                row_layout.addWidget(manage)
                if self._version_newer(entry["version"], installed_version):
                    update = QPushButton("⬆")
                    update.setObjectName("storeUpdate")
                    update.setToolTip(f"Mettre à jour depuis {installed_version}")
                    update.setFixedSize(42, 40)
                    update.clicked.connect(lambda _checked=False, mid=module_id: self._store_action("update", mid))
                    row_layout.addWidget(update)
                else:
                    current = QLabel("Installé")
                    current.setStyleSheet("color:#20d889;font-weight:700")
                    row_layout.addWidget(current)
            self.catalog_layout.addWidget(row)
        self.catalog_layout.addStretch(1)
        self._fill_order_list()

    def _store_action(self, operation: str, module_id: str) -> None:
        if module_id in self._pending_modules:
            return
        if operation == "uninstall":
            answer = QMessageBox.question(self, "Désinstaller le module", f"Retirer « {self._catalog_by_id[module_id]['name']} » ?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        entry = self._catalog_by_id[module_id]
        self._pending_modules.add(module_id)
        if operation == "update":
            self.catalog_status.setText(f"Téléchargement de la mise à jour de {entry['name']} vers {entry['version']}…")
        elif operation == "install":
            self.catalog_status.setText(f"Installation de {entry['name']}…")
        else:
            self.catalog_status.setText(f"Désinstallation de {entry['name']}…")
        self._render_catalog()
        future = self.store_executor.submit(self._perform_store_action, operation, entry)
        def completed(result) -> None:
            try:
                result.result()
                self.store_bridge.completed.emit(f"{operation}:{module_id}", True, "")
            except Exception as exc:
                self.store_bridge.completed.emit(f"{operation}:{module_id}", None, str(exc))
        future.add_done_callback(completed)

    def _perform_store_action(self, operation: str, entry: dict) -> None:
        if operation == "install":
            self.store.install(entry)
        elif operation == "update":
            self.store.update(entry)
        elif operation == "uninstall":
            self.store.uninstall(entry["id"])
        else:
            raise ModuleStoreError("Action de module inconnue.")

    def _store_completed(self, operation: str, result: object, error: str) -> None:
        if operation == "catalog":
            self.refresh_catalog_button.setEnabled(True)
            if error:
                self.catalog_status.setText(f"Catalogue indisponible : {error}")
                self._append_log(f"Catalogue de modules indisponible : {error}")
                return
            self.catalog, online = result
            self._catalog_by_id = {entry["id"]: entry for entry in self.catalog}
            self._ensure_timeline()
            source = "en ligne" if online else "local (hors connexion)"
            self.catalog_status.setText(f"{len(self.catalog)} modules disponibles · catalogue {source} · aucun module préinstallé")
            self._render_catalog()
            self._append_log(f"Catalogue chargé ({source}, {len(self.catalog)} modules).")
            return
        action, module_id = operation.split(":", 1)
        self._pending_modules.discard(module_id)
        if error:
            name = self._catalog_by_id.get(module_id, {}).get("name", module_id)
            self.catalog_status.setText(f"Échec de {action} pour {name} : {error}")
            self._append_log(f"Erreur {action} {module_id} : {error}")
            self._render_catalog()
            QMessageBox.warning(
                self,
                "Mise à jour impossible" if action == "update" else "Action impossible",
                f"{name} n’a pas pu être traité.\\n\\nDétail : {error}",
            )
            return
        if action == "install":
            entry = self._catalog_by_id[module_id]
            options = {setting["key"]: setting.get("default", "") for setting in entry.get("settings", [])}
            options.update({"enabled": True, "interval": 10})
            self.settings["module_options"][module_id] = options
            self.settings.setdefault("timeline", []).append({"id": module_id, "duration": 10})
            self.settings.setdefault("order", []).append(module_id)
            self._append_log(f"Module {entry['name']} installé ({entry['version']}).")
        elif action == "uninstall":
            self.settings["module_options"].pop(module_id, None)
            self.settings["timeline"] = [item for item in self.settings.get("timeline", []) if item.get("id") != module_id]
            self.settings["order"] = [item for item in self.settings.get("order", []) if item != module_id]
            self._append_log(f"Module {self._catalog_by_id[module_id]['name']} désinstallé.")
        elif action == "update":
            entry = self._catalog_by_id[module_id]
            self.catalog_status.setText(f"{entry['name']} mis à jour vers la version {entry['version']}.")
            self._append_log(f"Module {entry['name']} mis à jour vers la version {entry['version']}.")
            QMessageBox.information(
                self,
                "Mise à jour terminée",
                f"{entry['name']} est maintenant en version {entry['version']}.",
            )
        self._ensure_timeline()
        self.save_all()
        self._render_catalog()

    def _manage_module(self, entry: dict) -> None:
        module_id = entry["id"]
        options = dict(self.settings["module_options"].get(module_id, {}))
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Paramètres · {entry['name']}")
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        enabled = QCheckBox("Module actif dans l’alternance")
        enabled.setChecked(bool(options.get("enabled", False)))
        form.addRow("État", enabled)
        controls: dict[str, QWidget] = {}
        for setting in entry.get("settings", []):
            key = setting["key"]
            kind = setting["type"]
            value = options.get(key, setting.get("default", ""))
            if kind == "boolean":
                control = QCheckBox()
                control.setChecked(bool(value))
            elif kind == "choice":
                control = QComboBox()
                control.addItems([str(choice) for choice in setting["choices"]])
                control.setCurrentText(str(value))
            elif kind == "number":
                control = self._spin(int(value), int(setting.get("min", 0)), int(setting.get("max", 100)))
            else:
                control = QLineEdit(str(value))
            controls[key] = control
            form.addRow(setting["label"], control)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options["enabled"] = enabled.isChecked()
        for key, control in controls.items():
            if isinstance(control, QCheckBox):
                options[key] = control.isChecked()
            elif isinstance(control, QComboBox):
                options[key] = control.currentText()
            elif isinstance(control, QSpinBox):
                options[key] = control.value()
            elif isinstance(control, QLineEdit):
                options[key] = control.text()
        self.settings["module_options"][module_id] = options
        self.save_all()
        self._show_timeline_summary(module_id)
        self._append_log(f"Paramètres du module {entry['name']} enregistrés.")
    @staticmethod
    def _version_newer(candidate: str, current: str) -> bool:
        def parts(value: str) -> tuple[int, ...]:
            try:
                return tuple(int(part) for part in value.removeprefix("v").split("."))
            except ValueError:
                return (0,)
        return parts(candidate) > parts(current)

    def _osc_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.addLayout(self._page_header("Configuration OSC", "Paramètres réseau utilisés pour envoyer les messages à VRChat."))
        panel = QFrame()
        panel.setObjectName("panel")
        form = QVBoxLayout(panel)
        form.addWidget(self._section_title("Connexion VRChat", "VRChat reçoit les messages OSC sur son port entrant."))
        host = QLineEdit(str(self.settings["osc"].get("host", "127.0.0.1")))
        port = self._spin(self.settings["osc"].get("port", 9000), 1, 65535, "")
        receive = self._spin(self.settings["osc"].get("receive_port", 9001), 1, 65535, "")
        form.addWidget(self._field("Adresse IP de destination", host))
        form.addWidget(self._field("Port sortant VRChat", port))
        form.addWidget(self._field("Port entrant VRChat", receive))
        send_test = QPushButton("Envoyer un message de test")
        send_test.clicked.connect(lambda: self._send_test(host.text(), port.value()))
        form.addWidget(send_test)
        layout.addWidget(panel)
        layout.addStretch(1)
        self.host_edit_osc, self.port_osc, self.receive_port_spin = host, port, receive
        return page

    def _appearance_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.addLayout(self._page_header("Apparence", "Personnalisez l’aperçu et la présentation des messages."))
        panel = QFrame()
        panel.setObjectName("panel")
        form = QVBoxLayout(panel)
        form.addWidget(self._section_title("Style de l’application", "Le thème sombre est optimisé pour les longues sessions."))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Sombre", "Clair"])
        self.theme_combo.setCurrentText("Sombre" if self.settings["appearance"].get("theme", "dark") == "dark" else "Clair")
        self.theme_combo.currentTextChanged.connect(self._change_theme)
        form.addWidget(self._field("Thème", self.theme_combo))
        form.addWidget(QLabel("Limite VRChat : le texte de chatbox est limité à 144 caractères."))
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _general_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.addLayout(self._page_header("Paramètres généraux", "Options de démarrage, fréquence d’envoi et mode des modules."))
        panel = QFrame()
        panel.setObjectName("panel")
        form = QVBoxLayout(panel)
        self.general_interval = self._spin(self.settings["osc"].get("interval", 2), 1, 60)
        form.addWidget(self._field("Intervalle global de mise à jour (secondes)", self.general_interval))
        self.general_mode_group = QButtonGroup(self)
        self.general_mode_radios = {}
        for label, value in [("Un seul module", "single"), ("Alternance des modules", "alternate"), ("Tous en même temps", "all")]:
            radio = QRadioButton(label)
            radio.setProperty("mode", value)
            self.general_mode_group.addButton(radio)
            form.addWidget(radio)
            self.general_mode_radios[value] = radio
        self.general_mode_radios.get(self.settings["osc"].get("mode", "alternate"), self.general_mode_radios["alternate"]).setChecked(True)
        self.general_autostart = QCheckBox("Lancer OSCLinux au démarrage de la session")
        self.general_autostart.setChecked(bool(self.settings["osc"].get("startup", False)))
        form.addWidget(self.general_autostart)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _temporal_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        layout.addLayout(self._page_header(
            "Règle Temporelle",
            "Glissez les modules sur la règle, déplacez-les pour choisir l’ordre et étirez leur bord droit pour régler leur durée."
        ))
        available_panel = QFrame()
        available_panel.setObjectName("panel")
        available_layout = QVBoxLayout(available_panel)
        available_layout.addWidget(self._section_title("Modules disponibles", "Les modules installés peuvent être placés dans la séquence."))
        self.timeline_sources = ModuleSourceList()
        self.timeline_sources.setObjectName("timelineSources")
        self.timeline_sources.setGridSize(QSize(220, 125))
        self.timeline_sources.setMinimumHeight(135)
        self.timeline_sources.setMaximumHeight(270)
        self.timeline_sources.setViewMode(QListWidget.ViewMode.IconMode)
        self.timeline_sources.setFlow(QListWidget.Flow.LeftToRight)
        self.timeline_sources.setWrapping(True)
        self.timeline_sources.setMovement(QListWidget.Movement.Static)
        self.timeline_sources.setDragEnabled(True)
        self.timeline_sources.setMaximumHeight(105)
        available_layout.addWidget(self.timeline_sources)
        layout.addWidget(available_panel)

        timeline_panel = QFrame()
        timeline_panel.setObjectName("panel")
        timeline_layout = QVBoxLayout(timeline_panel)
        timeline_layout.addWidget(self._section_title("Séquence d’affichage", "La règle est graduée en secondes. Faites glisser les blocs pour changer leur ordre."))
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(False)
        self.timeline = TimelineWidget(self.settings.get("timeline") or [], {}, self)
        self.timeline_scroll.setWidget(self.timeline)
        timeline_layout.addWidget(self.timeline_scroll)
        layout.addWidget(timeline_panel)

        summary = QFrame()
        summary.setObjectName("panel")
        summary_layout = QVBoxLayout(summary)
        summary_layout.addWidget(self._section_title("Module sélectionné", "Résumé des informations et du contenu affiché dans la chatbox."))
        self.timeline_summary_title = QLabel("Sélectionnez un module dans la règle.")
        self.timeline_summary_title.setStyleSheet("font-size:16px;font-weight:700")
        self.timeline_summary_meta = QLabel("")
        self.timeline_summary_meta.setObjectName("muted")
        self.timeline_summary_description = QLabel("")
        self.timeline_summary_description.setWordWrap(True)
        self.timeline_summary_preview = QLabel("")
        self.timeline_summary_preview.setWordWrap(True)
        self.timeline_summary_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary_layout.addWidget(self.timeline_summary_title)
        summary_layout.addWidget(self.timeline_summary_meta)
        summary_layout.addWidget(self.timeline_summary_description)
        summary_layout.addWidget(self.timeline_summary_preview)
        layout.addWidget(summary, 1)

        self.timeline.sequenceChanged.connect(self._timeline_changed)
        self.timeline.moduleSelected.connect(self._show_timeline_summary)
        return self._scroll(page)

    def _ensure_timeline(self) -> None:
        installed = self.store.installed_versions()
        saved = self.settings.get("timeline")
        if not isinstance(saved, list):
            old_order = self.settings.get("order", [])
            saved = [
                {"id": module_id, "duration": self.settings.get("module_options", {}).get(module_id, {}).get("interval", 10)}
                for module_id in old_order
            ]
        normalized = []
        seen = set()
        for item in saved:
            if not isinstance(item, dict):
                continue
            module_id = item.get("id")
            if module_id not in installed or module_id in seen:
                continue
            try:
                duration = max(2, min(120, int(item.get("duration", 10))))
            except (TypeError, ValueError):
                duration = 10
            normalized.append({"id": module_id, "duration": duration})
            seen.add(module_id)
        normalized.extend({"id": mid, "duration": 10} for mid in installed if mid not in seen)
        self.settings["timeline"] = normalized
        self.settings["order"] = [item["id"] for item in normalized]
        self._refresh_timeline()

    def _refresh_timeline(self) -> None:
        if not hasattr(self, "timeline"):
            return
        installed = self.store.installed_versions()
        entries = {entry["id"]: entry for entry in self.catalog}
        self.timeline_sources.clear()
        for module_id, version in installed.items():
            entry = entries.get(module_id, {})
            item = QListWidgetItem(f'{entry.get("name", module_id)}\n{version}')
            item.setData(Qt.ItemDataRole.UserRole, module_id)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setToolTip("Glissez ce module dans la règle temporelle.")
            self.timeline_sources.addItem(item)
        names = {mid: entries.get(mid, {}).get("name", mid) for mid in installed}
        self.timeline.set_data(self.settings.get("timeline", []), names)
        if self.timeline.selected_id:
            self._show_timeline_summary(self.timeline.selected_id)

    def _timeline_changed(self, sequence: list) -> None:
        self.settings["timeline"] = [dict(item) for item in sequence]
        self.settings["order"] = [item["id"] for item in sequence]
        self.save_all()
        self._refresh_timeline()

    def _show_timeline_summary(self, module_id: str) -> None:
        entry = self._catalog_by_id.get(module_id, {})
        version = self.store.installed_versions().get(module_id, "—")
        item = next((part for part in self.settings.get("timeline", []) if part["id"] == module_id), None)
        duration = f'{item["duration"]} s dans la séquence' if item else "Non planifié"
        options = self.settings.get("module_options", {}).get(module_id, {})
        status = "Actif" if options.get("enabled", False) else "Inactif"
        self.timeline_summary_title.setText(entry.get("name", module_id))
        self.timeline_summary_meta.setText(f'Version {version} · Auteur : {entry.get("author", "—")} · {duration} · {status}')
        self.timeline_summary_description.setText(entry.get("description", "Description non disponible."))
        preview = self.providers.get(module_id, options, lambda: self.store.load_text(module_id, options))
        self.timeline_summary_preview.setText(f"Affichage prévu : {preview}")


    def _journal_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.addLayout(self._page_header("Journal", "État du programme, du réseau OSC et des modules."))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        clear = QPushButton("Effacer le journal")
        clear.clicked.connect(lambda: self.log_view.clear())
        layout.addWidget(self.log_view, 1)
        layout.addWidget(clear, 0, Qt.AlignmentFlag.AlignRight)
        return page

    def _section_title(self, title: str, subtitle: str) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 6)
        label = QLabel(title)
        label.setStyleSheet("font-size:15px;font-weight:700")
        hint = QLabel(subtitle)
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(hint)
        return container

    def _field(self, label: str, widget: QWidget) -> QWidget:
        field = QWidget()
        layout = QVBoxLayout(field)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)
        caption = QLabel(label)
        caption.setObjectName("muted")
        layout.addWidget(caption)
        layout.addWidget(widget)
        return field

    def _spin(self, value: int, minimum: int, maximum: int, suffix: str = " s") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(int(value))
        spin.setSuffix(suffix)
        return spin

    def _combo_spin(self, spin: QSpinBox) -> QWidget:
        return spin

    def _scroll(self, widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        scroll.setStyleSheet(
            "QScrollArea { background-color: #0d1425; border: 0; } "
            "QScrollArea::viewport { background-color: #0d1425; }"
        )
        widget.setStyleSheet("background-color: #0d1425;")
        scroll.viewport().setStyleSheet("background-color: #0d1425;")
        palette = scroll.viewport().palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#0d1425"))
        scroll.viewport().setPalette(palette)
        scroll.viewport().setAutoFillBackground(True)
        return scroll

    def _fill_order_list(self) -> None:
        self._ensure_timeline()
    def _move_order(self, delta: int) -> None:
        index = self.order_list.currentRow()
        target = index + delta
        if index < 0 or not (0 <= target < self.order_list.count()):
            return
        item = self.order_list.takeItem(index)
        self.order_list.insertItem(target, item)
        self.order_list.setCurrentRow(target)
        if hasattr(self, "timeline"):
            self.settings["timeline"] = [dict(item) for item in self.timeline.sequence]
            self.settings["order"] = [item["id"] for item in self.timeline.sequence]
        self._append_log("Ordre des modules modifié.")

    def _collect_settings(self) -> None:
        host = getattr(self, "host_edit", None)
        port = getattr(self, "port_spin", None)
        if host:
            self.settings["osc"]["host"] = host.text().strip() or "127.0.0.1"
            self.settings["osc"]["port"] = port.value()
        if hasattr(self, "host_edit_osc"):
            self.settings["osc"]["host"] = self.host_edit_osc.text().strip() or "127.0.0.1"
            self.settings["osc"]["port"] = self.port_osc.value()
            self.settings["osc"]["receive_port"] = self.receive_port_spin.value()
        interval = getattr(self, "interval_spin", None)
        if interval:
            self.settings["osc"]["interval"] = interval.value()
        if hasattr(self, "general_interval"):
            self.settings["osc"]["interval"] = self.general_interval.value()
        mode = self.mode_group.checkedButton() if hasattr(self, "mode_group") else None
        if hasattr(self, "general_mode_group") and self.general_mode_group.checkedButton():
            mode = self.general_mode_group.checkedButton()
        if mode:
            self.settings["osc"]["mode"] = mode.property("mode")
        startup = getattr(self, "autostart_check", None)
        if startup:
            self.settings["osc"]["startup"] = startup.isChecked()
        if hasattr(self, "general_autostart"):
            self.settings["osc"]["startup"] = self.general_autostart.isChecked()
        if hasattr(self, "order_list"):
            self.settings["order"] = [self.order_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.order_list.count())]
        if hasattr(self, "theme_combo"):
            self.settings["appearance"]["theme"] = "dark" if self.theme_combo.currentText() == "Sombre" else "light"

    def save_all(self) -> None:
        self._collect_settings()
        try:
            save_settings(self.settings)
            self._set_autostart(bool(self.settings["osc"].get("startup")), quiet=True)
            self._append_log("Configuration enregistrée.")
            self.statusBar().showMessage(f"Configuration enregistrée dans {SETTINGS_PATH}", 5000)
        except OSError as exc:
            QMessageBox.critical(self, "Enregistrement impossible", str(exc))

    def reset_settings(self) -> None:
        answer = QMessageBox.question(self, "Réinitialiser", "Restaurer les paramètres par défaut ?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        save_settings(DEFAULTS)
        QMessageBox.information(self, "Paramètres réinitialisés", "Relancez OSCLinux pour charger les valeurs par défaut.")

    def _set_autostart(self, enabled: bool, quiet: bool = False) -> None:
        path = Path.home() / ".config" / "autostart" / "osclinux.desktop"
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            executable = sys.executable
            app_path = Path(__file__).resolve().parent.parent / "OSCLinux.py"
            path.write_text(
                "[Desktop Entry]\nType=Application\nName=OSCLinux\n"
                f"Exec={shlex.quote(executable)} {shlex.quote(str(app_path))}\n"
                "Terminal=false\nX-GNOME-Autostart-enabled=true\n",
                encoding="utf-8",
            )
        else:
            path.unlink(missing_ok=True)
        if not quiet:
            self._append_log("Démarrage automatique activé." if enabled else "Démarrage automatique désactivé.")

    def _change_theme(self, theme: str) -> None:
        # The dark palette follows the supplied concept; light mode is a softer neutral palette.
        self.setStyleSheet(DARK_STYLE if theme == "Sombre" else DARK_STYLE.replace("#0d1425", "#e9eef7").replace("#0a1120", "#dfe6f1").replace("#111c31", "#f5f7fb").replace("#0c172a", "#ffffff").replace("#dce7ff", "#17243b").replace("#f2f6ff", "#101a30").replace("#ecf2ff", "#101a30").replace("#8fa6ce", "#526580").replace("#b4c5e7", "#263957"))

    def refresh_preview(self) -> None:
        if hasattr(self, "timeline") and self.timeline.selected_id:
            self._show_timeline_summary(self.timeline.selected_id)
        if self.last_heard and time.monotonic() - self.last_heard < 10:
            self.vrchat_state.setText("●  VRChat : détecté")
            self.vrchat_state.setStyleSheet("color:#20d889")
        else:
            self.vrchat_state.setText("●  VRChat : non détecté")
            self.vrchat_state.setStyleSheet("color:#8fa6ce")

    def toggle_script(self) -> None:
        if self.running:
            self.running = False
            self.cycle_timer.stop()
            if self.listener:
                self.listener.stop()
                self.listener = None
            self.run_button.setText("▶  Démarrer")
            self.script_state.setText("●  Script : arrêté")
            self.script_state.setStyleSheet("color:#8fa6ce")
            self._append_log("Script OSC arrêté.")
            return
        self.save_all()
        if not self._active_modules():
            QMessageBox.warning(self, "Aucun module actif", "Activez au moins un module avant de démarrer le script.")
            return
        try:
            host = self.settings["osc"]["host"]
            port = int(self.settings["osc"]["port"])
            self.osc.send_chatbox("OSCLinux démarré", host, port, send_now=True)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Envoi OSC impossible", str(exc))
            return
        self.running = True
        self.run_button.setText("■  Arrêter")
        self.script_state.setText("●  Script : actif")
        self.script_state.setStyleSheet("color:#20d889")
        self._append_log(f"Script OSC démarré vers {host}:{port}.")
        receive_port = int(self.settings["osc"].get("receive_port", 9001))
        self.listener = VRChatListener(receive_port, self.bridge.packet.emit)
        self.listener.start()
        self._send_next()

    def _active_modules(self) -> list[str]:
        installed = self.store.installed_versions()
        options = self.settings.get("module_options", {})
        sequence = self.settings.get("timeline", [])
        ordered = [item["id"] for item in sequence if item.get("id") in installed]
        ordered.extend(module_id for module_id in installed if module_id not in ordered)
        return [module_id for module_id in ordered if options.get(module_id, {}).get("enabled", False)]
    def _module_text(self, module_id: str) -> str:
        options = self.settings.get("module_options", {}).get(module_id, {})
        return self.providers.get(module_id, options, lambda: self.store.load_text(module_id, options))

    def _module_duration(self, module_id: str) -> int:
        entry = next((item for item in self.settings.get("timeline", []) if item.get("id") == module_id), {})
        try:
            return max(2, min(120, int(entry.get("duration", 10))))
        except (TypeError, ValueError):
            return 10

    def _send_next(self) -> None:
        if not self.running:
            return
        active = self._active_modules()
        if not active:
            self.toggle_script()
            return
        mode = self.settings["osc"].get("mode", "alternate")
        options = self.settings.get("module_options", {})
        try:
            if mode == "single":
                module_id = active[0]
                text = self._module_text(module_id)
                interval = int(self._module_duration(module_id))
                if text == "Chargement…":
                    interval = 1
                else:
                    self._transmit(text, module_id)
            elif mode == "all":
                texts = [self._module_text(module_id) for module_id in active]
                ready = [item for item in texts if item and item != "Chargement…"]
                text = " · ".join(ready)
                interval = 1 if not ready else int(self.settings["osc"].get("interval", 2))
                if ready:
                    self._transmit(text, "tous les modules")
            else:
                self.active_index %= len(active)
                module_id = active[self.active_index]
                self.active_index = (self.active_index + 1) % len(active)
                text = self._module_text(module_id)
                interval = int(self._module_duration(module_id))
                if text == "Chargement…":
                    interval = 1
                else:
                    self._transmit(text, module_id)
        except Exception as exc:
            self._append_log(f"Erreur module : {exc}")
            interval = int(self.settings["osc"].get("interval", 2))
        self.cycle_timer.start(max(1, interval) * 1000)

    def _transmit(self, text: str, key: str) -> None:
        if not text:
            self._append_log(f"{self._module_name(key)} : aucun texte à envoyer.")
            return
        try:
            self.osc.send_chatbox(text, self.settings["osc"]["host"], int(self.settings["osc"]["port"]), send_now=True, notification=False)
            self._append_log(f"Envoyé ({self._module_name(key)}) : {text}")
        except (OSError, ValueError) as exc:
            self._append_log(f"Erreur OSC : {exc}")

    def _send_test(self, host: str, port: int) -> None:
        try:
            self.osc.send_chatbox("OSCLinux · test OSC", host.strip() or "127.0.0.1", int(port), send_now=True)
            self._append_log(f"Message de test envoyé à {host}:{port}.")
            QMessageBox.information(self, "Test envoyé", "Le message OSC a été envoyé.")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Échec du test", str(exc))

    def _heard_vrchat(self, moment: float) -> None:
        self.last_heard = moment

    def _append_log(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        self.log_lines.append(line)
        if hasattr(self, "log_view"):
            self.log_view.append(line)

    def _module_name(self, key: str) -> str:
        return self._catalog_by_id.get(key, {}).get("name", key)

    def closeEvent(self, event) -> None:
        if self.running:
            self.cycle_timer.stop()
            if self.listener:
                self.listener.stop()
        self.save_all()
        self.store_executor.shutdown(wait=False, cancel_futures=True)
        self.providers.close()
        self.osc.close()
        event.accept()
