import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parts import extract_part_numbers  # noqa: E402
from periods import PeriodError, parse_period  # noqa: E402
from storage import Storage  # noqa: E402


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Need 86511-2S000 please", ["86511-2S000"]),
        ("price for 865112s000?", ["86511-2S000"]),
        ("58101 2SA70 and 58101-2SA70", ["58101-2SA70"]),
        ("قیمت ۸۶۵۱۱-۲S۰۰۰ دارید؟", ["86511-2S000"]),
        ("31112–3X500 (en dash)", ["31112-3X500"]),
        ("old kia 0K2N1-33-28Z", ["0K2N1-33-28Z"]),
        ("call 09123456789", []),
        ("call 0912345678", []),
        ("no parts here", []),
        ("1234567890123", []),
        ("A: 92101-3X020, B: 92102-3X020", ["92101-3X020", "92102-3X020"]),
    ],
)
def test_extract(text, expected):
    assert extract_part_numbers(text) == expected


def test_periods():
    tz = ZoneInfo("Asia/Tehran")
    now = datetime(2026, 10, 29, 15, 0, tzinfo=tz)
    s, e, _, rest = parse_period(["month", "20"], now)
    assert s == datetime(2026, 10, 1, tzinfo=tz) and e == now and rest == ["20"]
    s, e, _, _ = parse_period(["lastmonth"], now)
    assert s == datetime(2026, 9, 1, tzinfo=tz) and e == datetime(2026, 10, 1, tzinfo=tz)
    s, e, _, _ = parse_period(["7d"], now)
    assert e - s == timedelta(days=7)
    s, e, _, _ = parse_period(["2026-10-01", "2026-10-02"], now)
    assert e - s == timedelta(days=2)
    s, _, _, _ = parse_period([], now)
    assert now - s == timedelta(days=30)
    with pytest.raises(PeriodError):
        parse_period(["soon"], now)


def test_storage(tmp_path):
    db = Storage(str(tmp_path / "t.db"))
    now = datetime.now(timezone.utc)
    db.save_message(1, 1, 10, "a", now, "86511-2S000", ["86511-2S000"])
    db.save_message(1, 2, 11, "b", now, "86511-2S000 58101-2SA70", ["86511-2S000", "58101-2SA70"])
    db.save_message(1, 3, 11, "b", now - timedelta(days=40), "58101-2SA70", ["58101-2SA70"])
    db.save_message(1, 4, 12, "c", now, "hello", [])
    db.save_message(2, 1, 10, "a", now, "other group 58101-2SA70", ["58101-2SA70"])

    start, end = now - timedelta(days=30), now
    assert db.top_parts(1, start, end) == [("86511-2S000", 2, 2), ("58101-2SA70", 1, 1)]
    s = db.summary(1, start, end)
    assert s == {"messages": 3, "users": 3, "messages_with_parts": 2, "part_mentions": 3, "unique_parts": 2}

    # editing a message replaces its part numbers instead of double counting
    db.save_message(1, 1, 10, "a", now, "sorry, 58101-2SA70", ["58101-2SA70"])
    assert db.top_parts(1, start, end) == [("58101-2SA70", 2, 2), ("86511-2S000", 1, 1)]
    assert db.summary(1, start, end)["messages"] == 3
