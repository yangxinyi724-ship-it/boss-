"""侦察轮次策略 Planner — 不决定 query/城市/轮间休息时长；不提前结束本轮翻页。"""

from __future__ import annotations

import json
from typing import Any

from pet_boss.agents.planners.base import clamp_int, parse_llm_json_object
from pet_boss.ai.service import AIService

SCOUT_STRATEGY_PROMPT = """你是搜岗侦察策略规划器（Plan 层）。用户已固定搜索词与城市，你不能修改 query、city，也不能修改轮间休息秒数。

本轮翻页上限已固定为 {round_page_cap} 页，你必须扫满，不得提前结束。

根据本轮上下文，输出 JSON 计划（只输出 JSON）：
{{
  "round_page_cap": {round_page_cap},
  "effective_cap": {round_page_cap},
  "early_stop": false,
  "pass_target": 可选，1-6，多搜索词时本组关键词还需通过几个岗位再轮换（仅建议）,
  "strategy_summary": "一句话说明策略",
  "focus_notes": ["最多3条执行建议，勿涉及换词/换城市/休息时长/提前结束翻页"]
}}

约束：
- round_page_cap 与 effective_cap 必须都等于 {round_page_cap}
- early_stop 必须为 false
- 不要建议加快频率或缩短休息
- 不要输出 query、city、pause_sec、fatigue 字段

上下文：
{context_json}
"""


def _fallback_round_plan(round_page_cap: int | None, base_plan: dict[str, Any]) -> dict[str, Any]:
	cap = round_page_cap if round_page_cap and round_page_cap > 0 else base_plan.get("planned_cap")
	effective = base_plan.get("effective_cap", cap)
	if effective is None:
		effective = cap
	return {
		**base_plan,
		"planned_cap": cap,
		"effective_cap": effective,
		"early_stop": False,
		"fatigue": False,
		"planner": "heuristic",
		"strategy_summary": base_plan.get("stop_reason") or "按本轮页数上限扫满后休息",
		"focus_notes": [],
	}


def plan_scout_round_strategy(
	ai_service: AIService | None,
	*,
	context: dict[str, Any],
	round_page_cap: int | None,
	base_plan: dict[str, Any],
) -> dict[str, Any]:
	"""LLM 可补充说明；翻页上限以 round_page_cap 为准，禁止提前结束。"""
	if ai_service is None or round_page_cap is None or round_page_cap <= 0:
		return _fallback_round_plan(round_page_cap, base_plan)

	prompt = SCOUT_STRATEGY_PROMPT.format(
		context_json=json.dumps(context, ensure_ascii=False),
		round_page_cap=int(round_page_cap),
	)
	try:
		raw = ai_service.chat([
			{"role": "system", "content": "你是搜岗策略规划器。只输出 JSON。必须扫满本轮页数，不得提前结束。"},
			{"role": "user", "content": prompt},
		], agent="ZC", temperature=0.25, max_tokens=600)
		data = parse_llm_json_object(raw)
	except Exception:
		return _fallback_round_plan(round_page_cap, base_plan)

	cap = int(round_page_cap)
	pass_target = data.get("pass_target")
	pass_target_int: int | None = None
	if pass_target is not None:
		pass_target_int = clamp_int(pass_target, 1, 6, 0) or None

	plan = {
		"planned_cap": cap,
		"effective_cap": cap,
		"early_stop": False,
		"fatigue": False,
		"stop_reason": str(data.get("strategy_summary") or "").strip(),
		"planner": "llm",
		"strategy_summary": str(data.get("strategy_summary") or "").strip(),
		"focus_notes": [
			str(x).strip() for x in (data.get("focus_notes") or []) if str(x).strip()
		][:3],
	}
	if pass_target_int:
		plan["pass_target"] = pass_target_int
	return plan
