"""Telegram bot that records a Hyundai/Kia parts group and reports the most asked part numbers.

Run:  TELEGRAM_BOT_TOKEN=... python bot.py
See README.md for setup (the bot's privacy mode must be disabled).
"""

import asyncio
import csv
import io
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

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

db = Storage(DB_PATH)

HELP = f"""<b>Hyundai / Kia part number analytics</b>

/top [period] [N] – most asked part numbers (default: last 30 days, top 10)
/report – top parts for today, 7 days, 30 days and this month
/count [period] – number of group messages, users and part requests
/part &lt;number&gt; [period] – how often one part number was asked
/export [period] – CSV of all part requests
/chatid – show this chat's id

<b>Periods:</b> {PERIOD_HELP}
Examples: <code>/top 7d</code>, <code>/top month 20</code>, <code>/top today</code>,
<code>/count 24h</code>, <code>/top 2026-10-01 2026-10-15</code>, <code>/part 86511-2S000 all</code>
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
    if DEFAULT_CHAT_ID is None:
        await update.effective_message.reply_text(
            "In private chat set GROUP_ID in the bot config, or run the command inside the group."
        )
        return None
    return DEFAULT_CHAT_ID


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
    limit = int(rest[0]) if rest and rest[0].isdigit() else 10
    rows = db.top_parts(chat_id, start, end, min(max(limit, 1), 100))
    await update.effective_message.reply_text(_format_top(rows, label), parse_mode=ParseMode.HTML)


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
    # Every non-service group message, including edits (edits re-extract part numbers).
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, record_message))
    log.info("Bot started (db=%s, tz=%s)", DB_PATH, TZ)
    # Python 3.14+ no longer creates a default event loop; run_polling expects one.
    asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling(allowed_updates=["message", "edited_message"])


if __name__ == "__main__":
    main()
