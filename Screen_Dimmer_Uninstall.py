import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Optional

from PySide6.QtCore import QPoint, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegion, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

APP_NAME = "Screen_Dimmer"
PROGRAM_DIR_NAME = APP_NAME
START_MENU_FOLDER_NAME = APP_NAME
MANIFEST_FILE_NAME = "install_manifest.json"
BUILD_PROFILE = "py"
PROFILE_SETTINGS = {
    "py": {
        "install_mode": "py",
        "app_artifact_name": "Screen_Dimmer.py",
        "uninstall_artifact_name": "Screen_Dimmer_Uninstall.py",
        "intro_text": "This will remove the installed Python files, local settings and Start Menu shortcuts.",
    },
    "exe": {
        "install_mode": "exe",
        "app_artifact_name": "Screen_Dimmer.exe",
        "uninstall_artifact_name": "Screen_Dimmer_Uninstall.exe",
        "intro_text": "This will remove the installed executables, local settings and Start Menu shortcuts.",
    },
}
PROFILE = PROFILE_SETTINGS[BUILD_PROFILE]
INSTALL_MODE = PROFILE["install_mode"]
APP_ARTIFACT_NAME = PROFILE["app_artifact_name"]
UNINSTALL_ARTIFACT_NAME = PROFILE["uninstall_artifact_name"]
INTRO_TEXT = PROFILE["intro_text"]
WINDOW_TITLE = "Screen Dimmer Uninstall"
ELEVATED_UNINSTALL_ARG = "--elevated-uninstall"
AUTO_UNINSTALL_ARG = "--auto-uninstall"
CLOSE_ON_SUCCESS_ARG = "--close-on-success"

UI_THEME = {
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
    "danger": "#D85E59",
    "danger_hover": "#E46A65",
}


class UiHelpers:
    @staticmethod
    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def app_root() -> str:
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(sys.argv[0]))

    @staticmethod
    def normalize_path(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    @staticmethod
    def local_appdata_dir() -> str:
        base = os.getenv("LOCALAPPDATA")
        if not base:
            base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, APP_NAME)

    @staticmethod
    def program_files_x86_dir() -> str:
        base = os.getenv("ProgramFiles(x86)") or os.getenv("ProgramFiles") or r"C:\Program Files (x86)"
        return os.path.join(base, PROGRAM_DIR_NAME)

    @staticmethod
    def start_menu_programs_dir() -> str:
        appdata = os.getenv("APPDATA")
        if not appdata:
            appdata = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs")

    @staticmethod
    def start_menu_folder() -> str:
        return os.path.join(UiHelpers.start_menu_programs_dir(), START_MENU_FOLDER_NAME)

    @staticmethod
    def manifest_path() -> str:
        return os.path.join(UiHelpers.local_appdata_dir(), MANIFEST_FILE_NAME)


class RoundedWindowMixin:
    def __init__(self, radius: int = 16) -> None:
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


class DotButton(QPushButton):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_theme()

    def set_theme(self) -> None:
        self.setStyleSheet(
            f"""
            QPushButton {{
                background: {UI_THEME['danger']};
                border: none;
                border-radius: 9px;
            }}
            QPushButton:hover {{
                background: {UI_THEME['danger_hover']};
            }}
            QPushButton:disabled {{
                background: {UI_THEME['button_disabled_bg']};
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
        self.setMinimumWidth(96)
        self.setFlat(True)
        self.set_theme()

    def set_theme(self) -> None:
        if self.variant == "accent":
            bg = UI_THEME["accent"]
            fg = "#FFFFFF"
            hover = bg
        else:
            bg = UI_THEME["button_bg"]
            fg = UI_THEME["button_fg"]
            hover = UI_THEME["button_hover"]
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
                background: {UI_THEME['button_disabled_bg']};
                color: {UI_THEME['button_disabled_fg']};
            }}
            """
        )


class StatusPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(70)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 12, 12)
        painter.fillPath(path, QColor(UI_THEME["card_bg"]))
        painter.setPen(QPen(QColor(UI_THEME["border"]), 1))
        painter.drawPath(path)
        painter.end()


class InstallManifest:
    @staticmethod
    def load(path: Optional[str] = None) -> Optional[dict]:
        manifest_path = path or UiHelpers.manifest_path()
        if not os.path.exists(manifest_path):
            return None
        try:
            with open(manifest_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def save(data: dict, path: Optional[str] = None) -> str:
        manifest_path = path or UiHelpers.manifest_path()
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(prefix="manifest_", suffix=".json", dir=os.path.dirname(manifest_path))
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as temp_file:
                json.dump(data, temp_file, indent=4)
            os.replace(temp_path, manifest_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        return manifest_path


class WindowsOps:
    @staticmethod
    def is_admin() -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    @staticmethod
    def relaunch_as_admin(extra_args: Optional[list[str]] = None) -> bool:
        if WindowsOps.is_admin():
            return False
        if getattr(sys, "frozen", False):
            executable = sys.executable
            parameters = subprocess.list2cmdline(list(extra_args if extra_args is not None else sys.argv[1:]))
        else:
            executable = sys.executable
            launch_args = [os.path.abspath(sys.argv[0]), *(extra_args if extra_args is not None else sys.argv[1:])]
            parameters = subprocess.list2cmdline(launch_args)
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, parameters, None, 1)
        return result > 32

    @staticmethod
    def run_hidden(command: list[str]) -> subprocess.CompletedProcess:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return subprocess.run(command, startupinfo=startupinfo, capture_output=True, text=True)

    @staticmethod
    def remove_path(path: str) -> None:
        if not path or not os.path.exists(path):
            return
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass

    @staticmethod
    def terminate_process_by_path(target_path: str) -> None:
        normalized = UiHelpers.normalize_path(target_path)

        def ps_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        script = (
            "$target = [System.IO.Path]::GetFullPath(" + ps_quote(normalized) + "); "
            "$targetLower = $target.ToLowerInvariant(); "
            "Get-CimInstance Win32_Process | ForEach-Object { "
            "$exe = ''; "
            "$cmd = ''; "
            "try { if ($_.ExecutablePath) { $exe = [System.IO.Path]::GetFullPath($_.ExecutablePath).ToLowerInvariant() } } catch {} "
            "try { if ($_.CommandLine) { $cmd = $_.CommandLine.ToLowerInvariant() } } catch {} "
            "if ($exe -eq $targetLower -or $cmd.Contains($targetLower)) { "
            "try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} "
            "} "
            "}"
        )
        WindowsOps.run_hidden([
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ])

    @staticmethod
    def schedule_self_delete(script_path: str, install_dir: str, data_dir: str, start_menu_folder: str) -> None:
        temp_dir = tempfile.mkdtemp(prefix="screen_dimmer_uninstall_")
        cleanup_dir = temp_dir
        cleanup_path = os.path.join(cleanup_dir, "cleanup.cmd")
        neutral_dir = os.getenv("SystemRoot") or r"C:\Windows"
        script = f"""@echo off
setlocal
cd /d "{neutral_dir}" >nul 2>&1
:wait_script
>nul 2>&1 ping 127.0.0.1 -n 2
if exist "{script_path}" (
    del /f /q "{script_path}" >nul 2>&1
    if exist "{script_path}" goto wait_script
)
:cleanup_install
if exist "{install_dir}" (
    attrib -r -h -s "{install_dir}" /s /d >nul 2>&1
    rmdir /s /q "{install_dir}" >nul 2>&1
    if exist "{install_dir}" (
        >nul 2>&1 ping 127.0.0.1 -n 2
        goto cleanup_install
    )
)
:cleanup_data
if exist "{data_dir}" (
    attrib -r -h -s "{data_dir}" /s /d >nul 2>&1
    del /f /q "{os.path.join(data_dir, MANIFEST_FILE_NAME)}" >nul 2>&1
    rmdir /s /q "{data_dir}" >nul 2>&1
    if exist "{data_dir}" (
        >nul 2>&1 ping 127.0.0.1 -n 2
        goto cleanup_data
    )
)
:cleanup_menu
if exist "{start_menu_folder}" (
    attrib -r -h -s "{start_menu_folder}" /s /d >nul 2>&1
    rmdir /s /q "{start_menu_folder}" >nul 2>&1
    if exist "{start_menu_folder}" (
        >nul 2>&1 ping 127.0.0.1 -n 2
        goto cleanup_menu
    )
)
:cleanup_self
del /f /q "{cleanup_path}" >nul 2>&1
rmdir /s /q "{cleanup_dir}" >nul 2>&1
"""
        with open(cleanup_path, "w", encoding="utf-8", newline="\r\n") as file:
            file.write(script)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            ["cmd", "/d", "/c", cleanup_path],
            cwd=neutral_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )



def default_manifest() -> dict:
    install_dir = UiHelpers.program_files_x86_dir()
    data_dir = UiHelpers.local_appdata_dir()
    start_menu_dir = UiHelpers.start_menu_folder()
    return {
        "app_name": APP_NAME,
        "install_mode": INSTALL_MODE,
        "installed_at": UiHelpers.utc_now_iso(),
        "install_dir": install_dir,
        "data_dir": data_dir,
        "app_path": os.path.join(install_dir, APP_ARTIFACT_NAME),
        "uninstall_path": os.path.join(install_dir, UNINSTALL_ARTIFACT_NAME),
        "start_menu_folder": start_menu_dir,
        "shortcuts": {
            "app": os.path.join(start_menu_dir, f"{APP_NAME}.lnk"),
            "uninstall": os.path.join(start_menu_dir, f"{APP_NAME} Uninstall.lnk"),
        },
    }


class UninstallWindow(QFrame, DraggableMixin, RoundedWindowMixin):
    def __init__(self, close_on_success: bool = False) -> None:
        QFrame.__init__(self)
        DraggableMixin.__init__(self)
        RoundedWindowMixin.__init__(self, 18)
        self.manifest = InstallManifest.load() or default_manifest()
        self._uninstall_completed = False
        self._close_on_success = close_on_success
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(470, 310)
        self.setObjectName("UninstallWindow")
        self.setWindowTitle(WINDOW_TITLE)
        self.setAccessibleName("uninstallWindow")
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            f"""
            QFrame#UninstallWindow {{
                background: transparent;
            }}
            QFrame#Shell {{
                background: {UI_THEME['window_bg']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 17px;
            }}
            QWidget#Header {{
                background: {UI_THEME['header_bg']};
                border-top-left-radius: 17px;
                border-top-right-radius: 17px;
            }}
            QLabel {{
                color: {UI_THEME['text']};
                font: 9pt 'Segoe UI';
            }}
            QLabel#Muted {{
                color: {UI_THEME['muted']};
                font: 8pt 'Segoe UI';
            }}
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        shell = QFrame(self)
        shell.setObjectName("Shell")
        outer.addWidget(shell)

        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        header = QWidget(shell)
        header.setObjectName("Header")
        header.setFixedHeight(40)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 12, 0)
        header_layout.setSpacing(8)

        title = QLabel(WINDOW_TITLE, header)
        header_layout.addWidget(title)
        header_layout.addStretch(1)

        self.close_button = DotButton(header)
        self.close_button.clicked.connect(self.close)
        self.close_button.setObjectName("closeButton")
        self.close_button.setAccessibleName("closeButton")
        header_layout.addWidget(self.close_button)
        shell_layout.addWidget(header)

        body = QWidget(shell)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 14)
        body_layout.setSpacing(12)

        intro = QLabel(INTRO_TEXT, body)
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        body_layout.addWidget(intro)

        summary = StatusPanel(body)
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(4)
        app_line = QLabel(self.manifest.get("app_path", ""), summary)
        data_line = QLabel(self.manifest.get("data_dir", UiHelpers.local_appdata_dir()), summary)
        menu_line = QLabel(self.manifest.get("start_menu_folder", UiHelpers.start_menu_folder()), summary)
        for label in (app_line, data_line, menu_line):
            label.setObjectName("Muted")
            label.setWordWrap(True)
            summary_layout.addWidget(label)
        body_layout.addWidget(summary)

        self.status_label = QLabel("Ready to uninstall.", body)
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        body_layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.uninstall_button = PillButton("Uninstall", variant="accent", parent=body)
        self.uninstall_button.clicked.connect(self._handle_primary_button)
        self.uninstall_button.setObjectName("primaryActionButton")
        self.uninstall_button.setAccessibleName("uninstallButton")
        button_row.addWidget(self.uninstall_button)
        body_layout.addLayout(button_row)
        shell_layout.addWidget(body)

        header.mousePressEvent = self._header_mouse_press
        header.mouseMoveEvent = self._header_mouse_move
        header.mouseReleaseEvent = self._header_mouse_release
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        shortcut = QShortcut(Qt.Key.Key_Escape, self)
        shortcut.activated.connect(self.close)

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

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        QApplication.processEvents()

    def _handle_primary_button(self) -> None:
        if self._uninstall_completed:
            self.close()
            return
        self._start_uninstall()

    def _start_uninstall(self) -> None:
        self.uninstall_button.setEnabled(False)
        try:
            completed = self._uninstall()
            if completed:
                self._uninstall_completed = True
                if self._close_on_success:
                    self.close()
                    QApplication.instance().quit()
                    return
                self._set_status("Uninstall scheduled. Click Finish to close.")
                self.uninstall_button.setText("Finish")
                self.uninstall_button.setAccessibleName("finishButton")
                self.uninstall_button.setEnabled(True)
            else:
                self._set_status("Administrator elevation requested.")
        except Exception as exc:
            self._set_status(f"Uninstall failed: {exc}")
            self.uninstall_button.setEnabled(True)

    def _uninstall(self) -> bool:
        if not WindowsOps.is_admin():
            relaunch_args = [ELEVATED_UNINSTALL_ARG]
            if self._close_on_success:
                relaunch_args.append(CLOSE_ON_SUCCESS_ARG)
            if WindowsOps.relaunch_as_admin(relaunch_args):
                QApplication.instance().quit()
                return False
            raise RuntimeError("Administrator permission was not granted.")

        app_path = self.manifest.get("app_path") or os.path.join(self.manifest.get("install_dir", ""), APP_ARTIFACT_NAME)
        uninstall_path = self.manifest.get("uninstall_path") or os.path.abspath(
            sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
        )
        install_dir = self.manifest.get("install_dir") or os.path.dirname(app_path)
        data_dir = self.manifest.get("data_dir") or UiHelpers.local_appdata_dir()
        start_menu_folder = self.manifest.get("start_menu_folder") or UiHelpers.start_menu_folder()

        self._set_status("Closing running processes...")
        if app_path:
            WindowsOps.terminate_process_by_path(app_path)

        self._set_status("Removing Start Menu shortcuts...")
        for shortcut_path in (self.manifest.get("shortcuts") or {}).values():
            WindowsOps.remove_path(shortcut_path)
        WindowsOps.remove_path(start_menu_folder)

        self._set_status("Removing install manifest...")
        WindowsOps.remove_path(UiHelpers.manifest_path())

        self._set_status("Scheduling final cleanup...")
        WindowsOps.schedule_self_delete(
            script_path=uninstall_path,
            install_dir=install_dir,
            data_dir=data_dir,
            start_menu_folder=start_menu_folder,
        )
        return True


def parse_launch_options() -> tuple[bool, bool]:
    args = sys.argv[1:]
    auto_start_uninstall = any(arg in {ELEVATED_UNINSTALL_ARG, AUTO_UNINSTALL_ARG} for arg in args)
    close_on_success = CLOSE_ON_SUCCESS_ARG in args
    return auto_start_uninstall, close_on_success


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    auto_start_uninstall, close_on_success = parse_launch_options()
    window = UninstallWindow(close_on_success=close_on_success)
    window.show()
    if auto_start_uninstall:
        QTimer.singleShot(0, window._start_uninstall)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
