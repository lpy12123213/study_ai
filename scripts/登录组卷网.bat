@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
set "SCRIPT=%SCRIPT_DIR%ops\crawler\save_login.py"
set "ROOT_VENV_PY=%REPO_ROOT%\venv\Scripts\python.exe"
set "SCRIPTS_VENV_PY=%REPO_ROOT%\scripts\venv\Scripts\python.exe"
set "PY=python"
if exist "%ROOT_VENV_PY%" set "PY=%ROOT_VENV_PY%"
if not exist "%ROOT_VENV_PY%" if exist "%SCRIPTS_VENV_PY%" set "PY=%SCRIPTS_VENV_PY%"

if not exist "%SCRIPT%" goto missing_script

if "%~1"=="" goto prompt_subject
if "%~1"=="--dry-run" goto pass_all_args
if "%~1"=="--subject" goto pass_all_args
if "%~1"=="--bank-id" goto pass_all_args
if "%~1"=="--user-data-dir" goto pass_all_args

"%PY%" "%SCRIPT%" --subject "%~1"
exit /b %ERRORLEVEL%

:pass_all_args
"%PY%" "%SCRIPT%" %*
exit /b %ERRORLEVEL%

:prompt_subject
echo Please input the subject name to login. Use the same names as tool list_subjects.
echo Press Enter to use default.
set /p SUBJECT=Subject=
if "%SUBJECT%"=="" goto run_default
"%PY%" "%SCRIPT%" --subject "%SUBJECT%"
exit /b %ERRORLEVEL%

:run_default
"%PY%" "%SCRIPT%"
exit /b %ERRORLEVEL%

:missing_script
echo [FAIL] Login script not found: %SCRIPT%
exit /b 1
