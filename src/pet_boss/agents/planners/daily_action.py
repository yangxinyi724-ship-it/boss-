"""秘书 AI — 今日行动 Planner。"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from pet_boss.agents.planners.base import parse_llm_json_object
from pet_boss.ai.service import AIService

DAILY_ACTION_PROMPT = """你是求职秘书 AI，为用户制定「今日行动建议」。用户自行决定搜索词与城市，你不要替用户改 query/city。

根据数据输出 JSON（只输出 JSON）：
{{
  "headline": "今日一句话重点",
  "priorities": ["今日优先事项，最多5条"],
  "apply_today": [
    {{"title":"岗位","company":"公司","reason":"为何优先投/看","security_id":"","job_id":""}}
  ],
  "review_filtered": ["建议复盘的一类筛掉原因或模式，最多3条"],
  "profile_actions": ["画像/简历可改进点，最多3条"],
  "risk_notes": ["需注意的风险或节奏提醒，最多2条，勿建议缩短休息或刷频"]
}}

数据：
{context_json}
"""


def _heuristic_daily_plan(context: dict[str, Any]) -> dict[str, Any]:
	picks = context.get("daily_picks") or []
	priorities = []
	if picks:
		priorities.append(f"优先查看今日精选 {len(picks)} 个岗位")
	summary = context.get("summary") or {}
	if int(summary.get("passed_count") or 0) > 0:
		priorities.append("对已通过岗位补充 JD 细节并决定是否加入候选池")
	if int(summary.get("filtered_count") or 0) > 5:
		priorities.append("复盘分析筛掉记录，确认是否有误杀")
	if not priorities:
		priorities.append("保持搜岗运行，等待系统积累更多分析样本")
	return {
		"date": context.get("date") or date.today().isoformat(),
		"planner": "heuristic",
		"headline": "按当前搜岗节奏推进，优先处理已通过岗位",
		"priorities": priorities[:5],
		"apply_today": [],
		"review_filtered": [],
		"profile_actions": [],
		"risk_notes": ["轮间休息与翻页节奏由系统保守控制，不建议手动加速"],
	}


def plan_daily_actions(
	ai_service: AIService | None,
	*,
	context: dict[str, Any],
) -> dict[str, Any]:
	if ai_service is None:
		return _heuristic_daily_plan(context)
	prompt = DAILY_ACTION_PROMPT.format(
		context_json=json.dumps(context, ensure_ascii=False),
	)
	try:
		raw = ai_service.chat([
			{"role": "system", "content": "你是求职秘书。只输出 JSON，中文。"},
			{"role": "user", "content": prompt},
		], agent="MS", temperature=0.35, max_tokens=900)
		data = parse_llm_json_object(raw)
	except Exception:
		return _heuristic_daily_plan(context)

	apply_rows = []
	for row in data.get("apply_today") or []:
		if not isinstance(row, dict):
			continue
		title = str(row.get("title") or "").strip()
		if not title:
			continue
		apply_rows.append({
			"title": title,
			"company": str(row.get("company") or ""),
			"reason": str(row.get("reason") or ""),
			"security_id": str(row.get("security_id") or ""),
			"job_id": str(row.get("job_id") or ""),
		})

	return {
		"date": context.get("date") or date.today().isoformat(),
		"planner": "llm",
		"headline": str(data.get("headline") or "").strip() or "今日行动建议",
		"priorities": [str(x).strip() for x in (data.get("priorities") or []) if str(x).strip()][:5],
		"apply_today": apply_rows[:5],
		"review_filtered": [str(x).strip() for x in (data.get("review_filtered") or []) if str(x).strip()][:3],
		"profile_actions": [str(x).strip() for x in (data.get("profile_actions") or []) if str(x).strip()][:3],
		"risk_notes": [str(x).strip() for x in (data.get("risk_notes") or []) if str(x).strip()][:2],
	}
