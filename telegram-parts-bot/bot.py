"""Telegram bot that records a Hyundai/Kia parts group and reports the most asked part numbers.

Run:  TELEGRAM_BOT_TOKEN=... python bot.py
It reports on parts.db, so it also works for groups recorded by account_reader.py
(then the bot doesn't need to be in the group). See README.md for setup.
"""

import asyncio
import csv
import html
import io
import logging
import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import report as reports
from parts import extract_part_numbers, normalize_text
from periods import PERIOD_HELP, PeriodError, parse_period
from storage import Storage

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
# httpx logs every request URL, which contains the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("parts-bot")


def _int_set(env: str) -> set[int]:
    return {int(x) for x in os.environ.get(env, "").replace(" ", "").split(",") if x}


TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DB_PATH = os.environ.get("DB_PATH", "parts.db")
TZ = ZoneInfo(os.environ.get("TIMEZONE", "UTC"))
ADMIN_IDS = _int_set("ADMIN_IDS")            # who may run reports (empty = anyone)
TRACKED_CHATS = _int_set("TRACKED_CHAT_IDS")  # which groups to record (empty = all)
DEFAULT_CHAT_ID = int(os.environ["GROUP_ID"]) if os.environ.get("GROUP_ID") else None
TOP_N = reports.TOP_N  # default list length, TOP_N in the start script
MAX_MESSAGE = 3800     # Telegram allows 4096 characters; longer answers are sent as a .txt file

db = Storage(DB_PATH)

HELP = f"""<b>Hyundai / Kia part number analytics</b>

/top [period] [N] – most asked part numbers (default: last 30 days, top {TOP_N})
/report – top parts for 24 hours, 7 days, 30 days and this month
/count [period] – number of group messages, users and part requests
/part &lt;number&gt; [period] – how often one part number was asked
/avg &lt;number&gt; [&lt;number&gt; …] – average asks per month, rank, per-month counts
/prefix &lt;start&gt; [period] – all parts starting with e.g. 21910, most asked first
/monthly [first] [last] [N] – Excel: top N of each month
/average [first] [last] [N] – Excel: top N by average asks per month
/export [period] – CSV of all part requests
/chatid – show this chat's id and your user id

<b>Periods:</b> {PERIOD_HELP}
Examples: <code>/top 7d</code>, <code>/top month 100</code>, <code>/avg 264102G000</code>,
<code>/prefix 21910</code>, <code>/monthly 2025-11 2026-10 100</code>, <code>/average 2025-11 2026-10 400</code>
"""


# ---------------------------------------------------------------- recording

async def record_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    if TRACKED_CHATS and chat.id not in TRACKED_CHATS:
        return
    text = msg.text or msg.caption or ""
    if text.startswith("/"):
        return  # don't count bot commands as group messages
    user = msg.from_user
    parts = extract_part_numbers(text)
    db.save_message(
        chat.id,
        msg.message_id,
        user.id if user else None,
        (user.full_name if user else (msg.sender_chat.title if msg.sender_chat else None)),
        msg.date,
        text,
        parts,
    )
    if parts:
        log.info("chat %s msg %s parts %s", chat.id, msg.message_id, parts)


# ---------------------------------------------------------------- helpers

async def _target_chat(update: Update) -> int | None:
    """Group whose stats to show, or None (after replying with the reason)."""
    user = update.effective_user
    if ADMIN_IDS and (not user or user.id not in ADMIN_IDS):
        await update.effective_message.reply_text("Sorry, only bot admins can see reports.")
        return None
    chat = update.effective_chat
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        return chat.id
    if DEFAULT_CHAT_ID is not None:
        return DEFAULT_CHAT_ID
    chats = db.chats()
    if len(chats) == 1:
        return chats[0][0]  # only one group recorded: no need to configure GROUP_ID
    await update.effective_message.reply_text(
        "Set GROUP_ID in the bot's start file to the group to report on"
        + (": " + ", ".join(str(c) for c, _ in chats) if chats else " (the database is empty).")
    )
    return None


async def _send_text(update: Update, title: str, text: str, filename: str) -> None:
    """Monospace answer, or a .txt file when it's too long for one Telegram message."""
    if len(text) <= MAX_MESSAGE:
        await update.effective_message.reply_text(
            f"<b>{html.escape(title)}</b>\n<pre>{html.escape(text)}</pre>", parse_mode=ParseMode.HTML
        )
    else:
        await update.effective_message.reply_document(
            io.BytesIO(text.encode("utf-8")), filename=filename, caption=title
        )


async def _in_thread(fn, *args):
    """Run a slow report off the event loop, with its own database connection."""
    return await asyncio.to_thread(lambda: fn(Storage(DB_PATH), *args))


def _period(update: Update, args: list[str]):
    return parse_period(args, datetime.now(TZ))


def _format_top(rows, label: str) -> str:
    if not rows:
        return f"<b>Most asked – {label}</b>\nNo part numbers found."
    lines = [f"<b>Most asked – {label}</b>"]
    for i, (part, n, users) in enumerate(rows, 1):
        lines.append(f"{i}. <code>{part}</code> — {n}× ({users} user{'s' if users != 1 else ''})")
    return "\n".join(lines)


# ---------------------------------------------------------------- commands

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP, parse_mode=ParseMode.HTML)


async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        f"Chat id: <code>{update.effective_chat.id}</code>\n"
        f"Your user id: <code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = await _target_chat(update)
    if chat_id is None:
        return
    try:
        start, end, label, rest = _period(update, context.args)
    except PeriodError as e:
        await update.effective_message.reply_text(str(e))
        return
    limit = int(rest[0]) if rest and rest[0].isdigit() else TOP_N
    rows = db.top_parts(chat_id, start, end, min(max(limit, 1), 5000))
    text = _format_top(rows, label)
    if len(text) <= MAX_MESSAGE:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
        return
    lines = [f"{i:>4}. {part:<14} {n:>6}x  ({users} users)" for i, (part, n, users) in enumerate(rows, 1)]
    await _send_text(update, f"Most asked – {label}", "\n".join(lines), f"top{limit}.txt")


async def cmd_avg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = await _target_chat(update)
    if chat_id is None:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /avg 264102G000 [23040-2C250 …]")
        return
    try:
        text = await _in_thread(reports.part_averages, chat_id, context.args)
    except SystemExit as e:
        await update.effective_message.reply_text(str(e))
        return
    await _send_text(update, "Average asks per month", text, "average.txt")


async def cmd_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = await _target_chat(update)
    if chat_id is None:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /prefix 21910 [period]")
        return
    try:
        text = await _in_thread(reports.prefix_report, chat_id, context.args[0], context.args[1:], datetime.now(TZ))
    except (SystemExit, PeriodError) as e:
        await update.effective_message.reply_text(str(e))
        return
    await _send_text(update, f"Parts starting with {context.args[0]}", text, f"prefix_{context.args[0]}.txt")


async def _excel(update: Update, context: ContextTypes.DEFAULT_TYPE, build) -> None:
    chat_id = await _target_chat(update)
    if chat_id is None:
        return
    try:
        months, limit = reports.months_and_limit(context.args, datetime.now(TZ))
    except PeriodError as e:
        await update.effective_message.reply_text(str(e))
        return
    await update.effective_message.reply_text(
        f"Building the Excel file for {months[0]:%b %Y} – {months[-1]:%b %Y}, top {limit}…"
    )
    with tempfile.TemporaryDirectory() as folder:
        try:
            path = await _in_thread(build, chat_id, months, limit, folder)
        except SystemExit as e:
            await update.effective_message.reply_text(str(e))
            return
        with open(path, "rb") as f:
            await update.effective_message.reply_document(f, filename=os.path.basename(path))


async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _excel(update, context, reports.monthly_report)


async def cmd_average(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _excel(update, context, reports.average_report)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = await _target_chat(update)
    if chat_id is None:
        return
    now = datetime.now(TZ)
    blocks = []
    for key in ("24h", "7d", "30d", "month"):
        start, end, label, _ = parse_period([key], now)
        s = db.summary(chat_id, start, end)
        top = _format_top(db.top_parts(chat_id, start, end, 5), label)
        blocks.append(f"{top}\n<i>{s['messages']} messages, {s['part_mentions']} part requests</i>")
    await update.effective_message.reply_text("\n\n".join(blocks), parse_mode=ParseMode.HTML)


async def cmd_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = await _target_chat(update)
    if chat_id is None:
        return
    try:
        start, end, label, _ = _period(update, context.args)
    except PeriodError as e:
        await update.effective_message.reply_text(str(e))
        return
    s = db.summary(chat_id, start, end)
    await update.effective_message.reply_text(
        f"<b>Group activity – {label}</b>\n"
        f"Messages: <b>{s['messages']}</b>\n"
        f"Active users: {s['users']}\n"
        f"Messages with part numbers: {s['messages_with_parts']}\n"
        f"Part requests: {s['part_mentions']}\n"
        f"Different part numbers: {s['unique_parts']}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_part(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = await _target_chat(update)
    if chat_id is None:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /part 86511-2S000 [period]")
        return
    found = extract_part_numbers(context.args[0])
    part = found[0] if found else normalize_text(context.args[0])
    try:
        start, end, label, _ = _period(update, context.args[1:] or ["all"])
    except PeriodError as e:
        await update.effective_message.reply_text(str(e))
        return
    n, users = db.part_count(chat_id, part, start, end)
    await update.effective_message.reply_text(
        f"<code>{part}</code> was asked <b>{n}</b> times by {users} users ({label}).",
        parse_mode=ParseMode.HTML,
    )


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = await _target_chat(update)
    if chat_id is None:
        return
    try:
        start, end, label, _ = _period(update, context.args or ["all"])
    except PeriodError as e:
        await update.effective_message.reply_text(str(e))
        return
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "part_number", "user_id", "user_name", "message_id"])
    for ts, part, uid, name, mid in db.all_mentions(chat_id, start, end):
        w.writerow([datetime.fromtimestamp(ts, TZ).isoformat(), part, uid, name, mid])
    data = io.BytesIO(buf.getvalue().encode("utf-8-sig"))  # BOM so Excel reads UTF-8 names
    await update.effective_message.reply_document(
        data, filename=f"part_requests_{start:%Y%m%d}_{end:%Y%m%d}.csv", caption=label
    )


def main() -> None:
    if not TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_help))
    app.add_handler(CommandHandler("chatid", cmd_chatid))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("count", cmd_count))
    app.add_handler(CommandHandler("part", cmd_part))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("avg", cmd_avg))
    app.add_handler(CommandHandler("prefix", cmd_prefix))
    app.add_handler(CommandHandler("monthly", cmd_monthly))
    app.add_handler(CommandHandler("average", cmd_average))
    # Every non-service group message, including edits (edits re-extract part numbers).
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, record_message))
    log.info("Bot started (db=%s, tz=%s)", DB_PATH, TZ)
    # Python 3.14+ no longer creates a default event loop; run_polling expects one.
    asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling(allowed_updates=["message", "edited_message"])


if __name__ == "__main__":
    main()
