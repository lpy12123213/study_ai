@echo off
chcp 65001 >nul 2>&1
setlocal

rem Single-window launcher (PowerShell) for Windows.
rem Usage examples:
rem   start.bat              -> dev (backend + frontend)
rem   start.bat all          -> alias of dev (MCP stdio server is client-launched)
rem   start.bat backend      -> backend only
rem   start.bat frontend     -> frontend only
rem   start.bat mcp          -> MCP stdio server in foreground
rem   start.bat stop         -> kill the dev stack (pid file + ports 8000/5173)
rem   start.bat status       -> show dev stack pids and port occupancy
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

