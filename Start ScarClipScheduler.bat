@echo off
setlocal
cd /d "%~dp0"
title ScarClipScheduler

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/
  echo During installation, enable "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating an isolated Python environment for ScarClipScheduler...
  python -m venv .venv
  if errorlevel 1 (
    echo Could not create the virtual environment.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -c "import requests, googleapiclient, google_auth_oauthlib" >nul 2>nul
if errorlevel 1 (
  echo Installing free dependencies into the app's isolated environment...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Dependency installation failed. Check your internet connection and Python installation.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" app.py
if errorlevel 1 (
  echo.
  echo ScarClipScheduler closed with an error. See %%LOCALAPPDATA%%\ScarClipScheduler\app.log
  pause
)
endlocal
