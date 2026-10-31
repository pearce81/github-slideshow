import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("telethon")

import account_reader  # noqa: E402
from storage import Storage  # noqa: E402
from telethon.tl.types import MessageService  # noqa: E402


def msg(mid, text, when):
    return NS(id=mid, message=text, sender=None, sender_id=mid % 2, date=when)


class FakeClient:
    def __init__(self, messages):
        self.messages = messages

    async def iter_messages(self, entity, reverse, min_id, offset_date=None):
        for m in self.messages:
            if m.id > min_id and (offset_date is None or m.date > offset_date):
                yield m


def test_sync_is_incremental(tmp_path):
    db = Storage(str(tmp_path / "r.db"))
    now = datetime.now(timezone.utc)
    service = MessageService(id=3, peer_id=None, date=now, action=None)
    client = FakeClient([
        msg(1, "86511-2S000?", now - timedelta(days=100)),
        msg(2, "need 86511 2s000", now),
        service,
        msg(4, "/top", now),
        msg(5, "hello", now),
    ])
    assert asyncio.run(account_reader.sync(client, db, None, -100, days=30)) == 2  # 1 too old, 3 service, 4 command
    assert db.summary(-100, now - timedelta(days=1), now)["messages"] == 2

    client.messages.append(msg(6, "58101-2SA70", now))
    assert asyncio.run(account_reader.sync(client, db, None, -100, days=None)) == 1  # only the new one
    assert db.top_parts(-100, now - timedelta(days=1), now) == [("58101-2SA70", 1, 1), ("86511-2S000", 1, 1)]
