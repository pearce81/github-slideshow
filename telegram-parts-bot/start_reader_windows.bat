@echo off
REM Reads your group with YOUR Telegram account. Edit the 3 lines below, save, double-click.
REM Get API_ID and API_HASH at https://my.telegram.org -> API development tools.
set API_ID=12345678
set API_HASH=paste_your_api_hash_here
REM Group id from the list this window shows on first run (e.g. -1001234567890), or part of its name.
set GROUP=

cd /d "%~dp0"
py account_reader.py
pause
