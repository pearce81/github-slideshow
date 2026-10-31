@echo off
REM Double-click for the full report, or in cmd:  report top 7d   /  report count today
set TIMEZONE=Asia/Tehran
cd /d "%~dp0"
py report.py %*
pause
