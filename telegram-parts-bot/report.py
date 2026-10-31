"""Print the reports on your computer, without the bot.

    py report.py                         # top parts for 24h, 7 days, 30 days, this month
    py report.py top 7d                  # most asked in the last 7 days (top 50)
    py report.py top month 100           # top 100 this month
    py report.py count today             # number of messages
    py report.py part 86511-2S000 30d    # how often one part was asked
    py report.py export month            # save a CSV file (opens in Excel)
    py report.py monthly 2025-11 2026-10 100   # top 100 for each month -> Excel file

Periods: today | yesterday | 24h | 7d | 30d | month | lastmonth | all | <N>d |
YYYY-MM-DD [YYYY-MM-DD]
"""

import csv
import os
import sys
from datetime import date, datetime, time
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


def month_starts(first: str, last: str) -> list[date]:
    """['2025-11', '2026-10'] -> 1st day of every month from first to last, inclusive."""
    try:
        y, m = map(int, first.split("-")[:2])
        end_y, end_m = map(int, last.split("-")[:2])
    except ValueError:
        raise PeriodError("Months must look like 2025-11")
    months = []
    while (y, m) <= (end_y, end_m):
        months.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    if not months:
        raise PeriodError("The last month is before the first month")
    return months


def monthly_report(db: Storage, chat_id: int, months: list[date], limit: int) -> str:
    """Excel file: a summary sheet (parts x months) and one sheet per month. Returns the file name."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    bold = Font(bold=True)
    wb = Workbook()
    summary = wb.active
    summary.title = "All months"
    per_month = {}  # month label -> {part: count} for every part asked that month
    top_parts = set()  # parts that made at least one month's top list
    for first in months:
        nxt = date(first.year + first.month // 12, first.month % 12 + 1, 1)
        start = datetime.combine(first, time.min, tzinfo=TZ)
        end = datetime.combine(nxt, time.min, tzinfo=TZ)
        rows = db.top_parts(chat_id, start, end, limit)
        stats = db.summary(chat_id, start, end)
        label = f"{first:%Y-%m}"
        per_month[label] = {part: n for part, n, _ in db.top_parts(chat_id, start, end, -1)}
        top_parts.update(part for part, _, _ in rows)
        print(f"{first:%B %Y}: {stats['messages']} messages, {stats['part_mentions']} part requests")

        ws = wb.create_sheet(label)
        ws.append([f"Top {limit} part numbers – {first:%B %Y}"])
        ws.append([f"{stats['messages']} messages, {stats['part_mentions']} part requests, "
                   f"{stats['unique_parts']} different part numbers"])
        ws.append([])
        ws.append(["Rank", "Part number", "Times asked", "Different users"])
        for i, (part, n, users) in enumerate(rows, 1):
            ws.append([i, part, n, users])
        ws["A1"].font = bold
        for c in ws[4]:
            c.font = bold
        ws.column_dimensions["B"].width = 18
        ws.column_dimensions["C"].width = 13
        ws.column_dimensions["D"].width = 16
        ws.freeze_panes = "A5"

    # Summary: every part that made any month's top list, with its real count in every month.
    labels = list(per_month)
    table = {part: [per_month[m].get(part, 0) for m in labels] for part in top_parts}
    summary.append(["Part number", "Total asked", "Months asked", *labels])
    for part, counts in sorted(table.items(), key=lambda kv: (-sum(kv[1]), kv[0])):
        summary.append([part, sum(counts), sum(1 for n in counts if n), *[n or "" for n in counts]])
    for c in summary[1]:
        c.font = bold
    summary.column_dimensions["A"].width = 18
    summary.column_dimensions["B"].width = 12
    summary.column_dimensions["C"].width = 14
    summary.freeze_panes = "B2"

    name = f"monthly_top{limit}_{labels[0]}_to_{labels[-1]}.xlsx"
    wb.save(name)
    return name


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
    elif cmd == "monthly":
        # monthly [first YYYY-MM] [last YYYY-MM] [N]; default: last 12 months including this one
        months_args = [a for a in args if "-" in a]
        limit = next((int(a) for a in args if a.isdigit()), TOP_N)
        last = months_args[1] if len(months_args) > 1 else f"{now:%Y-%m}"
        if months_args:
            first = months_args[0]
        else:
            y, m = now.year, now.month - 11
            first = f"{y - 1}-{m + 12}" if m < 1 else f"{y}-{m}"
        name = monthly_report(db, chat_id, month_starts(first, last), limit)
        print(f"\nSaved {name}")
        if os.name == "nt":
            os.startfile(name)
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except PeriodError as e:
        raise SystemExit(str(e))
