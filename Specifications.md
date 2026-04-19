# Specifications

This document is the technical reference for the current state of the `Screen_Dimmer` repository. The public-facing overview lives in [README.md](README.md).

## Current Repository State

The repository currently contains:

- `Screen_Dimmer.py`
  Main application entrypoint.
- `Screen_Dimmer_Installer.py`
  Custom frameless installer with `py` and `exe` install profiles.
- `Screen_Dimmer_Uninstall.py`
  Custom frameless uninstaller with matching `py` and `exe` profiles.
- `build_release.bat`
  Release packaging script.
- `requirements.txt`
  Pinned Python dependencies.
- `README.md`
  Public project overview with screenshots.
- `Specifications.md`
  This technical reference.
- `LICENSE`
  MIT license.
- `img/`
  Icon assets, README screenshots, and the packaged source artwork archive.

Generated directories such as `build/`, `dist/`, and `__pycache__/` may exist locally after development or packaging runs, but they are ignored by `.gitignore` and are not source files.

The current `img/` folder includes:

- runtime icons:
  - `Screen_Dimmer.ico`
  - `Screen_Dimmer_Installer.ico`
  - `Screen_Dimmer_Uninstall.ico`
- PNG assets used for documentation or previews:
  - `Screen_Dimmer_Icon.png`
  - `Screen_Dimmer_Install.png`
  - `Screen_Dimmer_Uninstall.png`
  - `Screen_Dimer_PS_01.png`
  - `Screen_Dimer_PS_02.png`
  - `Screen_Dimer_PS_03.png`
  - `Screen_Dimer_PS_04.png`
- packaged artwork source archive:
  - `Screen_Dimmer_PSD.zip`

## Platform and Dependencies

This project is Windows-only by implementation, not just by recommendation.

Current Windows-specific dependencies in the code include:

- `ShellExecuteW` for elevation
- Win32 monitor APIs such as `GetMonitorInfoW`, `EnumDisplayDevicesW`, `MonitorFromWindow`, and `MonitorFromPoint`
- `%LOCALAPPDATA%` and `%APPDATA%`
- Start Menu shortcut creation through PowerShell and `WScript.Shell`
- detached `cleanup.cmd` based self-removal during uninstall

The pinned Python dependencies are:

- `PySide6==6.10.2`
- `pyinstaller==6.19.0`

Runtime expectations:

- source mode requires Python 3.x with `PySide6` available
- release packaging requires Python 3.x, `PyInstaller` on `PATH`, and Windows PowerShell

There is currently no automated test suite in the repository. Validation is driven by direct runtime checks and the internal automation flags exposed by the app, installer, and uninstaller.

## Main Application

The main application lives in `Screen_Dimmer.py`.

### Runtime Architecture

The current runtime structure is centered around these components:

- `ConfigStore`
  Loads, sanitizes, migrates, and atomically saves `%LOCALAPPDATA%\Screen_Dimmer\settings.json`.
- `CompactColorPicker`
  Frameless custom color picker with a color plane, hue slider, hex input, and live preview swatch.
- `MiniSettingsDialog`
  Compact settings window used for non-primary active sessions.
- `FullSettingsDialog`
  Full settings window used for the primary active session, including global animation controls, preview, and restore.
- `OverlayWindow`
  Frameless fullscreen overlay shown on a target display, with a settings button rendered above the tint surface.
- `OverlaySession`
  Owns one active overlay session for one display, including runtime animation, color/opacity updates, settings UI, and close behavior.
- `WinMonitorInfo`
  Resolves Windows monitor identity information used to map stable per-monitor profiles.
- `IpcBridge`
  Implements single-instance activation through `QLocalServer` and `QLocalSocket`.
- `DimmerController`
  Coordinates settings persistence, session ordering, per-monitor profile updates, theme state, runtime save scheduling, and global close behavior.

### Launch and Single-Instance Behavior

The main app is single-instance by design.

Launch flow:

1. The app checks whether a local IPC server named `Screen_Dimmer_Controller` is already running.
2. It resolves the target display.
3. If another instance is already active, it sends an activation request for that display and exits.
4. If no instance is active, it starts the IPC server, creates the initial overlay session, and enters the Qt event loop.

Current display selection logic:

- on first launch, the app prefers the foreground window's monitor, then the cursor monitor, then the primary screen
- when another instance is already running, it prefers the cursor monitor, then the foreground monitor, then the primary screen

This behavior is part of the current implementation and is more specific than a generic "launch on primary monitor" rule.

### Monitor Identity and Profile Persistence

Per-monitor persistence is not keyed only by Qt screen name.

Current key resolution order:

1. Windows monitor device ID
2. Windows monitor device registry key
3. stable Qt manufacturer/model/serial tuple
4. descriptive fallback based on screen name and geometry

This reduces the chance of losing a saved profile when display ordering changes.

Each monitor profile currently stores:

- `color`
- `opacity`
- `name`
- `last_seen_at`

The app also keeps:

- `global`
  Shared UI and animation settings
- `monitor_defaults`
  Default tint and opacity used when a display has no specific saved profile
- `monitor_profiles`
  Per-display saved overrides

### Settings Storage

The main app stores preferences in:

```text
%LOCALAPPDATA%\Screen_Dimmer\settings.json
```

The current persisted schema is:

```json
{
  "global": {
    "snappy_fade_in": true,
    "snappy_fade_out": true,
    "snappy_fade_in_time": 300,
    "snappy_fade_out_time": 180,
    "snappy_zoom_in": true,
    "snappy_zoom_out": true,
    "snappy_zoom_in_time": 300,
    "snappy_zoom_out_time": 180,
    "animation_frame_rate": 60,
    "snappy_zoom_in_scale": 0.88,
    "snappy_zoom_out_scale": 0.88,
    "ui_dark_mode": true
  },
  "monitor_defaults": {
    "color": "#000000",
    "opacity": 0.88
  },
  "monitor_profiles": {}
}
```

Current sanitization rules in `ConfigStore` include:

- opacity clamped to `0.10` through `1.00`
- animation frame rate clamped to `30` through `240`
- zoom scale clamped to `0.50` through `1.00`
- stored duration values clamped to `0` through `5000`
- invalid colors normalized back to the configured defaults

Current UI note:

- the persisted duration sanitizer accepts up to `5000`
- the current settings sliders expose `0` through `2000`

Important distinction:

- `settings.json` is the runtime configuration used by the main app
- `install_manifest.json` is not a runtime dependency of the dimmer itself; it is installation metadata for uninstall logic

### Settings UI Behavior

The UI is intentionally asymmetric between the primary and secondary active sessions.

Current behavior:

- the primary active session uses `FullSettingsDialog`
- non-primary active sessions use `MiniSettingsDialog`

Here, "primary" means the first session in the controller's current session order, not necessarily the operating system's primary monitor.

The current full dialog exposes:

- color selection
- opacity control
- dark mode toggle
- fade in and fade out enablement plus duration
- zoom in and zoom out enablement plus duration and scale
- animation FPS
- preview
- restore defaults confirmation

The current mini dialog exposes:

- color selection
- opacity control
- reset for the current display only

Current preview behavior:

- saves the current settings
- hides interactive controls
- replays the intro and outro animation cycle with delays
- restores dialog interactivity after preview completes

Current close behavior:

- clicking empty overlay space closes that display session
- `Esc` closes color pickers, settings dialogs, confirmation dialogs, or the active overlay session depending on focus state
- when the last overlay session closes, the application exits

### Internal Main-App Flag

The main app currently exposes one internal automation/testing flag:

```text
--auto-close-after-ms <milliseconds>
```

If provided, the app schedules an automatic close request after the given delay.

## Installer

The installer lives in `Screen_Dimmer_Installer.py`.

### Current Build Profile Model

The source tree currently keeps:

```python
BUILD_PROFILE = "py"
```

The installer supports two profiles:

- `py`
  Installs `Screen_Dimmer.py` and `Screen_Dimmer_Uninstall.py`
- `exe`
  Installs `Screen_Dimmer.exe` and `Screen_Dimmer_Uninstall.exe`

The repository is intentionally kept in `py` mode during normal development. `build_release.bat` temporarily rewrites the installer and uninstaller to `exe` mode for packaging, then restores the original source files.

The `py` profile is development-oriented. It copies Python scripts, not a private runtime, so the target machine is expected to have a working Python environment with the required dependencies.

### Source Resolution

The installer resolves source artifacts differently depending on whether it is running from source or from a frozen bundle:

- in `py` mode it looks in the project root / current working directory
- in `exe` mode it looks in the PyInstaller bundle root, the executable directory, and nearby `dist/` locations

This is why the same installer logic can be used both during local development and in the packaged release flow.

### Install Workflow

The current install workflow is:

1. Choose or confirm the install target.
   Default target: `C:\Program Files (x86)\Screen_Dimmer` or the system's resolved `ProgramFiles(x86)` equivalent.
2. If not already elevated, relaunch with administrator rights using `ShellExecuteW(..., "runas", ...)`.
3. Parse relaunch arguments, including install paths with spaces.
4. Resolve the app artifact and uninstall artifact for the active build profile.
5. Refuse to install into the same folder that contains the source project files.
6. Create the install directory and `%LOCALAPPDATA%\Screen_Dimmer`.
7. Stop the previously installed app process if the target app path is already in use.
8. Copy the app and uninstaller artifacts into the install directory.
9. Create Start Menu shortcuts for the app and uninstaller.
10. Write `%LOCALAPPDATA%\Screen_Dimmer\install_manifest.json`.

Current shortcut targets:

- `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Screen_Dimmer\Screen_Dimmer.lnk`
- `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Screen_Dimmer\Screen_Dimmer Uninstall.lnk`

After a successful install:

- the browse button is hidden
- the custom close dot is hidden
- the primary action button becomes `Finish`
- with `--close-on-success`, the installer closes automatically instead

### Install Manifest

The installer writes:

```text
%LOCALAPPDATA%\Screen_Dimmer\install_manifest.json
```

The current manifest fields are:

- `app_name`
- `install_mode`
- `installed_at`
- `install_dir`
- `data_dir`
- `app_path`
- `uninstall_path`
- `start_menu_folder`
- `shortcuts.app`
- `shortcuts.uninstall`

This file is the installation map consumed by the uninstaller. The main dimmer app does not need it for normal operation.

### Internal Installer Flags

The installer currently supports:

- `--auto-install`
- `--elevated-install`
- `--install-dir <path>`
- `--close-on-success`

When auto-start flags are present, the installer defers the actual install call with:

```python
QTimer.singleShot(0, window._start_install)
```

That is the current mechanism used to resume the intended action after relaunch/elevation.

## Uninstaller

The uninstaller lives in `Screen_Dimmer_Uninstall.py`.

### Current Build Profile Model

Like the installer, the uninstaller source tree currently keeps:

```python
BUILD_PROFILE = "py"
```

Its active artifact names depend on the selected profile:

- `py`
  Removes `Screen_Dimmer.py` and `Screen_Dimmer_Uninstall.py`
- `exe`
  Removes `Screen_Dimmer.exe` and `Screen_Dimmer_Uninstall.exe`

### Uninstall Workflow

At startup, the uninstaller loads `%LOCALAPPDATA%\Screen_Dimmer\install_manifest.json` when present. If the manifest is missing, it falls back to the default Windows paths derived from the active build profile.

The current uninstall workflow is:

1. If not elevated, relaunch with administrator rights using `ShellExecuteW(..., "runas", ...)`.
2. Resolve `app_path`, `uninstall_path`, `install_dir`, `data_dir`, and `start_menu_folder` from the manifest or fallback defaults.
3. Terminate the installed app process by matching executable path or command-line path.
4. Remove the Start Menu shortcuts and attempt to remove the Start Menu folder.
5. Remove `%LOCALAPPDATA%\Screen_Dimmer\install_manifest.json`.
6. Spawn a detached cleanup script.

The detached cleanup script:

- waits until the running uninstaller file can be deleted
- removes the install directory
- removes the local app data directory
- removes the Start Menu folder
- deletes itself and its temporary directory

The cleanup script is written as:

```text
cleanup.cmd
```

inside a temporary folder created under `%TEMP%`.

### Asynchronous Cleanup

Uninstall completion is asynchronous by design.

The UI reports success after the cleanup script has been scheduled, not after every file has already disappeared from disk. A filesystem check performed immediately after uninstall can still observe:

- the install directory
- `%LOCALAPPDATA%\Screen_Dimmer`
- the Start Menu folder

for a short period while `cleanup.cmd` is still running.

After a successful uninstall:

- the primary action button becomes `Finish`
- with `--close-on-success`, the uninstaller closes automatically instead

### Internal Uninstaller Flags

The uninstaller currently supports:

- `--auto-uninstall`
- `--elevated-uninstall`
- `--close-on-success`

When auto-start flags are present, the uninstaller defers the actual removal call with:

```python
QTimer.singleShot(0, window._start_uninstall)
```

## Build and Packaging

Release packaging is handled by `build_release.bat`.

### Current Build Sequence

The batch script currently performs these steps:

1. Create a temporary `backup/` directory in the project root.
2. Copy these source files into that backup:
   - `Screen_Dimmer.py`
   - `Screen_Dimmer_Installer.py`
   - `Screen_Dimmer_Uninstall.py`
3. Rewrite `BUILD_PROFILE = "py"` to `BUILD_PROFILE = "exe"` in:
   - `Screen_Dimmer_Installer.py`
   - `Screen_Dimmer_Uninstall.py`
4. Build the main app with PyInstaller:
   - `Screen_Dimmer.exe`
5. Build the uninstaller with PyInstaller:
   - `Screen_Dimmer_Uninstall.exe`
6. Build the installer with PyInstaller and embed both executables via `--add-data`:
   - `Screen_Dimmer_Installer.exe`
7. Restore the original source files from `backup/`.
8. Delete the temporary `backup/` directory.
9. Trim `dist/` by deleting:
   - `Screen_Dimmer.exe`
   - `Screen_Dimmer_Uninstall.exe`

### Actual Release Output

The final release artifact is currently:

```text
dist\Screen_Dimmer_Installer.exe
```

This is important because the packaging script does not leave all three executables in `dist/` after a successful run. It explicitly trims the intermediate app and uninstaller executables at the end.

At the moment, the local `dist/` folder in this repository contains only:

```text
dist\Screen_Dimmer_Installer.exe
```

### Build Inputs and Outputs

Current icon inputs:

- `img\Screen_Dimmer.ico`
- `img\Screen_Dimmer_Uninstall.ico`
- `img\Screen_Dimmer_Installer.ico`

Current PyInstaller work locations:

- `build\screen_dimmer\`
- `build\screen_dimmer_uninstall\`
- `build\screen_dimmer_installer\`
- `build\spec\`

These generated folders are ignored by `.gitignore`, together with:

- `build/`
- `dist/`
- `backup/`
- `*.spec`

## Runtime and Install Paths

Current default paths used across the project:

- local app data:

```text
%LOCALAPPDATA%\Screen_Dimmer
```

- runtime settings file:

```text
%LOCALAPPDATA%\Screen_Dimmer\settings.json
```

- install manifest:

```text
%LOCALAPPDATA%\Screen_Dimmer\install_manifest.json
```

- default install target:

```text
C:\Program Files (x86)\Screen_Dimmer
```

- Start Menu folder:

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Screen_Dimmer
```

These paths may resolve through environment variables such as `ProgramFiles(x86)`, `ProgramFiles`, `LOCALAPPDATA`, and `APPDATA`, but the logical layout above is the current intended Windows installation model.
