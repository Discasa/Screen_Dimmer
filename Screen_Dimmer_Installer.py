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
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

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
        "intro_text": "Install Screen Dimmer from the project Python files.",
        "app_detail_label": "Program script",
        "uninstall_detail_label": "Uninstaller script",
    },
    "exe": {
        "install_mode": "exe",
        "app_artifact_name": "Screen_Dimmer.exe",
        "uninstall_artifact_name": "Screen_Dimmer_Uninstall.exe",
        "intro_text": "Install Screen Dimmer from the packaged executable files.",
        "app_detail_label": "Program executable",
        "uninstall_detail_label": "Uninstaller executable",
    },
}
PROFILE = PROFILE_SETTINGS[BUILD_PROFILE]
INSTALL_MODE = PROFILE["install_mode"]
APP_ARTIFACT_NAME = PROFILE["app_artifact_name"]
UNINSTALL_ARTIFACT_NAME = PROFILE["uninstall_artifact_name"]
INTRO_TEXT = PROFILE["intro_text"]
APP_DETAIL_LABEL = PROFILE["app_detail_label"]
UNINSTALL_DETAIL_LABEL = PROFILE["uninstall_detail_label"]
WINDOW_TITLE = "Screen Dimmer Installer"
ELEVATED_INSTALL_ARG = "--elevated-install"
AUTO_INSTALL_ARG = "--auto-install"
INSTALL_DIR_ARG = "--install-dir"
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
    def bundle_root() -> str:
        if getattr(sys, "frozen", False):
            bundle_dir = getattr(sys, "_MEIPASS", None)
            if bundle_dir:
                return bundle_dir
        return UiHelpers.app_root()

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
    def create_shortcut(
        shortcut_path: str,
        target_path: str,
        working_directory: Optional[str] = None,
        description: str = "",
    ) -> None:
        os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)

        def ps_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        lines = [
            "$shell = New-Object -ComObject WScript.Shell",
            f"$shortcut = $shell.CreateShortcut({ps_quote(shortcut_path)})",
            f"$shortcut.TargetPath = {ps_quote(target_path)}",
        ]
        if working_directory:
            lines.append(f"$shortcut.WorkingDirectory = {ps_quote(working_directory)}")
        if description:
            lines.append(f"$shortcut.Description = {ps_quote(description)}")
        lines.append("$shortcut.Save()")
        script = "; ".join(lines)
        result = WindowsOps.run_hidden([
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to create shortcut.")

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


def resolve_source_file(filename: str) -> str:
    candidates = []
    if BUILD_PROFILE == "exe":
        candidates.extend([
            os.path.join(UiHelpers.bundle_root(), filename),
            os.path.join(UiHelpers.app_root(), filename),
            os.path.join(UiHelpers.app_root(), "dist", filename),
            os.path.join(os.getcwd(), filename),
            os.path.join(os.getcwd(), "dist", filename),
        ])
    else:
        candidates.extend([
            os.path.join(UiHelpers.app_root(), filename),
            os.path.join(os.getcwd(), filename),
        ])
    seen: set[str] = set()
    for candidate in candidates:
        normalized = UiHelpers.normalize_path(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(f"Missing source file: {filename}")



def default_manifest(install_dir: Optional[str] = None) -> dict:
    resolved_install_dir = install_dir or UiHelpers.program_files_x86_dir()
    data_dir = UiHelpers.local_appdata_dir()
    start_menu_dir = UiHelpers.start_menu_folder()
    return {
        "app_name": APP_NAME,
        "install_mode": INSTALL_MODE,
        "installed_at": UiHelpers.utc_now_iso(),
        "install_dir": resolved_install_dir,
        "data_dir": data_dir,
        "app_path": os.path.join(resolved_install_dir, APP_ARTIFACT_NAME),
        "uninstall_path": os.path.join(resolved_install_dir, UNINSTALL_ARTIFACT_NAME),
        "start_menu_folder": start_menu_dir,
        "shortcuts": {
            "app": os.path.join(start_menu_dir, f"{APP_NAME}.lnk"),
            "uninstall": os.path.join(start_menu_dir, f"{APP_NAME} Uninstall.lnk"),
        },
    }


class InstallerWindow(QFrame, DraggableMixin, RoundedWindowMixin):
    def __init__(self, close_on_success: bool = False) -> None:
        QFrame.__init__(self)
        DraggableMixin.__init__(self)
        RoundedWindowMixin.__init__(self, 18)
        self.install_target = UiHelpers.program_files_x86_dir()
        self._install_completed = False
        self._close_on_success = close_on_success
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(510, 360)
        self.setObjectName("InstallerWindow")
        self.setWindowTitle(WINDOW_TITLE)
        self.setAccessibleName("installerWindow")
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            f"""
            QFrame#InstallerWindow {{
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
        body_layout.addWidget(intro)

        target_card = StatusPanel(body)
        target_layout = QVBoxLayout(target_card)
        target_layout.setContentsMargins(14, 12, 14, 12)
        target_layout.setSpacing(4)
        target_title = QLabel("Install location", target_card)
        target_title.setStyleSheet(f"color: {UI_THEME['text']}; font: 8pt 'Segoe UI';")
        target_value = QLabel(self.install_target, target_card)
        target_value.setWordWrap(True)
        target_value.setObjectName("Muted")
        self.target_value = target_value
        target_layout.addWidget(target_title)
        target_layout.addWidget(target_value)
        body_layout.addWidget(target_card)

        details = StatusPanel(body)
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(14, 12, 14, 12)
        details_layout.setSpacing(4)
        line1 = QLabel(f"{APP_DETAIL_LABEL}: {APP_ARTIFACT_NAME}", details)
        line2 = QLabel(f"{UNINSTALL_DETAIL_LABEL}: {UNINSTALL_ARTIFACT_NAME}", details)
        line3 = QLabel(f"Settings folder: {UiHelpers.local_appdata_dir()}", details)
        for label in (line1, line2, line3):
            label.setObjectName("Muted")
            label.setWordWrap(True)
            details_layout.addWidget(label)
        body_layout.addWidget(details)

        self.status_label = QLabel("Ready to install.", body)
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        body_layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        self.browse_button = PillButton("Browse", parent=body)
        self.browse_button.clicked.connect(self._choose_install_target)
        self.browse_button.setObjectName("browseButton")
        self.browse_button.setAccessibleName("browseButton")
        button_row.addWidget(self.browse_button)

        self.install_button = PillButton("Install", variant="accent", parent=body)
        self.install_button.clicked.connect(self._handle_primary_button)
        self.install_button.setObjectName("primaryActionButton")
        self.install_button.setAccessibleName("installButton")
        button_row.addWidget(self.install_button)
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

    def _choose_install_target(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose install directory", self.install_target)
        if not chosen:
            return
        self.install_target = os.path.join(chosen, APP_NAME)
        self.target_value.setText(self.install_target)

    def _set_busy(self, busy: bool) -> None:
        self.install_button.setEnabled(not busy)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        QApplication.processEvents()

    def _handle_primary_button(self) -> None:
        if self._install_completed:
            self.close()
            return
        self._start_install()

    def _start_install(self) -> None:
        self._set_busy(True)
        try:
            completed = self._install()
            if not completed:
                return
            self._install_completed = True
            self._set_status("Installation completed successfully.")
            if self._close_on_success:
                self.close()
                QApplication.instance().quit()
                return
            self.browse_button.hide()
            self.close_button.hide()
            self.install_button.setText("Finish")
            self.install_button.setAccessibleName("finishButton")
            self.install_button.setEnabled(True)
        except Exception as exc:
            self._set_status(f"Install failed: {exc}")
            self._set_busy(False)

    def _validate_source_and_target(self, app_source: str, uninstall_source: str, install_dir: str) -> None:
        normalized_target = UiHelpers.normalize_path(install_dir)
        source_roots = {
            UiHelpers.normalize_path(os.path.dirname(app_source)),
            UiHelpers.normalize_path(os.path.dirname(uninstall_source)),
        }
        if normalized_target in source_roots:
            raise RuntimeError("Install target cannot be the same folder as the source project files.")

    def _install(self) -> bool:
        if not WindowsOps.is_admin():
            self._set_status("Requesting administrator permission...")
            relaunch_args = [ELEVATED_INSTALL_ARG, INSTALL_DIR_ARG, self.install_target]
            if self._close_on_success:
                relaunch_args.append(CLOSE_ON_SUCCESS_ARG)
            if WindowsOps.relaunch_as_admin(relaunch_args):
                QApplication.instance().quit()
                return False
            raise RuntimeError("Administrator permission was not granted.")

        app_source = resolve_source_file(APP_ARTIFACT_NAME)
        uninstall_source = resolve_source_file(UNINSTALL_ARTIFACT_NAME)

        install_dir = self.install_target
        self._validate_source_and_target(app_source, uninstall_source, install_dir)

        os.makedirs(install_dir, exist_ok=True)
        os.makedirs(UiHelpers.local_appdata_dir(), exist_ok=True)

        app_target = os.path.join(install_dir, APP_ARTIFACT_NAME)
        uninstall_target = os.path.join(install_dir, UNINSTALL_ARTIFACT_NAME)

        self._set_status("Stopping previous app process if needed...")
        WindowsOps.terminate_process_by_path(app_target)

        self._set_status("Copying application files...")
        shutil.copy2(app_source, app_target)
        shutil.copy2(uninstall_source, uninstall_target)

        self._set_status("Creating Start Menu shortcuts...")
        manifest = default_manifest(install_dir)
        manifest["installed_at"] = UiHelpers.utc_now_iso()
        manifest["app_path"] = app_target
        manifest["uninstall_path"] = uninstall_target

        WindowsOps.create_shortcut(
            manifest["shortcuts"]["app"],
            app_target,
            working_directory=install_dir,
            description="Launch Screen Dimmer",
        )
        WindowsOps.create_shortcut(
            manifest["shortcuts"]["uninstall"],
            uninstall_target,
            working_directory=install_dir,
            description="Uninstall Screen Dimmer",
        )

        self._set_status("Writing install manifest...")
        InstallManifest.save(manifest)
        return True


def parse_launch_options() -> tuple[bool, Optional[str], bool]:
    auto_start_install = False
    install_dir: Optional[str] = None
    close_on_success = False
    args = sys.argv[1:]
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {ELEVATED_INSTALL_ARG, AUTO_INSTALL_ARG}:
            auto_start_install = True
        elif arg == INSTALL_DIR_ARG and index + 1 < len(args):
            path_parts = [args[index + 1]]
            index += 1
            while index + 1 < len(args) and not args[index + 1].startswith("--"):
                path_parts.append(args[index + 1])
                index += 1
            install_dir = " ".join(path_parts)
        elif arg == CLOSE_ON_SUCCESS_ARG:
            close_on_success = True
        index += 1
    return auto_start_install, install_dir, close_on_success


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    auto_start_install, install_dir, close_on_success = parse_launch_options()
    window = InstallerWindow(close_on_success=close_on_success)
    if install_dir:
        window.install_target = install_dir
        window.target_value.setText(install_dir)
    window.show()
    if auto_start_install:
        QTimer.singleShot(0, window._start_install)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
