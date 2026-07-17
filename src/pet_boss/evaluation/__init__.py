"""职业阶段评估框架 — 可扩展维度 + 动态权重聚合。"""

from pet_boss.evaluation.engine import EvaluationEngine, evaluate_job_career_stage
from pet_boss.evaluation.models import (
	CandidateProfile,
	CareerStage,
	CareerStageSettings,
	DimensionResult,
	EvaluationResult,
)

__all__ = [
	"CandidateProfile",
	"CareerStage",
	"CareerStageSettings",
	"DimensionResult",
	"EvaluationEngine",
	"EvaluationResult",
	"evaluate_job_career_stage",
]
