"""SQLite storage and analytics queries."""

import math
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    user_id     INTEGER,
    user_name   TEXT,
    ts          INTEGER NOT NULL,          -- unix seconds, UTC
    text        TEXT,
    PRIMARY KEY (chat_id, message_id)
);
CREATE TABLE IF NOT EXISTS part_mentions (
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    part_number TEXT NOT NULL,
    user_id     INTEGER,
    ts          INTEGER NOT NULL,
    PRIMARY KEY (chat_id, message_id, part_number)
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages(chat_id, ts);
CREATE INDEX IF NOT EXISTS idx_mentions_chat_ts ON part_mentions(chat_id, ts);
CREATE INDEX IF NOT EXISTS idx_mentions_part ON part_mentions(chat_id, part_number);
"""


def _ts(dt: datetime, round_up: bool = False) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Messages are stored in whole seconds; round range ends up so a range ending
    # "now" still includes messages sent earlier in the current second.
    return math.ceil(dt.timestamp()) if round_up else int(dt.timestamp())


class Storage:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(SCHEMA)

    def save_message(self, chat_id, message_id, user_id, user_name, when: datetime, text, parts):
        """Store a message and its part numbers. Re-saving (e.g. on edit) replaces the parts."""
        self.save_messages([(chat_id, message_id, user_id, user_name, when, text, parts)])

    def save_messages(self, rows):
        """Bulk version of save_message, in a single transaction."""
        with self.conn:
            for row in rows:
                self._save(*row)

    def _save(self, chat_id, message_id, user_id, user_name, when: datetime, text, parts):
        ts = _ts(when)
        self.conn.execute(
            "INSERT INTO messages (chat_id, message_id, user_id, user_name, ts, text) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, message_id) DO UPDATE SET text = excluded.text",
            (chat_id, message_id, user_id, user_name, ts, text),
        )
        self.conn.execute(
            "DELETE FROM part_mentions WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        )
        self.conn.executemany(
            "INSERT INTO part_mentions (chat_id, message_id, part_number, user_id, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            [(chat_id, message_id, p, user_id, ts) for p in parts],
        )

    def last_message_id(self, chat_id) -> int:
        row = self.conn.execute("SELECT MAX(message_id) FROM messages WHERE chat_id = ?", (chat_id,)).fetchone()
        return row[0] or 0

    def chats(self):
        """[(chat_id, message_count)] for every chat in the database, biggest first."""
        return self.conn.execute(
            "SELECT chat_id, COUNT(*) FROM messages GROUP BY chat_id ORDER BY COUNT(*) DESC"
        ).fetchall()

    def top_parts(self, chat_id, start: datetime, end: datetime, limit=10):
        """[(part_number, times_asked, distinct_users)] most asked first."""
        return self.conn.execute(
            "SELECT part_number, COUNT(*) AS n, COUNT(DISTINCT user_id) AS users "
            "FROM part_mentions WHERE chat_id = ? AND ts >= ? AND ts < ? "
            "GROUP BY part_number ORDER BY n DESC, users DESC, part_number LIMIT ?",
            (chat_id, _ts(start), _ts(end, round_up=True), limit),
        ).fetchall()

    def part_count(self, chat_id, part_number, start: datetime, end: datetime):
        return self.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT user_id) FROM part_mentions "
            "WHERE chat_id = ? AND part_number = ? AND ts >= ? AND ts < ?",
            (chat_id, part_number, _ts(start), _ts(end, round_up=True)),
        ).fetchone()

    def summary(self, chat_id, start: datetime, end: datetime):
        """Dict with message, user, part-mention and unique-part counts for the range."""
        s, e = _ts(start), _ts(end, round_up=True)
        msgs, users = self.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT user_id) FROM messages "
            "WHERE chat_id = ? AND ts >= ? AND ts < ?",
            (chat_id, s, e),
        ).fetchone()
        mentions, unique_parts, msgs_with_parts = self.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT part_number), COUNT(DISTINCT message_id) "
            "FROM part_mentions WHERE chat_id = ? AND ts >= ? AND ts < ?",
            (chat_id, s, e),
        ).fetchone()
        return {
            "messages": msgs,
            "users": users,
            "messages_with_parts": msgs_with_parts,
            "part_mentions": mentions,
            "unique_parts": unique_parts,
        }

    def all_mentions(self, chat_id, start: datetime, end: datetime):
        return self.conn.execute(
            "SELECT m.ts, m.part_number, m.user_id, msg.user_name, m.message_id "
            "FROM part_mentions m JOIN messages msg "
            "ON msg.chat_id = m.chat_id AND msg.message_id = m.message_id "
            "WHERE m.chat_id = ? AND m.ts >= ? AND m.ts < ? ORDER BY m.ts",
            (chat_id, _ts(start), _ts(end, round_up=True)),
        ).fetchall()
