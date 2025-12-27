@echo off
setlocal

echo ================================================
echo ZuJuan login + save cookies
echo ================================================
echo(

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "PY=%PROJECT_ROOT%\venv\Scripts\python.exe"

set "SUBJECT=%~1"
if "%SUBJECT%"=="" (
  echo Please input the subject name to login. Use the same names as tool list_subjects.
  echo Press Enter to use default.
  set /p SUBJECT=Subject=
)

echo(

if exist "%PY%" (
  if "%SUBJECT%"=="" (
    "%PY%" "%SCRIPT_DIR%save_login.py"
  ) else (
    "%PY%" "%SCRIPT_DIR%save_login.py" --subject "%SUBJECT%"
  )
) else (
  if "%SUBJECT%"=="" (
    python "%SCRIPT_DIR%save_login.py"
  ) else (
    python "%SCRIPT_DIR%save_login.py" --subject "%SUBJECT%"
  )
)

endlocal
