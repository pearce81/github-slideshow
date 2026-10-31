"""Print the reports on your computer, without the bot.

    py report.py                         # top parts for 24h, 7 days, 30 days, this month
    py report.py top 7d                  # most asked in the last 7 days (top 50)
    py report.py top month 100           # top 100 this month
    py report.py count today             # number of messages
    py report.py part 86511-2S000 30d    # how often one part was asked
    py report.py export month            # save a CSV file (opens in Excel)

Periods: today | yesterday | 24h | 7d | 30d | month | lastmonth | all | <N>d |
YYYY-MM-DD [YYYY-MM-DD]
"""

import csv
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from parts import extract_part_numbers, normalize_text
from periods import PeriodError, parse_period
from storage import Storage

TZ = ZoneInfo(os.environ.get("TIMEZONE", "UTC"))
TOP_N = int(os.environ.get("TOP_N", "50"))  # how many part numbers each list shows


def pick_chat(db: Storage) -> int:
    if os.environ.get("GROUP_ID"):
        return int(os.environ["GROUP_ID"])
    chats = db.chats()
    if not chats:
        raise SystemExit("The database is empty. Run account_reader.py (or the bot) first.")
    if len(chats) > 1:
        listing = "\n".join(f"  {cid}  ({n} messages)" for cid, n in chats)
        raise SystemExit(f"Several groups in the database; set GROUP_ID to one of:\n{listing}")
    return chats[0][0]


def print_top(rows, label):
    print(f"\nMost asked – {label}")
    if not rows:
        print("  No part numbers found.")
    for i, (part, n, users) in enumerate(rows, 1):
        print(f"  {i:>2}. {part:<14} {n:>4}x  ({users} users)")


def main(argv: list[str]) -> None:
    db = Storage(os.environ.get("DB_PATH", "parts.db"))
    chat_id = pick_chat(db)
    now = datetime.now(TZ)
    cmd, args = (argv[0].lower(), argv[1:]) if argv else ("report", [])

    if cmd == "report":
        for key in ("24h", "7d", "30d", "month"):
            start, end, label, _ = parse_period([key], now)
            print_top(db.top_parts(chat_id, start, end, TOP_N), label)
            s = db.summary(chat_id, start, end)
            print(f"  ({s['messages']} messages, {s['part_mentions']} part requests)")
    elif cmd == "top":
        start, end, label, rest = parse_period(args, now)
        limit = int(rest[0]) if rest and rest[0].isdigit() else TOP_N
        print_top(db.top_parts(chat_id, start, end, limit), label)
    elif cmd == "count":
        start, end, label, _ = parse_period(args, now)
        s = db.summary(chat_id, start, end)
        print(f"Group activity – {label}")
        print(f"  Messages:                   {s['messages']}")
        print(f"  Active users:               {s['users']}")
        print(f"  Messages with part numbers: {s['messages_with_parts']}")
        print(f"  Part requests:              {s['part_mentions']}")
        print(f"  Different part numbers:     {s['unique_parts']}")
    elif cmd == "part" and args:
        found = extract_part_numbers(args[0])
        part = found[0] if found else normalize_text(args[0])
        start, end, label, _ = parse_period(args[1:] or ["all"], now)
        n, users = db.part_count(chat_id, part, start, end)
        print(f"{part} was asked {n} times by {users} users ({label}).")
    elif cmd == "export":
        start, end, label, _ = parse_period(args or ["all"], now)
        name = f"part_requests_{start:%Y%m%d}_{end:%Y%m%d}.csv"
        with open(name, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["date", "part_number", "user_id", "user_name", "message_id"])
            for ts, part, uid, uname, mid in db.all_mentions(chat_id, start, end):
                w.writerow([datetime.fromtimestamp(ts, TZ).isoformat(), part, uid, uname, mid])
        print(f"Saved {name} ({label})")
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except PeriodError as e:
        raise SystemExit(str(e))
