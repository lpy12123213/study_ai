@echo off
chcp 65001 >nul 2>&1
title Exam Paper Assistant
cd /d "%~dp0exam_paper_assistant"

echo ========================================
echo   Exam Paper Assistant Starting...
echo ========================================
echo.
echo Do not close this window!
echo.
echo Frontend: http://localhost:3000
echo API Docs: http://localhost:8000/docs
echo.
echo Press Ctrl+C to stop all services
echo ========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File ".\start.ps1" %*
pause
