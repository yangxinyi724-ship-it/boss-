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
	profile: Any | None = None,
) -> tuple[int, dict[str, Any] | None]:
	"""将一次 analyze 的通过/过滤岗位写入 SQLite，并更新侦察历史与 AI 记忆。

	返回 (写入条数, 最新 RAG 消融报告或 None)。
	"""
	from pet_boss.eval.rag_ablation import record_live_rag_ablation_for_job
	from pet_boss.rag.service import index_analysis_job

	query = criteria.query if criteria else ""
	city = criteria.city if criteria else ""
	count = 0
	ablation: dict[str, Any] | None = None
	data_dir = store._dir.parent if store is not None else None

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
		if data_dir is not None and store is not None and ai_service is not None:
			try:
				ablation = record_live_rag_ablation_for_job(
					data_dir,
					job,
					store=store,
					ai_service=ai_service,
					profile=profile,
					historical_status="passed",
					search_city=city or None,
				) or ablation
			except Exception:
				pass

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
		# 硬筛直滤（无分析理由）不跑消融
		if (
			data_dir is not None
			and store is not None
			and ai_service is not None
			and (
				job.get("analysis_reason")
				or job.get("profile_reason")
				or job.get("rag_meta")
				or int(job.get("analysis_score") or 0) > 0
			)
		):
			try:
				ablation = record_live_rag_ablation_for_job(
					data_dir,
					job,
					store=store,
					ai_service=ai_service,
					profile=profile,
					historical_status="filtered",
					search_city=city or None,
				) or ablation
			except Exception:
				pass

	return count, ablation


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
