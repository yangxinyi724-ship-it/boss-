"""结构化搜岗事件落盘（JSONL）。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# 写入观测日志的事件（控制体积，避免每个 glance 都落盘）
_RECORD_TYPES = frozenset({
	"start",
	"done",
	"stopped",
	"page_start",
	"page_done",
	"page_empty",
	"page_turn",
	"scout_list_exhausted",
	"scout_strategy_plan",
	"scout_query_switch",
	"scout_query_cooldown",
	"scout_history_skip",
	"scout_filter",
	"scout_transmit",
	"analysis_start",
	"job_passed",
	"job_filtered",
	"error_retry",
	"account_risk",
	"browser_session_lost",
	"browser_stuck",
	"round_pause",
	"round_fatigue_pause",
	"round_done",
	"round_start",
})


class ObservabilityStore:
	def __init__(self, data_dir: Path) -> None:
		self._dir = data_dir / "observability"
		self._dir.mkdir(parents=True, exist_ok=True)
		self._path = self._dir / "scout_events.jsonl"

	@property
	def path(self) -> Path:
		return self._path

	def append(self, record: dict[str, Any]) -> None:
		line = json.dumps(record, ensure_ascii=False, default=str)
		with self._path.open("a", encoding="utf-8") as f:
			f.write(line + "\n")

	def read_recent(self, *, limit: int = 2000) -> list[dict[str, Any]]:
		if not self._path.exists():
			return []
		lines = self._path.read_text(encoding="utf-8").splitlines()
		out: list[dict[str, Any]] = []
		for line in lines[-limit:]:
			line = line.strip()
			if not line:
				continue
			try:
				obj = json.loads(line)
			except json.JSONDecodeError:
				continue
			if isinstance(obj, dict):
				out.append(obj)
		return out


def record_scout_event(data_dir: Path, event: dict[str, Any] | None) -> None:
	"""管道事件钩子：关键类型写入 JSONL，并同步决策日志。"""
	if not isinstance(event, dict):
		return
	etype = str(event.get("type") or "")
	if etype not in _RECORD_TYPES:
		return

	stats = event.get("stats") if isinstance(event.get("stats"), dict) else {}
	search = stats.get("search") if isinstance(stats.get("search"), dict) else {}
	scout = stats.get("scout") if isinstance(stats.get("scout"), dict) else {}
	analysis = stats.get("analysis") if isinstance(stats.get("analysis"), dict) else {}

	record = {
		"ts": time.time(),
		"type": etype,
		"page": event.get("page") or search.get("current_page"),
		"round": event.get("round") or search.get("current_round"),
		"query": event.get("query") or search.get("current_query"),
		"message": (event.get("message") or "")[:240],
		"scout": {
			"jobs_seen": scout.get("jobs_seen"),
			"jobs_scout_passed": scout.get("jobs_scout_passed"),
			"jobs_history_skipped": scout.get("jobs_history_skipped"),
			"jobs_browse_skipped": scout.get("jobs_browse_skipped"),
		},
		"analysis": {
			"jobs_passed": analysis.get("jobs_passed"),
			"jobs_filtered": analysis.get("jobs_filtered"),
		},
		"search": {
			"pages_scanned": search.get("pages_scanned"),
			"jobs_seen": search.get("jobs_seen"),
		},
	}
	try:
		ObservabilityStore(data_dir).append(record)
	except OSError:
		return

	if etype in {"scout_strategy_plan", "scout_query_switch", "scout_list_exhausted"}:
		try:
			from pet_boss.agents.decision_log import record_agent_decision

			record_agent_decision(data_dir, event)
		except Exception:
			pass
