import asyncio
import importlib
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("telegram")


@pytest.fixture
def bot(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "b.db"))
    monkeypatch.setenv("TIMEZONE", "Asia/Tehran")
    monkeypatch.delenv("ADMIN_IDS", raising=False)
    monkeypatch.delenv("GROUP_ID", raising=False)
    import report
    import bot as bot_module
    importlib.reload(report)
    return importlib.reload(bot_module)


class Msg:
    def __init__(self, text):
        self.text, self.out = text, []

    async def reply_text(self, text, **kw):
        self.out.append(text)

    async def reply_document(self, doc, **kw):
        self.out.append(("file", kw.get("filename")))


def private(text):
    return NS(effective_message=Msg(text), effective_chat=NS(id=5, type="private"), effective_user=NS(id=5))


def test_help_only_uses_telegram_html_tags(bot):
    # Telegram rejects the whole message on an unknown tag such as <N>.
    assert set(re.findall(r"</?([a-zA-Z]+)", bot.HELP)) <= {"b", "code", "i", "pre"}


def test_part_number_typed_as_text_or_fake_command(bot):
    tz = ZoneInfo("Asia/Tehran")
    rows = [(-100, i, i, "u", datetime(2026, m, 5, tzinfo=tz), "", [p])
            for i, (m, p) in enumerate([(9, "26410-2G000"), (10, "26410-2G000"), (10, "26410-2G001")], 1)]
    bot.db.save_messages(rows)

    u = private("/264102g000 30d")
    asyncio.run(bot.on_text(u, None))
    reply = u.effective_message.out[0]
    assert "Part 264102G000" in reply and "Average per month" in reply and "last 30 days: asked" in reply

    u = private("26410")
    asyncio.run(bot.on_text(u, None))
    assert "2 found" in u.effective_message.out[0]

    u = private("hello")
    asyncio.run(bot.on_text(u, None))
    assert u.effective_message.out == ["Unknown command. Send /help for the list."]
