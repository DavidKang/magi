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


def test_ago_reads_the_largest_unit_that_fits():
    now = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc)
    found = [ages.ago(now - dt.timedelta(**delta), now) for delta in
             ({"seconds": 59}, {"minutes": 5}, {"minutes": 95}, {"days": 3, "hours": 4}, {"seconds": -30})]
    assert found == ["0m", "5m", "1h", "3d", "0m"], \
        "an age reads in the largest unit that fits: under a minute and a time still ahead read 0m, never a negative age"
