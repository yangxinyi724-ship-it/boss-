"""搜索词列表扫完记录 — 冷却期内不再使用同一搜索词。"""

from __future__ import annotations

import time
from typing import Any

from pet_boss.cache.store import CacheStore


def query_scope_key(query: str, city: str | None) -> str:
	q = str(query or "").strip()
	c = str(city or "").strip()
	return f"{c}\0{q}" if c else q


def record_scout_query_exhausted(
	cache: CacheStore,
	query: str,
	city: str | None,
	*,
	page: int | None = None,
) -> None:
	cache.record_scout_query_exhausted(query, city, page=page)


def is_query_on_cooldown(
	cache: CacheStore,
	query: str,
	city: str | None,
	cooldown_sec: float,
	*,
	now: float | None = None,
) -> bool:
	if cooldown_sec <= 0:
		return False
	exhausted_at = cache.get_scout_query_exhausted_at(query, city)
	if exhausted_at is None:
		return False
	now = time.time() if now is None else now
	return (now - exhausted_at) < cooldown_sec


def cooldown_remaining_sec(
	cache: CacheStore,
	query: str,
	city: str | None,
	cooldown_sec: float,
	*,
	now: float | None = None,
) -> float:
	if cooldown_sec <= 0:
		return 0.0
	exhausted_at = cache.get_scout_query_exhausted_at(query, city)
	if exhausted_at is None:
		return 0.0
	now = time.time() if now is None else now
	return max(0.0, cooldown_sec - (now - exhausted_at))


def select_next_query_index(
	queries: list[str],
	current_index: int,
	*,
	cache: CacheStore,
	city: str | None,
	cooldown_sec: float,
	now: float | None = None,
) -> tuple[int, bool]:
	"""返回下一可用搜索词下标；若全部在冷却则选最早到期者并标记 all_on_cooldown。"""
	n = len(queries)
	if n <= 1:
		return current_index, False
	now = time.time() if now is None else now
	for offset in range(1, n):
		idx = (current_index + offset) % n
		if not is_query_on_cooldown(cache, queries[idx], city, cooldown_sec, now=now):
			return idx, False
	best_idx = current_index
	best_at = cache.get_scout_query_exhausted_at(queries[current_index], city) or 0.0
	for idx, q in enumerate(queries):
		ex_at = cache.get_scout_query_exhausted_at(q, city)
		if ex_at is None:
			return idx, False
		if ex_at < best_at:
			best_at = ex_at
			best_idx = idx
	return best_idx, True
