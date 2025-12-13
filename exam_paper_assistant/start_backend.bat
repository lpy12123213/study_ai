@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
call venv\Scripts\activate.bat
python backend\app.py
