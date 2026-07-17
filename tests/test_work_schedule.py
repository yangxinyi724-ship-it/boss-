from datetime import datetime
from pathlib import Path

from pet_boss.web.work_schedule import (
	format_schedule_hint,
	is_within_work_schedule,
	load_work_schedule_periods,
	seconds_until_next_work_start,
)


def test_load_work_schedule_periods_from_desks_json():
	periods = load_work_schedule_periods()
	assert periods
	assert all("start" in p and "end" in p for p in periods)


def test_is_within_work_schedule_daytime():
	periods = [{"start": "09:00", "end": "18:00"}]
	assert is_within_work_schedule(periods, now=datetime(2026, 6, 9, 10, 0))
	assert not is_within_work_schedule(periods, now=datetime(2026, 6, 9, 19, 0))


def test_is_within_work_schedule_overnight():
	periods = [{"start": "22:00", "end": "06:00"}]
	assert is_within_work_schedule(periods, now=datetime(2026, 6, 9, 23, 0))
	assert is_within_work_schedule(periods, now=datetime(2026, 6, 9, 5, 0))
	assert not is_within_work_schedule(periods, now=datetime(2026, 6, 9, 12, 0))


def test_empty_periods_means_always_working():
	assert is_within_work_schedule([], now=datetime(2026, 6, 9, 3, 0))


def test_format_schedule_hint():
	periods = [{"start": "09:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}]
	assert format_schedule_hint(periods) == "09:00–12:00、14:00–18:00"


def test_seconds_until_next_work_start_evening():
	periods = [
		{"start": "09:00", "end": "12:00"},
		{"start": "13:00", "end": "17:00"},
		{"start": "18:00", "end": "21:00"},
	]
	# 17:34 → 下一班 18:00，约 26 分钟
	sec = seconds_until_next_work_start(periods, now=datetime(2026, 7, 16, 17, 34, 0))
	assert 25 * 60 <= sec <= 26 * 60
	# 已在班
	assert seconds_until_next_work_start(periods, now=datetime(2026, 7, 16, 10, 0)) == 0.0
	# 深夜 → 次日 09:00
	sec_night = seconds_until_next_work_start(periods, now=datetime(2026, 7, 16, 22, 0, 0))
	assert 10 * 3600 <= sec_night <= 11 * 3600


def test_load_work_schedule_periods_missing_file(tmp_path: Path):
	assert load_work_schedule_periods(desks_path=tmp_path / "missing.json") == []
