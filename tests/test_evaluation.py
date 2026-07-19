"""职业阶段评估与分析 AI 测试。"""

from pet_boss.agents.analysis_ai import AnalysisAI
from pet_boss.evaluation.engine import evaluate_job_career_stage
from pet_boss.evaluation.models import CareerStageSettings
from pet_boss.profile.models import (
	CareerDirection,
	ParsedResume,
	UserPreferences,
	UserProfile,
)


def _profile(**kwargs) -> UserProfile:
	prefs = UserPreferences()
	return UserProfile(
		parsed_resume=ParsedResume(
			skills=["Python", "FastAPI"],
			education="本科",
			city="深圳",
		),
		preferences=prefs,
		career=CareerDirection(primary_direction="AI应用开发"),
		**kwargs,
	)


def _sample_job(**overrides) -> dict:
	job = {
		"job_id": "j1",
		"security_id": "s1",
		"title": "AI 应用开发工程师",
		"company": "零探路径",
		"salary": "8-13K",
		"city": "深圳",
		"experience": "1-3年",
		"education": "本科",
		"description": "负责 AI 应用开发与落地，Python FastAPI",
		"stage": "A轮",
		"scale": "20-99人",
	}
	job.update(overrides)
	return job


def test_career_stage_evaluation_returns_dimensions():
	result = evaluate_job_career_stage(
		_sample_job(),
		_profile(),
		CareerStageSettings(enabled=True, stage="junior"),
	)
	assert result.overall_score > 0
	assert result.dimensions
	assert result.career_stage == "junior"


def test_analysis_ai_career_stage_mode():
	ai = AnalysisAI(pass_score=50, career_stage=CareerStageSettings(enabled=True, stage="junior"))
	result = ai.analyze([_sample_job()], _profile())
	job = result.passed_jobs[0] if result.passed_jobs else result.filtered_jobs[0]
	assert job.get("evaluation_mode") == "career_stage"
	assert job.get("career_stage_label")
	assert "rag_references" in job
	assert "rag_meta" in job
	assert isinstance(job["rag_references"], list)


def test_analysis_ai_legacy_mode_when_disabled():
	ai = AnalysisAI(pass_score=50, career_stage=CareerStageSettings(enabled=False))
	result = ai.analyze([_sample_job()], _profile())
	job = result.passed_jobs[0] if result.passed_jobs else result.filtered_jobs[0]
	assert job.get("evaluation_mode") != "career_stage"
