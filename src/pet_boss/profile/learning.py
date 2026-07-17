"""Step 5: Learning System — 基于反馈动态优化评分权重。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pet_boss.profile.store import ProfileStore

# 正向行为：提高相关维度权重
_POSITIVE_ACTIONS = {"interested", "shortlisted", "applied", "interviewed", "offer"}
_NEGATIVE_ACTIONS = {"rejected"}

_ACTION_DIMENSION_BOOST: dict[str, list[tuple[str, float]]] = {
	"interested": [("career_goal", 0.05), ("preference_fit", 0.03)],
	"shortlisted": [("skill_match", 0.04), ("career_goal", 0.04)],
	"applied": [("skill_match", 0.06), ("salary", 0.03), ("career_goal", 0.05)],
	"interviewed": [("skill_match", 0.05), ("growth", 0.04)],
	"offer": [("salary", 0.05), ("career_goal", 0.06)],
	"rejected": [("work_intensity", -0.03), ("company_stage", -0.02), ("preference_fit", -0.04)],
}


@dataclass
class FeedbackLearningResult:
	weights: dict[str, float]
	weight_changes: list[dict[str, Any]] = field(default_factory=list)
	ai_memory_added: list[dict[str, str]] = field(default_factory=list)


def apply_feedback_learning(
	store: ProfileStore,
	action: str,
	*,
	title: str = "",
	company: str = "",
	user_reason: str | None = None,
) -> FeedbackLearningResult:
	"""根据用户行为微调维度权重，返回更新后的权重与变更明细。"""
	weights = store.get_dimension_weights()
	weight_changes: list[dict[str, Any]] = []
	adjustments = _ACTION_DIMENSION_BOOST.get(action, [])
	for dim, delta in adjustments:
		current = weights.get(dim, 1.0)
		new_weight = max(0.5, min(2.0, current + delta))
		if abs(new_weight - current) > 1e-9:
			weight_changes.append({
				"dimension": dim,
				"before": round(current, 4),
				"after": round(new_weight, 4),
				"delta": delta,
			})
		weights[dim] = new_weight
		store.set_dimension_weight(dim, new_weight)

	ai_memory_added: list[dict[str, str]] = []
	if action in _NEGATIVE_ACTIONS and title:
		if user_reason:
			content = f"用户拒绝 {title}" + (f" @ {company}" if company else "") + f"：{user_reason}"
		else:
			content = f"用户明确拒绝：{title}" + (f" @ {company}" if company else "")
		store.add_ai_memory("analysis", "preference", content)
		ai_memory_added.append({
			"agent": "analysis",
			"category": "preference",
			"content": content,
		})
	elif action in _POSITIVE_ACTIONS and title:
		content = f"用户正向反馈：{title}" + (f" @ {company}" if company else "")
		store.add_ai_memory(
			"analysis",
			"preference",
			content,
			weight=0.7,
		)
		ai_memory_added.append({
			"agent": "analysis",
			"category": "preference",
			"content": content,
		})
	return FeedbackLearningResult(
		weights=weights,
		weight_changes=weight_changes,
		ai_memory_added=ai_memory_added,
	)


def feedback_summary_for_prompt(store: ProfileStore, limit: int = 20) -> str:
	events = store.list_feedback(limit=limit)
	if not events:
		return "（暂无历史反馈）"
	lines = []
	for e in events[:limit]:
		lines.append(f"- [{e['action']}] {e.get('title', '')} @ {e.get('company', '')}")
	pos = sum(1 for e in events if e["action"] in _POSITIVE_ACTIONS)
	neg = sum(1 for e in events if e["action"] in _NEGATIVE_ACTIONS)
	lines.append(f"统计: 正向 {pos} / 负向 {neg}")
	return "\n".join(lines)
