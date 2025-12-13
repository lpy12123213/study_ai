@echo off
chcp 65001 >nul 2>&1
setlocal enableextensions

rem Project root (without trailing backslash)
set "ROOT=%~dp0"
set "ROOT_CLEAN=%ROOT:~0,-1%"

rem -------- 1. Ensure venv exists --------
set "PY=%ROOT%venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [1/6] Creating virtual environment...
    python -m venv "%ROOT%venv" || exit /b 1
)

rem -------- 2. Activate venv --------
echo [2/6] Activating virtual environment...
call "%ROOT%venv\Scripts\activate.bat" || exit /b 1

rem -------- 3. Backend deps --------
echo [3/6] Checking backend deps...
"%PY%" -m pip show fastapi >nul 2>&1 || "%PY%" -m pip install -r "%ROOT%requirements.txt"

rem Playwright (install if missing)
"%PY%" -m playwright --version >nul 2>&1 || "%PY%" -m pip install playwright
"%PY%" -m playwright install chromium >nul 2>&1

rem -------- 4. Frontend deps --------
echo [4/6] Checking frontend deps...
if not exist "%ROOT%frontend\node_modules" (
    pushd "%ROOT%frontend"
    npm install
    popd
)

rem -------- 5. Start backend --------
echo [5/6] Starting backend at http://localhost:8000 ...
start "Backend - 8000" "%ROOT%start_backend.bat"

rem -------- 6. Start frontend --------
echo [6/6] Starting frontend at http://localhost:5173 ...
start "Frontend - 5173" "%ROOT%start_frontend.bat"

echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo Close the backend window to stop backend; Ctrl+C in frontend window to stop dev server.
echo.

endlocal
exit /b 0
