"""Read a Telegram group with YOUR OWN account (no bot needed) and save it for the reports.

Uses the Telegram API like Telegram Desktop does, so it can read every group you are
a member of. The first run asks for your phone number and the login code Telegram sends you.

    py account_reader.py --list                       # show your groups and their ids
    py account_reader.py --group -1001234567890       # load history, then keep recording
    py account_reader.py --group "Kia Parts" --days 90 --once

Needs API_ID and API_HASH from https://my.telegram.org -> API development tools.
"""

import argparse
import asyncio
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from telethon import TelegramClient, connection, utils
from telethon.tl.types import MessageService

from parts import extract_part_numbers
from storage import Storage

BATCH = 500


def proxy_settings(value: str | None) -> tuple[dict, str]:
    """TelegramClient proxy kwargs and a description, from PROXY or the system proxy.

    value: "socks5://host:port", "http://host:port", a Telegram MTProto proxy link
    (tg://proxy?server=..&port=..&secret=.. or https://t.me/proxy?...), "none", or
    empty to use the Windows/system proxy that VPN apps set, if any.
    """
    if value and value.strip().lower() == "none":
        return {}, "no proxy"
    if not value:
        system = urllib.request.getproxies()
        value = system.get("socks") or system.get("https") or system.get("http")
        if not value:
            return {}, "no proxy"
        if value.startswith("socks://"):
            value = "socks5://" + value[len("socks://"):]
    value = value.strip()

    url = urlsplit(value if "://" in value else "http://" + value)
    if "secret=" in url.query:  # tg://proxy?... or https://t.me/proxy?...
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        secret = q["secret"]
        if secret.lower().startswith("ee"):
            raise SystemExit(
                "This MTProto proxy uses a 'fake TLS' secret (starts with ee), which this program "
                "can't use. Use a proxy whose secret starts with dd, or your VPN's SOCKS/HTTP proxy."
            )
        return (
            {
                "connection": connection.ConnectionTcpMTProxyRandomizedIntermediate,
                "proxy": (q["server"], int(q["port"]), secret),
            },
            f"MTProto proxy {q['server']}:{q['port']}",
        )

    kind = {"socks5": "socks5", "socks5h": "socks5", "socks": "socks5", "socks4": "socks4",
            "http": "http", "https": "http"}.get(url.scheme.lower())
    if not kind or not url.hostname or not url.port:
        raise SystemExit(f"Can't understand PROXY '{value}'. Example: socks5://127.0.0.1:10808")
    proxy = {"proxy_type": kind, "addr": url.hostname, "port": url.port, "rdns": True}
    if url.username:
        proxy.update(username=url.username, password=url.password)
    return {"proxy": proxy}, f"{kind} proxy {url.hostname}:{url.port}"


def to_row(chat_id, msg):
    """Convert a Telethon message into a Storage row, or None if it shouldn't be counted."""
    if isinstance(msg, MessageService):
        return None  # joins, pins, title changes...
    text = msg.message or ""
    if text.startswith("/"):
        return None  # bot commands, same rule as bot.py
    name = utils.get_display_name(msg.sender) if msg.sender else None
    return (chat_id, msg.id, msg.sender_id, name or None, msg.date, text, extract_part_numbers(text))


async def find_group(client, query: str):
    """Find a group by id, @username / t.me link, or part of its title."""
    query = query.strip()
    if query.startswith("@") or "t.me/" in query:
        return await client.get_entity(query)
    matches = []
    async for d in client.iter_dialogs():
        if not (d.is_group or d.is_channel):
            continue
        if query.lstrip("-").isdigit() and d.id == int(query):
            return d.entity
        if query.lower() in (d.name or "").lower():
            matches.append(d)
    if len(matches) == 1:
        return matches[0].entity
    if not matches:
        raise SystemExit(f"No group matching '{query}'. Run with --list to see your groups.")
    names = "\n".join(f"  {d.id}  {d.name}" for d in matches)
    raise SystemExit(f"Several groups match '{query}', use the id instead:\n{names}")


async def sync(client, db: Storage, entity, chat_id: int, days: int | None) -> int:
    """Save every message newer than what is already in the database. Returns how many were saved."""
    last = db.last_message_id(chat_id)
    kwargs = {"reverse": True, "min_id": last}  # oldest first, so progress is resumable
    if not last and days:
        kwargs["offset_date"] = datetime.now(timezone.utc) - timedelta(days=days)
    rows, saved = [], 0
    async for msg in client.iter_messages(entity, **kwargs):
        row = to_row(chat_id, msg)
        if row:
            rows.append(row)
        if len(rows) >= BATCH:
            db.save_messages(rows)
            saved += len(rows)
            rows = []
            print(f"  ...{saved} messages saved (up to {msg.date:%Y-%m-%d})", flush=True)
    if rows:
        db.save_messages(rows)
        saved += len(rows)
    return saved


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list your groups and their ids")
    ap.add_argument("--group", default=os.environ.get("GROUP"), help="group id, @username, link or title")
    ap.add_argument("--days", type=int, help="on the first run only load this many days of history")
    ap.add_argument("--once", action="store_true", help="load new messages and exit (don't keep watching)")
    ap.add_argument("--every", type=int, default=60, help="seconds between checks for new messages")
    ap.add_argument("--db", default=os.environ.get("DB_PATH", "parts.db"))
    args = ap.parse_args()

    api_id, api_hash = os.environ.get("API_ID"), os.environ.get("API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("Set API_ID and API_HASH (from https://my.telegram.org -> API development tools)")

    client_kwargs, proxy_info = proxy_settings(os.environ.get("PROXY"))
    print(f"Connecting to Telegram ({proxy_info})...")

    # Logs in on first run (asks phone + code). account.session keeps you logged in:
    # keep it private, it gives access to your account.
    async with TelegramClient("account", int(api_id), api_hash, **client_kwargs) as client:
        me = await client.get_me()
        print(f"Logged in as {utils.get_display_name(me)}")

        if args.list or not args.group:
            print("\nYour groups (use the number with --group):")
            async for d in client.iter_dialogs():
                if d.is_group or d.is_channel:
                    print(f"  {d.id}  {d.name}")
            return

        entity = await find_group(client, args.group)
        chat_id = utils.get_peer_id(entity)  # same -100... id the bot uses
        db = Storage(args.db)
        print(f"Reading '{utils.get_display_name(entity)}' (id {chat_id}) into {args.db}")

        n = await sync(client, db, entity, chat_id, args.days)
        print(f"Loaded {n} new messages.")
        if args.once:
            return
        print(f"Watching for new messages every {args.every}s. Keep this window open; Ctrl+C to stop.")
        while True:
            await asyncio.sleep(args.every)
            try:
                n = await sync(client, db, entity, chat_id, None)
            except (ConnectionError, OSError) as e:
                print(f"Connection problem ({e}), retrying...")
                continue
            if n:
                print(f"{datetime.now():%H:%M} saved {n} new messages")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except ConnectionError:
        raise SystemExit(
            "\nCan't connect to Telegram. Turn on your VPN, or set PROXY in "
            "start_reader_windows.bat to your VPN's proxy (e.g. socks5://127.0.0.1:10808) "
            "or a Telegram proxy link. See README for details."
        )
