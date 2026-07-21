"""Agent 决策落盘 — 策略规划 / 换词等可审计节点。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _decisions_path(data_dir: Path) -> Path:
	d = data_dir / "observability"
	d.mkdir(parents=True, exist_ok=True)
	return d / "decisions.jsonl"


def record_agent_decision(data_dir: Path, event: dict[str, Any]) -> None:
	"""把管道中的关键决策事件写成统一决策记录。"""
	etype = str(event.get("type") or "")
	tool = {
		"scout_strategy_plan": "plan_scout_round_strategy",
		"scout_query_switch": "advance_search_query",
		"scout_list_exhausted": "mark_list_exhausted",
	}.get(etype)
	if not tool:
		return

	inputs: dict[str, Any] = {
		"page": event.get("page"),
		"round": event.get("round"),
		"query": event.get("query"),
	}
	outputs: dict[str, Any] = {
		"message": (event.get("message") or "")[:300],
	}
	if etype == "scout_strategy_plan":
		plan = event.get("plan") if isinstance(event.get("plan"), dict) else {}
		outputs["strategy_summary"] = plan.get("strategy_summary") or event.get("strategy_summary")
		outputs["effective_cap"] = plan.get("effective_cap") or event.get("effective_cap")
		outputs["focus_notes"] = plan.get("focus_notes") or event.get("focus_notes")
	elif etype == "scout_query_switch":
		outputs["next_query"] = event.get("next_query") or event.get("query")
		outputs["from_query"] = event.get("from_query") or event.get("prev_query")

	record = {
		"ts": time.time(),
		"agent": "ZC" if etype.startswith("scout_") else "system",
		"tool": tool,
		"event_type": etype,
		"inputs": inputs,
		"outputs": outputs,
		"rationale": (event.get("message") or outputs.get("strategy_summary") or "")[:400],
	}
	path = _decisions_path(data_dir)
	with path.open("a", encoding="utf-8") as f:
		f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def read_recent_decisions(data_dir: Path, *, limit: int = 50) -> list[dict[str, Any]]:
	path = _decisions_path(data_dir)
	if not path.exists():
		return []
	lines = path.read_text(encoding="utf-8").splitlines()
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
