"""侦察/分析 AI 自我完善 — 从评估结果与用户反馈沉淀偏好记忆。"""

from __future__ import annotations

from typing import Any

from pet_boss.cache.store import CacheStore
from pet_boss.profile.store import ProfileStore

_CATEGORY_LABELS = {
	"pass_pattern": "通过模式",
	"reject_pattern": "拒绝模式",
	"hard_fail_pattern": "硬性不符",
	"preferred_company": "偏好公司",
	"weak_match": "弱匹配",
	"preference": "用户偏好",
}


def learn_from_scout_hard_fail(
	store: ProfileStore,
	job: dict[str, Any],
	failures: list[str],
) -> None:
	key = CacheStore._make_watch_job_key(job)
	for item in failures[:3]:
		text = str(item).strip()
		if text:
			store.add_ai_memory("scout", "hard_fail_pattern", text, source_job_key=key)


def learn_from_analysis_outcome(
	store: ProfileStore,
	job: dict[str, Any],
	*,
	passed: bool,
) -> None:
	key = CacheStore._make_watch_job_key(job)
	title = str(job.get("title") or "")
	company = str(job.get("company") or "")
	score = int(job.get("analysis_score") or 0)

	if passed:
		for reason in (job.get("analysis_reason") or [])[:3]:
			text = str(reason).strip()
			if text:
				store.add_ai_memory("analysis", "pass_pattern", text, source_job_key=key)
		if company and title:
			store.add_ai_memory(
				"analysis",
				"preferred_company",
				f"{company} · {title}",
				source_job_key=key,
				weight=0.8,
			)
	else:
		for risk in (job.get("analysis_risk") or [])[:3]:
			text = str(risk).strip()
			if text:
				store.add_ai_memory("analysis", "reject_pattern", text, source_job_key=key)
		if score < 45 and company and title:
			store.add_ai_memory(
				"analysis",
				"weak_match",
				f"{title} @ {company}（{score} 分）",
				source_job_key=key,
				weight=0.6,
			)


def ai_memory_summary_for_prompt(
	store: ProfileStore,
	*,
	agent: str | None = None,
	limit: int = 18,
) -> str:
	items = store.list_ai_memory(agent=agent, limit=limit)
	if not items:
		items = store.list_ai_memory(limit=limit)
	if not items:
		return ""
	lines: list[str] = []
	for item in items:
		label = _CATEGORY_LABELS.get(item["category"], item["category"])
		lines.append(f"- [{label}] {item['content']}")
	return "AI 从历史侦察中总结的偏好记忆：\n" + "\n".join(lines)
