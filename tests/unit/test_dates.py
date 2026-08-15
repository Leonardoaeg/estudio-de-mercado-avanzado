from datetime import datetime, timedelta, timezone

from eci.utils.dates import age_days, in_reference_window, parse_date


def test_parse_date_iso_formats():
    assert parse_date("2026-01-15") is not None
    assert parse_date("2026-01-15T10:00:00Z") is not None
    assert parse_date("2026-01-15T10:00:00+00:00") is not None


def test_parse_date_none_and_invalid():
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("not a date") is None


def test_parse_date_naive_becomes_utc():
    dt = parse_date("2026-01-15")
    assert dt.tzinfo is not None


def test_age_days_basic():
    start = datetime.now(timezone.utc) - timedelta(days=45)
    assert age_days(start) == 45


def test_age_days_unparseable_returns_none():
    assert age_days("garbage") is None
    assert age_days(None) is None


def test_age_days_never_negative():
    future = datetime.now(timezone.utc) + timedelta(days=5)
    assert age_days(future) == 0


def test_in_reference_window_true_false_and_unknown():
    now = datetime.now(timezone.utc)
    assert in_reference_window(now - timedelta(days=45), min_age_days=30, max_age_days=90) is True
    assert in_reference_window(now - timedelta(days=5), min_age_days=30, max_age_days=90) is False
    assert in_reference_window(now - timedelta(days=200), min_age_days=30, max_age_days=90) is False
    assert in_reference_window(None, min_age_days=30, max_age_days=90) is None


def test_in_reference_window_boundaries_inclusive():
    now = datetime.now(timezone.utc)
    assert in_reference_window(now - timedelta(days=30), min_age_days=30, max_age_days=90) is True
    assert in_reference_window(now - timedelta(days=90), min_age_days=30, max_age_days=90) is True
