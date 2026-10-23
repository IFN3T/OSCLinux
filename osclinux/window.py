"""OSCLinux control center GUI."""

from __future__ import annotations

import os
import shlex
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
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

from osclinux.providers import ModuleDataProvider, WeatherProvider
from osclinux.settings import DEFAULTS, SETTINGS_PATH, load_settings, save_settings
from osclinux.osc import OscClient, VRChatListener
from osclinux.version import APP_NAME, APP_VERSION

MODULES = [
    ("spotify", "Spotify", "Titre, artiste et progression", "♫", "#1ed760"),
    ("system", "CPU / RAM / GPU", "Utilisation des ressources système", "▦", "#13b8e8"),
    ("temperatures", "Températures", "Températures du CPU et GPU", "♨", "#f04e89"),
    ("weather", "Météo", "Météo locale ou ville choisie", "☀", "#f6b928"),
    ("clock", "Horloge", "Heure et date", "◷", "#615cff"),
    ("custom", "Personnalisé", "Texte libre ou variables", "</>", "#368de7"),
]

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
QLabel { background: transparent; }
QTextEdit { color: #9db5dd; }
QStatusBar { color: #8fa6ce; border-top: 1px solid #1c2a45; }
QSlider::groove:horizontal { height: 5px; background: #283a5a; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: #5974ff; }
"""


class StatusBridge(QObject):
    packet = Signal(float)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.weather = WeatherProvider()
        self.providers = ModuleDataProvider(self.weather)
        self.osc = OscClient()
        self.listener: VRChatListener | None = None
        self.bridge = StatusBridge()
        self.bridge.packet.connect(self._heard_vrchat)
        self.running = False
        self.active_index = 0
        self.last_heard = 0.0
        self.log_lines: list[str] = []
        self.module_controls: dict[str, dict[str, QWidget]] = {}
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
        self._append_log("OSCLinux est prêt.")
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
            ("Modules", "▦"), ("Configuration OSC", "◉"), ("Apparence", "◈"),
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
        self.pages.addWidget(self._osc_page())
        self.pages.addWidget(self._appearance_page())
        self.pages.addWidget(self._general_page())
        self.pages.addWidget(self._journal_page())
        main_v.addWidget(self.pages, 1)
        self.statusBar().showMessage(f"Configuration : {SETTINGS_PATH}")
        self.host_edit.textChanged.connect(self.host_edit_osc.setText)
        self.host_edit_osc.textChanged.connect(self.host_edit.setText)
        self.port_spin.valueChanged.connect(self.port_osc.setValue)
        self.port_osc.valueChanged.connect(self.port_spin.setValue)
        self.interval_spin.valueChanged.connect(self.general_interval.setValue)
        self.general_interval.valueChanged.connect(self.interval_spin.setValue)
        for mode, first in (("single", self.single_radio), ("alternate", self.alternate_radio), ("all", self.simultaneous_radio)):
            second = self.general_mode_radios[mode]
            first.toggled.connect(lambda checked, target=second: target.setChecked(True) if checked else None)
            second.toggled.connect(lambda checked, target=first: target.setChecked(True) if checked else None)
        self.autostart_check.toggled.connect(self.general_autostart.setChecked)
        self.general_autostart.toggled.connect(self.autostart_check.setChecked)

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
        header.addLayout(self._page_header("Modules", "Activez et personnalisez les informations à afficher dans la chatbox VRChat."), 1)
        outer.addLayout(header)

        upper = QHBoxLayout()
        upper.setSpacing(14)
        modules_panel = QFrame()
        modules_panel.setObjectName("panel")
        module_layout = QVBoxLayout(modules_panel)
        module_layout.setContentsMargins(12, 12, 12, 12)
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, entry in enumerate(MODULES):
            grid.addWidget(self._module_card(*entry), index // 3, index % 3)
        module_layout.addLayout(grid)
        upper.addWidget(modules_panel, 7)

        preview = QFrame()
        preview.setObjectName("panel")
        preview_layout = QVBoxLayout(preview)
        preview_layout.addWidget(self._section_title("Aperçu de la chatbox", "Exemple des informations envoyées à VRChat."))
        self.preview_cards: dict[str, QLabel] = {}
        for key, name, _subtitle, icon, color in MODULES[:4]:
            card = QFrame()
            card.setObjectName("moduleCard")
            row = QHBoxLayout(card)
            icon_label = QLabel(icon)
            icon_label.setStyleSheet(f"font-size:20px;color:{color};min-width:32px")
            content = QVBoxLayout()
            name_label = QLabel(name)
            name_label.setStyleSheet("font-weight:700")
            preview_text = QLabel("En attente…")
            preview_text.setObjectName("muted")
            preview_text.setWordWrap(True)
            content.addWidget(name_label)
            content.addWidget(preview_text)
            row.addWidget(icon_label)
            row.addLayout(content, 1)
            preview_layout.addWidget(card)
            self.preview_cards[key] = preview_text
        preview_layout.addStretch(1)
        preview_note = QLabel("L’affichage réel dépend des modules actifs et de l’ordre défini.")
        preview_note.setObjectName("muted")
        preview_note.setWordWrap(True)
        preview_layout.addWidget(preview_note)
        upper.addWidget(preview, 3)
        outer.addLayout(upper, 6)

        lower = QHBoxLayout()
        order_panel = QFrame()
        order_panel.setObjectName("panel")
        order = QVBoxLayout(order_panel)
        order.addWidget(self._section_title("Ordre d’affichage", "Définissez l’ordre des modules dans l’alternance."))
        self.order_list = QListWidget()
        self.order_list.setMaximumHeight(150)
        self._fill_order_list()
        order.addWidget(self.order_list)
        order_controls = QHBoxLayout()
        self.order_up = QPushButton("↑ Monter")
        self.order_down = QPushButton("↓ Descendre")
        self.order_up.clicked.connect(lambda: self._move_order(-1))
        self.order_down.clicked.connect(lambda: self._move_order(1))
        order_controls.addWidget(self.order_up)
        order_controls.addWidget(self.order_down)
        order.addLayout(order_controls)
        lower.addWidget(order_panel, 5)

        settings_panel = QFrame()
        settings_panel.setObjectName("panel")
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.addWidget(self._section_title("Paramètres généraux", "Configuration du script et de la communication OSC."))
        row = QHBoxLayout()
        self.host_edit = QLineEdit(str(self.settings["osc"].get("host", "127.0.0.1")))
        self.host_edit.setPlaceholderText("127.0.0.1")
        self.port_spin = self._spin(self.settings["osc"].get("port", 9000), 1, 65535, "")
        self.interval_spin = self._spin(self.settings["osc"].get("interval", 2), 1, 60)
        row.addWidget(self._field("Adresse OSC (VRChat)", self.host_edit))
        row.addWidget(self._field("Port", self.port_spin))
        row.addWidget(self._field("Intervalle", self.interval_spin))
        settings_layout.addLayout(row)
        mode_row = QHBoxLayout()
        self.single_radio = QRadioButton("Un seul module")
        self.alternate_radio = QRadioButton("Alternance des modules")
        self.simultaneous_radio = QRadioButton("Tous en même temps")
        self.mode_group = QButtonGroup(self)
        for radio, mode in [(self.single_radio, "single"), (self.alternate_radio, "alternate"), (self.simultaneous_radio, "all")]:
            self.mode_group.addButton(radio)
            radio.setProperty("mode", mode)
            mode_row.addWidget(radio)
        mode = self.settings["osc"].get("mode", "alternate")
        {"single": self.single_radio, "alternate": self.alternate_radio, "all": self.simultaneous_radio}.get(mode, self.alternate_radio).setChecked(True)
        settings_layout.addLayout(mode_row)
        self.autostart_check = QCheckBox("Lancer OSCLinux au démarrage de session")
        self.autostart_check.setChecked(bool(self.settings["osc"].get("startup", False)))
        settings_layout.addWidget(self.autostart_check)
        lower.addWidget(settings_panel, 6)
        outer.addLayout(lower, 4)
        return self._scroll(page)

    def _module_card(self, key: str, name: str, description: str, icon: str, color: str) -> QFrame:
        card = QFrame()
        card.setObjectName("moduleCard")
        card.setProperty("moduleEnabled", bool(self.settings["modules"][key].get("enabled", False)))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        top = QHBoxLayout()
        icon_label = QLabel(icon)
        icon_label.setObjectName("icon")
        icon_label.setStyleSheet(f"color:{color};min-width:32px;max-width:32px;min-height:32px;max-height:32px")
        labels = QVBoxLayout()
        module_title = QLabel(name)
        module_title.setStyleSheet("font-weight:700;font-size:14px")
        desc = QLabel(description)
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        labels.addWidget(module_title)
        labels.addWidget(desc)
        enabled = QCheckBox("Actif")
        enabled.setChecked(bool(self.settings["modules"][key].get("enabled", False)))
        enabled.toggled.connect(lambda value, k=key, c=card: self._module_enabled(k, c, value))
        top.addWidget(icon_label)
        top.addLayout(labels, 1)
        top.addWidget(enabled)
        layout.addLayout(top)
        interval = self._spin(self.settings["modules"][key].get("interval", 10), 2, 120)
        self.module_controls[key] = {"enabled": enabled, "interval": interval}
        layout.addWidget(self._field("Temps d’affichage", self._combo_spin(interval)))
        if key == "spotify":
            formatting = QComboBox()
            formatting.addItems(["Titre + Artiste + Progression", "Titre + Artiste", "Artiste + Titre"])
            formatting.setCurrentText(self.settings["modules"][key].get("format", "Titre + Artiste + Progression"))
            hide = QCheckBox("Masquer si pause")
            hide.setChecked(bool(self.settings["modules"][key].get("hide_paused", True)))
            layout.addWidget(self._field("Format", formatting))
            layout.addWidget(hide)
            self.module_controls[key].update(format=formatting, hide_paused=hide)
        elif key in ("system", "temperatures"):
            checks = QHBoxLayout()
            fields = ("cpu", "ram", "gpu") if key == "system" else ("cpu", "gpu", "other")
            for field in fields:
                check = QCheckBox(field.upper() if field != "other" else "Autres")
                check.setChecked(bool(self.settings["modules"][key].get(field, field != "other")))
                checks.addWidget(check)
                self.module_controls[key][field] = check
            layout.addWidget(QLabel("Éléments à afficher"))
            layout.addLayout(checks)
        elif key == "weather":
            city = QLineEdit(str(self.settings["modules"][key].get("city", "Paris")))
            unit = QComboBox()
            unit.addItems(["°C", "°F"])
            unit.setCurrentText(str(self.settings["modules"][key].get("unit", "°C")))
            layout.addWidget(self._field("Ville", city))
            layout.addWidget(self._field("Unités", unit))
            self.module_controls[key].update(city=city, unit=unit)
        elif key == "clock":
            clock_format = QComboBox()
            clock_format.addItems(["24h", "12h"])
            clock_format.setCurrentText(self.settings["modules"][key].get("format", "24h"))
            layout.addWidget(self._field("Format", clock_format))
            self.module_controls[key]["format"] = clock_format
        elif key == "custom":
            message = QLineEdit(str(self.settings["modules"][key].get("message", "♫ Bonne journée !")))
            layout.addWidget(self._field("Message", message))
            self.module_controls[key]["message"] = message
        return card

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
        self.order_list.clear()
        order = self.settings.get("order", [entry[0] for entry in MODULES])
        by_key = {entry[0]: entry for entry in MODULES}
        for key in order:
            if key in by_key:
                entry = by_key[key]
                item = QListWidgetItem(f"{entry[3]}   {entry[1]}   ·   {self.settings['modules'][key].get('interval', 10)} s")
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.order_list.addItem(item)

    def _move_order(self, delta: int) -> None:
        index = self.order_list.currentRow()
        target = index + delta
        if index < 0 or not (0 <= target < self.order_list.count()):
            return
        item = self.order_list.takeItem(index)
        self.order_list.insertItem(target, item)
        self.order_list.setCurrentRow(target)
        self._append_log("Ordre des modules modifié.")

    def _module_enabled(self, key: str, card: QFrame, enabled: bool) -> None:
        card.setProperty("moduleEnabled", enabled)
        card.style().unpolish(card)
        card.style().polish(card)
        self.settings["modules"][key]["enabled"] = enabled

    def _collect_settings(self) -> None:
        modules = self.settings["modules"]
        for key, controls in self.module_controls.items():
            modules[key]["enabled"] = controls["enabled"].isChecked()
            modules[key]["interval"] = controls["interval"].value()
            for field, widget in controls.items():
                if field in ("enabled", "interval"):
                    continue
                if isinstance(widget, QCheckBox):
                    modules[key][field] = widget.isChecked()
                elif isinstance(widget, QComboBox):
                    modules[key][field] = widget.currentText()
                elif isinstance(widget, QLineEdit):
                    modules[key][field] = widget.text()
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
        for key, label in self.preview_cards.items():
            options = self.settings["modules"].get(key, {})
            if key in self.module_controls:
                options = self._options_for(key)
            try:
                label.setText(self.providers.get(key, options) or "En pause")
            except Exception as exc:
                label.setText(f"Indisponible : {exc}")
        if self.last_heard and time.monotonic() - self.last_heard < 10:
            self.vrchat_state.setText("●  VRChat : détecté")
            self.vrchat_state.setStyleSheet("color:#20d889")
        else:
            self.vrchat_state.setText("●  VRChat : non détecté")
            self.vrchat_state.setStyleSheet("color:#8fa6ce")

    def _options_for(self, key: str) -> dict:
        options = dict(self.settings["modules"].get(key, {}))
        controls = self.module_controls.get(key, {})
        for field, widget in controls.items():
            if field in ("enabled", "interval"):
                continue
            if isinstance(widget, QCheckBox):
                options[field] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                options[field] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                options[field] = widget.text()
        return options

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
        self._collect_settings()
        order = self.settings.get("order", [entry[0] for entry in MODULES])
        return [key for key in order if self.settings["modules"].get(key, {}).get("enabled")]

    def _send_next(self) -> None:
        if not self.running:
            return
        active = self._active_modules()
        if not active:
            self.toggle_script()
            return
        mode = self.settings["osc"].get("mode", "alternate")
        if mode == "single":
            key = active[0]
            text = self.providers.get(key, self._options_for(key))
            interval = int(self.settings["modules"][key].get("interval", 10))
            self._transmit(text, key)
        elif mode == "all":
            texts = [self.providers.get(key, self._options_for(key)) for key in active]
            text = " · ".join(item for item in texts if item)
            interval = int(self.settings["osc"].get("interval", 2))
            self._transmit(text, "tous les modules")
        else:
            self.active_index %= len(active)
            key = active[self.active_index]
            self.active_index = (self.active_index + 1) % len(active)
            text = self.providers.get(key, self._options_for(key))
            interval = int(self.settings["modules"][key].get("interval", 10))
            self._transmit(text, key)
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

    @staticmethod
    def _module_name(key: str) -> str:
        return next((entry[1] for entry in MODULES if entry[0] == key), key)

    def closeEvent(self, event) -> None:
        if self.running:
            self.cycle_timer.stop()
            if self.listener:
                self.listener.stop()
        self.save_all()
        self.providers.close()
        self.weather.close()
        self.osc.close()
        event.accept()
