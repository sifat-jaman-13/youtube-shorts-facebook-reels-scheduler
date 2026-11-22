@echo off
setlocal
cd /d "%~dp0"
title ScarClipScheduler - Native WPF

where dotnet >nul 2>nul
if errorlevel 1 (
  echo .NET 10 SDK was not found. Install it from https://dotnet.microsoft.com/download/dotnet/10.0
  pause
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the isolated background publishing environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Could not create the Python virtual environment.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -c "import requests, googleapiclient, google_auth_oauthlib, google.auth, tzdata" >nul 2>nul
if errorlevel 1 (
  echo Installing YouTube and Meta publishing dependencies...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Dependency installation failed. Check your connection and Python installation.
    pause
    exit /b 1
  )
)

set "SCARCLIP_PYTHON=%CD%\.venv\Scripts\python.exe"
dotnet run --project "native\ScarClipScheduler.Wpf\ScarClipScheduler.Wpf.csproj" --configuration Release
if errorlevel 1 (
  echo.
  echo ScarClipScheduler closed with an error. Check %%LOCALAPPDATA%%\ScarClipScheduler\app.log
  pause
)
endlocal
