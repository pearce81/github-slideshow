@echo off
REM Reads your group with YOUR Telegram account. Edit the lines below, save, double-click.
REM Get API_ID and API_HASH at https://my.telegram.org -> API development tools.
set API_ID=12345678
set API_HASH=paste_your_api_hash_here
REM Group id from the list this window shows on first run (e.g. -1001234567890), or part of its name.
set GROUP=

REM Proxy: leave empty to use your VPN's Windows proxy automatically.
REM Or set it yourself, e.g.  socks5://127.0.0.1:10808   http://127.0.0.1:10809
REM or a Telegram proxy link  tg://proxy?server=...&port=...&secret=...
set PROXY=

cd /d "%~dp0"
py account_reader.py
pause
