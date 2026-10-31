@echo off
REM Edit the two lines below, save, then double-click this file to start the bot.
set TELEGRAM_BOT_TOKEN=PASTE_YOUR_TOKEN_HERE
set TIMEZONE=Asia/Tehran

REM Optional (see README step "only you can see reports"):
REM set ADMIN_IDS=123456789
REM set GROUP_ID=-1001234567890

cd /d "%~dp0"
py bot.py
pause
