"""搜索词列表扫完冷却记录。"""

import time
from pathlib import Path

import pytest

from pet_boss.agents.scout_query_memory import (
	cooldown_remaining_sec,
	is_query_on_cooldown,
	record_scout_query_exhausted,
	select_next_query_index,
)
from pet_boss.cache.store import CacheStore
from pet_boss.web.work_schedule import load_scout_query_exhaust_cooldown_hours


def test_record_and_cooldown(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	record_scout_query_exhausted(cache, "Golang", "广州", page=3)
	exhausted_at = cache.get_scout_query_exhausted_at("Golang", "广州")
	assert exhausted_at is not None
	assert is_query_on_cooldown(cache, "Golang", "广州", 3600, now=exhausted_at + 100)
	assert not is_query_on_cooldown(cache, "Golang", "广州", 3600, now=exhausted_at + 4000)
	assert cooldown_remaining_sec(cache, "Golang", "广州", 3600, now=exhausted_at + 100) == pytest.approx(3500.0)


def test_select_next_skips_cooled_query(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	now = 1_000_000.0
	record_scout_query_exhausted(cache, "词A", "广州")
	queries = ["词A", "词B", "词C"]
	idx, all_cd = select_next_query_index(
		queries, 0, cache=cache, city="广州", cooldown_sec=3600, now=now + 10,
	)
	assert idx == 1
	assert all_cd is False


def test_select_next_all_on_cooldown_picks_earliest(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	now = 1_000_000.0
	record_scout_query_exhausted(cache, "词A", "广州")
	time.sleep(0.01)
	record_scout_query_exhausted(cache, "词B", "广州")
	queries = ["词A", "词B"]
	idx, all_cd = select_next_query_index(
		queries, 0, cache=cache, city="广州", cooldown_sec=3600, now=now + 10,
	)
	assert idx == 0
	assert all_cd is True


def test_load_scout_query_exhaust_cooldown_hours_custom(tmp_path: Path):
	path = tmp_path / "desks.json"
	path.write_text(
		'{"scout": {"queryExhaustCooldownHours": 2.5}}',
		encoding="utf-8",
	)
	assert load_scout_query_exhaust_cooldown_hours(desks_path=path) == 2.5


def test_clear_scout_history_removes_exhausted(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	record_scout_query_exhausted(cache, "词A", None)
	assert cache.get_scout_query_exhausted_at("词A", None) is not None
	cache.clear_all_scout_history()
	assert cache.get_scout_query_exhausted_at("词A", None) is None
