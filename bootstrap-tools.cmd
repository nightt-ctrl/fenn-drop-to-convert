@echo off
setlocal
set "SETUP_LOG=%FENN_DATA_DIR%\setup.log"
set "PLUGIN_VENV=%FENN_DATA_DIR%\venv"
set "PLUGIN_RUNTIME=%PLUGIN_VENV%\Scripts\python.exe"
if "%~1"=="probe" goto probe
if "%~1"=="prepare" goto prepare
if "%~1"=="python" goto python
if "%~1"=="runtime" goto runtime
exit /b 1

:probe
"%DTC_SETUP_PYTHON%" -I -B -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
exit /b %errorlevel%

:prepare
if not exist "%FENN_DATA_DIR%\" mkdir "%FENN_DATA_DIR%"
> "%SETUP_LOG%" echo Drop-to-Convert setup
exit /b %errorlevel%

:python
winget.exe install --id Python.Python.3.13 --exact --source winget --scope user --no-upgrade --disable-interactivity >> "%SETUP_LOG%" 2>&1
exit /b %errorlevel%

:runtime
"%DTC_SETUP_PYTHON%" -I -m venv "%PLUGIN_VENV%" >> "%SETUP_LOG%" 2>&1
if errorlevel 1 exit /b 1
set "PIP_CONFIG_FILE=NUL"
"%PLUGIN_RUNTIME%" -I -m pip --isolated install --no-input --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple -r "%~dp0requirements.txt" >> "%SETUP_LOG%" 2>&1
if errorlevel 1 exit /b 1
"%PLUGIN_RUNTIME%" -I -B -c "from PIL import Image; import imageio_ffmpeg, pypdfium2" >> "%SETUP_LOG%" 2>&1
exit /b %errorlevel%
