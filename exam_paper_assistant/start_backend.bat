@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
call venv\Scripts\activate.bat
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
