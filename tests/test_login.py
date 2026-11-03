"""Login age tracking and the expiry reminder (finance/login.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from finance import login

T0 = datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)


def test_login_time_is_the_last_failed_check():
    s = login.record({}, "no_login", T0)
    s = login.record(s, "unreachable", T0 + timedelta(hours=4))
    s = login.record(s, "ok", T0 + timedelta(hours=8))
    assert login.expires_by(s) == T0 + timedelta(days=7)
    # later successes do not move the estimate
    s2 = login.record(s, "ok", T0 + timedelta(days=2))
    assert login.expires_by(s2) == login.expires_by(s)


def test_without_a_failed_check_it_errs_early():
    s = login.record({}, "ok", T0)
    assert login.expires_by(s) == T0 - login.CHECK_GAP + timedelta(days=7)


def test_reminder_once_a_day_before_expiry():
    s = login.record(login.record({}, "no_login", T0), "ok", T0 + timedelta(hours=1))
    assert login.due_reminder(s, T0 + timedelta(days=5, hours=23)) is None
    assert login.due_reminder(s, T0 + timedelta(days=6)) == T0 + timedelta(days=7)
    s["reminded"] = True
    assert login.due_reminder(s, T0 + timedelta(days=6, hours=8)) is None


def test_a_lost_login_resets_and_a_new_one_starts_over():
    s = login.record(login.record({}, "no_login", T0), "ok", T0 + timedelta(hours=1))
    s["reminded"] = True
    later = T0 + timedelta(days=7, hours=2)
    s = login.record(s, "no_login", later)
    assert login.expires_by(s) is None
    s = login.record(s, "ok", later + timedelta(hours=3))
    assert login.expires_by(s) == later + timedelta(days=7)
    assert s["reminded"] is False
