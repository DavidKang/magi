import datetime as dt

from magi.domain import ages


def test_days_since_reads_today(monkeypatch):
    class Day(dt.date):
        @classmethod
        def today(cls):
            return dt.date(2026, 1, 10)
    monkeypatch.setattr(ages.dt, "date", Day)
    assert ages.days_since("2026-01-08T10:00:00Z") == 2, "ages count from the day they are read, not from import"
    assert ages.days_since("2026-01-08T23:30:00Z") == 1, "ages count days on the local calendar: 23:30 UTC is already the 9th in Madrid"
