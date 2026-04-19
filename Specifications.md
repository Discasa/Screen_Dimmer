# Specifications

## Overview

This repository contains three main application flows:

1. `Screen_Dimmer.py`
   The main dimmer application.
2. `Screen_Dimmer_Installer.py`
   A custom frameless installer that can work in two profiles:
   - `py` profile for editable/local Python-based installs
   - `exe` profile for packaged release installs
3. `Screen_Dimmer_Uninstall.py`
   A matching custom frameless uninstaller, also supporting both `py` and `exe` deployment modes.

The application is designed around a Windows-native installation layout, local AppData persistence, Start Menu shortcuts, and single-instance activation using Qt local sockets.

## Platform

This project is Windows-only by design.

It depends on Windows-specific behavior such as:

- `ShellExecuteW` for elevation
- `%LOCALAPPDATA%` and `%APPDATA%`
- Start Menu shortcut creation
- `Program Files (x86)` installation targets
- `cleanup.cmd` based delayed self-removal during uninstall

## Repository Layout

```text
Screen_Dimmer/
|-- Screen_Dimmer.py
|-- Screen_Dimmer_Installer.py
|-- Screen_Dimmer_Uninstall.py
|-- README.md
|-- Specifications.md
|-- requirements.txt
|-- build_release.bat
`-- img/
    |-- Screen_Dimmer.ico
    |-- Screen_Dimmer_Installer.ico
    |-- Screen_Dimmer_Uninstall.ico
    `-- source artwork files (.png / .psd)
```

Generated folders such as `build/` and `dist/` are created only during packaging.

## Architecture Summary

### `Screen_Dimmer.py`

The main application is organized around a few core responsibilities:

- `ConfigStore`
  Loads, sanitizes, and saves user settings in `%LOCALAPPDATA%\Screen_Dimmer\settings.json`.
- `OverlayWindow`
  Owns the frameless dimming surface that sits on top of the display.
- `OverlaySession`
  Manages one active overlay session for a display, including runtime styling, animation, and settings dialogs.
- `MiniSettingsDialog` and `FullSettingsDialog`
  Provide compact and expanded controls for color, opacity, theme, animation timing, zoom behavior, and performance settings.
- `CompactColorPicker`
  Supplies a custom frameless color picker with visual selection and hex editing.
- `IpcBridge`
  Uses `QLocalServer` and `QLocalSocket` so the app behaves as a single instance and can activate the relevant display instead of spawning duplicate background processes.
- `DimmerController`
  Coordinates sessions, persistence, theme state, monitor profiles, settings UI, and close behavior.

### `Screen_Dimmer_Installer.py`

The installer is a custom PySide6 window rather than a standard MSI-style setup program.

Its responsibilities are:

- resolve the correct artifact names based on the active `BUILD_PROFILE`
- elevate itself when administrator rights are required
- copy the application and uninstaller into the target installation directory
- create Start Menu shortcuts
- write `install_manifest.json` so the uninstaller knows exactly what was installed and where
- switch its buttons and close behavior appropriately after installation completes

### `Screen_Dimmer_Uninstall.py`

The uninstaller reads the installation manifest and removes everything that belongs to the application.

Its responsibilities are:

- load installation metadata from `install_manifest.json`
- elevate itself when needed
- close running app processes before cleanup
- remove Start Menu entries
- remove the installed app files
- remove `%LOCALAPPDATA%\Screen_Dimmer`
- schedule delayed cleanup via a temporary `cleanup.cmd` so the uninstaller can delete the installation directory after its own process exits

## Runtime Data

### `settings.json`

The main app stores user preferences in:

```text
%LOCALAPPDATA%\Screen_Dimmer\settings.json
```

At a high level, it contains:

- `global`
  Shared app-wide configuration such as theme mode, animation timings, zoom settings, and frame rate
- `monitor_defaults`
  The default color and opacity used when a display has no specific saved profile
- `monitor_profiles`
  Saved per-display settings keyed by monitor identity

This file is used by the main dimmer app.

### `install_manifest.json`

The installer writes:

```text
%LOCALAPPDATA%\Screen_Dimmer\install_manifest.json
```

This file is primarily for the uninstaller, not for the running dimmer itself.

It records installation metadata such as:

- install mode (`py` or `exe`)
- installation directory
- app path
- uninstaller path
- local data directory
- Start Menu folder
- shortcut targets

The uninstaller relies on this file to know what to remove.

## Installation Layout

By default, the installer targets:

```text
C:\Program Files (x86)\Screen_Dimmer
```

Typical installed artifacts include:

- `Screen_Dimmer.py` and `Screen_Dimmer_Uninstall.py` in Python mode
- `Screen_Dimmer.exe` and `Screen_Dimmer_Uninstall.exe` in packaged executable mode
- Start Menu shortcuts under:

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Screen_Dimmer
```

## Requirements

For source/editable usage:

- Windows
- Python 3.x
- PySide6

For packaging releases:

- Windows
- Python 3.x
- PySide6
- PyInstaller available on `PATH`
- Windows PowerShell available on the system

All Python dependencies used by the app and by the build flow are listed in:

```text
requirements.txt
```

Recommended setup:

```bash
pip install -r requirements.txt
```

If you only want to see the package list directly, `requirements.txt` currently contains:

- `PySide6` for the main app, installer, and uninstaller
- `pyinstaller` for `build_release.bat`

`build_release.bat` also calls `powershell` directly to switch the build profile in the installer and uninstaller before packaging. That is an operating-system dependency, not a pip package.

## Running From Source

Before launching from source, install the dependencies:

```bash
pip install -r requirements.txt
```

### Launch the main app

```bash
python Screen_Dimmer.py
```

### Launch the Python-mode installer

```bash
python Screen_Dimmer_Installer.py
```

### Launch the Python-mode uninstaller

```bash
python Screen_Dimmer_Uninstall.py
```

The Python-mode installer is useful during development because it keeps the project easy to edit and test without committing to a release build.

## Development Workflow

The intended day-to-day workflow is:

1. Edit the root `.py` files.
2. Test directly with Python.
3. When you want a release build, run `build_release.bat`.
4. Distribute the generated installer executable from `dist\Screen_Dimmer_Installer.exe`.

This keeps the repository source-first while still supporting a clean packaging flow.

## Build and Packaging Workflow

Packaging is handled by:

```text
build_release.bat
```

The batch file performs the following steps:

1. Creates a temporary `backup` folder.
2. Copies the editable root Python files into that backup folder.
3. Changes the installer and uninstaller `BUILD_PROFILE` from `py` to `exe`.
4. Builds:
   - `Screen_Dimmer.exe`
   - `Screen_Dimmer_Uninstall.exe`
   - `Screen_Dimmer_Installer.exe`
5. Deletes the temporary converted `.py` files from the root after the build phase.
6. Moves the original backed-up `.py` files back to the project root.
7. Removes the temporary `backup` folder.

This means the repository always returns to an editable Python state after the build completes.

### Build command

```bat
build_release.bat
```

Before running the build:

- install the packages from `requirements.txt`
- make sure `pyinstaller` resolves in the active shell
- run the command on Windows, where `powershell` is available

### Expected release outputs

After a successful build, the `dist\` folder contains:

- `Screen_Dimmer.exe`
- `Screen_Dimmer_Uninstall.exe`
- `Screen_Dimmer_Installer.exe`

For distribution, the main entrypoint is:

```text
dist\Screen_Dimmer_Installer.exe
```

## Python Mode vs EXE Mode

The installer and uninstaller support two build profiles.

### Python mode

- Used during development
- Installs `.py` artifacts
- Keeps the project simple to edit and retest
- Useful when you want to verify behavior before building a release

### EXE mode

- Used for packaged distribution
- Installs `.exe` artifacts
- The installer bundles the already built app and uninstaller executables
- Intended for end users who should only receive the release installer

## Advanced / Internal Automation Flags

These flags are useful for testing, scripted validation, or automation.

### Main app

```bash
python Screen_Dimmer.py --auto-close-after-ms 2000
```

This launches the dimmer and automatically closes it after the requested delay.

### Installer

```bash
python Screen_Dimmer_Installer.py --auto-install --install-dir "C:\Program Files (x86)\Screen_Dimmer" --close-on-success
```

Supported internal installer flags:

- `--auto-install`
- `--elevated-install`
- `--install-dir <path>`
- `--close-on-success`

### Uninstaller

```bash
python "C:\Program Files (x86)\Screen_Dimmer\Screen_Dimmer_Uninstall.py" --auto-uninstall --close-on-success
```

Supported internal uninstaller flags:

- `--auto-uninstall`
- `--elevated-uninstall`
- `--close-on-success`

These flags are mainly intended for automated validation and internal workflows, not for normal end users.

## UI Behavior Notes

- The project intentionally uses frameless windows for the main overlay, installer, and uninstaller.
- The red close dot in the custom windows replaces the normal system title bar close control.
- After installation completes, the installer hides the browse button and turns the main action into a `Finish` button.
- After uninstall completes, the uninstaller turns the main action into a `Finish` button.

## Verification Expectations

A correct install/uninstall cycle should produce the following results:

### After install

- the installation directory exists
- the app artifact exists
- the uninstaller artifact exists
- Start Menu shortcuts exist
- `%LOCALAPPDATA%\Screen_Dimmer\install_manifest.json` exists

### After uninstall

- the installation directory is removed
- `%LOCALAPPDATA%\Screen_Dimmer` is removed
- the Start Menu folder is removed
- no running Screen Dimmer process remains

Because uninstall cleanup is asynchronous, there can be a short delay before the final filesystem state is fully clean.
