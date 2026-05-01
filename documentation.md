# Screen Dimmer Documentation

This document is the current operational guide for the Screen Dimmer repository. The deeper implementation reference remains in `Specifications.md`.

## 1. Purpose

Screen Dimmer is a Windows desktop utility that places frameless tinted overlays on one or more displays. Each display can keep its own opacity, tint, and animation behavior.

## 2. Repository Layout

```text
Screen_Dimmer
  Screen_Dimmer.py             Main application entrypoint
  Screen_Dimmer_Installer.py   Custom installer
  Screen_Dimmer_Uninstall.py   Custom uninstaller
  build_release.bat            Release packaging script
  img                          Icons, screenshots, and artwork archive
  img/scripts                  Image-related helper scripts, when present
  requirements.txt             Runtime and build dependencies
  README.md                    User-facing overview
  documentation.md             Operational documentation
  Specifications.md            Detailed technical reference
  CHANGELOG.md                 Project history
  LICENSE                      MIT license
```

Generated folders such as `build`, `dist`, and `__pycache__` are local artifacts and should not be committed.

## 3. Runtime Data

The app stores settings under:

```text
%LOCALAPPDATA%\Screen_Dimmer\settings.json
```

The installer and uninstaller also use Windows-specific shell, shortcut, and cleanup behavior. This project is Windows-only by implementation.

## 4. Main Features

- Full-screen dim overlays for each display.
- Per-monitor opacity and tint profiles.
- Light and dark settings UI.
- Custom hex tint input and color picker.
- Configurable fade and zoom animation timing.
- Single-instance activation through local IPC.
- Custom installer and uninstaller workflows.

## 5. Development

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run from source:

```powershell
python .\Screen_Dimmer.py
```

Build release artifacts:

```powershell
.\build_release.bat
```

Basic syntax validation:

```powershell
python -m py_compile .\Screen_Dimmer.py .\Screen_Dimmer_Installer.py .\Screen_Dimmer_Uninstall.py
```

## 6. Maintenance Guidelines

- Keep `README.md` short and user-facing.
- Keep this file aligned with current operations and release workflow.
- Keep `Specifications.md` aligned with implementation details when architecture changes.
- Update screenshots in `img` when visible UI behavior changes.
- Keep image-related helper scripts under `img/scripts`.
- Validate installer and uninstaller flows on Windows before release.

## 7. License

Screen Dimmer is distributed under the MIT License. See `LICENSE` for the full text.
