"""宠物页工作时间表 — 与 desks.json workSchedule 一致。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

_DESKS_PATH = Path(__file__).resolve().parent / "static" / "pet" / "desks.json"


def _parse_hhmm(value: str) -> int | None:
	if not isinstance(value, str):
		return None
	parts = value.strip().split(":")
	if len(parts) != 2:
		return None
	try:
		hour = int(parts[0])
		minute = int(parts[1])
	except ValueError:
		return None
	if hour < 0 or hour > 23 or minute < 0 or minute > 59:
		return None
	return hour * 60 + minute


def load_work_schedule_periods(*, desks_path: Path | None = None) -> list[dict[str, Any]]:
	path = desks_path or _DESKS_PATH
	if not path.is_file():
		return []
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return []
	periods = raw.get("workSchedule", {}).get("periods")
	if not isinstance(periods, list):
		return []
	out: list[dict[str, Any]] = []
	for item in periods:
		if isinstance(item, dict) and item.get("start") and item.get("end"):
			out.append({"start": str(item["start"]), "end": str(item["end"])})
	return out


def is_within_work_schedule(
	periods: list[dict[str, Any]],
	*,
	now: datetime | None = None,
) -> bool:
	if not periods:
		return True
	now = now or datetime.now()
	mins = now.hour * 60 + now.minute
	for period in periods:
		start = _parse_hhmm(str(period.get("start") or ""))
		end = _parse_hhmm(str(period.get("end") or ""))
		if start is None or end is None or start == end:
			continue
		if start < end:
			if start <= mins < end:
				return True
		elif mins >= start or mins < end:
			return True
	return False


def format_schedule_hint(periods: list[dict[str, Any]]) -> str:
	return "、".join(f"{p.get('start', '')}–{p.get('end', '')}" for p in periods if p)


def seconds_until_next_work_start(
	periods: list[dict[str, Any]],
	*,
	now: datetime | None = None,
) -> float:
	"""距下一工作时段开始的秒数；已在工作时间返回 0；无时段返回 0。"""
	if not periods:
		return 0.0
	now = now or datetime.now()
	if is_within_work_schedule(periods, now=now):
		return 0.0
	mins = now.hour * 60 + now.minute
	sec_into_minute = now.second + now.microsecond / 1_000_000
	best: float | None = None
	for period in periods:
		start = _parse_hhmm(str(period.get("start") or ""))
		end = _parse_hhmm(str(period.get("end") or ""))
		if start is None or end is None or start == end:
			continue
		# 今日该时段开始
		delta_min = start - mins
		if delta_min < 0:
			delta_min += 24 * 60
		# 若 start==mins 但已过该秒且当前不在班（理论上不会），仍算下一圈
		candidate = delta_min * 60.0 - sec_into_minute
		if candidate < 0:
			candidate += 24 * 3600
		if best is None or candidate < best:
			best = candidate
	return float(best if best is not None else 0.0)


def load_scout_query_pass_depth(*, desks_path: Path | None = None) -> tuple[int, int]:
	"""读取 desks.json scout.queryPassDepth，返回 (min, max) 默认 1～6。"""
	path = desks_path or _DESKS_PATH
	lo, hi = 1, 6
	if not path.is_file():
		return lo, hi
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return lo, hi
	scout = raw.get("scout")
	if not isinstance(scout, dict):
		return lo, hi
	depth = scout.get("queryPassDepth")
	if not isinstance(depth, dict):
		return lo, hi
	try:
		lo = int(depth.get("min", lo))
		hi = int(depth.get("max", hi))
	except (TypeError, ValueError):
		return 1, 6
	lo = max(1, lo)
	hi = max(lo, hi)
	return lo, hi


def load_scout_query_exhaust_cooldown_hours(*, desks_path: Path | None = None) -> float:
	"""读取 desks.json scout.queryExhaustCooldownHours，默认 4 小时。"""
	path = desks_path or _DESKS_PATH
	default_hours = 4.0
	if not path.is_file():
		return default_hours
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return default_hours
	scout = raw.get("scout")
	if not isinstance(scout, dict):
		return default_hours
	try:
		hours = float(scout.get("queryExhaustCooldownHours", default_hours))
	except (TypeError, ValueError):
		return default_hours
	return max(0.0, hours)
