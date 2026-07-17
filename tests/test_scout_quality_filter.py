"""侦察质量过滤测试。"""

from pet_boss.agents.scout_hard_filter import ScoutFilterConfig, evaluate_hard_criteria
from pet_boss.agents.scout_quality_filter import (
	_boss_activity_status,
	evaluate_scout_quality_filters,
	is_agency_hr_job,
	is_inactive_boss,
	is_long_inactive_boss,
)
from pet_boss.profile.models import CareerDirection, ParsedResume, UserPreferences, UserProfile
from pet_boss.search_filters import SearchFilterCriteria


def _profile(**pref_overrides) -> UserProfile:
	prefs = UserPreferences()
	for k, v in pref_overrides.items():
		setattr(prefs, k, v)
	return UserProfile(
		parsed_resume=ParsedResume(skills=["Python"], education="本科", city="深圳"),
		preferences=prefs,
		career=CareerDirection(primary_direction="后端开发"),
	)


def test_agency_hr_headhunter_title_rejected():
	job = {
		"brandName": "科锐国际",
		"bossTitle": "猎头顾问",
		"activeTimeDesc": "今日活跃",
	}
	rejected, msg = is_agency_hr_job(job)
	assert rejected is True
	assert "猎头" in msg


def test_direct_company_hrbp_not_rejected():
	job = {
		"brandName": "成长科技",
		"bossTitle": "HRBP",
		"activeTimeDesc": "刚刚活跃",
	}
	rejected, _ = is_agency_hr_job(job)
	assert rejected is False


def test_offline_boss_not_filtered():
	job = {"brandName": "成长科技", "bossTitle": "技术总监", "activeTimeDesc": "离线"}
	inactive, msg = is_long_inactive_boss(job)
	assert inactive is False
	assert msg == ""


def test_two_weeks_inactive_not_filtered():
	job = {"brandName": "成长科技", "bossTitle": "技术总监", "activeTimeDesc": "2周前活跃"}
	inactive, _ = is_long_inactive_boss(job)
	assert inactive is False


def test_three_weeks_inactive_filtered():
	job = {"brandName": "成长科技", "bossTitle": "技术总监", "activeTimeDesc": "3周前活跃"}
	inactive, msg = is_long_inactive_boss(job)
	assert inactive is True
	assert "半个月" in msg


def test_half_year_inactive_filtered():
	job = {"brandName": "成长科技", "bossTitle": "技术总监", "activeTimeDesc": "半年前活跃"}
	inactive, msg = is_inactive_boss(job)
	assert inactive is True
	assert "半个月" in msg


def test_online_boss_passes_activity():
	job = {"brandName": "成长科技", "bossTitle": "CTO", "bossOnline": True}
	inactive, _ = is_long_inactive_boss(job)
	assert inactive is False


def test_activity_status_days_threshold():
	assert _boss_activity_status("10天前活跃") == "recent"
	assert _boss_activity_status("15天前活跃") == "long_inactive"
	assert _boss_activity_status("离线") == "unknown"


def test_scout_hard_rejects_agency_at_scout_stage():
	job = {
		"jobName": "AI 应用开发工程师",
		"brandName": "科锐国际",
		"bossTitle": "猎头顾问",
		"activeTimeDesc": "今日活跃",
		"salaryDesc": "10-15K",
	}
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=ScoutFilterConfig())
	assert hard.passed is False
	assert any("猎头" in f or "人力资源" in f for f in hard.failures)


def test_scout_hard_rejects_inactive_boss_without_filters():
	job = {
		"jobName": "Python 工程师",
		"brandName": "成长科技",
		"bossTitle": "技术总监",
		"activeTimeDesc": "1年前活跃",
		"salaryDesc": "15-20K",
	}
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=ScoutFilterConfig())
	assert hard.passed is False
	assert any("半个月" in f or "不活跃" in f for f in hard.failures)


def test_scout_hard_offline_passes_without_filters():
	job = {
		"jobName": "Python 工程师",
		"brandName": "成长科技",
		"bossTitle": "技术总监",
		"activeTimeDesc": "离线",
		"salaryDesc": "15-20K",
	}
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=ScoutFilterConfig())
	assert hard.passed is True


def test_scout_hard_relaxes_inactive_when_excellent_match():
	job = {
		"jobName": "Python 工程师",
		"brandName": "成长科技",
		"bossTitle": "技术总监",
		"activeTimeDesc": "1个月前活跃",
		"salaryDesc": "15-20K",
		"jobDegree": "本科",
		"jobExperience": "1-3年",
	}
	filters = ScoutFilterConfig.from_payload({
		"salary": True,
		"salary_range": {"min": "10", "max": "30"},
		"education": True,
		"education_range": {"min": "大专", "max": "硕士"},
	})
	hard = evaluate_hard_criteria(
		job,
		_profile(),
		scout_filters=filters,
	)
	assert hard.passed is True
	assert any("酌情保留" in r for r in hard.reasons)
	assert hard.checks.get("boss_active") is True


def test_scout_hard_inactive_not_relaxed_when_salary_fails():
	job = {
		"jobName": "Python 工程师",
		"brandName": "成长科技",
		"bossTitle": "技术总监",
		"activeTimeDesc": "1个月前活跃",
		"salaryDesc": "5-8K",
		"jobDegree": "本科",
	}
	filters = ScoutFilterConfig.from_payload({
		"salary": True,
		"salary_range": {"min": "10", "max": "30"},
	})
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=filters)
	assert hard.passed is False
	assert any("薪资" in f for f in hard.failures)
	assert not any("酌情保留" in r for r in hard.reasons)


def test_quality_filter_pass_reasons():
	passed, reasons, failures, checks = evaluate_scout_quality_filters({
		"brandName": "字节跳动",
		"bossTitle": "技术总监",
		"activeTimeDesc": "刚刚活跃",
	})
	assert passed is True
	assert failures == []
	assert checks["agency_hr"] is True


def test_quality_filter_offline_not_rejected():
	passed, _, failures, _ = evaluate_scout_quality_filters({
		"brandName": "字节跳动",
		"bossTitle": "技术总监",
		"activeTimeDesc": "离线",
	})
	assert passed is True
	assert failures == []
