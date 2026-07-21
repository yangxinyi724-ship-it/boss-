"""从 JSONL 汇总可观测指标。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from pet_boss.observability.event_log import ObservabilityStore


def summarize_observability(data_dir: Path, *, limit: int = 3000) -> dict[str, Any]:
	store = ObservabilityStore(data_dir)
	rows = store.read_recent(limit=limit)
	types = Counter(str(r.get("type") or "") for r in rows)

	history_skips = types.get("scout_history_skip", 0)
	filters = types.get("scout_filter", 0)
	passed = types.get("job_passed", 0)
	filtered = types.get("job_filtered", 0)
	pages = types.get("page_start", 0)
	errors = types.get("error_retry", 0) + types.get("account_risk", 0)
	browser = types.get("browser_session_lost", 0) + types.get("browser_stuck", 0)
	switches = types.get("scout_query_switch", 0)
	plans = types.get("scout_strategy_plan", 0)

	last = rows[-1] if rows else None
	return {
		"log_path": str(store.path),
		"events_read": len(rows),
		"by_type": dict(types.most_common(40)),
		"totals": {
			"page_starts": pages,
			"history_skips": history_skips,
			"hard_filters": filters,
			"analysis_passed": passed,
			"analysis_filtered": filtered,
			"query_switches": switches,
			"strategy_plans": plans,
			"errors_or_risk": errors,
			"browser_issues": browser,
		},
		"latest": {
			"type": last.get("type") if last else None,
			"page": last.get("page") if last else None,
			"query": last.get("query") if last else None,
			"message": last.get("message") if last else None,
			"ts": last.get("ts") if last else None,
		},
	}
