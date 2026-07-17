"""分析 AI — 深度评估匹配度、发展前景与隐形雷点，低分 pass。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pet_boss.agents.analysis_scoring import (
	DEFAULT_PASS_SCORE,
	enrich_job_with_analysis_score,
)
from pet_boss.agents.school_company_fit import (
	apply_school_company_fit_to_enriched,
	should_exclude_by_school_company_fit,
)
from pet_boss.ai.service import AIService
from pet_boss.evaluation.engine import evaluate_job_career_stage, evaluation_to_job_fields
from pet_boss.evaluation.models import CareerStageSettings
from pet_boss.profile.models import UserProfile
from pet_boss.profile.store import ProfileStore
from pet_boss.search_filters import SearchFilterCriteria


def resolve_analysis_filter_reason(
	job: dict[str, Any],
	*,
	pass_score: int = DEFAULT_PASS_SCORE,
) -> str:
	"""从分析结果中提取筛掉原因，供事件/资料柜展示。"""
	explicit = str(job.get("analysis_filter_reason") or "").strip()
	if explicit:
		return explicit
	fit = job.get("school_company_fit") or {}
	if fit.get("exclude"):
		risks = list(job.get("analysis_risk") or job.get("profile_risk") or [])
		if risks:
			return str(risks[0])
		return "院校层级与公司招聘偏好不匹配"
	risks = list(job.get("analysis_risk") or job.get("profile_risk") or [])
	if risks:
		return str(risks[0])
	reasons = list(job.get("analysis_reason") or job.get("profile_reason") or [])
	if reasons:
		return str(reasons[0])
	score = int(job.get("analysis_score") or 0)
	return f"综合得分 {score} 分，低于通过线 {pass_score} 分"


@dataclass
class AnalysisResult:
	jobs_received: int = 0
	jobs_passed: int = 0
	jobs_filtered: int = 0
	passed_jobs: list[dict[str, Any]] = field(default_factory=list)
	filtered_jobs: list[dict[str, Any]] = field(default_factory=list)


class AnalysisAI:
	"""分析 AI：对侦察传来的岗位做深度分析，低分丢弃。"""

	def __init__(
		self,
		*,
		pass_score: int = DEFAULT_PASS_SCORE,
		career_stage: CareerStageSettings | None = None,
	) -> None:
		self._pass_score = pass_score
		self._career_stage = career_stage or CareerStageSettings()

	def analyze(
		self,
		jobs: list[dict[str, Any]],
		profile: UserProfile,
		*,
		store: ProfileStore | None = None,
		ai_service: AIService | None = None,
		criteria: SearchFilterCriteria | None = None,
	) -> AnalysisResult:
		result = AnalysisResult(jobs_received=len(jobs))
		for job in jobs:
			if self._career_stage.enabled:
				eval_result = evaluate_job_career_stage(
					job, profile, self._career_stage,
					store=store, ai_service=ai_service,
				)
				enriched = {**job, **evaluation_to_job_fields(eval_result)}
				enriched = apply_school_company_fit_to_enriched(
					job, profile, enriched, ai_service=ai_service,
				)
			else:
				enriched = enrich_job_with_analysis_score(
					job, profile,
					store=store,
					ai_service=ai_service,
					target_city=criteria.city if criteria else None,
					pass_score=self._pass_score,
				)
			score = enriched.get("analysis_score", 0)
			if should_exclude_by_school_company_fit(enriched):
				enriched["analysis_passed"] = False
			elif self._career_stage.enabled and score >= self._pass_score:
				enriched["analysis_passed"] = True
			elif self._career_stage.enabled:
				enriched["analysis_passed"] = False
			else:
				enriched["analysis_passed"] = score >= self._pass_score
			if enriched["analysis_passed"]:
				enriched["analysis_status"] = "passed"
				result.passed_jobs.append(enriched)
			else:
				enriched["analysis_filter_reason"] = resolve_analysis_filter_reason(
					enriched,
					pass_score=self._pass_score,
				)
				enriched["analysis_status"] = "filtered"
				result.filtered_jobs.append(enriched)
		result.jobs_passed = len(result.passed_jobs)
		result.jobs_filtered = len(result.filtered_jobs)
		result.passed_jobs.sort(key=lambda j: j.get("analysis_score", 0), reverse=True)
		return result
