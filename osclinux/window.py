"""OSCLinux control center GUI."""

from __future__ import annotations

import os
import re
import shutil
import shlex
import sys
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QImageReader, QMovie, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
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
from osclinux.theme_store import BASE_THEME_ID, LIGHT_THEME_ID, ThemeStore, ThemeStoreError
from osclinux.providers import ModuleDataProvider
from osclinux.settings import DEFAULTS, SETTINGS_PATH, load_settings, save_settings
from osclinux.osc import OscClient, VRChatListener
from osclinux.version import APP_NAME, APP_VERSION


def _theme_icon_pixmap(icon_id: str, icon_definitions=None, icon_visuals=None, size: int = 26, icon_assets=None) -> QPixmap:
    """Load a theme image icon, render bounded primitives, or use the built-in fallback."""
    asset_path = (icon_assets or {}).get(icon_id)
    if asset_path:
        image_icon = QPixmap(str(asset_path))
        if not image_icon.isNull():
            return image_icon.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scale = size / 32
    painter.scale(scale, scale)
    icon_visuals = icon_visuals or {}
    primary = QColor(icon_visuals.get("foreground_color", "#8fb4ff"))
    secondary = QColor(icon_visuals.get("secondary_color", "#dce7ff"))
    stroke_width = float(icon_visuals.get("stroke_width", 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(primary, stroke_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

    definitions = (icon_definitions or {}).get(icon_id)
    if definitions:
        for shape in definitions:
            kind = shape["type"]
            if kind == "line":
                painter.setPen(QPen(QColor(shape["color"]), float(shape["width"]), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawLine(shape["x1"], shape["y1"], shape["x2"], shape["y2"])
                continue
            stroke = shape.get("stroke")
            painter.setPen(QPen(QColor(stroke), float(shape.get("stroke_width", 1))) if stroke else Qt.PenStyle.NoPen)
            painter.setBrush(QColor(shape["fill"]) if shape.get("fill") else Qt.BrushStyle.NoBrush)
            if kind == "rect":
                painter.drawRect(QRectF(shape["x"], shape["y"], shape["width"], shape["height"]))
            elif kind == "ellipse":
                painter.drawEllipse(QRectF(shape["x"], shape["y"], shape["width"], shape["height"]))
            elif kind == "polygon":
                path = QPainterPath()
                points = shape["points"]
                path.moveTo(points[0][0], points[0][1])
                for x, y in points[1:]:
                    path.lineTo(x, y)
                path.closeSubpath()
                painter.drawPath(path)
        painter.end()
        return pixmap

    if icon_id in {"modules", "cube"}:
        top = QPainterPath(); top.moveTo(16, 4); top.lineTo(27, 10); top.lineTo(16, 16); top.lineTo(5, 10); top.closeSubpath()
        left = QPainterPath(); left.moveTo(5, 10); left.lineTo(16, 16); left.lineTo(16, 28); left.lineTo(5, 22); left.closeSubpath()
        right = QPainterPath(); right.moveTo(27, 10); right.lineTo(16, 16); right.lineTo(16, 28); right.lineTo(27, 22); right.closeSubpath()
        painter.drawPath(top); painter.drawPath(left); painter.drawPath(right)
    elif icon_id in {"timeline", "clock"}:
        painter.drawEllipse(5, 5, 22, 22); painter.drawLine(16, 9, 16, 16); painter.drawLine(16, 16, 22, 19)
        painter.setBrush(secondary); painter.drawEllipse(14, 14, 4, 4)
    elif icon_id in {"osc", "network"}:
        painter.setPen(QPen(primary, stroke_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(8, 8, 24, 16); painter.drawLine(8, 24, 24, 16); painter.drawLine(8, 8, 8, 24)
        for x, y, color in ((8, 8, primary), (8, 24, secondary), (24, 16, primary)):
            painter.setBrush(color); painter.drawEllipse(x - 3, y - 3, 6, 6)
    elif icon_id in {"themes", "palette"}:
        painter.drawEllipse(5, 5, 22, 22)
        for x, y, color in ((11, 11, secondary), (20, 10, primary), (11, 20, primary), (20, 20, secondary)):
            painter.setBrush(color); painter.drawEllipse(x - 2, y - 2, 4, 4)
    elif icon_id in {"settings", "gear"}:
        painter.drawEllipse(10, 10, 12, 12); painter.setBrush(primary); painter.drawEllipse(14, 14, 4, 4)
        for angle in range(0, 360, 45):
            painter.save(); painter.translate(16, 16); painter.rotate(angle); painter.drawLine(0, -8, 0, -12); painter.restore()
    elif icon_id in {"journal", "log"}:
        painter.drawRoundedRect(7, 4, 19, 24, 2, 2)
        for y in (11, 16, 21): painter.drawLine(12, y, 22, y)
        painter.setBrush(secondary); painter.drawEllipse(4, 8, 4, 4); painter.drawEllipse(4, 17, 4, 4)
    elif icon_id in {"audio", "audio_player", "music"}:
        note = QPainterPath(); note.moveTo(19, 6); note.lineTo(19, 22); note.cubicTo(18, 26, 11, 27, 10, 23); note.cubicTo(10, 20, 14, 18, 18, 20); note.lineTo(18, 10); note.lineTo(26, 8); note.lineTo(26, 19)
        painter.drawPath(note); painter.setBrush(secondary); painter.drawEllipse(22, 17, 5, 5); painter.drawEllipse(7, 21, 6, 5)
    elif icon_id in {"system", "performance"}:
        painter.setBrush(secondary); painter.drawRoundedRect(6, 18, 5, 10, 1, 1); painter.drawRoundedRect(14, 12, 5, 16, 1, 1); painter.drawRoundedRect(22, 6, 5, 22, 1, 1)
    elif icon_id in {"temperatures", "temperature"}:
        painter.drawRoundedRect(12, 5, 8, 17, 4, 4); painter.drawEllipse(9, 19, 14, 12)
        painter.setPen(QPen(secondary, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)); painter.drawLine(16, 11, 16, 23); painter.setBrush(secondary); painter.drawEllipse(13, 22, 6, 6)
    elif icon_id == "weather":
        painter.drawEllipse(7, 5, 12, 12); painter.setPen(QPen(secondary, 2));
        for angle in range(0, 360, 45):
            painter.save(); painter.translate(13, 11); painter.rotate(angle); painter.drawLine(0, -8, 0, -11); painter.restore()
        painter.setPen(QPen(primary, 2)); painter.drawArc(9, 16, 18, 12, 0, 180 * 16); painter.drawLine(7, 22, 27, 22)
    elif icon_id in {"custom", "message"}:
        bubble = QPainterPath(); bubble.moveTo(6, 7); bubble.lineTo(26, 7); bubble.lineTo(26, 21); bubble.lineTo(17, 21); bubble.lineTo(10, 27); bubble.lineTo(11, 21); bubble.lineTo(6, 21); bubble.closeSubpath()
        painter.drawPath(bubble); painter.setBrush(secondary)
        for x in (12, 16, 20): painter.drawEllipse(x, 13, 2, 2)
    else:
        painter.drawEllipse(6, 6, 20, 20)
    painter.end()
    return pixmap


class ThemedBackgroundWidget(QWidget):
    """Paint a validated image and one of the built-in decorative patterns."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.background_pixmap = QPixmap()
        self.background_image = QImage()
        self.background_movie = None
        self.background_video = None
        self.background_image_opacity = 100
        self.background_fit = "cover"
        self.background_overlay_color = "#000000"
        self.background_overlay_opacity = 0
        self.background_pattern = {"style": "none", "opacity": 0, "color": "#5974ff"}

    def set_theme_background(self, image_path, background: dict | None, pattern: dict | None) -> None:
        if self.background_movie is not None:
            self.background_movie.stop()
            self.background_movie.deleteLater()
            self.background_movie = None
        if self.background_video is not None:
            self.background_video.stop()
            self.background_video.deleteLater()
            self.background_video = None
        self.background_pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        self.background_image = QImage()
        background = background or {}
        self.background_image_opacity = background.get("image_opacity", 100)
        self.background_fit = background.get("fit", "cover")
        self.background_overlay_color = background.get("overlay_color", "#000000")
        self.background_overlay_opacity = background.get("overlay_opacity", 0)
        self.background_pattern = pattern or {"style": "none", "opacity": 0, "color": "#5974ff"}
        if image_path:
            suffix = Path(image_path).suffix.lower()
            animated_webp = suffix == ".webp" and QImageReader(str(image_path)).supportsAnimation()
            if suffix == ".gif" or animated_webp:
                self.background_movie = QMovie(str(image_path), parent=self)
                self.background_movie.setCacheMode(QMovie.CacheMode.CacheNone)
                self.background_movie.frameChanged.connect(self.update)
                self.background_movie.start()
            elif suffix == ".webm":
                self.background_video = QMediaPlayer(self)
                video_sink = QVideoSink(self.background_video)
                video_sink.videoFrameChanged.connect(self._video_frame_changed)
                self.background_video.setVideoSink(video_sink)
                self.background_video.setLoops(QMediaPlayer.Loops.Infinite)
                self.background_video.setSource(QUrl.fromLocalFile(str(image_path)))
                self.background_video.play()
        self.update()

    def _video_frame_changed(self, frame) -> None:
        self.background_image = frame.toImage()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        bounds = self.rect()
        movie_pixmap = self.background_movie.currentPixmap() if self.background_movie else QPixmap()
        pixmap = movie_pixmap if not movie_pixmap.isNull() else self.background_pixmap
        if not pixmap.isNull():
            image_width, image_height = pixmap.width(), pixmap.height()
            if self.background_fit == "stretch":
                target = bounds
            else:
                scale_x = bounds.width() / max(1, image_width)
                scale_y = bounds.height() / max(1, image_height)
                scale = max(scale_x, scale_y) if self.background_fit == "cover" else min(scale_x, scale_y)
                width = max(1, round(image_width * scale))
                height = max(1, round(image_height * scale))
                target = QRectF((bounds.width() - width) / 2, (bounds.height() - height) / 2, width, height)
            painter.setOpacity(self.background_image_opacity / 100)
            painter.drawPixmap(target, pixmap, pixmap.rect())
            painter.setOpacity(1.0)
        elif not self.background_image.isNull():
            image_width, image_height = self.background_image.width(), self.background_image.height()
            if self.background_fit == "stretch":
                target = bounds
            else:
                scale_x = bounds.width() / max(1, image_width)
                scale_y = bounds.height() / max(1, image_height)
                scale = max(scale_x, scale_y) if self.background_fit == "cover" else min(scale_x, scale_y)
                width = max(1, round(image_width * scale))
                height = max(1, round(image_height * scale))
                target = QRectF((bounds.width() - width) / 2, (bounds.height() - height) / 2, width, height)
            painter.setOpacity(self.background_image_opacity / 100)
            painter.drawImage(target, self.background_image, self.background_image.rect())
            painter.setOpacity(1.0)
        if self.background_overlay_opacity:
            overlay = QColor(self.background_overlay_color)
            overlay.setAlpha(round(255 * self.background_overlay_opacity / 100))
            painter.fillRect(bounds, overlay)
        self._paint_pattern(painter, bounds)

    def _paint_pattern(self, painter: QPainter, bounds) -> None:
        pattern = self.background_pattern
        style = pattern.get("style", "none")
        opacity = pattern.get("opacity", 0)
        if style == "none" or not opacity:
            return
        color = QColor(pattern.get("color", "#5974ff"))
        painter.save()
        painter.setOpacity(opacity / 100)
        painter.setPen(QPen(color, 1.5))
        width, height = bounds.width(), bounds.height()
        if style == "pixel":
            cell = max(20, min(34, min(width, height) // 26))
            block_colors = [QColor("#477a36"), QColor("#70a647"), QColor("#815332"), QColor("#67432e"), QColor("#4f5244")]
            for column, x in enumerate(range(0, width, cell)):
                height_blocks = 2 + ((column * 7 + 3) % 4)
                if column % 2:
                    height_blocks = max(2, height_blocks - 1)
                for row in range(height_blocks):
                    y = height - (row + 1) * cell
                    if x < cell * 3 or x > width - cell * 4 or row < 2:
                        color_index = 0 if row == height_blocks - 1 else 2 + ((column + row) % 2)
                        if row == height_blocks - 2:
                            color_index = 1
                        painter.fillRect(x, y, cell, cell, block_colors[color_index])
                        painter.setPen(QPen(QColor(255, 255, 255, 24), 1))
                        painter.drawLine(x, y, x + cell - 1, y)
                        painter.setPen(QPen(QColor(0, 0, 0, 34), 1))
                        painter.drawLine(x, y + cell - 1, x + cell, y + cell - 1)
            painter.setPen(Qt.PenStyle.NoPen)
            for row in range(4):
                for column in range(4):
                    if (row + column) % 3 == 0:
                        painter.fillRect(width - (column + 1) * cell, row * cell, cell, cell, block_colors[(row + column) % len(block_colors)])
        elif style == "circuit":
            # Low contrast city silhouettes echo the neon skyline without
            # obscuring text or changing the application's layout.
            buildings = [(0, .64, .10, .36), (.035, .52, .10, .48), (.075, .70, .08, .30),
                         (.88, .66, .09, .34), (.94, .54, .08, .46), (.82, .75, .08, .25)]
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 32))
            for bx, by, bw, bh in buildings:
                x, y = round(width * bx), round(height * by)
                w, h = max(16, round(width * bw)), max(24, round(height * bh))
                painter.drawRect(x, y, w, h)
                painter.setPen(QPen(color, 1))
                for wy in range(y + 12, y + h - 8, 18):
                    for wx in range(x + 7, x + w - 5, 14):
                        painter.drawPoint(wx, wy)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for index, (x_ratio, y_ratio) in enumerate(((.08, .22), (.82, .18), (.14, .82), (.9, .76), (.54, .1))):
                x, y = round(width * x_ratio), round(height * y_ratio)
                path = QPainterPath()
                path.moveTo(x, y)
                path.lineTo(x + (72 if index % 2 == 0 else -72), y)
                path.lineTo(x + (72 if index % 2 == 0 else -72), y + (42 if index < 3 else -42))
                painter.drawPath(path)
                painter.drawEllipse(x - 3, y - 3, 6, 6)
            painter.setPen(QPen(QColor("#ff35c7"), 1.2))
            painter.drawLine(0, round(height * .18), round(width * .1), round(height * .18))
            painter.drawLine(round(width * .9), round(height * .87), width, round(height * .87))
        elif style == "sakura":
            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 170), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            branch = QPainterPath(); branch.moveTo(0, 0); branch.cubicTo(width * .08, height * .12, width * .02, height * .22, width * .17, height * .31)
            branch.cubicTo(width * .22, height * .34, width * .23, height * .41, width * .27, height * .47)
            painter.drawPath(branch)
            branch = QPainterPath(); branch.moveTo(width, height); branch.cubicTo(width * .91, height * .87, width * .94, height * .78, width * .82, height * .7)
            branch.cubicTo(width * .77, height * .66, width * .75, height * .6, width * .72, height * .56)
            painter.drawPath(branch)
            for x_ratio, y_ratio, size in ((.08, .13, 12), (.16, .25, 10), (.23, .38, 9), (.28, .48, 9), (.9, .86, 13), (.83, .75, 10), (.76, .64, 9), (.67, .13, 8), (.9, .18, 11)):
                painter.save()
                painter.translate(round(width * x_ratio), round(height * y_ratio))
                for angle in range(0, 360, 72):
                    painter.save()
                    painter.rotate(angle)
                    painter.drawEllipse(-size * .34, -size * 1.15, size * .68, size)
                    painter.restore()
                painter.setBrush(color)
                painter.drawEllipse(-size * .22, -size * .22, size * .44, size * .44)
                painter.restore()
        painter.restore()

DEFAULT_COLORS = {
    "window_bg": "#0d1425", "window_text": "#dce7ff", "sidebar_bg": "#0a1120",
    "topbar_bg": "#0d1425", "panel_bg": "#111c31", "card_bg": "#111c31",
    "preview_bg": "#0a1120", "bubble_bg": "#22242a", "bubble_border": "#454957", "text_primary": "#dce7ff",
    "text_title": "#f2f6ff", "text_page_title": "#ecf2ff", "text_muted": "#8fa6ce",
    "text_secondary": "#9db5dd", "preview_text": "#f2f3f5", "preview_hint": "#8992a5",
    "border": "#263a5b", "border_strong": "#263a5b", "button_bg": "#1a2944",
    "button_hover": "#263a60", "button_border": "#2d4266", "button_hover_border": "#587df7",
    "button_text": "#dce7ff", "primary_bg": "#334ff0", "primary_hover": "#4560ff",
    "primary_border": "#536bff", "primary_text": "#ffffff", "danger_text": "#ff9eae",
    "danger_bg": "#3a2033", "success_bg": "#16834f", "success_hover": "#1ba862",
    "success_border": "#22b970", "success_text": "#ffffff", "nav_text": "#b4c5e7", "nav_active_bg": "#344ff0",
    "nav_active_text": "#ffffff", "nav_hover_bg": "#15233c", "input_bg": "#0c172a",
    "input_border": "#293d60", "input_text": "#dce7ff", "input_focus": "#536bff",
    "selection_bg": "#344ff0", "check_bg": "#111c31", "check_border": "#50668c",
    "check_active": "#405bfa", "check_active_border": "#7387ff", "radio_active": "#526aff",
    "radio_center": "#b8c4ff", "scroll_handle": "#2c4167", "scroll_border": "#3a5685",
    "scroll_hover": "#4969a3", "scroll_hover_border": "#6688ca", "timeline_selected": "#1b3157",
    "timeline_selected_border": "#5974ff", "slider_track": "#283a5a", "slider_handle": "#5974ff",
    "status_border": "#1c2a45", "status_text": "#8fa6ce", "accent": "#426cf3",
    "timeline_bg": "#0d1425", "timeline_tick": "#8fa6ce", "timeline_guide": "#263a5b",
    "timeline_text": "#f2f6ff", "timeline_secondary": "#b8c8e6", "timeline_block1": "#263d70",
    "timeline_block2": "#1c5360", "timeline_block3": "#593664", "timeline_block4": "#61501f",
    "timeline_block5": "#244e3b", "timeline_selected_border": "#718eff",
    "timeline_border": "#3b5685",
}

DEFAULT_SHAPE = {
    "button_radius": 7, "panel_radius": 10, "card_radius": 10, "input_radius": 6,
    "control_radius": 4, "button_padding_y": 9, "button_padding_x": 13,
    "timeline_radius": 7, "bubble_radius": 12, "icon_radius": 20,
}

LIGHT_THEME = {
    "colors": {
        "window_bg": "#f1f4f9", "window_text": "#17243b", "sidebar_bg": "#e2e9f3",
        "topbar_bg": "#f8faff", "panel_bg": "#ffffff", "card_bg": "#f8faff",
        "preview_bg": "#e8eef7", "bubble_bg": "#22242a", "bubble_border": "#454957", "text_primary": "#17243b",
        "text_title": "#101a30", "text_page_title": "#101a30", "text_muted": "#526580",
        "text_secondary": "#526580", "preview_text": "#f2f3f5", "preview_hint": "#c0c6d2",
        "border": "#c5d1e2", "border_strong": "#aebdd1", "button_bg": "#f4f7fc",
        "button_hover": "#e5ecf6", "button_border": "#bdcbe0", "button_hover_border": "#7891bd",
        "button_text": "#263957", "primary_bg": "#334ff0", "primary_hover": "#4560ff",
        "primary_border": "#536bff", "primary_text": "#ffffff", "danger_text": "#a72e4b",
        "danger_bg": "#fff0f3", "success_bg": "#16834f", "success_hover": "#1ba862",
        "success_border": "#22b970", "success_text": "#ffffff", "nav_text": "#263957", "nav_active_bg": "#344ff0",
        "nav_active_text": "#ffffff", "nav_hover_bg": "#cbd7e8", "input_bg": "#ffffff",
        "input_border": "#bdcbe0", "input_text": "#17243b", "input_focus": "#536bff",
        "selection_bg": "#344ff0", "check_bg": "#ffffff", "check_border": "#7386a3",
        "check_active": "#405bfa", "check_active_border": "#7387ff", "radio_active": "#526aff",
        "radio_center": "#ffffff", "scroll_handle": "#b8c6da", "scroll_border": "#a4b4cc",
        "scroll_hover": "#8ea5c7", "scroll_hover_border": "#738db5", "timeline_selected": "#dce7fb",
        "timeline_selected_border": "#5974ff", "slider_track": "#cbd6e5", "slider_handle": "#5974ff",
        "status_border": "#bdcbe0", "status_text": "#526580", "accent": "#426cf3",
        "timeline_bg": "#f1f4f9", "timeline_tick": "#526580", "timeline_guide": "#c5d1e2",
        "timeline_text": "#17243b", "timeline_secondary": "#526580", "timeline_block1": "#dbe7ff",
        "timeline_block2": "#d8edf0", "timeline_block3": "#ecdef0", "timeline_block4": "#f1e8ce",
        "timeline_block5": "#d8ebdf", "timeline_selected_border": "#405bfa",
        "timeline_border": "#aebdd1",
    },
    "shape": {**DEFAULT_SHAPE, "button_radius": 10, "panel_radius": 12, "card_radius": 10, "input_radius": 8, "timeline_radius": 7},
}

_STYLE_TEMPLATE = """
QMainWindow, QWidget#mainArea, QStackedWidget#pages { background: @window_bg; color: @window_text; font-family: 'Noto Sans', 'DejaVu Sans', sans-serif; font-size: 13px; }
QWidget { background: @window_bg; color: @text_primary; font-family: 'Noto Sans', 'DejaVu Sans', sans-serif; font-size: 13px; }
QFrame#sidebar { background: @sidebar_bg; border-right: 1px solid @status_border; }
QFrame#topbar { background: @topbar_bg; border-bottom: 1px solid @status_border; }
QFrame#panel { background: @panel_bg; border: 1px solid @border; border-radius: ${panel_radius}px; }
QFrame#moduleCard { background: @card_bg; border: 1px solid @border; border-radius: ${card_radius}px; }
QFrame#vrchatPreview { background: @preview_bg; border: 1px solid @border; border-radius: ${panel_radius}px; }
QFrame#vrchatBubble { background: @bubble_bg; border: 1px solid @bubble_border; border-radius: ${bubble_radius}px; }
QFrame#moduleCard[moduleEnabled="true"] { border: 1px solid @accent; }
QLabel#title { font-size: 22px; font-weight: 700; color: @text_title; }
QLabel#pageTitle { font-size: 20px; font-weight: 700; color: @text_page_title; }
QLabel#muted { color: @text_muted; }
QLabel#previewEyebrow { color: @text_muted; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#vrchatPreviewText { color: @preview_text; font-size: 16px; }
QLabel#previewHint { color: @preview_hint; font-size: 11px; }
QLabel#icon { background: @button_bg; border-radius: ${icon_radius}px; padding: 7px; font-size: 22px; }
QPushButton { background: @button_bg; border: 1px solid @button_border; border-radius: ${button_radius}px; padding: ${button_padding_y}px ${button_padding_x}px; color: @button_text; }
QPushButton:hover { background: @button_hover; border-color: @button_hover_border; }
QPushButton#primary { background: @primary_bg; border: 1px solid @primary_border; color: @primary_text; font-weight: 700; }
QPushButton#primary:hover { background: @primary_hover; }
QPushButton#danger { color: @danger_text; }
QPushButton#storeAdd { background: @success_bg; border-color: @success_border; color: @success_text; font-size: 22px; font-weight: 700; }
QPushButton#storeAdd:hover { background: @success_hover; }
QPushButton#storeRemove { background: @danger_bg; color: @danger_text; font-size: 22px; font-weight: 700; }
QPushButton#storeUpdate { background: @button_hover; color: @input_focus; font-size: 20px; font-weight: 700; }
QPushButton#nav { text-align: left; padding: 12px 14px; background: transparent; border: 0; color: @nav_text; }
QPushButton#nav:checked { background: @nav_active_bg; color: @nav_active_text; font-weight: 700; }
QPushButton#nav:hover:!checked { background: @nav_hover_bg; }
QLineEdit, QComboBox, QSpinBox, QTextEdit, QListWidget { background: @input_bg; border: 1px solid @input_border; border-radius: ${input_radius}px; padding: 8px; color: @input_text; selection-background-color: @selection_bg; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus { border-color: @input_focus; }
QComboBox::drop-down { border: 0; width: 24px; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator { border: 1px solid @check_border; border-radius: ${control_radius}px; background: @check_bg; }
QCheckBox::indicator:checked { background: @check_active; border-color: @check_active_border; }
QRadioButton::indicator { border: 1px solid @check_border; border-radius: 8px; background: @check_bg; }
QRadioButton::indicator:checked { background: @radio_active; border: 4px solid @radio_center; }
QScrollArea, QStackedWidget#pages, QScrollArea > QWidget, QAbstractScrollArea::viewport { border: 0; background: @window_bg; }
QScrollBar:horizontal { height: 10px; background: transparent; margin: 3px 8px 2px 8px; }
QScrollBar:vertical { width: 10px; background: transparent; margin: 8px 2px 8px 2px; }
QScrollBar::handle:horizontal, QScrollBar::handle:vertical { background: @scroll_handle; border: 1px solid @scroll_border; border-radius: 4px; min-width: 28px; min-height: 28px; }
QScrollBar::handle:horizontal:hover, QScrollBar::handle:vertical:hover { background: @scroll_hover; border-color: @scroll_hover_border; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { width: 0; height: 0; border: none; background: transparent; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QListWidget#timelineSources::item { background: @card_bg; border: 1px solid @border; border-radius: ${card_radius}px; margin: 4px; padding: 8px; }
QListWidget#timelineSources::item:selected { background: @timeline_selected; border-color: @timeline_selected_border; }
QLabel#timelineEmptyState { background: @card_bg; border: 1px solid @border; border-radius: ${card_radius}px; padding: 12px; color: @text_secondary; font-size: 14px; font-weight: 600; }
QLabel { background: transparent; }
QTextEdit { color: @text_secondary; }
QStatusBar { color: @status_text; border-top: 1px solid @status_border; }
QSlider::groove:horizontal { height: 5px; background: @slider_track; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: @slider_handle; }
"""


def _build_stylesheet(colors: dict[str, str], shape: dict[str, int] | None = None) -> str:
    palette = {**DEFAULT_COLORS, **colors}
    metrics = {**DEFAULT_SHAPE, **(shape or {})}
    stylesheet = re.sub(r"@([a-z_]+)", lambda match: palette[match.group(1)], _STYLE_TEMPLATE)
    return re.sub(r"\$\{([a-z_]+)\}", lambda match: str(metrics[match.group(1)]), stylesheet)


def _default_theme_visuals(colors: dict[str, str]) -> dict:
    return {
        "panel": {"border_width": 1, "border_style": "solid", "border_color": colors.get("border", "#263a5b"), "highlight_color": None},
        "card": {"border_width": 1, "border_style": "solid", "border_color": colors.get("border", "#263a5b"), "highlight_color": None},
        "button": {"border_width": 1, "border_style": "solid", "border_color": colors.get("button_border", "#2d4266"), "highlight_color": None},
        "icon": {"background_color": colors.get("button_bg", "#1a2944"), "border_color": colors.get("accent", "#5974ff"), "border_width": 1, "corner_style": "rounded", "stroke_width": 2, "foreground_color": colors.get("accent", "#5974ff"), "secondary_color": colors.get("text_primary", "#dce7ff")},
    }


def _apply_surface_style(stylesheet: str, visuals: dict, shape: dict[str, int], texture_assets: dict | None = None) -> str:
    """Render bounded per-component border and icon settings from theme JSON."""
    for object_name, config in (("panel", visuals["panel"]), ("moduleCard", visuals["card"])):
        width = config["border_width"]
        border = "none" if width == 0 else f"{width}px {config['border_style']} {config['border_color']}"
        stylesheet += f"QFrame#{object_name} {{ border: {border}; }}\n"
        if config["highlight_color"] and width:
            stylesheet += f"QFrame#{object_name} {{ border-top-color: {config['highlight_color']}; border-left-color: {config['highlight_color']}; }}\n"
    button = visuals["button"]
    button_border = "none" if button["border_width"] == 0 else f"{button['border_width']}px {button['border_style']} {button['border_color']}"
    stylesheet += f"QPushButton, QPushButton#primary, QPushButton#danger, QPushButton#storeAdd, QPushButton#storeRemove, QPushButton#storeUpdate {{ border: {button_border}; }}\n"
    if button["highlight_color"] and button["border_width"]:
        stylesheet += f"QPushButton, QPushButton#primary, QPushButton#danger, QPushButton#storeAdd, QPushButton#storeRemove, QPushButton#storeUpdate {{ border-top-color: {button['highlight_color']}; border-left-color: {button['highlight_color']}; }}\n"
    icon = visuals["icon"]
    icon_border = "none" if icon["border_width"] == 0 else f"{icon['border_width']}px solid {icon['border_color']}"
    radius = 0 if icon["corner_style"] == "square" else (24 if icon["corner_style"] == "circle" else shape.get("icon_radius", 20))
    stylesheet += f"QLabel#icon {{ background: {icon['background_color']}; border: {icon_border}; border-radius: {radius}px; }}\n"
    texture_selectors = {
        "panel": "QFrame#panel",
        "card": "QFrame#moduleCard",
        "sidebar": "QFrame#sidebar",
        "topbar": "QFrame#topbar",
        "button": "QPushButton",
    }
    for component, asset_path in (texture_assets or {}).items():
        selector = texture_selectors.get(component)
        if selector and asset_path:
            image_url = QUrl.fromLocalFile(str(asset_path)).toString()
            stylesheet += f'{selector} {{ border-image: url("{image_url}") 0 0 0 0 stretch stretch; }}\n'
    return stylesheet


def _replace_style_colors(stylesheet: str, replacements: dict[str, str]) -> str:
    return re.sub(r"#[0-9a-fA-F]{6}", lambda match: replacements.get(match.group(0).lower(), match.group(0)), stylesheet)


DARK_STYLE = _build_stylesheet(DEFAULT_COLORS)
LIGHT_STYLE = _build_stylesheet(LIGHT_THEME["colors"], LIGHT_THEME["shape"])


class StatusBridge(QObject):
    packet = Signal(float)


class StoreBridge(QObject):
    completed = Signal(str, object, str)


_MODULE_MIME_TYPE = "application/x-osclinux-module-id"


def _module_id_from_mime(mime) -> str:
    if mime.hasFormat(_MODULE_MIME_TYPE):
        try:
            return bytes(mime.data(_MODULE_MIME_TYPE)).decode("utf-8").strip()
        except (TypeError, UnicodeDecodeError):
            return ""
    return mime.text().strip() if mime.hasText() else ""


class ModuleSourceList(QListWidget):
    moduleDropped = Signal(str)
    EMPTY_STATE_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        # QAbstractScrollArea delivers drag events to its viewport, not always
        # to the QListWidget subclass itself. Observe that viewport directly so
        # dropping a timeline block works over both cards and empty space.
        self.viewport().setAcceptDrops(True)
        self.viewport().installEventFilter(self)

    def show_empty_state(self, text: str) -> None:
        """Show a centered, larger empty-state card while keeping the list droppable."""
        self.clear()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        item = QListWidgetItem()
        item.setData(self.EMPTY_STATE_ROLE, True)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.addItem(item)

        card = QLabel(text)
        card.setObjectName("timelineEmptyState")
        card.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.setFixedSize(480, 68)
        card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        container = QWidget()
        container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self.setItemWidget(item, container)
        self._resize_empty_state_cell()

    def _resize_empty_state_cell(self) -> None:
        if self.count() != 1 or not self.item(0).data(self.EMPTY_STATE_ROLE):
            return
        size = self.viewport().size()
        cell_size = QSize(max(1, size.width() - 16), max(1, size.height() - 16))
        self.setGridSize(cell_size)
        self.item(0).setSizeHint(cell_size)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_empty_state_cell()

    def mimeData(self, items):
        mime = super().mimeData(items)
        if items:
            module_id = items[0].data(Qt.ItemDataRole.UserRole)
            if module_id:
                module_id = str(module_id)
                mime.setText(module_id)
                mime.setData(_MODULE_MIME_TYPE, module_id.encode("utf-8"))
        return mime

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() in (
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        ):
            module_id = _module_id_from_mime(event.mimeData())
            if module_id and event.source() is not self:
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                if event.type() == QEvent.Type.Drop:
                    self.moduleDropped.emit(module_id)
                return True
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        if event.source() is not self and _module_id_from_mime(event.mimeData()):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.source() is not self and _module_id_from_mime(event.mimeData()):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event):
        if event.source() is self:
            event.ignore()
            return
        module_id = _module_id_from_mime(event.mimeData())
        if module_id:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            self.moduleDropped.emit(module_id)
            return
        event.ignore()


class TimelineWidget(QWidget):
    sequenceChanged = Signal(object)
    moduleSelected = Signal(str)

    def __init__(self, sequence: list[dict], names: dict[str, str], parent=None):
        super().__init__(parent)
        self.sequence = [dict(item) for item in sequence]
        self.names = names
        self.selected_id = ""
        self.light_theme = False
        self.theme_colors: dict[str, str] = {}
        self.drag_index = -1
        self.resize_index = -1
        self.press_x = 0
        self.dragging_block = False
        self.playhead_seconds: float | None = None
        self.setAcceptDrops(True)
        self.setMinimumHeight(125)
        self.setMouseTracking(True)
        self._update_width()

    def set_data(self, sequence: list[dict], names: dict[str, str]):
        self.sequence = [dict(item) for item in sequence]
        self.names = names
        if self.selected_id not in {item["id"] for item in self.sequence}:
            self.selected_id = ""
        self._update_width()
        self.update()

    def set_light_theme(self, enabled: bool) -> None:
        self.light_theme = enabled
        self.update()

    def set_theme_colors(self, colors: dict[str, str]) -> None:
        self.theme_colors = dict(colors)
        self.update()

    def set_theme_shape(self, shape: dict[str, int]) -> None:
        self.theme_shape = dict(shape)
        self.update()

    def set_playhead(self, module_id: str = "", progress: float = 0.0) -> None:
        item_index = next((index for index, item in enumerate(self.sequence) if item["id"] == module_id), -1)
        if item_index < 0:
            self.playhead_seconds = None
        else:
            elapsed = sum(int(item.get("duration", 10)) for item in self.sequence[:item_index])
            duration = int(self.sequence[item_index].get("duration", 10))
            self.playhead_seconds = elapsed + duration * max(0.0, min(1.0, progress))
        self.update()

    def _update_width(self):
        total = sum(int(item.get("duration", 10)) for item in self.sequence)
        content_width = max(900, 70 + total * 12)
        self.setMinimumWidth(content_width)
        self.resize(content_width, 125)

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
        color = lambda key, fallback: self.theme_colors.get(key, fallback)
        background = color("timeline_bg", "#0d1425")
        tick_color = color("timeline_tick", "#8fa6ce")
        guide_color = color("timeline_guide", "#263a5b")
        foreground = color("timeline_text", "#f2f6ff")
        secondary = color("timeline_secondary", "#b8c8e6")
        card_colors = [color(f"timeline_block{index}", fallback) for index, fallback in enumerate(("#263d70", "#1c5360", "#593664", "#61501f", "#244e3b"), 1)]
        selected_border = color("timeline_selected_border", "#718eff")
        card_border = color("timeline_border", "#3b5685")
        painter.fillRect(self.rect(), QColor(background))
        positions = self._positions()
        total = sum(int(item.get("duration", 10)) for item in self.sequence)
        painter.setPen(QColor(tick_color))
        last_tick = ((total + 4) // 5) * 5
        for second in range(0, last_tick + 1, 5):
            x = 54 + second * 12
            painter.drawLine(x, 25, x, 43)
            painter.drawText(x - 12, 18, f"{second}s")
        painter.setPen(QColor(guide_color))
        painter.drawLine(54, 42, max(70, 54 + total * 12), 42)
        for index, (item, (x, width)) in enumerate(zip(self.sequence, positions)):
            selected = item["id"] == self.selected_id
            painter.setBrush(QColor(card_colors[index % len(card_colors)]))
            painter.setPen(QColor(selected_border if selected else card_border))
            radius = getattr(self, "theme_shape", {}).get("timeline_radius", 7)
            painter.drawRoundedRect(x, 54, width - 4, 58, radius, radius)
            painter.setPen(QColor(foreground))
            name = self.names.get(item["id"], item["id"])
            painter.drawText(x + 9, 78, painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, max(20, width - 25)))
            painter.setPen(QColor(secondary))
            painter.drawText(x + 9, 99, f'{item.get("duration", 10)} s')
            painter.setPen(QColor(tick_color))
            painter.drawLine(x + width - 7, 59, x + width - 7, 106)
        if not self.sequence:
            painter.setPen(QColor(tick_color))
            painter.drawText(54, 83, "Glissez ici les modules à planifier.")
        if self.playhead_seconds is not None and self.sequence:
            marker_x = round(54 + self.playhead_seconds * 12)
            marker_color = color("accent", "#426cf3")
            painter.setPen(QPen(QColor(marker_color), 2))
            painter.drawLine(marker_x, 24, marker_x, 116)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(marker_color))
            painter.drawEllipse(marker_x - 5, 45, 10, 10)

    def _index_at(self, x):
        for index, (left, width) in enumerate(self._positions()):
            if left <= x <= left + width:
                return index
        return -1

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_x = int(event.position().x())
            self.drag_index = self._index_at(self.press_x)
            self.dragging_block = False
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
            if not self.dragging_block and abs(int(event.position().x()) - self.press_x) >= QApplication.startDragDistance():
                self.dragging_block = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self.dragging_block:
                available = self._available_modules_at(event.globalPosition().toPoint())
                self.setCursor(Qt.CursorShape.DragMoveCursor if available else Qt.CursorShape.ClosedHandCursor)
                self.update()

    def mouseReleaseEvent(self, event):
        if self.resize_index >= 0:
            self.resize_index = -1
            self.sequenceChanged.emit([dict(item) for item in self.sequence])
        elif self.dragging_block and self.drag_index >= 0:
            index = self.drag_index
            module = self.sequence[index]
            available = self._available_modules_at(event.globalPosition().toPoint())
            if available is not None:
                # Handle timeline -> available-list removal directly. The
                # standard Qt drag cursor rejects this cross-scroll-area drop
                # on some Linux desktops even though both widgets accept it.
                available.moduleDropped.emit(module["id"])
            elif self.rect().contains(event.position().toPoint()):
                self.sequence.pop(index)
                insert_at = len(self.sequence)
                x = int(event.position().x())
                for target_index, (left, width) in enumerate(self._positions()):
                    if x < left + width // 2:
                        insert_at = target_index
                        break
                self.sequence.insert(insert_at, module)
                self.selected_id = module["id"]
                self._update_width()
                self.update()
                self.sequenceChanged.emit([dict(item) for item in self.sequence])
        self.drag_index = -1
        self.dragging_block = False
        self.unsetCursor()
        self.update()

    def _available_modules_at(self, global_position):
        available = self.window().findChild(ModuleSourceList, "timelineSources")
        if available is None:
            return None
        viewport = available.viewport()
        local_position = viewport.mapFromGlobal(global_position)
        return available if viewport.rect().contains(local_position) else None

    def dragEnterEvent(self, event):
        module_id = _module_id_from_mime(event.mimeData())
        if module_id and self._module_is_enabled(module_id):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        module_id = _module_id_from_mime(event.mimeData())
        if module_id and self._module_is_enabled(module_id):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event):
        module_id = _module_id_from_mime(event.mimeData())
        if not module_id or not self._module_is_enabled(module_id):
            event.ignore()
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
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    def _module_is_enabled(self, module_id: str) -> bool:
        settings = getattr(self.window(), "settings", {})
        return bool(settings.get("module_options", {}).get(module_id, {}).get("enabled", False))


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
        saved_theme = self.settings.setdefault("appearance", {}).get("theme", "base")
        if saved_theme == "dark":
            self.settings["appearance"]["theme"] = BASE_THEME_ID
        elif saved_theme == "light":
            self.settings["appearance"]["theme"] = "light"
        self.store = ModuleStore()
        self.theme_store = ThemeStore()
        self.catalog: list[dict] = []
        self._catalog_by_id: dict[str, dict] = {}
        self._pending_modules: set[str] = set()
        self.theme_catalog: list[dict] = []
        self._theme_by_id: dict[str, dict] = {}
        self._pending_themes: set[str] = set()
        self.theme_visuals = _default_theme_visuals(DEFAULT_COLORS)
        self.theme_icon_definitions = {}
        self.theme_icon_assets = {}
        self.store_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="osclinux-store")
        self.store_bridge = StoreBridge()
        self.store_bridge.completed.connect(self._store_completed)
        self.nav_buttons: list[QPushButton] = []
        self.nav_icon_ids: list[str] = []
        self.module_icon_labels: list[tuple[QLabel, str]] = []
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
        self.module_refresh_timer = QTimer(self)
        self.module_refresh_timer.timeout.connect(self._refresh_current_module)
        self.current_module_id = ""
        self.current_module_text: str | None = None
        self.current_module_started_at = 0.0
        self.current_module_duration = 0.0
        self.playhead_timer = QTimer(self)
        self.playhead_timer.setInterval(50)
        self.playhead_timer.timeout.connect(self._update_timeline_playhead)
        self._build_ui()
        self._change_theme(self.settings["appearance"].get("theme", BASE_THEME_ID))
        self.refresh_preview()
        self._append_log("OSCLinux est prêt. Aucun module n’est installé par défaut.")
        QTimer.singleShot(100, self.refresh_catalog)
        QTimer.singleShot(150, self.refresh_theme_catalog)
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
        brand_row = QHBoxLayout()
        brand_icon = QLabel()
        brand_icon.setObjectName("icon")
        brand_icon.setFixedSize(38, 38)
        brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_icon.setPixmap(_theme_icon_pixmap("osc", {}, self.theme_visuals["icon"], 28))
        self.brand_icon_label = brand_icon
        brand_row.addWidget(brand_icon)
        brand = QLabel("OSCLinux")
        brand.setObjectName("title")
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        side.addLayout(brand_row)
        subtitle = QLabel("OSC Manager · Modules")
        subtitle.setObjectName("muted")
        side.addWidget(subtitle)
        side.addSpacing(22)
        nav_group = QButtonGroup(self)
        nav_group.setExclusive(True)
        for index, (text, icon_id) in enumerate([
            ("Modules", "modules"), ("Règle Temporelle", "timeline"), ("Configuration OSC", "osc"), ("Thèmes", "themes"),
            ("Paramètres généraux", "settings"), ("Journal", "journal"),
        ]):
            button = QPushButton(text)
            button.setIcon(QIcon(_theme_icon_pixmap(icon_id, {}, self.theme_visuals["icon"], 24)))
            button.setIconSize(QSize(24, 24))
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _checked=False, i=index: self._navigate_to_page(i))
            nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            self.nav_icon_ids.append(icon_id)
            side.addWidget(button)
        side.addStretch(1)
        brand_card = QFrame()
        brand_card.setObjectName("panel")
        bc = QVBoxLayout(brand_card)
        bc.addWidget(QLabel("VRCHAT OSC MANAGER"))
        bc.addWidget(QLabel(f"Version {APP_VERSION}"))
        bc.addWidget(QLabel("Linux · Session locale"))
        side.addWidget(brand_card)

        main_area = ThemedBackgroundWidget()
        self.main_area = main_area
        main_area.setObjectName("mainArea")
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
        self.pages.setObjectName("pages")
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

    def _navigate_to_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self._apply_theme_icons()

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

    def refresh_theme_catalog(self) -> None:
        if not hasattr(self, "refresh_theme_button"):
            return
        self.refresh_theme_button.setEnabled(False)
        self.theme_status.setText("Récupération du catalogue des thèmes…")
        future = self.store_executor.submit(self.theme_store.fetch_catalog)

        def completed(result) -> None:
            try:
                catalog, online = result.result()
                self.store_bridge.completed.emit("theme_catalog", (catalog, online), "")
            except Exception as exc:
                self.store_bridge.completed.emit("theme_catalog", None, str(exc))

        future.add_done_callback(completed)

    def _render_theme_catalog(self) -> None:
        while self.theme_catalog_layout.count():
            item = self.theme_catalog_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        installed = self.theme_store.installed_versions()
        if not self.theme_catalog:
            empty = QLabel("Aucun thème supplémentaire dans le catalogue.")
            empty.setObjectName("muted")
            self.theme_catalog_layout.addWidget(empty)
        active = self.settings["appearance"].get("theme", BASE_THEME_ID)
        for theme_id, action in self.default_theme_actions.items():
            action.setText("Thème actif" if active == theme_id else "Utiliser")
            action.setEnabled(active != theme_id)
        for entry in self.theme_catalog:
            theme_id = entry["id"]
            row = QFrame()
            row.setObjectName("moduleCard")
            row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(14, 10, 12, 10)
            row_layout.setSpacing(10)
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
            installed_version = installed.get(theme_id)
            if theme_id in self._pending_themes:
                pending = QPushButton("…")
                pending.setEnabled(False)
                row_layout.addWidget(pending)
            elif installed_version is None:
                add = QPushButton("＋")
                add.setObjectName("storeAdd")
                add.setToolTip("Installer ce thème")
                add.setFixedSize(42, 40)
                add.clicked.connect(lambda _checked=False, tid=theme_id: self._theme_action("install", tid))
                row_layout.addWidget(add)
            else:
                remove = QPushButton("×")
                remove.setObjectName("storeRemove")
                remove.setToolTip("Désinstaller ce thème")
                remove.setFixedSize(42, 40)
                remove.clicked.connect(lambda _checked=False, tid=theme_id: self._theme_action("uninstall", tid))
                row_layout.addWidget(remove)
                use = QPushButton("Thème actif" if active == theme_id else "Utiliser")
                use.setEnabled(active != theme_id)
                use.setFixedWidth(110)
                use.clicked.connect(lambda _checked=False, tid=theme_id: self._use_theme(tid))
                row_layout.addWidget(use)
                if self._version_newer(entry["version"], installed_version):
                    update = QPushButton("⬆")
                    update.setObjectName("storeUpdate")
                    update.setToolTip(f"Mettre à jour depuis {installed_version}")
                    update.setFixedSize(42, 40)
                    update.clicked.connect(lambda _checked=False, tid=theme_id: self._theme_action("update", tid))
                    row_layout.addWidget(update)
            self.theme_catalog_layout.addWidget(row)
        self.theme_catalog_layout.addStretch(1)

    def _theme_action(self, operation: str, theme_id: str) -> None:
        if theme_id in self._pending_themes:
            return
        if operation == "uninstall":
            entry = self._theme_by_id[theme_id]
            answer = QMessageBox.question(self, "Désinstaller le thème", f"Retirer « {entry['name']} » ?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        entry = self._theme_by_id[theme_id]
        self._pending_themes.add(theme_id)
        self.theme_status.setText(f"{operation.capitalize()} de {entry['name']}…")
        self._render_theme_catalog()

        def perform() -> None:
            if operation == "install":
                self.theme_store.install(entry)
            elif operation == "update":
                self.theme_store.update(entry)
            elif operation == "uninstall":
                self.theme_store.uninstall(theme_id)
            else:
                raise ThemeStoreError("Action de thème inconnue.")

        future = self.store_executor.submit(perform)

        def completed(result) -> None:
            try:
                result.result()
                self.store_bridge.completed.emit(f"theme_action:{operation}:{theme_id}", True, "")
            except Exception as exc:
                self.store_bridge.completed.emit(f"theme_action:{operation}:{theme_id}", None, str(exc))

        future.add_done_callback(completed)

    def _use_theme(self, theme_id: str) -> None:
        if theme_id != BASE_THEME_ID and theme_id not in self.theme_store.installed_versions():
            QMessageBox.information(self, "Thème non installé", "Installez d’abord ce thème depuis le catalogue.")
            return
        self.settings["appearance"]["theme"] = theme_id
        self._change_theme(theme_id)
        self.save_all()
        if hasattr(self, "theme_catalog_layout"):
            self._render_theme_catalog()

    def _render_catalog(self) -> None:
        while self.catalog_layout.count():
            item = self.catalog_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        installed = self.store.installed_versions()
        self.module_icon_labels = []
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
            module_icon = QLabel()
            module_icon.setObjectName("icon")
            module_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            module_icon.setFixedSize(50, 50)
            module_icon.setPixmap(_theme_icon_pixmap(module_id, self.theme_icon_definitions, self.theme_visuals["icon"], 32, self.theme_icon_assets))
            self.module_icon_labels.append((module_icon, module_id))
            row_layout.addWidget(module_icon)
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
        if operation == "theme_catalog" or operation.startswith("theme_action:"):
            self._theme_store_completed(operation, result, error)
            return
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

    def _theme_store_completed(self, operation: str, result: object, error: str) -> None:
        if operation == "theme_catalog":
            self.refresh_theme_button.setEnabled(True)
            if error:
                self.theme_status.setText(f"Catalogue de thèmes indisponible : {error}")
                self._append_log(f"Catalogue de thèmes indisponible : {error}")
                return
            self.theme_catalog, online = result
            self._theme_by_id = {entry["id"]: entry for entry in self.theme_catalog}
            source = "en ligne" if online else "local (hors connexion)"
            self.theme_status.setText(f"{len(self.theme_catalog)} thèmes disponibles · catalogue {source}")
            self._render_theme_catalog()
            self._append_log(f"Catalogue de thèmes chargé ({source}, {len(self.theme_catalog)} thèmes).")
            return

        _, action, theme_id = operation.split(":", 2)
        self._pending_themes.discard(theme_id)
        entry = self._theme_by_id.get(theme_id, {"name": theme_id, "version": "?"})
        if error:
            self.theme_status.setText(f"Échec de {action} pour {entry['name']} : {error}")
            self._append_log(f"Erreur {action} du thème {theme_id} : {error}")
            self._render_theme_catalog()
            QMessageBox.warning(self, "Action sur le thème impossible", f"{entry['name']} n’a pas pu être traité.\n\nDétail : {error}")
            return
        if action == "uninstall" and self.settings["appearance"].get("theme") == theme_id:
            self.settings["appearance"]["theme"] = BASE_THEME_ID
            self._change_theme(BASE_THEME_ID)
        elif action == "update" and self.settings["appearance"].get("theme") == theme_id:
            self._change_theme(theme_id)
        if action == "install":
            self.theme_status.setText(f"{entry['name']} installé. Vous pouvez maintenant l’appliquer.")
        elif action == "update":
            self.theme_status.setText(f"{entry['name']} mis à jour vers la version {entry['version']}.")
        else:
            self.theme_status.setText(f"{entry['name']} désinstallé.")
        self._append_log(f"Thème {entry['name']} : {action} terminé.")
        self.save_all()
        self._render_theme_catalog()

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
        player_controls: set[str] = set()
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
            elif kind == "player":
                player_controls.add(key)
                control = QComboBox()
                players = self._available_media_players()
                # Keep the saved choice visible if the player is currently closed.
                if value and str(value) not in players:
                    control.addItem(f"{value} (indisponible)", str(value))
                for player in players:
                    control.addItem(player, player)
                if not control.count():
                    control.addItem("Aucun lecteur détecté", "")
                selected = control.findData(str(value))
                if selected >= 0:
                    control.setCurrentIndex(selected)
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
                options[key] = control.currentData() if key in player_controls else control.currentText()
            elif isinstance(control, QSpinBox):
                options[key] = control.value()
            elif isinstance(control, QLineEdit):
                options[key] = control.text()
        self.settings["module_options"][module_id] = options
        self._ensure_timeline()
        self.save_all()
        self._show_timeline_summary(module_id)
        self._append_log(f"Paramètres du module {entry['name']} enregistrés.")

    @staticmethod
    def _available_media_players() -> list[str]:
        playerctl = shutil.which("playerctl")
        if not playerctl:
            return []
        try:
            result = subprocess.run([playerctl, "-l"], capture_output=True, text=True, timeout=1, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode:
            return []
        return list(dict.fromkeys(line.strip() for line in result.stdout.splitlines() if line.strip()))
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
        layout.setSpacing(12)
        page_header = QHBoxLayout()
        page_header.addLayout(self._page_header("Thèmes", "Choisissez l’apparence d’OSCLinux ou installez des thèmes depuis le catalogue."), 1)
        self.refresh_theme_button = QPushButton("↻  Actualiser le catalogue")
        self.refresh_theme_button.clicked.connect(self.refresh_theme_catalog)
        page_header.addWidget(self.refresh_theme_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(page_header)
        current_panel = QFrame()
        current_panel.setObjectName("panel")
        current_layout = QVBoxLayout(current_panel)
        current_layout.addWidget(self._section_title("Thèmes par défaut", "Sombre et Clair sont intégrés à OSCLinux et ne peuvent pas être supprimés."))
        self.default_theme_actions = {}
        defaults = (
            (BASE_THEME_ID, "OSCLinux Sombre", "Thème sombre d’origine d’OSCLinux.", "1.0.0"),
            (LIGHT_THEME_ID, "Clair", "Thème clair intégré, disponible même hors connexion.", "1.1.0"),
        )
        for theme_id, name, description, version in defaults:
            row = self._build_default_theme_row(theme_id, name, description, version)
            current_layout.addWidget(row)
        layout.addWidget(current_panel)

        catalog_panel = QFrame()
        catalog_panel.setObjectName("panel")
        catalog_layout = QVBoxLayout(catalog_panel)
        catalog_layout.addWidget(self._section_title("Catalogue des thèmes", "Installez uniquement les thèmes que vous souhaitez utiliser."))
        self.theme_status = QLabel("Chargement du catalogue des thèmes…")
        self.theme_status.setObjectName("muted")
        catalog_layout.addWidget(self.theme_status)
        self.theme_catalog_panel = QFrame()
        self.theme_catalog_panel.setObjectName("panel")
        self.theme_catalog_layout = QVBoxLayout(self.theme_catalog_panel)
        self.theme_catalog_layout.setContentsMargins(10, 10, 10, 10)
        self.theme_catalog_layout.setSpacing(8)
        catalog_layout.addWidget(self.theme_catalog_panel, 1)
        layout.addWidget(catalog_panel, 1)
        layout.addWidget(QLabel("Limite VRChat : le texte de chatbox est limité à 144 caractères."))
        return self._scroll(page)

    def _build_default_theme_row(self, theme_id: str, title: str, description_text: str, version: str) -> QFrame:
        row = QFrame()
        row.setObjectName("moduleCard")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(14, 10, 12, 10)
        info = QVBoxLayout()
        name = QLabel(title)
        name.setStyleSheet("font-size:15px;font-weight:700")
        info.addWidget(name)
        description = QLabel(description_text)
        description.setObjectName("muted")
        description.setWordWrap(True)
        info.addWidget(description)
        info.addWidget(QLabel(f"Version {version} · Auteur : OSCLinux"))
        row_layout.addLayout(info, 1)
        action = QPushButton("Utiliser")
        action.setFixedWidth(110)
        action.clicked.connect(lambda _checked=False, tid=theme_id: self._use_theme(tid))
        self.default_theme_actions[theme_id] = action
        row_layout.addWidget(action)
        return row

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
        for label, value in [("Un seul module", "single"), ("Alternance des modules", "alternate")]:
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
            "Ajoutez un module en le glissant sur la règle. Pour le retirer, ramenez-le dans la liste. Déplacez les blocs pour choisir l’ordre et étirez leur bord droit pour régler leur durée."
        ))
        available_panel = QFrame()
        available_panel.setObjectName("panel")
        available_layout = QVBoxLayout(available_panel)
        available_layout.addWidget(self._section_title("Modules disponibles", "Glissez ici un module de la règle pour le retirer de la séquence."))
        self.timeline_sources = ModuleSourceList()
        self.timeline_sources.setObjectName("timelineSources")
        self.timeline_sources.setGridSize(QSize(220, 125))
        self.timeline_sources.setFixedHeight(150)
        self.timeline_sources.setViewMode(QListWidget.ViewMode.IconMode)
        self.timeline_sources.setFlow(QListWidget.Flow.LeftToRight)
        self.timeline_sources.setWrapping(False)
        self.timeline_sources.setMovement(QListWidget.Movement.Static)
        self.timeline_sources.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.timeline_sources.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.timeline_sources.setDragEnabled(True)
        self.timeline_sources.setAcceptDrops(True)
        self.timeline_sources.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.timeline_sources.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.timeline_sources.moduleDropped.connect(self._remove_timeline_module)
        available_layout.addWidget(self.timeline_sources)
        layout.addWidget(available_panel)

        timeline_panel = QFrame()
        timeline_panel.setObjectName("panel")
        timeline_layout = QVBoxLayout(timeline_panel)
        timeline_layout.addWidget(self._section_title("Séquence d’affichage", "Déposez ici les modules à afficher ; ramenez un bloc dans la liste du dessus pour le retirer."))
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(False)
        self.timeline_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.timeline_scroll.setFixedHeight(140)
        self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.timeline = TimelineWidget(self.settings.get("timeline") or [], {}, self)
        self.timeline.setMaximumHeight(125)
        self.timeline_scroll.setWidget(self.timeline)
        timeline_layout.addWidget(self.timeline_scroll)
        layout.addWidget(timeline_panel)

        summary = QFrame()
        summary.setObjectName("panel")
        summary_layout = QVBoxLayout(summary)
        summary_layout.addWidget(self._section_title("Module sélectionné", "Résumé des informations et du contenu affiché dans la chatbox."))

        summary_content = QHBoxLayout()
        summary_content.setSpacing(20)
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(12)
        self.timeline_summary_title = QLabel("Sélectionnez un module dans la règle.")
        self.timeline_summary_title.setStyleSheet("font-size:16px;font-weight:700")
        self.timeline_summary_meta = QLabel("")
        self.timeline_summary_meta.setObjectName("muted")
        self.timeline_summary_meta.setWordWrap(True)
        self.timeline_summary_description = QLabel("")
        self.timeline_summary_description.setWordWrap(True)
        self.timeline_summary_preview = QLabel("")
        self.timeline_summary_preview.setWordWrap(True)
        self.timeline_summary_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_layout.addWidget(self.timeline_summary_title)
        details_layout.addWidget(self.timeline_summary_meta)
        details_layout.addWidget(self.timeline_summary_description)
        details_layout.addStretch(1)
        summary_content.addWidget(details, 6)

        preview_panel = QFrame()
        preview_panel.setObjectName("vrchatPreview")
        preview_panel.setMinimumSize(340, 185)
        preview_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(16, 14, 16, 14)
        preview_layout.setSpacing(10)
        preview_header = QHBoxLayout()
        preview_eyebrow = QLabel("APERÇU CHATBOX")
        preview_eyebrow.setObjectName("previewEyebrow")
        vrchat_label = QLabel("VRChat")
        vrchat_label.setObjectName("muted")
        preview_header.addWidget(preview_eyebrow)
        preview_header.addStretch(1)
        preview_header.addWidget(vrchat_label)
        preview_layout.addLayout(preview_header)

        bubble = QFrame()
        bubble.setObjectName("vrchatBubble")
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(16, 13, 16, 13)
        bubble_layout.addWidget(self.timeline_summary_preview)
        preview_layout.addWidget(bubble, 1, Qt.AlignmentFlag.AlignVCenter)
        preview_hint = QLabel("Rendu indicatif · le texte dépend des données du module")
        preview_hint.setObjectName("previewHint")
        preview_hint.setWordWrap(True)
        preview_layout.addWidget(preview_hint)
        summary_content.addWidget(preview_panel, 5)
        summary_layout.addLayout(summary_content, 1)
        layout.addWidget(summary, 1)

        self.timeline.sequenceChanged.connect(self._timeline_changed)
        self.timeline.moduleSelected.connect(self._show_timeline_summary)
        return self._scroll(page)

    def _ensure_timeline(self) -> None:
        installed = self.store.installed_versions()
        module_options = self.settings.setdefault("module_options", {})
        migrated_options = False
        for module_id in installed:
            options = module_options.get(module_id)
            if not isinstance(options, dict):
                options = {}
                module_options[module_id] = options
                migrated_options = True
            # Older settings files may not have the activation flag. Treat a
            # missing flag as enabled, while keeping an explicit False choice.
            if "enabled" not in options:
                options["enabled"] = True
                migrated_options = True
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
            if (
                module_id not in installed
                or module_id in seen
                or not module_options.get(module_id, {}).get("enabled", False)
            ):
                continue
            try:
                duration = max(2, min(120, int(item.get("duration", 10))))
            except (TypeError, ValueError):
                duration = 10
            normalized.append({"id": module_id, "duration": duration})
            seen.add(module_id)
        self.settings["timeline"] = normalized
        self.settings["order"] = [item["id"] for item in normalized]
        if migrated_options:
            self.save_all()
        self._refresh_timeline()

    def _refresh_timeline(self) -> None:
        if not hasattr(self, "timeline"):
            return
        installed = self.store.installed_versions()
        entries = {entry["id"]: entry for entry in self.catalog}
        scheduled = {item["id"] for item in self.settings.get("timeline", [])}
        self.timeline_sources.clear()
        self.timeline_sources.setGridSize(QSize(220, 125))
        for module_id, version in installed.items():
            if module_id in scheduled:
                continue
            entry = entries.get(module_id, {})
            enabled = bool(self.settings.get("module_options", {}).get(module_id, {}).get("enabled", False))
            marker = "" if enabled else "●  "
            item = QListWidgetItem(f'{marker}{entry.get("name", module_id)}\n{version}')
            item.setData(Qt.ItemDataRole.UserRole, module_id)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if enabled:
                item.setToolTip("Glissez ce module dans la règle temporelle.")
            else:
                colors = getattr(self, "theme_colors", DEFAULT_COLORS)
                item.setForeground(QColor(colors.get("danger_text", "#ff7186")))
                item.setBackground(QColor(colors.get("danger_bg", "#3a2033")))
                item.setToolTip("Module désactivé : activez-le dans ses paramètres avant de l’ajouter à la règle.")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            self.timeline_sources.addItem(item)
        if self.timeline_sources.count() == 0:
            self.timeline_sources.show_empty_state("Tous les modules sont dans la règle")
        else:
            self.timeline_sources.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        names = {mid: entries.get(mid, {}).get("name", mid) for mid in installed}
        self.timeline.set_data(self.settings.get("timeline", []), names)
        if self.timeline.selected_id:
            self._show_timeline_summary(self.timeline.selected_id)
        else:
            self._clear_timeline_summary()

    def _timeline_changed(self, sequence: list) -> None:
        self.settings["timeline"] = [dict(item) for item in sequence]
        self.settings["order"] = [item["id"] for item in sequence]
        self.save_all()
        self._refresh_timeline()

    def _remove_timeline_module(self, module_id: str) -> None:
        sequence = [dict(item) for item in self.settings.get("timeline", []) if item.get("id") != module_id]
        if len(sequence) == len(self.settings.get("timeline", [])):
            return
        self.timeline.sequence = sequence
        if self.timeline.selected_id == module_id:
            self.timeline.selected_id = sequence[0]["id"] if sequence else ""
        self.timeline._update_width()
        self.timeline.update()
        self._timeline_changed(sequence)

    def _clear_timeline_summary(self) -> None:
        if not hasattr(self, "timeline_summary_title"):
            return
        self.timeline_summary_title.setText("Sélectionnez un module dans la règle.")
        self.timeline_summary_meta.clear()
        self.timeline_summary_description.clear()
        self.timeline_summary_preview.clear()

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
        preview = self._module_text(module_id)
        self.timeline_summary_preview.setText(preview or "Aucun contenu à afficher pour le moment.")


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
        # QSpinBox's internal editor does not honor the shared QSS padding
        # consistently. Match the inset used by QLineEdit so numeric values
        # line up with text inputs in every theme.
        spin.lineEdit().setTextMargins(8, 0, 0, 0)
        return spin

    def _combo_spin(self, spin: QSpinBox) -> QWidget:
        return spin

    def _scroll(self, widget: QWidget) -> QScrollArea:
        widget.setObjectName("pageContent")
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.viewport().setObjectName("pageViewport")
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
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

    def _change_theme(self, theme_id: str) -> None:
        if theme_id in {"dark", ""}:
            theme_id = BASE_THEME_ID
        colors = dict(DEFAULT_COLORS)
        shape = dict(DEFAULT_SHAPE)
        visuals = _default_theme_visuals(colors)
        icon_definitions = {}
        icon_assets = {}
        texture_assets = {}
        background_config = None
        background_image_path = None
        pattern_config = None
        if theme_id == BASE_THEME_ID:
            stylesheet = DARK_STYLE
        else:
            try:
                configuration = self.theme_store.configuration(theme_id)
                if configuration["schema_version"] == 1:
                    # Keep existing installations working while the bundled light theme moves to component tokens.
                    if theme_id == "light":
                        configuration = self.theme_store.bundled_configuration("light")
                    else:
                        stylesheet = _replace_style_colors(DARK_STYLE, configuration["colors"])
                        configuration = None
                if configuration is not None:
                    colors.update(configuration["colors"])
                    shape.update(configuration["shape"])
                    background_config = configuration.get("background")
                    pattern_config = configuration.get("pattern")
                    visuals = configuration.get("visuals", visuals)
                    icon_definitions = configuration.get("icon_drawings", {})
                    icon_assets = {
                        icon_id: self.theme_store.asset_path(theme_id, filename)
                        for icon_id, filename in configuration.get("icons", {}).items()
                    }
                    texture_assets = {
                        surface: self.theme_store.asset_path(theme_id, filename)
                        for surface, filename in configuration.get("textures", {}).items()
                    }
                    background_image_path = self.theme_store.background_path(theme_id, configuration)
                    stylesheet = _build_stylesheet(colors, shape)
            except ThemeStoreError as exc:
                self._append_log(f"Thème {theme_id} invalide : {exc}")
                theme_id = BASE_THEME_ID
                self.settings["appearance"]["theme"] = BASE_THEME_ID
                colors = dict(DEFAULT_COLORS)
                shape = dict(DEFAULT_SHAPE)
                visuals = _default_theme_visuals(colors)
                icon_definitions = {}
                icon_assets = {}
                texture_assets = {}
                stylesheet = DARK_STYLE
                background_config = None
                background_image_path = None
                pattern_config = None
        stylesheet = _apply_surface_style(stylesheet, visuals, shape, texture_assets)
        if background_config or (pattern_config and pattern_config.get("style") != "none"):
            stylesheet += """
QStackedWidget#pages { background: transparent; }
QWidget#pageContent { background: transparent; }
QScrollArea#pageScroll { background: transparent; }
QScrollArea#pageScroll QWidget#pageViewport { background: transparent; }
"""
        self._light_theme = theme_id == "light"
        self.theme_colors = colors
        self.theme_visuals = visuals
        self.theme_icon_definitions = icon_definitions
        self.theme_icon_assets = icon_assets
        self.setStyleSheet(stylesheet)
        self._apply_theme_icons()
        if hasattr(self, "main_area"):
            self.main_area.set_theme_background(background_image_path, background_config, pattern_config)
        if hasattr(self, "timeline"):
            self.timeline.set_theme_colors(colors)
            self.timeline.set_theme_shape(shape)
        if hasattr(self, "default_theme_actions"):
            active = self.settings["appearance"].get("theme", BASE_THEME_ID)
            for theme_id, action in self.default_theme_actions.items():
                action.setText("Thème actif" if active == theme_id else "Utiliser")
                action.setEnabled(active != theme_id)

    def _apply_theme_icons(self) -> None:
        icon_visuals = self.theme_visuals.get("icon", {})
        if hasattr(self, "brand_icon_label"):
            self.brand_icon_label.setPixmap(_theme_icon_pixmap("osc", self.theme_icon_definitions, icon_visuals, 28, self.theme_icon_assets))
        for button, icon_id in zip(self.nav_buttons, self.nav_icon_ids):
            button.setIcon(QIcon(_theme_icon_pixmap(icon_id, self.theme_icon_definitions, icon_visuals, 24, self.theme_icon_assets)))
        for label, icon_id in self.module_icon_labels:
            label.setPixmap(_theme_icon_pixmap(icon_id, self.theme_icon_definitions, icon_visuals, 32, self.theme_icon_assets))

    def refresh_preview(self) -> None:
        muted_color = "#526580" if getattr(self, "_light_theme", False) else "#8fa6ce"
        if hasattr(self, "timeline") and self.timeline.selected_id:
            self._show_timeline_summary(self.timeline.selected_id)
        if self.last_heard and time.monotonic() - self.last_heard < 10:
            self.vrchat_state.setText("●  VRChat : détecté")
            self.vrchat_state.setStyleSheet("color:#20d889")
        else:
            self.vrchat_state.setText("●  VRChat : non détecté")
            self.vrchat_state.setStyleSheet(f"color:{muted_color}")

    def toggle_script(self) -> None:
        if self.running:
            self.running = False
            self.cycle_timer.stop()
            self.module_refresh_timer.stop()
            self.playhead_timer.stop()
            self.current_module_id = ""
            self.current_module_text = None
            if hasattr(self, "timeline"):
                self.timeline.set_playhead()
            if self.listener:
                self.listener.stop()
                self.listener = None
            self.run_button.setText("▶  Démarrer")
            self.script_state.setText("●  Script : arrêté")
            muted_color = "#526580" if getattr(self, "_light_theme", False) else "#8fa6ce"
            self.script_state.setStyleSheet(f"color:{muted_color}")
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
        self.playhead_timer.start()
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
        return [module_id for module_id in ordered if options.get(module_id, {}).get("enabled", False)]
    def _module_text(self, module_id: str) -> str:
        options = self.settings.get("module_options", {}).get(module_id, {})
        return self.providers.get(
            module_id,
            options,
            lambda: self.store.load_text(module_id, options),
            refresh_interval=self._module_refresh_interval(),
        )

    def _module_refresh_interval(self) -> int:
        try:
            return max(1, min(60, int(self.settings.get("osc", {}).get("interval", 2))))
        except (TypeError, ValueError):
            return 2

    def _refresh_current_module(self) -> None:
        if not self.running or not self.current_module_id:
            return
        if self.current_module_id not in self._active_modules():
            return
        try:
            text = self._module_text(self.current_module_id)
            if text not in {"", "Chargement…"} and text != self.current_module_text:
                self._transmit(text, self.current_module_id)
                self.current_module_text = text
        except Exception as exc:
            self._append_log(f"Erreur module : {exc}")

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
                self._start_timeline_playhead(module_id, interval)
                self.current_module_text = None
                self.module_refresh_timer.start(self._module_refresh_interval() * 1000)
                if text == "Chargement…":
                    interval = 1
                else:
                    self._transmit(text, module_id)
                    self.current_module_text = text
            else:
                self.active_index %= len(active)
                module_id = active[self.active_index]
                self.active_index = (self.active_index + 1) % len(active)
                text = self._module_text(module_id)
                interval = int(self._module_duration(module_id))
                self._start_timeline_playhead(module_id, interval)
                self.current_module_text = None
                self.module_refresh_timer.start(self._module_refresh_interval() * 1000)
                if text == "Chargement…":
                    interval = 1
                else:
                    self._transmit(text, module_id)
                    self.current_module_text = text
        except Exception as exc:
            self._append_log(f"Erreur module : {exc}")
            interval = int(self.settings["osc"].get("interval", 2))
        self.cycle_timer.start(max(1, interval) * 1000)

    def _start_timeline_playhead(self, module_id: str, duration: int) -> None:
        self.current_module_id = module_id
        self.current_module_started_at = time.monotonic()
        self.current_module_duration = max(1, duration)
        self._update_timeline_playhead()

    def _update_timeline_playhead(self) -> None:
        if not self.running or not self.current_module_id or not hasattr(self, "timeline"):
            return
        elapsed = max(0.0, time.monotonic() - self.current_module_started_at)
        progress = min(1.0, elapsed / self.current_module_duration)
        self.timeline.set_playhead(self.current_module_id, progress)

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
            self.module_refresh_timer.stop()
            self.playhead_timer.stop()
            if self.listener:
                self.listener.stop()
        self.save_all()
        self.store_executor.shutdown(wait=False, cancel_futures=True)
        self.providers.close()
        self.osc.close()
        event.accept()
