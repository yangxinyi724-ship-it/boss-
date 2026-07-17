"""User Profile Intelligence System — 数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FeedbackAction = Literal[
	"viewed",
	"interested",
	"shortlisted",
	"rejected",
	"applied",
	"interviewed",
	"offer",
]
Priority = Literal["high", "medium", "low"]
RiskTolerance = Literal["low", "medium", "high"]
JobSeekingStage = Literal["exploring", "active", "urgent", "passive"]


@dataclass
class ParsedResume:
	"""Step 1: 简历解析结构化输出。"""

	skills: list[str] = field(default_factory=list)
	projects: list[dict[str, Any]] = field(default_factory=list)
	years_of_experience: float | None = None
	industries: list[str] = field(default_factory=list)
	tools: list[str] = field(default_factory=list)
	education: str = ""
	school_name: str = ""
	school_tier: str = ""
	school_tier_code: int = 0
	school_tier_reason: str = ""
	gender: str = ""
	age: int | None = None
	city: str = ""
	languages: list[str] = field(default_factory=list)
	summary: str = ""
	real_capabilities: list[str] = field(default_factory=list)
	source_resume: str = ""

	def to_dict(self) -> dict[str, Any]:
		return {
			"skills": self.skills,
			"projects": self.projects,
			"years_of_experience": self.years_of_experience,
			"industries": self.industries,
			"tools": self.tools,
			"education": self.education,
			"school_name": self.school_name,
			"school_tier": self.school_tier,
			"school_tier_code": self.school_tier_code,
			"school_tier_reason": self.school_tier_reason,
			"gender": self.gender,
			"age": self.age,
			"city": self.city,
			"languages": self.languages,
			"summary": self.summary,
			"real_capabilities": self.real_capabilities,
			"source_resume": self.source_resume,
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> ParsedResume:
		return cls(
			skills=list(data.get("skills") or []),
			projects=list(data.get("projects") or []),
			years_of_experience=data.get("years_of_experience"),
			industries=list(data.get("industries") or []),
			tools=list(data.get("tools") or []),
			education=str(data.get("education") or ""),
			school_name=str(data.get("school_name") or ""),
			school_tier=str(data.get("school_tier") or ""),
			school_tier_code=int(data.get("school_tier_code") or 0),
			school_tier_reason=str(data.get("school_tier_reason") or ""),
			gender=str(data.get("gender") or ""),
			age=data.get("age") if data.get("age") is not None else None,
			city=str(data.get("city") or ""),
			languages=list(data.get("languages") or []),
			summary=str(data.get("summary") or ""),
			real_capabilities=list(data.get("real_capabilities") or []),
			source_resume=str(data.get("source_resume") or ""),
		)


@dataclass
class UserPreferences:
	"""Step 2: 交互式用户画像 — 偏好与约束。"""

	role_preference: str = ""  # 技术 / 运营 / 产品 ...
	salary_vs_growth: str = ""  # salary / growth / balanced
	overtime_tolerance: str = ""  # yes / no / occasional
	startup_fit: bool | None = None
	sales_role_ok: bool | None = None
	remote_ok: bool | None = None
	ai_app_vs_core: str = ""  # application / infrastructure / both
	product_vs_engineering: str = ""
	career_change_ok: bool | None = None
	stability_priority: str = ""  # high / medium / low
	job_seeking_stage: JobSeekingStage = "active"
	risk_tolerance: RiskTolerance = "medium"
	extra_notes: dict[str, Any] = field(default_factory=dict)
	interview_transcript: list[dict[str, str]] = field(default_factory=list)

	def to_dict(self) -> dict[str, Any]:
		return {
			"role_preference": self.role_preference,
			"salary_vs_growth": self.salary_vs_growth,
			"overtime_tolerance": self.overtime_tolerance,
			"startup_fit": self.startup_fit,
			"sales_role_ok": self.sales_role_ok,
			"remote_ok": self.remote_ok,
			"ai_app_vs_core": self.ai_app_vs_core,
			"product_vs_engineering": self.product_vs_engineering,
			"career_change_ok": self.career_change_ok,
			"stability_priority": self.stability_priority,
			"job_seeking_stage": self.job_seeking_stage,
			"risk_tolerance": self.risk_tolerance,
			"extra_notes": self.extra_notes,
			"interview_transcript": self.interview_transcript,
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> UserPreferences:
		return cls(
			role_preference=str(data.get("role_preference") or ""),
			salary_vs_growth=str(data.get("salary_vs_growth") or ""),
			overtime_tolerance=str(data.get("overtime_tolerance") or ""),
			startup_fit=data.get("startup_fit"),
			sales_role_ok=data.get("sales_role_ok"),
			remote_ok=data.get("remote_ok"),
			ai_app_vs_core=str(data.get("ai_app_vs_core") or ""),
			product_vs_engineering=str(data.get("product_vs_engineering") or ""),
			career_change_ok=data.get("career_change_ok"),
			stability_priority=str(data.get("stability_priority") or ""),
			job_seeking_stage=data.get("job_seeking_stage") or "active",
			risk_tolerance=data.get("risk_tolerance") or "medium",
			extra_notes=dict(data.get("extra_notes") or {}),
			interview_transcript=list(data.get("interview_transcript") or []),
		)


@dataclass
class CareerDirection:
	"""Step 3: 职业方向推理。"""

	primary_direction: str = ""
	secondary_direction: str = ""
	avoid_direction: list[str] = field(default_factory=list)
	risk_tolerance: RiskTolerance = "medium"
	startup_fit: bool = True
	remote_fit: bool = False
	strengths: list[str] = field(default_factory=list)
	gaps: list[str] = field(default_factory=list)
	growth_paths: list[str] = field(default_factory=list)
	realistic_path: str = ""
	long_term_path: str = ""

	def to_dict(self) -> dict[str, Any]:
		return {
			"primary_direction": self.primary_direction,
			"secondary_direction": self.secondary_direction,
			"avoid_direction": self.avoid_direction,
			"risk_tolerance": self.risk_tolerance,
			"startup_fit": self.startup_fit,
			"remote_fit": self.remote_fit,
			"strengths": self.strengths,
			"gaps": self.gaps,
			"growth_paths": self.growth_paths,
			"realistic_path": self.realistic_path,
			"long_term_path": self.long_term_path,
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> CareerDirection:
		return cls(
			primary_direction=str(data.get("primary_direction") or ""),
			secondary_direction=str(data.get("secondary_direction") or ""),
			avoid_direction=list(data.get("avoid_direction") or []),
			risk_tolerance=data.get("risk_tolerance") or "medium",
			startup_fit=bool(data.get("startup_fit", True)),
			remote_fit=bool(data.get("remote_fit", False)),
			strengths=list(data.get("strengths") or []),
			gaps=list(data.get("gaps") or []),
			growth_paths=list(data.get("growth_paths") or []),
			realistic_path=str(data.get("realistic_path") or ""),
			long_term_path=str(data.get("long_term_path") or ""),
		)


@dataclass
class AdaptiveScore:
	"""Step 4: 自适应岗位评分。"""

	score: int = 0
	reason: list[str] = field(default_factory=list)
	risk: list[str] = field(default_factory=list)
	priority: Priority = "medium"
	dimensions: dict[str, int] = field(default_factory=dict)
	rag_references: list[dict[str, Any]] = field(default_factory=list)
	review_plan: dict[str, Any] | None = None

	def to_dict(self) -> dict[str, Any]:
		return {
			"score": self.score,
			"reason": self.reason,
			"risk": self.risk,
			"priority": self.priority,
			"dimensions": self.dimensions,
			"rag_references": self.rag_references,
			"review_plan": self.review_plan,
		}


@dataclass
class InterviewSession:
	"""交互式画像会话状态。"""

	resume_name: str = ""
	questions_asked: int = 0
	max_questions: int = 10
	completed: bool = False
	current_question: str = ""
	current_topic: str = ""
	last_reasoning: str = ""
	question_source: str = ""  # ai | fallback
	transcript: list[dict[str, str]] = field(default_factory=list)

	def to_dict(self) -> dict[str, Any]:
		return {
			"resume_name": self.resume_name,
			"questions_asked": self.questions_asked,
			"max_questions": self.max_questions,
			"completed": self.completed,
			"current_question": self.current_question,
			"current_topic": self.current_topic,
			"last_reasoning": self.last_reasoning,
			"question_source": self.question_source,
			"transcript": self.transcript,
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> InterviewSession:
		return cls(
			resume_name=str(data.get("resume_name") or ""),
			questions_asked=int(data.get("questions_asked") or 0),
			max_questions=int(data.get("max_questions") or 10),
			completed=bool(data.get("completed")),
			current_question=str(data.get("current_question") or ""),
			current_topic=str(data.get("current_topic") or ""),
			last_reasoning=str(data.get("last_reasoning") or ""),
			question_source=str(data.get("question_source") or ""),
			transcript=list(data.get("transcript") or []),
		)


@dataclass
class UserProfile:
	"""完整用户画像聚合。"""

	parsed_resume: ParsedResume | None = None
	preferences: UserPreferences | None = None
	career: CareerDirection | None = None
	memory_summary: str = ""
	updated_at: str = ""

	def to_dict(self) -> dict[str, Any]:
		return {
			"parsed_resume": self.parsed_resume.to_dict() if self.parsed_resume else None,
			"preferences": self.preferences.to_dict() if self.preferences else None,
			"career": self.career.to_dict() if self.career else None,
			"memory_summary": self.memory_summary,
			"updated_at": self.updated_at,
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> UserProfile:
		pr = data.get("parsed_resume")
		pref = data.get("preferences")
		career = data.get("career")
		return cls(
			parsed_resume=ParsedResume.from_dict(pr) if isinstance(pr, dict) else None,
			preferences=UserPreferences.from_dict(pref) if isinstance(pref, dict) else None,
			career=CareerDirection.from_dict(career) if isinstance(career, dict) else None,
			memory_summary=str(data.get("memory_summary") or ""),
			updated_at=str(data.get("updated_at") or ""),
		)
