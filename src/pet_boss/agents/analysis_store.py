"""分析 AI 结果持久化 — 供秘书 AI 生成日报。"""

from __future__ import annotations

from typing import Any

from pet_boss.agents.analysis_ai import AnalysisResult
from pet_boss.agents.scout_memory import record_scout_outcome
from pet_boss.ai.service import AIService
from pet_boss.cache.store import CacheStore
from pet_boss.profile.scout_learning import learn_from_analysis_outcome
from pet_boss.profile.store import ProfileStore
from pet_boss.search_filters import SearchFilterCriteria


def persist_analysis_result(
	cache: CacheStore,
	result: AnalysisResult,
	*,
	criteria: SearchFilterCriteria | None = None,
	channel: str = "",
	store: ProfileStore | None = None,
	ai_service: AIService | None = None,
) -> int:
	"""将一次 analyze 的通过/过滤岗位写入 SQLite，并更新侦察历史与 AI 记忆。"""
	from pet_boss.rag.service import index_analysis_job

	query = criteria.query if criteria else ""
	city = criteria.city if criteria else ""
	count = 0
	for job in result.passed_jobs:
		cache.record_analysis_job(
			job, "passed",
			search_query=query,
			search_city=city or "",
			channel=channel,
		)
		record_scout_outcome(
			cache, job, "passed",
			channel=channel,
			analysis_score=int(job.get("analysis_score") or 0),
		)
		if store:
			learn_from_analysis_outcome(store, job, passed=True)
			if ai_service is not None:
				index_analysis_job(
					store, ai_service, job,
					status="passed",
					search_query=query,
					search_city=city or "",
				)
		count += 1
	for job in result.filtered_jobs:
		cache.record_analysis_job(
			job, "filtered",
			search_query=query,
			search_city=city or "",
			channel=channel,
		)
		record_scout_outcome(
			cache, job, "filtered",
			channel=channel,
			analysis_score=int(job.get("analysis_score") or 0),
		)
		if store:
			learn_from_analysis_outcome(store, job, passed=False)
			if ai_service is not None:
				index_analysis_job(
					store, ai_service, job,
					status="filtered",
					search_query=query,
					search_city=city or "",
				)
		count += 1
	return count


def day_record_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
	passed = [r for r in records if r.get("status") == "passed"]
	filtered = [r for r in records if r.get("status") == "filtered"]
	scores = [int(r.get("analysis_score") or 0) for r in passed]
	return {
		"total": len(records),
		"passed_count": len(passed),
		"filtered_count": len(filtered),
		"avg_pass_score": round(sum(scores) / len(scores), 1) if scores else 0,
		"top_score": max(scores) if scores else 0,
	}
