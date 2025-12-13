@echo off
chcp 65001 >nul
setlocal

echo ================================================
echo ZuJuan login + save cookies
echo ================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "PY=%PROJECT_ROOT%\venv\Scripts\python.exe"

if exist "%PY%" (
  "%PY%" "%SCRIPT_DIR%save_login.py"
) else (
  python "%SCRIPT_DIR%save_login.py"
)

endlocal
