"""EvaluationEngine — 聚合各维度评分。"""

from __future__ import annotations

import json
from typing import Any

from pet_boss.ai.service import AIService
from pet_boss.evaluation.candidate_profile import build_candidate_profile
from pet_boss.evaluation.dimensions import DIMENSION_EVALUATORS
from pet_boss.evaluation.models import (
	CandidateProfile,
	CareerStage,
	CareerStageSettings,
	DimensionResult,
	EvaluationResult,
)
from pet_boss.evaluation.signals import job_text_blob
from pet_boss.evaluation.stages import (
	DIMENSION_LABELS,
	STAGE_DIMENSION_WEIGHTS,
	STAGE_LABELS,
	adjust_weights_for_profile,
	stage_dimensions,
)
from pet_boss.profile.models import UserProfile
from pet_boss.profile.store import ProfileStore


class EvaluationEngine:
	"""可扩展评估引擎：各维度独立模块 + 动态权重聚合。"""

	def __init__(
		self,
		stage: CareerStage = "junior",
		*,
		ai_service: AIService | None = None,
	) -> None:
		self.stage = stage
		self._ai_service = ai_service

	def evaluate(
		self,
		job: dict[str, Any],
		candidate: CandidateProfile,
	) -> EvaluationResult:
		blob = job_text_blob(job)
		base_weights = STAGE_DIMENSION_WEIGHTS[self.stage]
		weights = adjust_weights_for_profile(base_weights, self.stage, candidate.to_dict())

		dimensions: dict[str, DimensionResult] = {}
		for key in stage_dimensions(self.stage):
			evaluator = DIMENSION_EVALUATORS.get(key)
			if evaluator is None:
				continue
			dimensions[key] = evaluator(job, blob, candidate)

		if self._ai_service is not None:
			dimensions = self._merge_ai_dimensions(job, candidate, dimensions)

		overall, confidence = self._aggregate(dimensions, weights)
		risk_key = "risk_assessment" if "risk_assessment" in dimensions else "risk"
		risk_dim = dimensions.get(risk_key)
		risk_score = risk_dim.score if risk_dim else 60
		risk_level = "低" if risk_score >= 70 else ("中" if risk_score >= 45 else "高")
		risk_items: list[str] = []
		if risk_dim:
			risk_items.extend(risk_dim.evidence)
			if risk_score < 55 and risk_dim.reasoning:
				risk_items.append(risk_dim.reasoning)

		recommend: list[str] = []
		for key, dim in sorted(dimensions.items(), key=lambda x: -x[1].score):
			if key in (risk_key,) or dim.score < 60:
				continue
			label = DIMENSION_LABELS.get(key, key)
			if dim.evidence:
				recommend.append(f"{label}：{dim.evidence[0]}")
			elif dim.score >= 72:
				recommend.append(f"{label} 表现较好（{int(dim.score)}）")
			if len(recommend) >= 4:
				break

		from pet_boss.agents.analysis_scoring import sanitize_risk_lists

		recommend, risk_warnings = sanitize_risk_lists(
			recommend,
			risk_items,
			ai_service=self._ai_service,
			job=job,
			stage_label=STAGE_LABELS[self.stage],
		)

		suitable = self._suitable_for(candidate, overall, risk_level)

		return EvaluationResult(
			overall_score=overall,
			confidence=confidence,
			career_stage=self.stage,
			dimensions=dimensions,
			recommend_reasons=recommend or ["整体匹配一般，建议结合 JD 详情判断"],
			risk_warnings=risk_warnings,
			suitable_for=suitable,
			risk_level=risk_level,
			weights_used=weights,
		)

	def _aggregate(
		self,
		dimensions: dict[str, DimensionResult],
		weights: dict[str, float],
	) -> tuple[float, float]:
		total_w = 0.0
		score_sum = 0.0
		conf_sum = 0.0
		for key, weight in weights.items():
			dim = dimensions.get(key)
			if dim is None:
				continue
			total_w += weight
			score_sum += dim.score * weight
			conf_sum += dim.confidence * weight
		if total_w <= 0:
			return 50.0, 0.5
		return score_sum / total_w, conf_sum / total_w

	def _suitable_for(
		self,
		candidate: CandidateProfile,
		overall: float,
		risk_level: str,
	) -> str:
		stage_label = STAGE_LABELS[self.stage]
		if overall >= 75 and risk_level != "高":
			return f"适合{stage_label}阶段、追求{'培养与成长' if self.stage == 'junior' else '竞争力提升' if self.stage == 'intermediate' else '影响力放大'}的候选人"
		if overall >= 60:
			return f"可考虑 — 与当前{stage_label}目标部分匹配"
		return f"不太适合当前{stage_label}阶段目标"

	def _merge_ai_dimensions(
		self,
		job: dict[str, Any],
		candidate: CandidateProfile,
		heuristic: dict[str, DimensionResult],
	) -> dict[str, DimensionResult]:
		try:
			from pet_boss.evaluation.ai_scoring import score_dimensions_with_ai

			ai_dims = score_dimensions_with_ai(
				self._ai_service,
				job,
				candidate,
				self.stage,
				list(heuristic.keys()),
			)
		except Exception:
			return heuristic
		merged: dict[str, DimensionResult] = {}
		for key, h in heuristic.items():
			ai = ai_dims.get(key)
			if ai is None:
				merged[key] = h
				continue
			score = ai.score * 0.65 + h.score * 0.35 if ai.score > 0 else h.score
			evidence = list(dict.fromkeys(ai.evidence + h.evidence))[:5]
			merged[key] = DimensionResult(
				score=score,
				confidence=max(h.confidence, ai.confidence),
				evidence=evidence,
				reasoning=ai.reasoning or h.reasoning,
			)
		return merged


def evaluate_job_career_stage(
	job: dict[str, Any],
	profile: UserProfile,
	settings: CareerStageSettings,
	*,
	store: ProfileStore | None = None,
	ai_service: AIService | None = None,
) -> EvaluationResult:
	candidate = build_candidate_profile(profile, store=store)
	engine = EvaluationEngine(settings.stage, ai_service=ai_service)
	return engine.evaluate(job, candidate)


def evaluation_to_job_fields(result: EvaluationResult) -> dict[str, Any]:
	"""映射到现有 analysis_* 字段，供前端与持久化复用。"""
	dim_scores = {k: int(round(v.score)) for k, v in result.dimensions.items()}
	dim_labeled = {
		DIMENSION_LABELS.get(k, k): int(round(v.score))
		for k, v in result.dimensions.items()
	}
	return {
		"analysis_score": int(round(result.overall_score)),
		"analysis_reason": result.recommend_reasons,
		"analysis_risk": result.risk_warnings,
		"analysis_priority": (
			"high" if result.overall_score >= 80 else ("medium" if result.overall_score >= 60 else "low")
		),
		"analysis_dimensions": dim_scores,
		"analysis_dimensions_labeled": dim_labeled,
		"profile_score": int(round(result.overall_score)),
		"profile_reason": result.recommend_reasons,
		"profile_risk": result.risk_warnings,
		"profile_dimensions": dim_scores,
		"match_score": int(round(result.overall_score)),
		"match_reasons": result.recommend_reasons,
		"evaluation_mode": "career_stage",
		"career_stage": result.career_stage,
		"career_stage_label": STAGE_LABELS[result.career_stage],
		"evaluation_confidence": round(result.confidence, 2),
		"evaluation_suitable_for": result.suitable_for,
		"evaluation_risk_level": result.risk_level,
		"career_stage_evaluation": result.to_dict(),
	}
