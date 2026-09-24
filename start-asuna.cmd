@echo off
chcp 65001 >nul
title Asuna Web Host
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
:start
"%~dp0.venv\Scripts\python.exe" -m asuna.cli ui --config "%~dp0config\local.json" %*
if %errorlevel%==75 goto start
exit /b %errorlevel%
