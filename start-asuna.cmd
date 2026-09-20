@echo off
chcp 65001 >nul
title Asuna Chat
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
"%~dp0.venv\Scripts\python.exe" -m asuna.cli chat --config "%~dp0config\local.json" %*
