"""院校层级匹配测试。"""

from pet_boss.agents.scout_hard_filter import ScoutFilterConfig, evaluate_hard_criteria
from pet_boss.agents.school_tier_match import (
	detect_job_school_requirement,
	evaluate_school_tier_match,
	infer_user_school_tier,
)
from pet_boss.profile.models import ParsedResume, UserProfile


def _profile(*, education="本科", school_tier="", school_name="", summary="") -> UserProfile:
	return UserProfile(
		parsed_resume=ParsedResume(
			education=education,
			school_tier=school_tier,
			school_name=school_name,
			summary=summary or education,
			city="广州",
		),
	)


def test_infer_tier_from_school_tier_field():
	info = infer_user_school_tier(_profile(school_tier="三本"))
	assert info.tier == 2
	assert "三本" in info.label


def test_infer_tier_unknown_when_only_school_name():
	info = infer_user_school_tier(_profile(school_name="浙江大学", summary="计算机本科"))
	assert info.tier == 0
	assert "浙江大学" in info.evidence[0]


def test_infer_tier_erben_default():
	info = infer_user_school_tier(_profile(school_tier="二本"))
	assert info.tier == 3


def test_detect_job_985_requirement():
	req = detect_job_school_requirement({
		"title": "Java开发",
		"description": "要求985院校毕业，统招本科",
	})
	assert req is not None
	assert req.tier >= 5


def test_filter_985_job_for_erben_user():
	passed, _, failures, _ = evaluate_school_tier_match(
		{
			"title": "后端",
			"description": "仅限985院校，计算机相关专业",
		},
		_profile(school_tier="二本"),
	)
	assert passed is False
	assert failures
	assert "985" in failures[0] or "211" in failures[0] or "二本" in failures[0]


def test_pass_211_job_for_211_user():
	passed, reasons, failures, _ = evaluate_school_tier_match(
		{"description": "211院校优先"},
		_profile(school_tier="211", school_name="北京邮电大学"),
	)
	assert passed is True
	assert not failures


def test_detect_job_985_211_fulltime_wording():
	req = detect_job_school_requirement({
		"title": "AI Agent开发工程师",
		"description": "1、985/211全日制本科及以上学历，计算机、人工智能等相关专业",
	})
	assert req is not None
	assert req.tier >= 5


def test_filter_985_211_job_for_sanben_user():
	passed, _, failures, _ = evaluate_school_tier_match(
		{
			"title": "AI Agent",
			"description": "985/211全日制本科及以上学历",
		},
		UserProfile(
			parsed_resume=ParsedResume(
				school_name="广州商学院",
				school_tier="三本/民办本科",
				school_tier_code=2,
				education="本科",
			),
		),
	)
	assert passed is False
	assert failures


def test_scout_hard_filter_always_applies_school_tier():
	result = evaluate_hard_criteria(
		{
			"title": "算法",
			"description": "双一流高校，985/211优先",
		},
		_profile(school_tier="三本"),
		scout_filters=ScoutFilterConfig(),
	)
	assert result.passed is False
	assert result.failures
