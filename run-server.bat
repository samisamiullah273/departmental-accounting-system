@echo off
title Departmental Accounting Server
cd /d "%~dp0"
echo Starting Departmental Accounting at http://127.0.0.1:8000
echo Keep this window open while using the software.
echo.
python -m src.app
echo.
echo The server has stopped. Press any key to close this window.
pause >nul