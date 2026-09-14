from datetime import datetime, timedelta, timezone

import pytest

from app.scheduler import ScheduledJob, Scheduler


NOW = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)


def test_due_is_utc_safe_and_emits_once() -> None:
    scheduler = Scheduler()
    scheduler.add(ScheduledJob("s1", "publish", NOW + timedelta(minutes=1)))
    scheduler.add(ScheduledJob("s2", "publish", NOW - timedelta(minutes=1)))
    assert [item.schedule_id for item in scheduler.due(NOW)] == ["s2"]
    assert scheduler.due(NOW + timedelta(hours=1)) == ()


def test_pause_and_resume() -> None:
    scheduler = Scheduler()
    scheduler.add(ScheduledJob("s1", "publish", NOW))
    scheduler.pause("s1")
    assert scheduler.due(NOW) == ()
    scheduler.resume("s1")
    assert [item.schedule_id for item in scheduler.due(NOW)] == ["s1"]


def test_schedule_requires_timezone_aware_run_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ScheduledJob("s1", "publish", datetime(2026, 1, 1))
