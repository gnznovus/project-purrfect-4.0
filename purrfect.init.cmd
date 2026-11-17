@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
pushd "%ROOT%"
if errorlevel 1 exit /b 2
if not exist "%PYTHON%" (
  echo Creating local Python 3.14 environment...
  py -3.14 -m venv "%ROOT%.venv"
  if errorlevel 1 (
    echo Python 3.14 is required. Install Python 3.14 and try again.
    popd
    exit /b 2
  )
)
"%PYTHON%" -c "import sys;sys.exit(0 if sys.version_info >= (3,14) else 2)"
if errorlevel 1 (
  echo Existing virtual environment must use Python 3.14 or newer.
  popd
  exit /b 2
)
"%PYTHON%" -m pip install -e ".[dev]"
if errorlevel 1 (
  echo Failed to install development dependencies.
  popd
  exit /b 1
)
"%PYTHON%" -m purrfect.dev.supervisor init
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" (
  echo.
  echo Purr initialized. Run purrfect.start and purrfect.status.
)
popd
exit /b %EXIT_CODE%
