@echo off
chcp 65001 >nul
title Asuna Native DSH Host
cd /d "%~dp0"
node "%~dp0tools\asuna-launch.mjs" ui %*
exit /b %errorlevel%
