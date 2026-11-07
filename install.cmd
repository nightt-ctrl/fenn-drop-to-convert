@echo off
setlocal
set "BOOTSTRAP=python"
if not "%~1"=="" set "BOOTSTRAP=%~1"
set "PLUGIN_DIR=%APPDATA%\Fenn\plugins\drop-to-convert"
set "VENV=%APPDATA%\Fenn\plugin-data\drop-to-convert\venv"

"%BOOTSTRAP%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    >&2 echo Install Python 3.11 or newer, or pass its full python.exe path to install.cmd.
    exit /b 1
)
if not exist "%VENV%\Scripts\python.exe" (
    "%BOOTSTRAP%" -m venv "%VENV%"
    if errorlevel 1 exit /b 1
)
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 exit /b 1

if not exist "%PLUGIN_DIR%\" (
    mkdir "%PLUGIN_DIR%"
    if errorlevel 1 exit /b 1
)
if /I not "%~dp0"=="%PLUGIN_DIR%\" (
    for %%F in (conversion.py main.py fenn.py launch.cmd THIRD-PARTY-NOTICES.txt plugin.toml) do (
        copy /y "%~dp0%%F" "%PLUGIN_DIR%\%%F" >nul
        if errorlevel 1 exit /b 1
    )
)
echo Drop-to-Convert installed. Enable Plugin dev mode in Fenn Settings and open the Convert tile.
