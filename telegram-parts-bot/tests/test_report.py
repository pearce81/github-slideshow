import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
openpyxl = pytest.importorskip("openpyxl")

import report  # noqa: E402
from storage import Storage  # noqa: E402


def test_month_starts():
    assert report.month_starts("2025-11", "2026-02") == [
        date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]
    with pytest.raises(report.PeriodError):
        report.month_starts("2026-02", "2025-11")


def test_monthly_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tz = ZoneInfo("Asia/Tehran")
    monkeypatch.setattr(report, "TZ", tz)
    db = Storage(str(tmp_path / "p.db"))
    db.save_messages([
        (-1, 1, 1, "a", datetime(2025, 11, 3, tzinfo=tz), "", ["86511-2S000"]),
        (-1, 2, 2, "b", datetime(2025, 11, 4, tzinfo=tz), "", ["86511-2S000", "58101-2SA70"]),
        (-1, 3, 1, "a", datetime(2025, 12, 1, 0, 10, tzinfo=tz), "", ["58101-2SA70"]),
        (-1, 4, 1, "a", datetime(2025, 10, 31, 23, 50, tzinfo=tz), "", ["11111-OCTOB"]),  # before range
    ])
    name = report.monthly_report(db, -1, report.month_starts("2025-11", "2025-12"), 1)
    wb = openpyxl.load_workbook(name)
    assert wb.sheetnames == ["All months", "2025-11", "2025-12"]
    rows = [[c.value for c in r] for r in wb["All months"].iter_rows()]
    assert rows[1:] == [["58101-2SA70", 2, 2, 1, 1], ["86511-2S000", 2, 1, 2, None]]
    assert [c.value for c in wb["2025-11"][5]] == [1, "86511-2S000", 2, 2]
