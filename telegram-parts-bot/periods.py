"""Turn user period arguments ("7d", "month", "2026-10-01 2026-10-15") into time ranges."""

from datetime import datetime, timedelta, date, time

PERIOD_HELP = (
    "today | yesterday | 24h | 7d | 30d | month | lastmonth | all | <N>d | "
    "YYYY-MM-DD [YYYY-MM-DD]"
)


class PeriodError(ValueError):
    pass


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise PeriodError(f"Bad date '{s}', use YYYY-MM-DD")


def parse_period(args: list[str], now: datetime) -> tuple[datetime, datetime, str, list[str]]:
    """Parse the period from the start of ``args``.

    ``now`` must be timezone-aware; calendar periods (today, month...) use its tz.
    Returns (start, end, human label, remaining args). Defaults to the last 30 days.
    """
    tz = now.tzinfo
    midnight = datetime.combine(now.date(), time.min, tzinfo=tz)
    if not args:
        return now - timedelta(days=30), now, "last 30 days", []

    key, rest = args[0].lower(), args[1:]

    if key in ("today", "day"):
        return midnight, now, "today", rest
    if key == "yesterday":
        return midnight - timedelta(days=1), midnight, "yesterday", rest
    if key in ("24h", "lastday"):
        return now - timedelta(hours=24), now, "last 24 hours", rest
    if key in ("week", "7d"):
        return now - timedelta(days=7), now, "last 7 days", rest
    if key == "month":
        start = midnight.replace(day=1)
        return start, now, f"this month ({start:%B %Y})", rest
    if key == "lastmonth":
        end = midnight.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
        return start, end, f"last month ({start:%B %Y})", rest
    if key == "all":
        return datetime(1970, 1, 2, tzinfo=tz), now, "all time", rest
    if key.endswith("d") and key[:-1].isdigit() and int(key[:-1]) > 0:
        n = int(key[:-1])
        return now - timedelta(days=n), now, f"last {n} days", rest
    if key.endswith("h") and key[:-1].isdigit() and int(key[:-1]) > 0:
        n = int(key[:-1])
        return now - timedelta(hours=n), now, f"last {n} hours", rest
    if len(key) == 10 and key[4] == "-":
        d1 = _parse_date(key)
        d2 = d1
        if rest and len(rest[0]) == 10 and rest[0][4] == "-":
            d2 = _parse_date(rest[0])
            rest = rest[1:]
        if d2 < d1:
            raise PeriodError("End date is before start date")
        start = datetime.combine(d1, time.min, tzinfo=tz)
        end = datetime.combine(d2 + timedelta(days=1), time.min, tzinfo=tz)
        label = f"{d1}" if d1 == d2 else f"{d1} → {d2}"
        return start, end, label, rest

    raise PeriodError(f"Unknown period '{args[0]}'. Use: {PERIOD_HELP}")
