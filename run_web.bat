@echo off
cd /d "%~dp0"
echo Starting OmniStudio Pro (Downloader + AI Enhancer + Web Scraper)...

set "PY_EXE="
if exist "venv\Scripts\python.exe" (
    set "PY_EXE=venv\Scripts\python.exe"
) else if exist "..\video-downloader\venv\Scripts\python.exe" (
    set "PY_EXE=..\video-downloader\venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

echo Using Python: %PY_EXE%
start "" "http://127.0.0.1:8000"
"%PY_EXE%" server.py
pause
