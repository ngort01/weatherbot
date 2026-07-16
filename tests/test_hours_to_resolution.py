"""Characterization: hours_to_resolution"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import weatherbet as wb


def test_invalid_returns_999():
    assert wb.hours_to_resolution("not-a-date") == 999.0
    assert wb.hours_to_resolution("") == 999.0


def test_future_end_positive_hours():
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    end = now + timedelta(hours=10)
    end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    real_datetime = datetime

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return now

        @classmethod
        def fromisoformat(cls, s):
            return real_datetime.fromisoformat(s)

    with patch("weatherbet.datetime", FakeDateTime):
        h = wb.hours_to_resolution(end_str)
    assert abs(h - 10.0) < 1e-6


def test_past_end_clamped_to_zero():
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    end = now - timedelta(hours=3)
    end_str = end.isoformat().replace("+00:00", "Z")

    real_datetime = datetime

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return now

        @classmethod
        def fromisoformat(cls, s):
            return real_datetime.fromisoformat(s)

    with patch("weatherbet.datetime", FakeDateTime):
        assert wb.hours_to_resolution(end_str) == 0.0
