@echo off
REM Telegram bot for the reports. Edit the lines below, save, then double-click this file.
REM Token from @BotFather. Never share it or show it in a screenshot.
set TELEGRAM_BOT_TOKEN=PASTE_YOUR_TOKEN_HERE
set TIMEZONE=Asia/Tehran
REM Your Telegram user id (send /chatid to the bot to see it). Only these ids get reports.
REM Several ids: separate with commas. Empty = ANYONE who finds the bot can see your data.
set ADMIN_IDS=
REM How many part numbers lists show by default
set TOP_N=50
REM Only needed if parts.db holds more than one group:
REM set GROUP_ID=-1001234567890

cd /d "%~dp0"
py bot.py
pause
