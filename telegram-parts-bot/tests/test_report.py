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


def test_average_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tz = ZoneInfo("Asia/Tehran")
    monkeypatch.setattr(report, "TZ", tz)
    db = Storage(str(tmp_path / "p.db"))
    rows, mid = [], 0
    # Jan: 10 msgs (full), Feb: none, Mar: 10 msgs (full), Apr: 2 msgs (partial)
    for month, n_a, n_other in ((1, 6, 4), (3, 2, 8), (4, 2, 0)):
        for k in range(n_a + n_other):
            mid += 1
            part = "86511-2S000" if k < n_a else f"0450{k}-00115"
            rows.append((-1, mid, k, "u", datetime(2026, month, 5, tzinfo=tz), "", [part]))
    db.save_messages(rows)
    name = report.average_report(db, -1, report.month_starts("2026-01", "2026-04"), 2)
    ws = openpyxl.load_workbook(name)["By monthly average"]
    data = [[c.value for c in r] for r in ws.iter_rows()]
    assert data[0][:7] == ["Rank", "Part number", "Average per month", "Total (2 full months)",
                           "Months asked (of 2)", "Jan 2026", "Mar 2026"]
    assert data[0][7] == "Apr 2026 (partial)"
    assert data[1] == [1, "865112S000", 4, 8, 2, 6, 2, 2]  # (6 + 2) / 2, April not averaged
    assert data[2][1] == "0450600115" and len(data) == 3     # dash removed, leading zero kept, limit 2
