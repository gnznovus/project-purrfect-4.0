@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Purr environment missing. Run setup-local.ps1 first.
  exit /b 2
)
pushd "%ROOT%"
"%PYTHON%" -m purrfect.dev.supervisor start
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
