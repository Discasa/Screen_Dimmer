import ctypes
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
    QShortcut,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


APP_FOLDER_NAME = "Screen_Dimmer"
SETTINGS_FILE_NAME = "settings.json"
IPC_SERVER_NAME = "Screen_Dimmer_Controller"
AUTO_CLOSE_AFTER_MS_ARG = "--auto-close-after-ms"
PREVIEW_MID_HOLD_MS = 1000
PREVIEW_STAGE_DELAY_MS = 1000

GEAR_BUTTON_THEME = {
    "bg": "#17181A",
    "fg": "#F3F5FA",
    "hover": "#23262D",
    "border": "#2D3138",
}

DEFAULT_GLOBAL_SETTINGS = {
    "snappy_fade_in": True,
    "snappy_fade_out": True,
    "snappy_fade_in_time": 300,
    "snappy_fade_out_time": 180,
    "snappy_zoom_in": True,
    "snappy_zoom_out": True,
    "snappy_zoom_in_time": 300,
    "snappy_zoom_out_time": 180,
    "animation_frame_rate": 60,
    "snappy_zoom_in_scale": 0.88,
    "snappy_zoom_out_scale": 0.88,
    "ui_dark_mode": True,
}

DEFAULT_MONITOR_SETTINGS = {
    "color": "#000000",
    "opacity": 0.88,
}

THEMES = {
    "light": {
        "window_bg": "#F3F4F7",
        "window_shell": "#E6E8EE",
        "header_bg": "#F3F4F7",
        "card_bg": "#FFFFFF",
        "border": "#D7DBE4",
        "text": "#232731",
        "muted": "#727988",
        "entry_bg": "#ECEEF4",
        "entry_fg": "#232731",
        "button_bg": "#E4E7EF",
        "button_fg": "#232731",
        "button_hover": "#D9DEE8",
        "button_disabled_bg": "#EEF1F5",
        "button_disabled_fg": "#A0A6B2",
        "accent": "#4B67FF",
        "slider_bg": "#FFFFFF",
        "slider_trough": "#D3D8E4",
        "toggle_off": "#D6DAE3",
        "toggle_border": "#CDD2DC",
        "close_dot": "#D85E59",
        "close_dot_hover": "#E46A65",
    },
    "dark": {
        "window_bg": "#242426",
        "window_shell": "#1A1A1C",
        "header_bg": "#242426",
        "card_bg": "#2B2C30",
        "border": "#202126",
        "text": "#ECEDEF",
        "muted": "#B6B8BE",
        "entry_bg": "#52545A",
        "entry_fg": "#ECEDEF",
        "button_bg": "#575960",
        "button_fg": "#ECEDEF",
        "button_hover": "#646771",
        "button_disabled_bg": "#3B3D43",
        "button_disabled_fg": "#8F949E",
        "accent": "#4B67FF",
        "slider_bg": "#2B2C30",
        "slider_trough": "#5B5D66",
        "toggle_off": "#5C5F68",
        "toggle_border": "#5C5F68",
        "close_dot": "#D85E59",
        "close_dot_hover": "#E46A65",
    },
}


class UiHelpers:
    @staticmethod
    def clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    @staticmethod
    def normalize_color(candidate: str) -> Optional[str]:
        if not isinstance(candidate, str):
            return None
        color = QColor(candidate.strip())
        if not color.isValid():
            return None
        return color.name().upper()

    @staticmethod
    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class RoundedWindowMixin:
    def __init__(self, radius: int = 15) -> None:
        self._window_radius = radius

    def _update_window_mask(self) -> None:
        rect = self.rect().adjusted(1, 1, -1, -1)
        if rect.width() <= 0 or rect.height() <= 0:
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), self._window_radius, self._window_radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))


class DraggableMixin:
    def __init__(self) -> None:
        self._drag_offset: Optional[QPoint] = None

    def start_drag(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def perform_drag(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def end_drag(self) -> None:
        self._drag_offset = None


class ConfigStore:
    def __init__(self) -> None:
        self.app_dir = self._get_app_dir()
        self.settings_path = os.path.join(self.app_dir, SETTINGS_FILE_NAME)

    @staticmethod
    def _get_app_dir() -> str:
        appdata = os.getenv("LOCALAPPDATA")
        if not appdata:
            home = os.path.expanduser("~")
            appdata = os.path.join(home, "AppData", "Local")
        return os.path.join(appdata, APP_FOLDER_NAME)

    @staticmethod
    def _sanitize_bool(value, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        return default

    @staticmethod
    def _sanitize_int(value, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(round(float(value)))
            return int(UiHelpers.clamp(parsed, minimum, maximum))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _sanitize_float(value, default: float, minimum: float, maximum: float, digits: int = 2) -> float:
        try:
            parsed = float(value)
            return round(UiHelpers.clamp(parsed, minimum, maximum), digits)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _sanitize_color(value, default: str) -> str:
        normalized = UiHelpers.normalize_color(value)
        return normalized or default

    def _sanitize_global(self, data) -> dict:
        merged = dict(DEFAULT_GLOBAL_SETTINGS)
        if isinstance(data, dict):
            merged.update(data)
        return {
            "snappy_fade_in": self._sanitize_bool(merged.get("snappy_fade_in"), DEFAULT_GLOBAL_SETTINGS["snappy_fade_in"]),
            "snappy_fade_out": self._sanitize_bool(merged.get("snappy_fade_out"), DEFAULT_GLOBAL_SETTINGS["snappy_fade_out"]),
            "snappy_fade_in_time": self._sanitize_int(merged.get("snappy_fade_in_time"), DEFAULT_GLOBAL_SETTINGS["snappy_fade_in_time"], 0, 5000),
            "snappy_fade_out_time": self._sanitize_int(merged.get("snappy_fade_out_time"), DEFAULT_GLOBAL_SETTINGS["snappy_fade_out_time"], 0, 5000),
            "snappy_zoom_in": self._sanitize_bool(merged.get("snappy_zoom_in"), DEFAULT_GLOBAL_SETTINGS["snappy_zoom_in"]),
            "snappy_zoom_out": self._sanitize_bool(merged.get("snappy_zoom_out"), DEFAULT_GLOBAL_SETTINGS["snappy_zoom_out"]),
            "snappy_zoom_in_time": self._sanitize_int(merged.get("snappy_zoom_in_time"), DEFAULT_GLOBAL_SETTINGS["snappy_zoom_in_time"], 0, 5000),
            "snappy_zoom_out_time": self._sanitize_int(merged.get("snappy_zoom_out_time"), DEFAULT_GLOBAL_SETTINGS["snappy_zoom_out_time"], 0, 5000),
            "animation_frame_rate": self._sanitize_int(merged.get("animation_frame_rate"), DEFAULT_GLOBAL_SETTINGS["animation_frame_rate"], 30, 240),
            "snappy_zoom_in_scale": self._sanitize_float(merged.get("snappy_zoom_in_scale"), DEFAULT_GLOBAL_SETTINGS["snappy_zoom_in_scale"], 0.50, 1.0),
            "snappy_zoom_out_scale": self._sanitize_float(merged.get("snappy_zoom_out_scale"), DEFAULT_GLOBAL_SETTINGS["snappy_zoom_out_scale"], 0.50, 1.0),
            "ui_dark_mode": self._sanitize_bool(merged.get("ui_dark_mode"), DEFAULT_GLOBAL_SETTINGS["ui_dark_mode"]),
        }

    def _sanitize_monitor_defaults(self, data) -> dict:
        merged = dict(DEFAULT_MONITOR_SETTINGS)
        if isinstance(data, dict):
            merged.update(data)
        return {
            "color": self._sanitize_color(merged.get("color"), DEFAULT_MONITOR_SETTINGS["color"]),
            "opacity": self._sanitize_float(merged.get("opacity"), DEFAULT_MONITOR_SETTINGS["opacity"], 0.10, 1.0),
        }

    def _sanitize_monitor_profiles(self, profiles) -> dict:
        sanitized: dict[str, dict] = {}
        if not isinstance(profiles, dict):
            return sanitized
        for screen_key, data in profiles.items():
            if not isinstance(screen_key, str) or not isinstance(data, dict):
                continue
            sanitized[screen_key] = {
                "color": self._sanitize_color(data.get("color"), DEFAULT_MONITOR_SETTINGS["color"]),
                "opacity": self._sanitize_float(data.get("opacity"), DEFAULT_MONITOR_SETTINGS["opacity"], 0.10, 1.0),
                "name": str(data.get("name", ""))[:160],
                "last_seen_at": str(data.get("last_seen_at", ""))[:64],
            }
        return sanitized

    def sanitize(self, data) -> dict:
        if isinstance(data, dict) and "global" in data:
            return {
                "global": self._sanitize_global(data.get("global")),
                "monitor_defaults": self._sanitize_monitor_defaults(data.get("monitor_defaults")),
                "monitor_profiles": self._sanitize_monitor_profiles(data.get("monitor_profiles")),
            }

        legacy_global = self._sanitize_global(data)
        legacy_defaults = self._sanitize_monitor_defaults(data)
        return {
            "global": legacy_global,
            "monitor_defaults": legacy_defaults,
            "monitor_profiles": {},
        }

    def load(self) -> dict:
        os.makedirs(self.app_dir, exist_ok=True)
        if not os.path.exists(self.settings_path):
            settings = self.sanitize({})
            self.save(settings)
            return settings

        try:
            with open(self.settings_path, "r", encoding="utf-8") as file:
                loaded = json.load(file)
        except (OSError, json.JSONDecodeError):
            loaded = {}

        settings = self.sanitize(loaded)
        if settings != loaded:
            self.save(settings)
        return settings

    def save(self, settings: dict) -> None:
        os.makedirs(self.app_dir, exist_ok=True)
        sanitized = self.sanitize(settings)

        fd, temp_path = tempfile.mkstemp(prefix="settings_", suffix=".json", dir=self.app_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                json.dump(sanitized, temp_file, indent=4)
            os.replace(temp_path, self.settings_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


class EscapeFilter(QObject):
    def __init__(self, controller: "DimmerController") -> None:
        super().__init__()
        self.controller = controller

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                return self.controller.handle_escape()
        return super().eventFilter(watched, event)


class ColorPlane(QWidget):
    colorSelected = Signal(float, float)

    def __init__(self, hue: float = 0.0, saturation: float = 1.0, value: float = 1.0, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._hue = UiHelpers.clamp(hue, 0.0, 1.0)
        self._saturation = UiHelpers.clamp(saturation, 0.0, 1.0)
        self._value = UiHelpers.clamp(value, 0.0, 1.0)
        self._palette = THEMES["dark"]
        self.setFixedSize(220, 180)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_theme(self, palette: dict) -> None:
        self._palette = palette
        self.update()

    def set_hue(self, hue: float) -> None:
        hue = UiHelpers.clamp(hue, 0.0, 1.0)
        if abs(self._hue - hue) < 0.0001:
            return
        self._hue = hue
        self.update()

    def set_sv(self, saturation: float, value: float) -> None:
        self._saturation = UiHelpers.clamp(saturation, 0.0, 1.0)
        self._value = UiHelpers.clamp(value, 0.0, 1.0)
        self.update()

    @property
    def saturation(self) -> float:
        return self._saturation

    @property
    def value(self) -> float:
        return self._value

    def _apply_position(self, position: QPoint) -> None:
        inner = self.rect().adjusted(1, 1, -1, -1)
        if inner.width() <= 0 or inner.height() <= 0:
            return
        x = UiHelpers.clamp(position.x() - inner.left(), 0, inner.width())
        y = UiHelpers.clamp(position.y() - inner.top(), 0, inner.height())
        saturation = x / inner.width()
        value = 1.0 - (y / inner.height())
        self.set_sv(saturation, value)
        self.colorSelected.emit(self._saturation, self._value)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply_position(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_position(event.position().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = 10.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)

        base_color = QColor.fromHsvF(self._hue if self._hue < 1.0 else 0.0, 1.0, 1.0)
        painter.fillPath(path, base_color)

        white_gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        white_gradient.setColorAt(0.0, QColor(255, 255, 255))
        white_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, white_gradient)

        black_gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        black_gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        black_gradient.setColorAt(1.0, QColor(0, 0, 0, 255))
        painter.fillPath(path, black_gradient)

        painter.setClipping(False)
        painter.setPen(QPen(QColor(self._palette["border"]), 1))
        painter.drawPath(path)

        handle_x = rect.left() + self._saturation * rect.width()
        handle_y = rect.top() + (1.0 - self._value) * rect.height()
        outer = QColor("#FFFFFF")
        inner = QColor.fromHsvF(self._hue if self._hue < 1.0 else 0.0, self._saturation, self._value)
        painter.setPen(QPen(QColor(0, 0, 0, 140), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(round(handle_x), round(handle_y)), 7, 7)
        painter.setPen(QPen(outer, 2))
        painter.setBrush(inner)
        painter.drawEllipse(QPoint(round(handle_x), round(handle_y)), 6, 6)
        painter.end()


class HueSlider(QWidget):
    hueChanged = Signal(float)

    def __init__(self, hue: float = 0.0, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._hue = UiHelpers.clamp(hue, 0.0, 1.0)
        self._palette = THEMES["dark"]
        self.setFixedSize(22, 180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_theme(self, palette: dict) -> None:
        self._palette = palette
        self.update()

    def set_hue(self, hue: float) -> None:
        self._hue = UiHelpers.clamp(hue, 0.0, 1.0)
        self.update()

    def _apply_position(self, position: QPoint) -> None:
        inner = self.rect().adjusted(4, 1, -4, -1)
        if inner.height() <= 0:
            return
        y = UiHelpers.clamp(position.y() - inner.top(), 0, inner.height())
        hue = y / inner.height()
        self.set_hue(hue)
        self.hueChanged.emit(self._hue)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply_position(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_position(event.position().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(4, 1, -4, -1)
        radius = rect.width() / 2
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.00, QColor("#FF0000"))
        gradient.setColorAt(1.0 / 6.0, QColor("#FFFF00"))
        gradient.setColorAt(2.0 / 6.0, QColor("#00FF00"))
        gradient.setColorAt(3.0 / 6.0, QColor("#00FFFF"))
        gradient.setColorAt(4.0 / 6.0, QColor("#0000FF"))
        gradient.setColorAt(5.0 / 6.0, QColor("#FF00FF"))
        gradient.setColorAt(1.00, QColor("#FF0000"))
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor(self._palette["border"]), 1))
        painter.drawPath(path)

        marker_y = rect.top() + self._hue * rect.height()
        marker_rect = QRectF(0, marker_y - 4, self.width(), 8)
        marker_path = QPainterPath()
        marker_path.addRoundedRect(marker_rect, 4, 4)
        painter.fillPath(marker_path, QColor(255, 255, 255, 230))
        painter.setPen(QPen(QColor(0, 0, 0, 100), 1))
        painter.drawPath(marker_path)
        painter.end()


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, value: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._checked = bool(value)
        self._palette = THEMES["dark"]
        self.setFixedSize(34, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_theme(self, palette: dict) -> None:
        self._palette = palette
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._checked = not self._checked
            self.update()
            self.toggled.emit(self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(2, 2, -2, -2)
        radius = rect.height() / 2

        if self.isEnabled():
            track_color = QColor(self._palette["accent"] if self._checked else self._palette["toggle_off"])
            border_color = QColor("transparent") if self._checked else QColor(self._palette["toggle_border"])
            knob_color = QColor("#FFFFFF")
        else:
            track_color = QColor(self._palette["slider_trough"])
            border_color = QColor(self._palette["toggle_border"])
            knob_color = QColor(self._palette["border"])

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, track_color)
        if border_color.alpha() > 0:
            painter.setPen(QPen(border_color, 1))
            painter.drawPath(path)
        else:
            painter.setPen(Qt.PenStyle.NoPen)

        knob_diameter = self.height() - 8
        knob_y = 4
        knob_x = self.width() - knob_diameter - 4 if self._checked else 4
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob_color)
        painter.drawEllipse(knob_x, knob_y, knob_diameter, knob_diameter)
        painter.end()


class DotButton(QPushButton):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_theme(self, palette: dict) -> None:
        self.setStyleSheet(
            f"""
            QPushButton {{
                background: {palette['close_dot']};
                border: none;
                border-radius: 9px;
            }}
            QPushButton:hover {{
                background: {palette['close_dot_hover']};
            }}
            QPushButton:disabled {{
                background: {palette['toggle_off']};
            }}
            """
        )


class PillButton(QPushButton):
    def __init__(self, text: str, variant: str = "default", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.variant = variant
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(30)
        self.setMinimumWidth(92)
        self.setFlat(True)

    def set_theme(self, palette: dict) -> None:
        if self.variant == "accent":
            bg = palette["accent"]
            fg = "#FFFFFF"
            hover = bg
        else:
            bg = palette["button_bg"]
            fg = palette["button_fg"]
            hover = palette["button_hover"]
        self.setStyleSheet(
            f"""
            QPushButton {{
                background: {bg};
                color: {fg};
                border: none;
                border-radius: 15px;
                padding: 0 14px;
                font: 8pt 'Segoe UI';
            }}
            QPushButton:hover {{
                background: {hover};
            }}
            QPushButton:disabled {{
                background: {palette['button_disabled_bg']};
                color: {palette['button_disabled_fg']};
            }}
            """
        )


class SettingsCard(QFrame):
    def __init__(self, title: str, palette: dict, minimum_height: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsCard")
        self.setMinimumHeight(minimum_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 8, 10, 8)
        self.layout.setSpacing(6)

        self.title_label = QLabel(title, self)
        self.layout.addWidget(self.title_label)
        self.set_theme(palette)

    def set_theme(self, palette: dict) -> None:
        self.setStyleSheet(
            f"""
            QFrame#SettingsCard {{
                background: {palette['card_bg']};
                border: 1px solid {palette['border']};
                border-radius: 12px;
            }}
            """
        )
        self.title_label.setStyleSheet(f"color: {palette['text']}; font: 9pt 'Segoe UI';")


class SliderRow(QWidget):
    def __init__(
        self,
        title: str,
        minimum: int,
        maximum: int,
        initial: int,
        formatter: Callable[[int], str],
        changed: Callable[[int], None],
        palette: dict,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._formatter = formatter
        self._changed = changed

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(0)
        root_layout.addLayout(header)

        self.title_label = QLabel(title, self)
        self.value_label = QLabel(formatter(initial), self)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header.addWidget(self.title_label)
        header.addWidget(self.value_label, 0, Qt.AlignmentFlag.AlignRight)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(initial)
        self.slider.valueChanged.connect(self._on_changed)
        root_layout.addWidget(self.slider)

        self.set_theme(palette)

    def _on_changed(self, value: int) -> None:
        self.value_label.setText(self._formatter(value))
        self._changed(value)

    def set_theme(self, palette: dict) -> None:
        self.title_label.setStyleSheet(f"color: {palette['text']}; font: 8pt 'Segoe UI';")
        self.value_label.setStyleSheet(f"color: {palette['muted']}; font: 8pt 'Segoe UI';")
        self.slider.setStyleSheet(
            f"""
            QSlider {{ background: transparent; }}
            QSlider::groove:horizontal {{
                background: {palette['slider_trough']};
                height: 4px;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {palette['accent']};
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
                border: none;
            }}
            QSlider::sub-page:horizontal {{
                background: {palette['accent']};
                border-radius: 2px;
            }}
            QSlider::add-page:horizontal {{
                background: {palette['slider_trough']};
                border-radius: 2px;
            }}
            """
        )


class FloatSliderRow(QWidget):
    def __init__(
        self,
        title: str,
        minimum: float,
        maximum: float,
        initial: float,
        step: float,
        formatter: Callable[[float], str],
        changed: Callable[[float], None],
        palette: dict,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.step = step
        self.minimum = minimum
        self.maximum = maximum
        self.formatter = formatter
        self.changed = changed

        scaled_max = int(round((maximum - minimum) / step))
        scaled_initial = int(round((initial - minimum) / step))

        self.row = SliderRow(
            title=title,
            minimum=0,
            maximum=scaled_max,
            initial=scaled_initial,
            formatter=lambda raw: self.formatter(self.to_value(raw)),
            changed=lambda raw: self.changed(self.to_value(raw)),
            palette=palette,
            parent=self,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.row)

    def to_value(self, raw: int) -> float:
        return round(self.minimum + raw * self.step, 2)

    def set_theme(self, palette: dict) -> None:
        self.row.set_theme(palette)


class ToggleRow(QWidget):
    def __init__(self, title: str, initial: bool, changed: Callable[[bool], None], palette: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.label = QLabel(title, self)
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle = ToggleSwitch(initial, self)
        self.toggle.toggled.connect(changed)
        layout.addWidget(self.label)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignRight)
        self.set_theme(palette)

    def set_theme(self, palette: dict) -> None:
        self.label.setStyleSheet(f"color: {palette['text']}; font: 8pt 'Segoe UI';")
        self.toggle.set_theme(palette)


class CompactColorPicker(QDialog, RoundedWindowMixin):
    colorApplied = Signal(str)

    def __init__(self, initial_color: str, palette: dict, parent: Optional[QWidget] = None) -> None:
        QDialog.__init__(self, parent)
        RoundedWindowMixin.__init__(self, 15)
        self.palette = palette
        self._current_color = QColor(initial_color)
        if not self._current_color.isValid():
            self._current_color = QColor(DEFAULT_MONITOR_SETTINGS["color"])
        self._stored_hue = 0.0
        self._app_filter_installed = False

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("CompactColorPicker")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(292, 286)

        self.setStyleSheet(
            f"""
            QDialog#CompactColorPicker {{
                background: transparent;
                border: none;
            }}
            QFrame#ColorPickerShell {{
                background: {palette['window_bg']};
                border: 1px solid {palette['border']};
                border-radius: 14px;
            }}
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        shell = QFrame(self)
        shell.setObjectName("ColorPickerShell")
        outer.addWidget(shell)

        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        header = QWidget(shell)
        header.setFixedHeight(36)
        header.setStyleSheet(f"background: {palette['header_bg']}; border-top-left-radius: 14px; border-top-right-radius: 14px;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 0, 10, 0)
        header_layout.setSpacing(8)

        title_label = QLabel("Choose Color", header)
        title_label.setStyleSheet(f"color: {palette['text']}; font: 9pt 'Segoe UI';")
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)

        close_button = DotButton(header)
        close_button.set_theme(palette)
        close_button.clicked.connect(self.close)
        header_layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        shell_layout.addWidget(header)

        body = QWidget(shell)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(12)

        picker_row = QHBoxLayout()
        picker_row.setContentsMargins(0, 0, 0, 0)
        picker_row.setSpacing(10)

        self.color_plane = ColorPlane(parent=body)
        self.color_plane.set_theme(palette)
        picker_row.addWidget(self.color_plane)

        self.hue_slider = HueSlider(parent=body)
        self.hue_slider.set_theme(palette)
        picker_row.addWidget(self.hue_slider)
        body_layout.addLayout(picker_row)

        footer = QWidget(body)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(8)

        html_label = QLabel("HTML", footer)
        html_label.setStyleSheet(f"color: {palette['muted']}; font: 8pt 'Segoe UI';")
        footer_layout.addWidget(html_label)

        self.html_edit = QLineEdit(footer)
        self.html_edit.setFixedHeight(30)
        self.html_edit.setMaxLength(7)
        self.html_edit.setStyleSheet(
            f"background: {palette['entry_bg']};"
            f"color: {palette['entry_fg']};"
            "border: none;"
            "border-radius: 8px;"
            "padding: 6px 10px;"
            "font: 8pt 'Consolas';"
        )
        footer_layout.addWidget(self.html_edit, 1)

        self.preview_swatch = QWidget(footer)
        self.preview_swatch.setFixedSize(24, 24)
        footer_layout.addWidget(self.preview_swatch, 0, Qt.AlignmentFlag.AlignVCenter)

        body_layout.addWidget(footer)
        shell_layout.addWidget(body)

        self.color_plane.colorSelected.connect(self._on_sv_changed)
        self.hue_slider.hueChanged.connect(self._on_hue_changed)
        self.html_edit.textEdited.connect(self._on_html_text_edited)
        self.html_edit.editingFinished.connect(self._on_html_editing_finished)

        shortcut = QShortcut(Qt.Key.Key_Escape, self)
        shortcut.activated.connect(self.close)

        self.set_color(self._current_color, emit=False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_window_mask()
        app = QApplication.instance()
        if app is not None and not self._app_filter_installed:
            app.installEventFilter(self)
            self._app_filter_installed = True
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_window_mask()

    def closeEvent(self, event) -> None:
        app = QApplication.instance()
        if app is not None and self._app_filter_installed:
            app.removeEventFilter(self)
            self._app_filter_installed = False
        super().closeEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        next_widget = QApplication.focusWidget()
        if next_widget is None or not self.isAncestorOf(next_widget):
            QTimer.singleShot(0, self.close)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not self.isVisible():
            return False
        if event.type() == QEvent.Type.MouseButtonPress:
            global_pos = None
            if hasattr(event, "globalPosition"):
                global_pos = event.globalPosition().toPoint()
            elif hasattr(event, "globalPos"):
                global_pos = event.globalPos()
            if global_pos is not None and not self.frameGeometry().contains(global_pos):
                QTimer.singleShot(0, self.close)
        elif event.type() == QEvent.Type.WindowDeactivate:
            active_window = QApplication.activeWindow()
            if active_window is None or (active_window is not self and not self.isAncestorOf(active_window)):
                QTimer.singleShot(0, self.close)
        return False

    def set_color(self, color: QColor, emit: bool = False) -> None:
        if not color.isValid():
            return
        self._current_color = QColor(color)
        hue, saturation, value, _alpha = self._current_color.getHsvF()
        if hue < 0:
            hue = self._stored_hue
        else:
            self._stored_hue = UiHelpers.clamp(hue, 0.0, 1.0)

        self.hue_slider.set_hue(self._stored_hue)
        self.color_plane.set_hue(self._stored_hue)
        self.color_plane.set_sv(saturation, value)

        html = self._current_color.name().upper()
        if self.html_edit.text() != html:
            self.html_edit.setText(html)
        self.preview_swatch.setStyleSheet(f"background: {html}; border: 1px solid {self.palette['border']}; border-radius: 8px;")
        if emit:
            self.colorApplied.emit(html)

    def _on_hue_changed(self, hue: float) -> None:
        self._stored_hue = UiHelpers.clamp(hue, 0.0, 1.0)
        self.color_plane.set_hue(self._stored_hue)
        self._apply_from_hsv(self._stored_hue, self.color_plane.saturation, self.color_plane.value)

    def _on_sv_changed(self, saturation: float, value: float) -> None:
        self._apply_from_hsv(self._stored_hue, saturation, value)

    def _apply_from_hsv(self, hue: float, saturation: float, value: float) -> None:
        color = QColor.fromHsvF(
            UiHelpers.clamp(hue, 0.0, 1.0) if hue < 1.0 else 0.0,
            UiHelpers.clamp(saturation, 0.0, 1.0),
            UiHelpers.clamp(value, 0.0, 1.0),
        )
        self.set_color(color, emit=True)

    def _on_html_text_edited(self, text: str) -> None:
        normalized = UiHelpers.normalize_color(text)
        if normalized is None:
            return
        self.set_color(QColor(normalized), emit=True)

    def _on_html_editing_finished(self) -> None:
        normalized = UiHelpers.normalize_color(self.html_edit.text())
        if normalized is None:
            self.html_edit.setText(self._current_color.name().upper())
            return
        self.set_color(QColor(normalized), emit=True)


class ConfirmDialog(QDialog, DraggableMixin, RoundedWindowMixin):
    def __init__(self, controller: "DimmerController", parent: QWidget) -> None:
        QDialog.__init__(self, parent)
        DraggableMixin.__init__(self)
        RoundedWindowMixin.__init__(self, 13)
        self.controller = controller
        palette = controller.palette

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(True)
        self.setFixedSize(304, 146)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("ConfirmDialog")
        self.setStyleSheet(
            f"""
            QDialog#ConfirmDialog {{ background: transparent; border: none; }}
            QFrame#ConfirmShell {{ background: {palette['window_bg']}; border: 1px solid {palette['border']}; border-radius: 12px; }}
            QWidget#ConfirmHeader {{ background: {palette['header_bg']}; border-top-left-radius: 12px; border-top-right-radius: 12px; }}
            QWidget#ConfirmBody {{ background: transparent; }}
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        shell = QFrame(self)
        shell.setObjectName("ConfirmShell")
        outer.addWidget(shell)

        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        header = QWidget(shell)
        header.setObjectName("ConfirmHeader")
        header.setFixedHeight(34)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 10, 8)
        header_layout.setSpacing(8)

        title = QLabel("Restore defaults", header)
        title.setStyleSheet(f"color: {palette['text']}; font: 9pt 'Segoe UI';")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        header_layout.addWidget(title)
        header_layout.addStretch(1)

        close_button = DotButton(header)
        close_button.set_theme(palette)
        close_button.clicked.connect(self.reject)
        header_layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        shell_layout.addWidget(header)

        body = QWidget(shell)
        body.setObjectName("ConfirmBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 10, 14, 12)
        body_layout.setSpacing(14)

        message = QLabel("Global settings and this display will be restored.", body)
        message.setWordWrap(True)
        message.setStyleSheet(f"color: {palette['muted']}; font: 8pt 'Segoe UI';")
        body_layout.addWidget(message)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        restore_button = PillButton("Restore", variant="accent", parent=body)
        restore_button.setFixedWidth(112)
        restore_button.set_theme(palette)
        restore_button.clicked.connect(self.accept)
        button_row.addWidget(restore_button)
        button_row.addStretch(1)
        body_layout.addLayout(button_row)
        shell_layout.addWidget(body)

        header.mousePressEvent = self._header_mouse_press
        header.mouseMoveEvent = self._header_mouse_move
        header.mouseReleaseEvent = self._header_mouse_release

        shortcut = QShortcut(Qt.Key.Key_Escape, self)
        shortcut.activated.connect(self.reject)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_window_mask()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_window_mask()

    def _header_mouse_press(self, event) -> None:
        self.start_drag(event)

    def _header_mouse_move(self, event) -> None:
        self.perform_drag(event)

    def _header_mouse_release(self, _event) -> None:
        self.end_drag()


class FramelessSettingsBase(QDialog, DraggableMixin, RoundedWindowMixin):
    def __init__(self, session: "OverlaySession", object_name: str, size: tuple[int, int], radius: int) -> None:
        QDialog.__init__(self, session.overlay)
        DraggableMixin.__init__(self)
        RoundedWindowMixin.__init__(self, radius)
        self.session = session
        self.controller = session.controller
        self.palette = self.controller.palette
        self.color_picker: Optional[CompactColorPicker] = None
        self.color_edit: Optional[QLineEdit] = None
        self.choose_button: Optional[PillButton] = None
        self.color_swatch: Optional[QWidget] = None
        self.interactive_widgets: list[QWidget] = []
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName(object_name)
        self.setFixedSize(*size)

    def _line_edit_style(self) -> str:
        return (
            f"background: {self.palette['entry_bg']};"
            f"color: {self.palette['entry_fg']};"
            "border: none;"
            "border-radius: 8px;"
            "padding: 6px 10px;"
            "font: 8pt 'Consolas';"
        )

    def _make_shell(self, radius: int) -> tuple[QFrame, QVBoxLayout]:
        self.setStyleSheet(
            f"""
            QDialog#{self.objectName()} {{ background: transparent; border: none; }}
            QFrame#DialogShell {{ background: {self.palette['window_bg']}; border: 1px solid {self.palette['border']}; border-radius: {radius}px; }}
            """
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        shell = QFrame(self)
        shell.setObjectName("DialogShell")
        outer.addWidget(shell)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        return shell, shell_layout

    def _build_header(self, shell_layout: QVBoxLayout, title_text: str, close_callback: Callable[[], None], radius: int) -> QWidget:
        header = QWidget(self)
        header.setFixedHeight(38)
        header.setStyleSheet(
            f"background: {self.palette['header_bg']}; border-top-left-radius: {radius}px; border-top-right-radius: {radius}px;"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 12, 0)
        header_layout.setSpacing(8)
        title_label = QLabel(title_text, header)
        title_label.setStyleSheet(f"color: {self.palette['text']}; font: 12pt 'Segoe UI';")
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        close_button = DotButton(header)
        close_button.set_theme(self.palette)
        close_button.clicked.connect(close_callback)
        header_layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.interactive_widgets.append(close_button)
        shell_layout.addWidget(header)

        header.mousePressEvent = self._header_mouse_press
        header.mouseMoveEvent = self._header_mouse_move
        header.mouseReleaseEvent = self._header_mouse_release
        title_label.mousePressEvent = self._header_mouse_press
        title_label.mouseMoveEvent = self._header_mouse_move
        title_label.mouseReleaseEvent = self._header_mouse_release
        return header

    def _header_mouse_press(self, event) -> None:
        self.start_drag(event)

    def _header_mouse_move(self, event) -> None:
        self.perform_drag(event)

    def _header_mouse_release(self, _event) -> None:
        self.end_drag()

    def _position_color_picker(self, picker: CompactColorPicker, anchor: QWidget) -> None:
        global_pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 8))
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        if screen is None:
            picker.move(global_pos)
            return
        available = screen.availableGeometry()
        x = global_pos.x()
        y = global_pos.y()
        if x + picker.width() > available.right():
            x = available.right() - picker.width()
        if y + picker.height() > available.bottom():
            y = anchor.mapToGlobal(QPoint(0, -picker.height() - 8)).y()
        x = max(available.left(), x)
        y = max(available.top(), y)
        picker.move(x, y)

    def _toggle_color_picker(self) -> None:
        if self.choose_button is None:
            return
        if self.color_picker is not None and self.color_picker.isVisible():
            self.color_picker.close()
            return
        picker = CompactColorPicker(self.session.profile["color"], self.palette, self)
        picker.colorApplied.connect(self._apply_color_value)
        picker.destroyed.connect(lambda _obj=None: setattr(self, "color_picker", None))
        self.color_picker = picker
        self._position_color_picker(picker, self.choose_button)
        picker.show()
        picker.raise_()
        picker.activateWindow()

    def _apply_color_value(self, color: str) -> None:
        normalized = UiHelpers.normalize_color(color)
        if not normalized:
            return
        if self.color_edit is not None:
            self.color_edit.setText(normalized)
        self._apply_color_to_ui(normalized)
        self.session.update_local_value("color", normalized, apply_runtime=True)

    def _commit_color(self) -> None:
        if self.color_edit is None:
            return
        normalized = UiHelpers.normalize_color(self.color_edit.text()) or self.session.profile["color"]
        self.color_edit.setText(normalized)
        self._apply_color_to_ui(normalized)
        if self.color_picker is not None:
            self.color_picker.set_color(QColor(normalized), emit=False)
        self.session.update_local_value("color", normalized, apply_runtime=True)

    def _apply_color_to_ui(self, color: str) -> None:
        if self.color_swatch is not None:
            self.color_swatch.setStyleSheet(f"background: {color}; border: none; border-radius: 9px;")

    def closeEvent(self, event) -> None:
        if self.color_picker is not None:
            self.color_picker.close()
            self.color_picker = None
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_window_mask()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_window_mask()

    def set_controls_enabled(self, enabled: bool) -> None:
        for widget in self.interactive_widgets:
            widget.setEnabled(enabled)


class MiniSettingsDialog(FramelessSettingsBase):
    def __init__(self, session: "OverlaySession") -> None:
        super().__init__(session, "MiniSettingsDialog", (340, 196), 15)
        shell, shell_layout = self._make_shell(14)
        self._build_header(shell_layout, "Screen Dimmer", self.session.close_settings_window, 14)

        body = QWidget(shell)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 12, 12)
        body_layout.setSpacing(10)

        subtitle = QLabel("This display", body)
        subtitle.setStyleSheet(f"color: {self.palette['muted']}; font: 8pt 'Segoe UI';")
        body_layout.addWidget(subtitle)

        color_row = QWidget(body)
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(8)
        label = QLabel("Color", color_row)
        label.setStyleSheet(f"color: {self.palette['text']}; font: 8pt 'Segoe UI';")
        color_layout.addWidget(label)

        self.color_edit = QLineEdit(self.session.profile["color"], color_row)
        self.color_edit.setFixedWidth(88)
        self.color_edit.setStyleSheet(self._line_edit_style())
        self.interactive_widgets.append(self.color_edit)
        color_layout.addWidget(self.color_edit)

        self.choose_button = PillButton("Choose", parent=color_row)
        self.choose_button.setFixedWidth(92)
        self.choose_button.set_theme(self.palette)
        self.choose_button.clicked.connect(self._toggle_color_picker)
        self.interactive_widgets.append(self.choose_button)
        color_layout.addWidget(self.choose_button)

        self.color_swatch = QWidget(color_row)
        self.color_swatch.setFixedSize(18, 18)
        self._apply_color_to_ui(self.session.profile["color"])
        color_layout.addStretch(1)
        color_layout.addWidget(self.color_swatch)
        body_layout.addWidget(color_row)
        self.color_edit.editingFinished.connect(self._commit_color)

        opacity_row = FloatSliderRow(
            title="Opacity",
            minimum=0.10,
            maximum=1.00,
            initial=self.session.profile["opacity"],
            step=0.01,
            formatter=lambda value: f"{value:.2f}",
            changed=lambda value: self.session.update_local_value("opacity", round(value, 2), apply_runtime=True),
            palette=self.palette,
            parent=body,
        )
        self.interactive_widgets.append(opacity_row.row.slider)
        body_layout.addWidget(opacity_row)

        reset_button = PillButton("Reset This Display", parent=body)
        reset_button.set_theme(self.palette)
        reset_button.setFixedWidth(150)
        reset_button.clicked.connect(self.session.restore_monitor_defaults)
        self.interactive_widgets.append(reset_button)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(reset_button)
        button_row.addStretch(1)
        body_layout.addLayout(button_row)
        shell_layout.addWidget(body)

        shortcut = QShortcut(Qt.Key.Key_Escape, self)
        shortcut.activated.connect(self.session.close_settings_window)

class FullSettingsDialog(FramelessSettingsBase):
    def __init__(self, session: "OverlaySession") -> None:
        super().__init__(session, "FullSettingsDialog", (470, 620), 17)
        self.confirm_dialog: Optional[ConfirmDialog] = None
        shell, shell_layout = self._make_shell(16)
        self._build_header(shell_layout, "Screen Dimmer", self.session.close_settings_window, 16)

        body = QWidget(shell)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 8, 10, 8)
        body_layout.setSpacing(8)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        body_layout.addLayout(grid)

        grid.addWidget(self._build_appearance_card(), 0, 0, 1, 2)
        grid.addWidget(self._build_fade_card("Fade In", "snappy_fade_in", "snappy_fade_in_time"), 1, 0)
        grid.addWidget(self._build_fade_card("Fade Out", "snappy_fade_out", "snappy_fade_out_time"), 1, 1)
        grid.addWidget(self._build_zoom_card("Zoom In", "snappy_zoom_in", "snappy_zoom_in_time", "snappy_zoom_in_scale"), 2, 0)
        grid.addWidget(self._build_zoom_card("Zoom Out", "snappy_zoom_out", "snappy_zoom_out_time", "snappy_zoom_out_scale"), 2, 1)
        grid.addWidget(self._build_performance_card(), 3, 0, 1, 2)

        footer = QWidget(body)
        footer.setFixedHeight(44)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 8, 0, 0)
        footer_layout.setSpacing(10)
        footer_layout.addStretch(1)

        preview_button = PillButton("Preview", parent=footer)
        restore_button = PillButton("Restore", parent=footer)
        preview_button.setFixedWidth(106)
        restore_button.setFixedWidth(106)
        preview_button.set_theme(self.palette)
        restore_button.set_theme(self.palette)
        preview_button.clicked.connect(self.session.preview_current_settings)
        restore_button.clicked.connect(self._confirm_restore)
        footer_layout.addWidget(preview_button)
        footer_layout.addWidget(restore_button)
        footer_layout.addStretch(1)
        self.interactive_widgets.extend([preview_button, restore_button])

        body_layout.addWidget(footer)
        shell_layout.addWidget(body)

        shortcut = QShortcut(Qt.Key.Key_Escape, self)
        shortcut.activated.connect(self.session.close_settings_window)

    def _label(self, text: str, muted: bool = False) -> QLabel:
        label = QLabel(text, self)
        label.setStyleSheet(f"color: {self.palette['muted' if muted else 'text']}; font: 8pt 'Segoe UI';")
        return label

    def _build_appearance_card(self) -> SettingsCard:
        card = SettingsCard("Appearance", self.palette, 122, self)

        color_row = QWidget(card)
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(8)
        color_layout.addWidget(self._label("Color"))

        self.color_edit = QLineEdit(self.session.profile["color"], color_row)
        self.color_edit.setFixedWidth(88)
        self.color_edit.setStyleSheet(self._line_edit_style())
        self.interactive_widgets.append(self.color_edit)
        color_layout.addWidget(self.color_edit)

        self.choose_button = PillButton("Choose", parent=color_row)
        self.choose_button.setFixedWidth(92)
        self.choose_button.set_theme(self.palette)
        self.choose_button.clicked.connect(self._toggle_color_picker)
        self.interactive_widgets.append(self.choose_button)
        color_layout.addWidget(self.choose_button)

        self.color_swatch = QWidget(color_row)
        self.color_swatch.setFixedSize(18, 18)
        self._apply_color_to_ui(self.session.profile["color"])
        color_layout.addStretch(1)
        color_layout.addWidget(self.color_swatch)
        card.layout.addWidget(color_row)
        self.color_edit.editingFinished.connect(self._commit_color)

        opacity_row = FloatSliderRow(
            title="Opacity",
            minimum=0.10,
            maximum=1.00,
            initial=self.session.profile["opacity"],
            step=0.01,
            formatter=lambda value: f"{value:.2f}",
            changed=lambda value: self.session.update_local_value("opacity", round(value, 2), apply_runtime=True),
            palette=self.palette,
            parent=card,
        )
        self.interactive_widgets.append(opacity_row.row.slider)
        card.layout.addWidget(opacity_row)

        dark_mode_row = ToggleRow(
            title="Dark mode",
            initial=self.controller.global_config["ui_dark_mode"],
            changed=lambda value: self.controller.set_theme_mode(bool(value)),
            palette=self.palette,
            parent=card,
        )
        self.interactive_widgets.append(dark_mode_row.toggle)
        card.layout.addWidget(dark_mode_row)
        return card

    def _build_fade_card(self, title: str, enabled_key: str, time_key: str) -> SettingsCard:
        card = SettingsCard(title, self.palette, 96, self)
        toggle_row = ToggleRow(
            title="Enabled",
            initial=self.controller.global_config[enabled_key],
            changed=lambda value, key=enabled_key: self.controller.update_global_value(key, value, apply_runtime=False),
            palette=self.palette,
            parent=card,
        )
        self.interactive_widgets.append(toggle_row.toggle)
        card.layout.addWidget(toggle_row)

        slider_row = SliderRow(
            title="Duration (ms)",
            minimum=0,
            maximum=2000,
            initial=self.controller.global_config[time_key],
            formatter=lambda value: f"{int(value)} ms",
            changed=lambda value, key=time_key: self.controller.update_global_value(key, int(value), apply_runtime=False),
            palette=self.palette,
            parent=card,
        )
        self.interactive_widgets.append(slider_row.slider)
        card.layout.addWidget(slider_row)
        return card

    def _build_zoom_card(self, title: str, enabled_key: str, time_key: str, scale_key: str) -> SettingsCard:
        card = SettingsCard(title, self.palette, 122, self)
        toggle_row = ToggleRow(
            title="Enabled",
            initial=self.controller.global_config[enabled_key],
            changed=lambda value, key=enabled_key: self.controller.update_global_value(key, value, apply_runtime=False),
            palette=self.palette,
            parent=card,
        )
        self.interactive_widgets.append(toggle_row.toggle)
        card.layout.addWidget(toggle_row)

        slider_row = SliderRow(
            title="Duration (ms)",
            minimum=0,
            maximum=2000,
            initial=self.controller.global_config[time_key],
            formatter=lambda value: f"{int(value)} ms",
            changed=lambda value, key=time_key: self.controller.update_global_value(key, int(value), apply_runtime=False),
            palette=self.palette,
            parent=card,
        )
        self.interactive_widgets.append(slider_row.slider)
        card.layout.addWidget(slider_row)

        scale_row = FloatSliderRow(
            title="Scale",
            minimum=0.50,
            maximum=1.00,
            initial=self.controller.global_config[scale_key],
            step=0.01,
            formatter=lambda value: f"{value:.2f}",
            changed=lambda value, key=scale_key: self.controller.update_global_value(key, round(value, 2), apply_runtime=False),
            palette=self.palette,
            parent=card,
        )
        self.interactive_widgets.append(scale_row.row.slider)
        card.layout.addWidget(scale_row)
        return card

    def _build_performance_card(self) -> SettingsCard:
        card = SettingsCard("Performance", self.palette, 74, self)
        slider_row = SliderRow(
            title="Animation FPS",
            minimum=30,
            maximum=240,
            initial=self.controller.global_config["animation_frame_rate"],
            formatter=lambda value: f"{int(value)} FPS",
            changed=lambda value: self.controller.update_global_value("animation_frame_rate", int(value), apply_runtime=False),
            palette=self.palette,
            parent=card,
        )
        self.interactive_widgets.append(slider_row.slider)
        card.layout.addWidget(slider_row)
        return card

    def _confirm_restore(self) -> None:
        dialog = ConfirmDialog(self.controller, self)
        self.confirm_dialog = dialog
        result = dialog.exec()
        self.confirm_dialog = None
        if result == QDialog.DialogCode.Accepted:
            self.controller.restore_primary_defaults(self.session)

    def closeEvent(self, event) -> None:
        if self.confirm_dialog is not None and self.confirm_dialog.isVisible():
            self.confirm_dialog.reject()
            self.confirm_dialog = None
        super().closeEvent(event)


class OverlayWindow(QWidget):
    clicked_empty = Signal()

    def __init__(self, session: "OverlaySession") -> None:
        super().__init__(None)
        self.session = session
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle("Screen Dimmer")
        self.setAccessibleName("screenDimmerOverlay")
        self.base = QWidget(self)
        self.base.setObjectName("OverlayBase")
        self.base.setAccessibleName("overlayBase")
        self.base.mousePressEvent = self._base_mouse_press

        self.gear_button = QPushButton("⚙", self.base)
        self.gear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.gear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gear_button.setFixedSize(30, 30)
        self.gear_button.clicked.connect(self.session.open_settings_window)
        self.gear_button.setObjectName("settingsButton")
        self.gear_button.setAccessibleName("settingsButton")
        self._reposition_children()

    def resizeEvent(self, event) -> None:
        self.base.setGeometry(self.rect())
        self._reposition_children()
        super().resizeEvent(event)

    def _reposition_children(self) -> None:
        self.gear_button.move(12, 12)

    def _base_mouse_press(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked_empty.emit()
        event.accept()

    def apply_runtime_style(self, color: str) -> None:
        self.base.setStyleSheet(f"background: {color}; border: none;")
        self.gear_button.setStyleSheet(
            f"""
            QPushButton {{
                background: {GEAR_BUTTON_THEME['bg']};
                color: {GEAR_BUTTON_THEME['fg']};
                border: 1px solid {GEAR_BUTTON_THEME['border']};
                border-radius: 9px;
                font: 11pt 'Segoe UI Symbol';
            }}
            QPushButton:hover {{
                background: {GEAR_BUTTON_THEME['hover']};
            }}
            """
        )

    def show_settings_button(self, visible: bool) -> None:
        self.gear_button.setVisible(visible)


class OverlaySession(QObject):
    def __init__(self, controller: "DimmerController", screen) -> None:
        super().__init__()
        self.controller = controller
        self.screen = screen
        self.screen_key = controller.screen_key(screen)
        self.profile = controller.ensure_monitor_profile(screen)
        self.overlay = OverlayWindow(self)
        self.overlay.clicked_empty.connect(self.on_overlay_click)
        self.settings_dialog: Optional[QDialog] = None
        self.active_animation: Optional[QTimer] = None
        self.is_closing = False
        self.is_animating = False
        self.is_preview_running = False
        self._screen_geometry = self.screen.geometry()
        self.apply_initial_state()
        self.apply_runtime_settings(skip_geometry=True)
        self.overlay.show()
        self.focus_overlay()
        self.play_intro_animation(show_button_when_done=True)

    def focus_overlay(self) -> None:
        self.overlay.raise_()
        self.overlay.activateWindow()
        self.overlay.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def center_rect(self, width: int, height: int) -> QRect:
        x = self._screen_geometry.x() + max(0, (self._screen_geometry.width() - width) // 2)
        y = self._screen_geometry.y() + max(0, (self._screen_geometry.height() - height) // 2)
        return QRect(x, y, width, height)

    def scaled_rect(self, scale: float) -> QRect:
        scale = UiHelpers.clamp(scale, 0.01, 1.0)
        width = max(1, round(self._screen_geometry.width() * scale))
        height = max(1, round(self._screen_geometry.height() * scale))
        x = self._screen_geometry.x() + (self._screen_geometry.width() - width) // 2
        y = self._screen_geometry.y() + (self._screen_geometry.height() - height) // 2
        return QRect(x, y, width, height)

    def sanitize_duration(self, value) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def stop_active_animation(self) -> None:
        if self.active_animation is not None:
            self.active_animation.stop()
            self.active_animation.deleteLater()
            self.active_animation = None
        self.is_animating = False

    @staticmethod
    def _interpolate(start: float, end: float, factor: float) -> float:
        return start + (end - start) * factor

    def animate_overlay(
        self,
        start_rect: QRect,
        end_rect: QRect,
        start_opacity: float,
        end_opacity: float,
        duration: int,
        easing: QEasingCurve.Type,
        on_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        self.stop_active_animation()
        if duration <= 0:
            self.overlay.setGeometry(end_rect)
            self.overlay.setWindowOpacity(end_opacity)
            if on_complete is not None:
                on_complete()
            return

        self.is_animating = True
        timer = QTimer(self.overlay)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.setInterval(self.controller.frame_duration_ms())
        easing_curve = QEasingCurve(easing)
        start_time = time.perf_counter()

        def finish() -> None:
            timer.stop()
            timer.deleteLater()
            self.active_animation = None
            self.is_animating = False
            self.overlay.setGeometry(end_rect)
            self.overlay.setWindowOpacity(end_opacity)
            if on_complete is not None:
                on_complete()

        def step() -> None:
            elapsed_ms = min(duration, (time.perf_counter() - start_time) * 1000.0)
            progress = UiHelpers.clamp(elapsed_ms / duration, 0.0, 1.0)
            factor = easing_curve.valueForProgress(progress)
            current_rect = QRect(
                round(self._interpolate(start_rect.x(), end_rect.x(), factor)),
                round(self._interpolate(start_rect.y(), end_rect.y(), factor)),
                max(1, round(self._interpolate(start_rect.width(), end_rect.width(), factor))),
                max(1, round(self._interpolate(start_rect.height(), end_rect.height(), factor))),
            )
            current_opacity = self._interpolate(start_opacity, end_opacity, factor)
            self.overlay.setGeometry(current_rect)
            self.overlay.setWindowOpacity(float(current_opacity))
            if elapsed_ms >= duration:
                finish()

        timer.timeout.connect(step)
        self.active_animation = timer
        step()
        timer.start()

    def apply_initial_state(self) -> None:
        self._screen_geometry = self.screen.geometry()
        global_config = self.controller.global_config
        initial_opacity = 0.0 if global_config["snappy_fade_in"] else UiHelpers.clamp(self.profile["opacity"], 0.0, 1.0)
        initial_scale = global_config["snappy_zoom_in_scale"] if global_config["snappy_zoom_in"] else 1.0
        self.overlay.setGeometry(self.scaled_rect(initial_scale))
        self.overlay.setWindowOpacity(initial_opacity)
        self.overlay.show_settings_button(False)

    def apply_runtime_settings(self, skip_geometry: bool = False) -> None:
        self.overlay.apply_runtime_style(self.profile["color"])
        if not skip_geometry and not self.is_animating and not self.is_closing and not self.is_preview_running:
            self.overlay.setGeometry(self.scaled_rect(1.0))
            self.overlay.setWindowOpacity(UiHelpers.clamp(self.profile["opacity"], 0.0, 1.0))
        self.refresh_runtime_visibility()
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            self.settings_dialog.raise_()

    def refresh_runtime_visibility(self) -> None:
        show_button = not self.is_closing and self.settings_dialog is None and not self.is_preview_running
        self.overlay.show_settings_button(show_button)

    def play_intro_animation(self, show_button_when_done: bool = False, on_complete: Optional[Callable[[], None]] = None) -> None:
        global_config = self.controller.global_config
        fade_duration = self.sanitize_duration(global_config["snappy_fade_in_time"]) if global_config["snappy_fade_in"] else 0
        zoom_duration = self.sanitize_duration(global_config["snappy_zoom_in_time"]) if global_config["snappy_zoom_in"] else 0
        duration = max(fade_duration, zoom_duration)
        start_scale = global_config["snappy_zoom_in_scale"] if global_config["snappy_zoom_in"] else 1.0

        def finalize() -> None:
            self.overlay.setGeometry(self.scaled_rect(1.0))
            self.overlay.setWindowOpacity(UiHelpers.clamp(self.profile["opacity"], 0.0, 1.0))
            if show_button_when_done:
                self.refresh_runtime_visibility()
            self.focus_overlay()
            if on_complete is not None:
                on_complete()

        self.animate_overlay(
            start_rect=self.scaled_rect(start_scale),
            end_rect=self.scaled_rect(1.0),
            start_opacity=0.0 if global_config["snappy_fade_in"] else UiHelpers.clamp(self.profile["opacity"], 0.0, 1.0),
            end_opacity=UiHelpers.clamp(self.profile["opacity"], 0.0, 1.0),
            duration=duration,
            easing=QEasingCurve.Type.OutCubic,
            on_complete=finalize,
        )

    def play_outro_animation(self, destroy_on_finish: bool = False, on_complete: Optional[Callable[[], None]] = None) -> None:
        global_config = self.controller.global_config
        fade_duration = self.sanitize_duration(global_config["snappy_fade_out_time"]) if global_config["snappy_fade_out"] else 0
        zoom_duration = self.sanitize_duration(global_config["snappy_zoom_out_time"]) if global_config["snappy_zoom_out"] else 0
        duration = max(fade_duration, zoom_duration)
        end_scale = global_config["snappy_zoom_out_scale"] if global_config["snappy_zoom_out"] else 1.0

        def finalize() -> None:
            self.overlay.setGeometry(self.scaled_rect(end_scale if global_config["snappy_zoom_out"] else 1.0))
            self.overlay.setWindowOpacity(0.0)
            if destroy_on_finish:
                self.overlay.close()
            if on_complete is not None:
                on_complete()

        self.animate_overlay(
            start_rect=self.overlay.geometry(),
            end_rect=self.scaled_rect(end_scale),
            start_opacity=float(self.overlay.windowOpacity()),
            end_opacity=0.0,
            duration=duration,
            easing=QEasingCurve.Type.InCubic,
            on_complete=finalize,
        )

    def update_local_value(self, key: str, value, apply_runtime: bool = True) -> None:
        self.profile[key] = value
        self.controller.update_monitor_profile(self.screen_key, self.profile, self.screen)
        if apply_runtime:
            self.apply_runtime_settings(skip_geometry=False)
        self.controller.schedule_save()

    def on_overlay_click(self) -> None:
        if self.is_closing or self.is_animating or self.is_preview_running:
            return
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            return
        self.request_close()

    def open_settings_window(self) -> None:
        if self.is_closing or self.is_animating or self.is_preview_running:
            return
        dialog_class = FullSettingsDialog if self.controller.is_primary(self.screen_key) else MiniSettingsDialog
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            if isinstance(self.settings_dialog, dialog_class):
                self.settings_dialog.raise_()
                self.settings_dialog.activateWindow()
                return
            self.settings_dialog.close()
            self.settings_dialog = None

        dialog = dialog_class(self)
        dialog.move(self.center_rect(dialog.width(), dialog.height()).topLeft())
        dialog.finished.connect(self._on_settings_finished)
        self.settings_dialog = dialog
        self.overlay.show_settings_button(False)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_settings_finished(self, _result: int) -> None:
        self.settings_dialog = None
        self.controller.save_now()
        self.refresh_runtime_visibility()
        self.focus_overlay()

    def close_settings_window(self) -> None:
        if self.is_preview_running:
            return
        if self.settings_dialog is not None:
            self.settings_dialog.close()

    def preview_current_settings(self) -> None:
        if self.is_closing or self.is_animating or self.is_preview_running:
            return
        self.controller.save_now()
        self.is_preview_running = True
        if self.settings_dialog is not None:
            self.settings_dialog.set_controls_enabled(False)
        self.overlay.show_settings_button(False)

        def after_reopen() -> None:
            self.is_preview_running = False
            if self.settings_dialog is not None:
                self.settings_dialog.set_controls_enabled(True)
                self.settings_dialog.raise_()
                self.settings_dialog.activateWindow()

        def after_preview_outro() -> None:
            self.apply_initial_state()
            QTimer.singleShot(PREVIEW_STAGE_DELAY_MS, lambda: self.play_intro_animation(False, after_reopen))

        def after_preview_intro() -> None:
            QTimer.singleShot(PREVIEW_MID_HOLD_MS, lambda: self.play_outro_animation(False, after_preview_outro))

        self.apply_initial_state()
        QTimer.singleShot(PREVIEW_STAGE_DELAY_MS, lambda: self.play_intro_animation(False, after_preview_intro))

    def restore_monitor_defaults(self) -> None:
        defaults = self.controller.monitor_defaults
        self.profile["color"] = defaults["color"]
        self.profile["opacity"] = defaults["opacity"]
        self.controller.update_monitor_profile(self.screen_key, self.profile, self.screen)
        self.apply_runtime_settings(skip_geometry=False)
        self.controller.rebuild_session_dialog(self)
        self.controller.schedule_save()

    def request_close(self) -> None:
        if self.is_closing or self.is_preview_running:
            return
        self.is_closing = True
        self.overlay.show_settings_button(False)
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            self.settings_dialog.close()
            self.settings_dialog = None
        self.play_outro_animation(True, lambda: self.controller.finish_close_session(self.screen_key))


class _WinPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _WinRect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _WinMonitorInfoExStruct(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("rcMonitor", _WinRect),
        ("rcWork", _WinRect),
        ("dwFlags", ctypes.c_uint32),
        ("szDevice", ctypes.c_wchar * 32),
    ]


class _WinDisplayDevice(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("DeviceName", ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags", ctypes.c_uint32),
        ("DeviceID", ctypes.c_wchar * 128),
        ("DeviceKey", ctypes.c_wchar * 128),
    ]


class WinMonitorInfo:
    MONITOR_DEFAULTTONULL = 0

    @staticmethod
    def _normalize_device_name(device_name: Optional[str]) -> str:
        if not isinstance(device_name, str):
            return ""
        normalized = device_name.strip().upper()
        normalized = normalized.replace("\\.\\", "")
        return normalized

    @staticmethod
    def _normalize_device_id(device_id: Optional[str]) -> str:
        if not isinstance(device_id, str):
            return ""
        return device_id.strip().upper()

    @staticmethod
    def _normalize_device_key(device_key: Optional[str]) -> str:
        if not isinstance(device_key, str):
            return ""
        return device_key.strip().upper()

    @staticmethod
    def _enum_display_device(device_name: Optional[str], index: int = 0) -> Optional[_WinDisplayDevice]:
        if os.name != "nt":
            return None
        display = _WinDisplayDevice()
        display.cb = ctypes.sizeof(_WinDisplayDevice)
        target = device_name if device_name else None
        if not ctypes.windll.user32.EnumDisplayDevicesW(target, index, ctypes.byref(display), 0):
            return None
        return display

    @staticmethod
    def _get_monitor_device_name(monitor_handle) -> Optional[str]:
        if not monitor_handle:
            return None
        info = _WinMonitorInfoExStruct()
        info.cbSize = ctypes.sizeof(_WinMonitorInfoExStruct)
        if not ctypes.windll.user32.GetMonitorInfoW(monitor_handle, ctypes.byref(info)):
            return None
        return WinMonitorInfo._normalize_device_name(info.szDevice)

    @staticmethod
    def get_foreground_monitor_device_name() -> Optional[str]:
        if os.name != "nt":
            return None
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            monitor = user32.MonitorFromWindow(hwnd, WinMonitorInfo.MONITOR_DEFAULTTONULL)
            return WinMonitorInfo._get_monitor_device_name(monitor)
        except Exception:
            return None

    @staticmethod
    def get_cursor_monitor_device_name() -> Optional[str]:
        if os.name != "nt":
            return None
        try:
            user32 = ctypes.windll.user32
            point = _WinPoint()
            if not user32.GetCursorPos(ctypes.byref(point)):
                return None
            monitor = user32.MonitorFromPoint(point, WinMonitorInfo.MONITOR_DEFAULTTONULL)
            return WinMonitorInfo._get_monitor_device_name(monitor)
        except Exception:
            return None

    @staticmethod
    def get_screen_identity(screen) -> dict:
        qt_name = WinMonitorInfo._normalize_device_name((screen.name() or "") if screen is not None else "")
        adapter_name = f"\\.\\{qt_name}" if qt_name else None
        monitor_device = WinMonitorInfo._enum_display_device(adapter_name, 0) if adapter_name else None
        return {
            "qt_name": qt_name,
            "monitor_device_id": WinMonitorInfo._normalize_device_id(getattr(monitor_device, "DeviceID", "")),
            "monitor_device_key": WinMonitorInfo._normalize_device_key(getattr(monitor_device, "DeviceKey", "")),
        }


class IpcBridge(QObject):
    activationRequested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.server: Optional[QLocalServer] = None
        self._sockets: list[QLocalSocket] = []

    @staticmethod
    def has_running_server(timeout_ms: int = 80) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(IPC_SERVER_NAME)
        is_connected = socket.waitForConnected(timeout_ms)
        if is_connected:
            socket.disconnectFromServer()
        return is_connected

    @staticmethod
    def send_activation(screen_key: str) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(IPC_SERVER_NAME)
        if not socket.waitForConnected(150):
            return False
        payload = json.dumps({"screen_key": screen_key}).encode("utf-8")
        socket.write(payload)
        socket.flush()
        socket.waitForBytesWritten(150)
        socket.disconnectFromServer()
        return True

    def start(self) -> bool:
        server = QLocalServer(self)
        if not server.listen(IPC_SERVER_NAME):
            QLocalServer.removeServer(IPC_SERVER_NAME)
            if not server.listen(IPC_SERVER_NAME):
                return False
        server.newConnection.connect(self._on_new_connection)
        self.server = server
        return True

    def _on_new_connection(self) -> None:
        if self.server is None:
            return
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._sockets.append(socket)
            socket.readyRead.connect(lambda sock=socket: self._read_socket(sock))
            socket.disconnected.connect(lambda sock=socket: self._cleanup_socket(sock))

    def _read_socket(self, socket: QLocalSocket) -> None:
        payload = bytes(socket.readAll()).decode("utf-8", errors="ignore")
        try:
            data = json.loads(payload or "{}")
        except json.JSONDecodeError:
            data = {}
        screen_key = data.get("screen_key")
        if isinstance(screen_key, str) and screen_key:
            self.activationRequested.emit(screen_key)
        socket.disconnectFromServer()

    def _cleanup_socket(self, socket: QLocalSocket) -> None:
        if socket in self._sockets:
            self._sockets.remove(socket)
        socket.deleteLater()


class DimmerController(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.config_store = ConfigStore()
        self.settings_data = self.config_store.load()
        self.global_config = dict(self.settings_data["global"])
        self.monitor_defaults = dict(self.settings_data["monitor_defaults"])
        self.monitor_profiles = dict(self.settings_data["monitor_profiles"])
        self.sessions: dict[str, OverlaySession] = {}
        self.session_order: list[str] = []
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_now)
        self.escape_filter = EscapeFilter(self)
        self.app.installEventFilter(self.escape_filter)
        self.ipc_bridge = IpcBridge()
        self.ipc_bridge.activationRequested.connect(self.activate_screen_by_key)

    @property
    def palette(self) -> dict:
        return THEMES["dark"] if self.global_config.get("ui_dark_mode") else THEMES["light"]

    def start_server(self) -> bool:
        return self.ipc_bridge.start()

    def run(self) -> int:
        return self.app.exec()

    def schedule_save(self) -> None:
        self.save_timer.start(90)

    def save_now(self) -> None:
        self.save_timer.stop()
        self.config_store.save(
            {
                "global": self.global_config,
                "monitor_defaults": self.monitor_defaults,
                "monitor_profiles": self.monitor_profiles,
            }
        )

    def frame_duration_ms(self) -> int:
        fps = max(1, int(self.global_config.get("animation_frame_rate", 60)))
        return max(1, round(1000.0 / fps))

    def _legacy_screen_key(self, screen) -> str:
        manufacturer = getattr(screen, "manufacturer", lambda: "")() or ""
        model = getattr(screen, "model", lambda: "")() or ""
        serial = getattr(screen, "serialNumber", lambda: "")() or ""
        geometry = screen.geometry()
        qt_name = (screen.name() or "").strip().upper().replace("\\.\\", "")
        stable = "|".join(part.strip() for part in [manufacturer, model, serial] if part.strip())
        parts = [qt_name]
        if stable:
            parts.append(stable)
        parts.append(f"{geometry.width()}x{geometry.height()}")
        return "|".join(part for part in parts if part)

    def screen_key(self, screen) -> str:
        identity = WinMonitorInfo.get_screen_identity(screen)
        manufacturer = (getattr(screen, "manufacturer", lambda: "")() or "").strip().upper()
        model = (getattr(screen, "model", lambda: "")() or "").strip().upper()
        serial = (getattr(screen, "serialNumber", lambda: "")() or "").strip().upper()
        geometry = screen.geometry()

        monitor_device_id = identity.get("monitor_device_id") or ""
        if monitor_device_id:
            return f"MONITORID|{monitor_device_id}"

        monitor_device_key = identity.get("monitor_device_key") or ""
        if monitor_device_key:
            return f"MONITORKEY|{monitor_device_key}"

        stable_parts = [part for part in [manufacturer, model, serial] if part]
        if len(stable_parts) >= 3:
            return f"QTSTABLE|{'|'.join(stable_parts)}"

        qt_name = identity.get("qt_name") or "DISPLAY"
        descriptive_parts = [part for part in [qt_name, manufacturer, model] if part]
        return f"FALLBACK|{'|'.join(descriptive_parts)}|{geometry.width()}x{geometry.height()}|{geometry.x()},{geometry.y()}"

    def screen_key_aliases(self, screen) -> list[str]:
        aliases: list[str] = []
        for candidate in (self.screen_key(screen), self._legacy_screen_key(screen)):
            if candidate and candidate not in aliases:
                aliases.append(candidate)
        return aliases

    def screen_label(self, screen) -> str:
        name = screen.name().strip() or "Display"
        geometry = screen.geometry()
        return f"{name} ({geometry.width()}x{geometry.height()})"

    def find_screen_by_key(self, screen_key: str):
        for screen in QGuiApplication.screens():
            if screen_key in self.screen_key_aliases(screen):
                return screen
        return None

    @staticmethod
    def _profiles_equal_except_timestamp(left: Optional[dict], right: Optional[dict]) -> bool:
        left_copy = dict(left or {})
        right_copy = dict(right or {})
        left_copy.pop("last_seen_at", None)
        right_copy.pop("last_seen_at", None)
        return left_copy == right_copy

    def _find_existing_profile_key_for_screen(self, screen) -> Optional[str]:
        for candidate in self.screen_key_aliases(screen):
            if candidate in self.monitor_profiles:
                return candidate
        return None

    def ensure_monitor_profile(self, screen) -> dict:
        current_key = self.screen_key(screen)
        existing_key = self._find_existing_profile_key_for_screen(screen)
        existing_profile = self.monitor_profiles.get(existing_key or current_key, {})

        profile = dict(self.monitor_defaults)
        profile.update(existing_profile)
        profile["color"] = UiHelpers.normalize_color(profile.get("color")) or self.monitor_defaults["color"]
        profile["opacity"] = UiHelpers.clamp(float(profile.get("opacity", self.monitor_defaults["opacity"])), 0.10, 1.0)
        profile["name"] = self.screen_label(screen)
        profile["last_seen_at"] = UiHelpers.utc_now_iso()

        previous_current = self.monitor_profiles.get(current_key)
        if existing_key and existing_key != current_key:
            self.monitor_profiles.pop(existing_key, None)
        self.monitor_profiles[current_key] = dict(profile)

        requires_persist = existing_key not in {None, current_key} or previous_current is None
        if not requires_persist:
            requires_persist = not self._profiles_equal_except_timestamp(previous_current, self.monitor_profiles[current_key])
        if requires_persist:
            self.schedule_save()
        return dict(profile)

    def update_monitor_profile(self, screen_key: str, profile: dict, screen) -> None:
        self.monitor_profiles[screen_key] = {
            "color": UiHelpers.normalize_color(profile.get("color")) or self.monitor_defaults["color"],
            "opacity": round(UiHelpers.clamp(float(profile.get("opacity", self.monitor_defaults["opacity"])), 0.10, 1.0), 2),
            "name": self.screen_label(screen),
            "last_seen_at": UiHelpers.utc_now_iso(),
        }

    def is_primary(self, screen_key: str) -> bool:
        return bool(self.session_order) and self.session_order[0] == screen_key

    def activate_screen_by_key(self, screen_key: str) -> None:
        if screen_key in self.sessions:
            return
        screen = self.find_screen_by_key(screen_key)
        if screen is None:
            return
        session = OverlaySession(self, screen)
        self.sessions[screen_key] = session
        self.session_order.append(screen_key)
        self.refresh_all_visibility()

    def activate_initial_screen(self, screen) -> None:
        self.activate_screen_by_key(self.screen_key(screen))

    def refresh_all_visibility(self) -> None:
        for session in self.sessions.values():
            session.refresh_runtime_visibility()

    def update_global_value(self, key: str, value, apply_runtime: bool = True) -> None:
        self.global_config[key] = value
        if apply_runtime:
            for session in self.sessions.values():
                session.apply_runtime_settings(skip_geometry=False)
        self.schedule_save()

    def set_theme_mode(self, is_dark: bool) -> None:
        self.update_global_value("ui_dark_mode", bool(is_dark), apply_runtime=True)
        for session in list(self.sessions.values()):
            self.rebuild_session_dialog(session)

    def rebuild_session_dialog(self, session: OverlaySession) -> None:
        if session.settings_dialog is None or not session.settings_dialog.isVisible():
            return
        position = session.settings_dialog.pos()
        session.settings_dialog.close()
        session.settings_dialog = None
        session.open_settings_window()
        if session.settings_dialog is not None:
            session.settings_dialog.move(position)
            session.settings_dialog.raise_()
            session.settings_dialog.activateWindow()

    def restore_primary_defaults(self, session: OverlaySession) -> None:
        self.global_config = dict(DEFAULT_GLOBAL_SETTINGS)
        session.profile["color"] = self.monitor_defaults["color"]
        session.profile["opacity"] = self.monitor_defaults["opacity"]
        self.update_monitor_profile(session.screen_key, session.profile, session.screen)
        for active in self.sessions.values():
            active.apply_runtime_settings(skip_geometry=False)
        for active in list(self.sessions.values()):
            self.rebuild_session_dialog(active)
        self.save_now()

    def finish_close_session(self, screen_key: str) -> None:
        session = self.sessions.pop(screen_key, None)
        if session is None:
            return
        was_primary = self.is_primary(screen_key)
        self.session_order = [key for key in self.session_order if key != screen_key]
        if was_primary and self.session_order:
            promoted = self.sessions.get(self.session_order[0])
            if promoted is not None and isinstance(promoted.settings_dialog, MiniSettingsDialog):
                promoted.settings_dialog.close()
                promoted.settings_dialog = None
        if not self.sessions:
            self.save_now()
            self.app.quit()
            return
        self.refresh_all_visibility()

    def handle_escape(self) -> bool:
        active_modal = QApplication.activeModalWidget()
        if isinstance(active_modal, ConfirmDialog):
            active_modal.reject()
            return True

        active_window = QApplication.activeWindow()
        if isinstance(active_window, CompactColorPicker):
            active_window.close()
            return True
        if isinstance(active_window, (FullSettingsDialog, MiniSettingsDialog)):
            active_window.close()
            return True
        if isinstance(active_window, OverlayWindow):
            active_window.session.request_close()
            return True

        for screen_key in reversed(self.session_order):
            session = self.sessions.get(screen_key)
            if session is None:
                continue
            dialog = session.settings_dialog
            if isinstance(dialog, FramelessSettingsBase) and dialog.color_picker is not None and dialog.color_picker.isVisible():
                dialog.color_picker.close()
                return True
            if dialog is not None and dialog.isVisible():
                dialog.close()
                return True

        if active_window is not None:
            return False

        if self.session_order:
            primary = self.sessions.get(self.session_order[0])
            if primary is not None:
                primary.request_close()
                return True
        return False


def _find_screen_by_device_name(device_name: Optional[str]):
    if not device_name:
        return None
    normalized_target = device_name.strip().upper().replace("\\.\\", "")
    for screen in QGuiApplication.screens():
        normalized_name = (screen.name() or "").strip().upper().replace("\\.\\", "")
        if normalized_name == normalized_target:
            return screen
    return None


def resolve_launch_screen(has_existing_instance: bool = False):
    cursor_screen = _find_screen_by_device_name(WinMonitorInfo.get_cursor_monitor_device_name())
    if cursor_screen is None:
        cursor_screen = QGuiApplication.screenAt(QCursor.pos())

    foreground_screen = _find_screen_by_device_name(WinMonitorInfo.get_foreground_monitor_device_name())

    if has_existing_instance:
        if cursor_screen is not None:
            return cursor_screen
        if foreground_screen is not None:
            return foreground_screen
        return QGuiApplication.primaryScreen()

    if foreground_screen is not None and cursor_screen is not None:
        if foreground_screen == cursor_screen:
            return foreground_screen
        return foreground_screen

    if foreground_screen is not None:
        return foreground_screen
    if cursor_screen is not None:
        return cursor_screen
    return QGuiApplication.primaryScreen()


def parse_launch_options() -> Optional[int]:
    args = sys.argv[1:]
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == AUTO_CLOSE_AFTER_MS_ARG:
            if index + 1 >= len(args):
                return 0
            try:
                return int(args[index + 1])
            except ValueError:
                return 0
        index += 1
    return None


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    auto_close_after_ms = parse_launch_options()
    has_existing_instance = IpcBridge.has_running_server()
    target_screen = resolve_launch_screen(has_existing_instance=has_existing_instance) or QGuiApplication.primaryScreen()
    if target_screen is None:
        return 1

    temp_controller = DimmerController(app)
    target_screen_key = temp_controller.screen_key(target_screen)
    if IpcBridge.send_activation(target_screen_key):
        return 0

    controller = temp_controller
    if not controller.start_server():
        return 1
    controller.activate_initial_screen(target_screen)
    if auto_close_after_ms is not None:
        delay = max(0, auto_close_after_ms)

        def request_auto_close() -> None:
            if not controller.handle_escape():
                app.quit()

        QTimer.singleShot(delay, request_auto_close)
        QTimer.singleShot(delay + 2500, app.quit)
    return controller.run()


if __name__ == "__main__":
    raise SystemExit(main())
