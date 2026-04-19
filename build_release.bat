@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
set "BACKUP_DIR=%PROJECT_ROOT%backup"
set "DIST_DIR=%PROJECT_ROOT%dist"
set "BUILD_DIR=%PROJECT_ROOT%build"
set "SPEC_DIR=%BUILD_DIR%\spec"
set "EXIT_CODE=0"

call :prepare_backup || goto :build_failed
call :set_build_profile "%PROJECT_ROOT%Screen_Dimmer_Installer.py" exe || goto :build_failed
call :set_build_profile "%PROJECT_ROOT%Screen_Dimmer_Uninstall.py" exe || goto :build_failed
call :run_build || goto :build_failed
goto :restore_and_exit

:build_failed
set "EXIT_CODE=1"

:restore_and_exit
call :restore_sources
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Build failed.
    exit /b 1
)
call :trim_dist || exit /b 1

echo.
echo Build completed successfully.
echo Ready to distribute:
echo   "%DIST_DIR%\Screen_Dimmer_Installer.exe"
exit /b 0

:prepare_backup
if exist "%BACKUP_DIR%" rmdir /s /q "%BACKUP_DIR%"
mkdir "%BACKUP_DIR%" || exit /b 1
for %%F in (Screen_Dimmer.py Screen_Dimmer_Installer.py Screen_Dimmer_Uninstall.py) do (
    copy /y "%PROJECT_ROOT%%%F" "%BACKUP_DIR%\%%F" >nul || exit /b 1
)
exit /b 0

:set_build_profile
set "TARGET_FILE=%~1"
set "TARGET_PROFILE=%~2"
powershell -NoProfile -Command "$path = $env:TARGET_FILE; $profile = $env:TARGET_PROFILE; $quote = [char]34; $content = Get-Content -LiteralPath $path -Raw; $pattern = 'BUILD_PROFILE = ' + $quote + '(py|exe)' + $quote; $replacement = 'BUILD_PROFILE = ' + $quote + $profile + $quote; $updated = [regex]::Replace($content, $pattern, $replacement, 1); if ($updated -eq $content) { throw 'BUILD_PROFILE marker not found.' }; [System.IO.File]::WriteAllText($path, $updated, [System.Text.UTF8Encoding]::new($false))" || exit /b 1
exit /b 0

:run_build
where pyinstaller >nul 2>nul || exit /b 1
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"
if not exist "%SPEC_DIR%" mkdir "%SPEC_DIR%"

pyinstaller --noconfirm --clean --onefile --windowed --name Screen_Dimmer --icon "%PROJECT_ROOT%img\Screen_Dimmer.ico" --distpath "%DIST_DIR%" --workpath "%BUILD_DIR%\screen_dimmer" --specpath "%SPEC_DIR%" "%PROJECT_ROOT%Screen_Dimmer.py" || exit /b 1
pyinstaller --noconfirm --clean --onefile --windowed --name Screen_Dimmer_Uninstall --icon "%PROJECT_ROOT%img\Screen_Dimmer_Uninstall.ico" --distpath "%DIST_DIR%" --workpath "%BUILD_DIR%\screen_dimmer_uninstall" --specpath "%SPEC_DIR%" "%PROJECT_ROOT%Screen_Dimmer_Uninstall.py" || exit /b 1

if not exist "%DIST_DIR%\Screen_Dimmer.exe" exit /b 1
if not exist "%DIST_DIR%\Screen_Dimmer_Uninstall.exe" exit /b 1

pyinstaller --noconfirm --clean --onefile --windowed --name Screen_Dimmer_Installer --icon "%PROJECT_ROOT%img\Screen_Dimmer_Installer.ico" --add-data "%DIST_DIR%\Screen_Dimmer.exe;." --add-data "%DIST_DIR%\Screen_Dimmer_Uninstall.exe;." --distpath "%DIST_DIR%" --workpath "%BUILD_DIR%\screen_dimmer_installer" --specpath "%SPEC_DIR%" "%PROJECT_ROOT%Screen_Dimmer_Installer.py" || exit /b 1

if not exist "%DIST_DIR%\Screen_Dimmer_Installer.exe" exit /b 1
exit /b 0

:restore_sources
for %%F in (Screen_Dimmer.py Screen_Dimmer_Installer.py Screen_Dimmer_Uninstall.py) do (
    if exist "%PROJECT_ROOT%%%F" del /f /q "%PROJECT_ROOT%%%F"
)
for %%F in (Screen_Dimmer.py Screen_Dimmer_Installer.py Screen_Dimmer_Uninstall.py) do (
    if exist "%BACKUP_DIR%\%%F" move /y "%BACKUP_DIR%\%%F" "%PROJECT_ROOT%%%F" >nul
)
if exist "%BACKUP_DIR%" rmdir /s /q "%BACKUP_DIR%"
exit /b 0

:trim_dist
for %%F in (Screen_Dimmer.exe Screen_Dimmer_Uninstall.exe) do (
    if exist "%DIST_DIR%\%%F" del /f /q "%DIST_DIR%\%%F" || exit /b 1
)
exit /b 0
