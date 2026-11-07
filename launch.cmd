@echo off
setlocal
if not defined FENN_DATA_DIR set "FENN_DATA_DIR=%APPDATA%\Fenn\plugin-data\drop-to-convert"
set "PLUGIN_PYTHON=%FENN_DATA_DIR%\venv\Scripts\python.exe"
if not exist "%PLUGIN_PYTHON%" (
    >&2 echo Drop-to-Convert is missing its Python environment. Run install.cmd from the repository.
    exit /b 1
)
"%PLUGIN_PYTHON%" -B "%~dp0main.py"
exit /b %errorlevel%
