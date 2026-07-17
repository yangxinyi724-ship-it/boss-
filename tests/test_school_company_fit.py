"""院校-公司匹配测试。"""

import json

from pet_boss.agents.analysis_ai import AnalysisAI
from pet_boss.agents.school_company_fit import (
	apply_school_company_fit_to_enriched,
	assess_school_company_fit,
	assess_school_company_fit_heuristic,
	should_exclude_by_school_company_fit,
)
from pet_boss.agents.school_tier_match import infer_user_school_tier
from pet_boss.profile.models import ParsedResume, UserProfile


def _profile(
	school_name: str = "",
	school_tier: str = "",
	school_tier_code: int = 0,
	school_tier_reason: str = "",
) -> UserProfile:
	return UserProfile(
		parsed_resume=ParsedResume(
			education="本科",
			school_name=school_name,
			school_tier=school_tier,
			school_tier_code=school_tier_code,
			school_tier_reason=school_tier_reason,
			city="广州",
		),
	)


def test_secretary_school_tier_code_used_for_scout():
	info = infer_user_school_tier(_profile(
		school_name="广州商学院",
		school_tier="三本/民办本科",
		school_tier_code=2,
		school_tier_reason="民办本科",
	))
	assert info.tier == 2
	assert "秘书" in info.evidence[0]


def test_heuristic_needs_tier_not_school_name_only():
	fit = assess_school_company_fit_heuristic(
		{"company": "华为", "title": "Python 开发"},
		_profile(school_name="广州商学院"),
	)
	assert fit.fit_level == "unknown"


def test_heuristic_with_secretary_tier():
	fit = assess_school_company_fit_heuristic(
		{"company": "某科技公司", "title": "Python 开发"},
		_profile(school_name="广州商学院", school_tier="三本", school_tier_code=2),
	)
	assert fit.fit_level == "low"


class _FakeSchoolFitAI:
	def chat(self, messages, **kwargs):
		content = messages[-1]["content"]
		if "红绿分区" in content or "reason 候选" in content:
			return json.dumps({
				"reason": [],
				"risk": ["华为几乎不考虑三本/民办本科"],
			}, ensure_ascii=False)
		return json.dumps({
			"fit_level": "low",
			"exclude": True,
			"score_adjustment": -32,
			"reasons": [],
			"risks": ["华为几乎不考虑三本/民办本科"],
		}, ensure_ascii=False)


def test_ai_judges_company_friendliness_not_school_tier():
	fit = assess_school_company_fit(
		{"company": "华为", "title": "Python"},
		_profile(
			school_name="广州商学院",
			school_tier="三本/民办本科",
			school_tier_code=2,
			school_tier_reason="民办本科院校",
		),
		ai_service=_FakeSchoolFitAI(),
	)
	assert fit.fit_level == "low"
	assert fit.exclude is True
	assert fit.source == "ai"


def test_apply_school_fit_exclude_flag():
	enriched = apply_school_company_fit_to_enriched(
		{"company": "华为", "title": "Python 开发"},
		_profile(
			school_name="广州商学院",
			school_tier="三本/民办本科",
			school_tier_code=2,
		),
		{"analysis_score": 54, "analysis_reason": [], "analysis_risk": []},
		ai_service=_FakeSchoolFitAI(),
	)
	assert should_exclude_by_school_company_fit(enriched)
	assert enriched["school_company_fit"]["exclude"] is True


def test_explicit_jd_985_211_excludes_sanben():
	from pet_boss.agents.school_company_fit import (
		apply_school_company_fit_to_enriched,
		assess_explicit_jd_school_mismatch,
		should_exclude_by_school_company_fit,
	)

	profile = _profile(
		school_name="广州商学院",
		school_tier="三本/民办本科",
		school_tier_code=2,
	)
	job = {
		"company": "南伽科技",
		"title": "AI Agent开发工程师",
		"description": "985/211全日制本科及以上学历，计算机相关专业",
	}
	fit = assess_explicit_jd_school_mismatch(job, profile)
	assert fit is not None
	assert fit.exclude is True
	assert "985" in fit.risks[0] or "211" in fit.risks[0]

	enriched = apply_school_company_fit_to_enriched(
		job, profile,
		{"analysis_score": 58, "analysis_reason": [], "analysis_risk": []},
	)
	assert should_exclude_by_school_company_fit(enriched)
	assert enriched["analysis_score"] <= 23


def test_analysis_ai_filters_explicit_jd_mismatch():
	from pet_boss.agents.analysis_ai import AnalysisAI

	ai = AnalysisAI(pass_score=50)
	profile = _profile(
		school_name="广州商学院",
		school_tier="三本/民办本科",
		school_tier_code=2,
	)
	result = ai.analyze(
		[{
			"title": "AI Agent",
			"company": "测试公司",
			"description": "985/211全日制本科及以上学历",
		}],
		profile,
		ai_service=None,
	)
	assert result.jobs_filtered == 1
	assert result.filtered_jobs[0]["analysis_passed"] is False

	ai = AnalysisAI(pass_score=50)
	profile = _profile(
		school_name="广州商学院",
		school_tier="三本/民办本科",
		school_tier_code=2,
	)
	result = ai.analyze(
		[{"title": "Python", "company": "华为", "analysis_score": 80}],
		profile,
		ai_service=_FakeSchoolFitAI(),
	)
	assert result.jobs_filtered == 1
	assert result.filtered_jobs[0]["analysis_passed"] is False
