"""职业阶段评估 — 数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CareerStage = Literal["junior", "intermediate", "expert"]


@dataclass
class CareerStageSettings:
	enabled: bool = False
	stage: CareerStage = "junior"

	@classmethod
	def from_payload(cls, payload: dict[str, Any] | None) -> CareerStageSettings:
		if not payload:
			return cls()
		stage = str(payload.get("stage") or "junior")
		if stage not in ("junior", "intermediate", "expert"):
			stage = "junior"
		return cls(
			enabled=bool(payload.get("enabled")),
			stage=stage,  # type: ignore[arg-type]
		)


@dataclass
class DimensionResult:
	score: float
	confidence: float
	evidence: list[str] = field(default_factory=list)
	reasoning: str = ""

	def to_dict(self) -> dict[str, Any]:
		return {
			"score": round(self.score, 1),
			"confidence": round(self.confidence, 2),
			"evidence": self.evidence,
			"reasoning": self.reasoning,
		}


@dataclass
class CandidateProfile:
	"""求职画像 — 用于动态调整各维度权重。"""

	career_goal: str = ""
	learning_priority: int = 3
	salary_priority: int = 3
	mentor_needed: int = 3
	risk_preference: str = "medium"
	preferred_team_size: str = ""
	preferred_company_types: list[str] = field(default_factory=list)
	skills: list[str] = field(default_factory=list)
	years_of_experience: float | None = None
	career_change_ok: bool = False
	ai_interest: str = ""

	def to_dict(self) -> dict[str, Any]:
		return {
			"career_goal": self.career_goal,
			"learning_priority": self.learning_priority,
			"salary_priority": self.salary_priority,
			"mentor_needed": self.mentor_needed,
			"risk_preference": self.risk_preference,
			"preferred_team_size": self.preferred_team_size,
			"preferred_company_types": self.preferred_company_types,
			"skills": self.skills,
			"years_of_experience": self.years_of_experience,
			"career_change_ok": self.career_change_ok,
			"ai_interest": self.ai_interest,
		}


@dataclass
class EvaluationResult:
	overall_score: float
	confidence: float
	career_stage: CareerStage
	dimensions: dict[str, DimensionResult]
	recommend_reasons: list[str] = field(default_factory=list)
	risk_warnings: list[str] = field(default_factory=list)
	suitable_for: str = ""
	risk_level: str = "medium"
	weights_used: dict[str, float] = field(default_factory=dict)

	def to_dict(self) -> dict[str, Any]:
		return {
			"overall_score": round(self.overall_score, 1),
			"confidence": round(self.confidence, 2),
			"career_stage": self.career_stage,
			"dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
			"recommend_reasons": self.recommend_reasons,
			"risk_warnings": self.risk_warnings,
			"suitable_for": self.suitable_for,
			"risk_level": self.risk_level,
			"weights_used": self.weights_used,
		}
