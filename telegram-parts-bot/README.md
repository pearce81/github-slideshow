# Hyundai / Kia Parts Analytics Telegram Bot

A Telegram bot that sits in a parts group, records every message, pulls out
Hyundai/Kia part numbers (e.g. `86511-2S000`, `58101-2SA70`, `0K2N1-33-28Z`) and
tells you which part numbers are asked the most in any period, plus how many
messages the group gets.

## What it can answer

| Command | Example | Result |
|---|---|---|
| `/top [period] [N]` | `/top 7d`, `/top month 20` | Most asked part numbers (default: last 30 days, top 10) |
| `/report` | `/report` | Top 5 for last 24 h, 7 days, 30 days and this month, with message counts |
| `/count [period]` | `/count today` | Number of group messages, active users, part requests, different parts |
| `/part <number> [period]` | `/part 86511-2S000 30d` | How many times (and by how many people) one part was asked |
| `/export [period]` | `/export month` | CSV file of every part request (opens in Excel) |
| `/chatid` | | Shows the group id and your user id (for configuration) |

**Periods:** `today`, `yesterday`, `24h`, `7d`, `30d`, `month` (this calendar month),
`lastmonth`, `all`, any `<N>d` / `<N>h`, a date `2026-10-01`, or a range
`2026-10-01 2026-10-15`.

### How part numbers are recognised

* `86511-2S000`, `86511 2S000`, `865112s000`, `86511.2S000` → all counted as `86511-2S000`
* Persian/Arabic digits (`۸۶۵۱۱-۲S۰۰۰`) and different dash characters are handled
* Old Kia format `0K2N1-33-28Z`
* Numbers that look like phone numbers (`0912…` without a dash) are ignored
* If one message repeats the same part, it counts once; editing a message updates its parts
* Each count also shows how many *different users* asked, so one person spamming doesn't dominate

## Setup

1. **Create the bot**: talk to [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. **Let it read the group** (important): in BotFather → `/mybots` → your bot →
   *Bot Settings* → *Group Privacy* → **Turn off**. Otherwise the bot only sees commands.
   (Alternatively make the bot a group admin.)
3. **Add the bot to the group.**
4. **Run it** (Python 3.10+):

   ```bash
   cd telegram-parts-bot
   pip install -r requirements.txt
   cp .env.example .env        # fill in TELEGRAM_BOT_TOKEN and TIMEZONE
   set -a; source .env; set +a
   python bot.py
   ```

   Keep it running on a server/VPS (e.g. with `systemd`, `screen`, or Docker) so it
   records messages continuously.
5. In the group send `/chatid`. Put that id into `GROUP_ID` if you want to ask for
   reports in a private chat with the bot, and your user id into `ADMIN_IDS` so only you
   can see reports.

### Loading old messages

Telegram bots can only see messages sent **after** they were added. To analyse the
group's history, export it once from **Telegram Desktop**: open the group → ⋮ →
*Export chat history* → untick media → format **JSON**. Then:

```bash
python import_history.py ~/Downloads/ChatExport/result.json --chat-id -1001234567890
```

(`--chat-id` is the id `/chatid` shows.) Importing twice is safe; messages are not duplicated.

## Files

* `bot.py` – the Telegram bot (commands + message recording)
* `parts.py` – part number extraction/normalisation
* `periods.py` – period parsing (`7d`, `month`, date ranges…)
* `storage.py` – SQLite storage and analytics queries
* `import_history.py` – import a Telegram Desktop JSON export
* `tests/` – run with `pip install pytest && pytest`
