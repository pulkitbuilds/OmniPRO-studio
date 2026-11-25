@echo off
cd /d "%~dp0"
if "%~1"=="" (
    echo Usage: run_cli.bat ^<video_url^> [--quality best^|1080p^|720p^|480p^|audio] [--enhance] [--scale 2^|4]
    echo        run_cli.bat --enhance-file ^<path_to_video^> [--scale 2^|4]
    echo        run_cli.bat --scrape ^<website_url^> [--scrape-mode auto^|cards^|tables^|json_ld^|article] [--scrape-pages 1]
    pause
    exit /b
)

set "PY_EXE="
if exist "venv\Scripts\python.exe" (
    set "PY_EXE=venv\Scripts\python.exe"
) else if exist "..\video-downloader\venv\Scripts\python.exe" (
    set "PY_EXE=..\video-downloader\venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

"%PY_EXE%" cli.py %*
pause
