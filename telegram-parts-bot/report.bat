@echo off
REM Double-click for the full report, or in cmd:  report top 7d   /  report count today
set TIMEZONE=Asia/Tehran
REM How many part numbers each list shows
set TOP_N=50
cd /d "%~dp0"
py report.py %*
pause
