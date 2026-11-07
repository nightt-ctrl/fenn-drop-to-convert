@echo off
setlocal
if not defined FENN_DATA_DIR set "FENN_DATA_DIR=%APPDATA%\Fenn\plugin-data\drop-to-convert"
set "PLUGIN_PYTHON=%FENN_DATA_DIR%\venv\Scripts\python.exe"
if not exist "%PLUGIN_PYTHON%" goto setup
"%PLUGIN_PYTHON%" -I -B -c "from PIL import Image; import imageio_ffmpeg, pypdfium2" >nul 2>nul
if errorlevel 1 goto setup
:run
"%PLUGIN_PYTHON%" -E -s -B "%~dp0main.py"
exit /b %errorlevel%

:setup
"%SystemRoot%\System32\cscript.exe" //nologo "%~dp0bootstrap.js"
if "%errorlevel%"=="10" goto run
if "%errorlevel%"=="0" exit /b 0
echo {"type":"tile","view":{"type":"text","text":"Setup needed"}}
echo {"type":"page","view":{"type":"text","wrap":true,"text":"Windows could not open the setup screen. Run install.cmd from the Drop-to-Convert repository, then reopen the plugin."}}
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "while ($null -ne [Console]::ReadLine()) {}"
