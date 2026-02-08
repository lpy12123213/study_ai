@echo off
chcp 65001 >nul 2>&1
setlocal

rem Single-window launcher (PowerShell) for Windows.
rem Usage examples:
rem   start.bat              -> dev (backend + frontend)
rem   start.bat all          -> backend + frontend + mcp
rem   start.bat backend      -> backend only
rem   start.bat frontend     -> frontend only
rem   start.bat mcp          -> mcp only
rem   start.bat setup        -> install deps only
rem   start.bat doctor       -> run smoke checks

set "ROOT=%~dp0"

where powershell >nul 2>&1
if errorlevel 1 (
  echo [ERROR] PowerShell not found. Please run on Windows with PowerShell available.
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%start.ps1" %*
exit /b %ERRORLEVEL%

