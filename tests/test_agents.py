from pathlib import Path

from pet_boss.agents.analysis_ai import AnalysisAI
from pet_boss.agents.analysis_scoring import (
	build_analysis_profile_payload,
	filter_scout_scope_risks,
	normalize_analysis_labels,
	score_job_analysis_heuristic,
)
from pet_boss.agents.scout_ai import ScoutAI
from pet_boss.agents.scout_hard_filter import ScoutFilterConfig, evaluate_hard_criteria
from pet_boss.cache.store import CacheStore
from pet_boss.profile.models import CareerDirection, ParsedResume, UserPreferences, UserProfile


def _sample_job(**overrides):
	base = {
		"job_id": "j1",
		"security_id": "s1",
		"title": "Golang 后端工程师",
		"company": "测试科技",
		"salary": "20-35K",
		"city": "广州",
		"experience": "3-5年",
		"education": "本科",
		"skills": ["Golang", "K8s"],
		"welfare": ["五险一金", "双休"],
	}
	base.update(overrides)
	return base


def _profile(**pref_overrides) -> UserProfile:
	prefs = UserPreferences(overtime_tolerance="no", stability_priority="high")
	for k, v in pref_overrides.items():
		setattr(prefs, k, v)
	return UserProfile(
		parsed_resume=ParsedResume(
			skills=["Golang", "Python"],
			tools=["K8s"],
			city="广州",
			education="本科",
			summary="后端工程师",
		),
		preferences=prefs,
		career=CareerDirection(primary_direction="后端开发", avoid_direction=["纯销售"]),
	)


def _filters(**kwargs) -> ScoutFilterConfig:
	base = {
		"enabled": frozenset(),
		"salary_min": "",
		"salary_max": "",
		"education_min": "",
		"education_max": "",
		"experience_min": "",
		"experience_max": "",
		"weekend_modes": frozenset(),
		"insurance_types": frozenset(),
	}
	base.update(kwargs)
	return ScoutFilterConfig(**base)


def test_scout_dedup_transmitted(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	channel = ScoutAI.make_channel(query="Golang", city="广州")
	scout = ScoutAI(cache, channel=channel)
	jobs = [_sample_job(), _sample_job(job_id="j2", security_id="s2", title="Python 开发")]

	r1 = scout.scout(jobs, _profile())
	assert len(r1.new_jobs) == 2
	scout.mark_transmitted(r1.new_jobs)

	r2 = scout.scout(jobs, _profile())
	assert len(r2.new_jobs) == 0
	assert r2.jobs_history_skipped == 2


def test_scout_hard_rejects_overtime():
	job = _sample_job(description="996 大小周，单休，加班严重")
	filters = _filters(enabled=frozenset({"overtime"}))
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=filters)
	assert hard.passed is False
	assert any("加班" in f for f in hard.failures)


def test_scout_education_in_custom_range():
	job = _sample_job(education="大专")
	filters = _filters(
		enabled=frozenset({"education"}),
		education_min="大专",
		education_max="本科",
	)
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=filters)
	assert hard.passed is True


def test_scout_education_outside_custom_range():
	job = _sample_job(education="硕士")
	filters = _filters(
		enabled=frozenset({"education"}),
		education_min="大专",
		education_max="本科",
	)
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=filters)
	assert hard.passed is False


def test_scout_salary_higher_than_range_passes():
	job = _sample_job(salary="15-25K·13薪")
	filters = _filters(enabled=frozenset({"salary"}), salary_min="6", salary_max="10")
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=filters)
	assert hard.passed is True


def test_scout_salary_below_min_fails():
	job = _sample_job(salary="3-5K")
	filters = _filters(enabled=frozenset({"salary"}), salary_min="6", salary_max="10")
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=filters)
	assert hard.passed is False


def test_scout_salary_custom_range():
	job = _sample_job(salary="20-35K")
	filters = _filters(enabled=frozenset({"salary"}), salary_min="15", salary_max="30")
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=filters)
	assert hard.passed is True


def test_scout_weekend_modes():
	job = _sample_job(welfare=["单休"])
	filters = _filters(enabled=frozenset({"weekend"}), weekend_modes=frozenset({"双休"}))
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=filters)
	assert hard.passed is False

	job_ok = _sample_job(welfare=["双休"])
	hard_ok = evaluate_hard_criteria(job_ok, _profile(), scout_filters=filters)
	assert hard_ok.passed is True


def test_scout_insurance_types():
	job = _sample_job(welfare=["五险"])
	filters = _filters(enabled=frozenset({"insurance"}), insurance_types=frozenset({"有社保"}))
	hard = evaluate_hard_criteria(job, _profile(), scout_filters=filters)
	assert hard.passed is True


def test_scout_from_payload():
	cfg = ScoutFilterConfig.from_payload({
		"salary": True,
		"weekend": True,
		"salary_range": {"min": "10", "max": "20"},
		"weekend_modes": ["双休", "大小周"],
	})
	assert cfg.is_enabled("salary")
	assert cfg.salary_min == "10"
	assert "双休" in cfg.weekend_modes


def test_scout_disabled_filter_passes_all():
	job = _sample_job(city="珠海", education="大专")
	hard = evaluate_hard_criteria(
		job, _profile(), scout_filters=_filters(enabled=frozenset()),
	)
	assert hard.passed is True


def test_normalize_analysis_labels_dedupes_only():
	reason, risk = normalize_analysis_labels(
		["技能较匹配", "技能较匹配"],
		["JD堆叠", "JD堆叠"],
	)
	assert reason == ["技能较匹配"]
	assert risk == ["JD堆叠"]


def test_filter_scout_scope_risks_removes_commute():
	risks = filter_scout_scope_risks([
		"岗位地点在珠海，用户现居广州，需考虑通勤或搬迁成本",
		"公司名含外包/人力派遣特征，需核实实际用工",
	])
	assert len(risks) == 1
	assert "外包" in risks[0]


def test_filter_scout_scope_risks_removes_hard_pass_confirmation():
	from pet_boss.agents.analysis_scoring import sanitize_risk_lists

	risks = filter_scout_scope_risks([
		"岗位硬性条件全部通过 (学历、经验、薪资等)",
		"JD职责堆叠，一人多岗",
	])
	assert len(risks) == 1
	assert "一人多岗" in risks[0]

	reason, risk = sanitize_risk_lists(
		["技能较匹配"],
		["岗位硬性条件全部通过 (学历、经验、薪资等)"],
	)
	assert reason == ["技能较匹配"]
	assert risk == []


def test_analysis_profile_omits_resume_city():
	payload = build_analysis_profile_payload(_profile(), target_city="广州")
	assert "city" not in (payload.get("parsed_resume") or {})
	assert payload["job_search_context"]["target_city"] == "广州"


def test_analysis_detects_shell_company_hints():
	job = _sample_job(
		company="某某人力资源",
		title="不限经验 轻松月入 销售",
		description="急招",
		scale="",
		stage="",
	)
	result = score_job_analysis_heuristic(job, _profile())
	assert result.score < 70
	assert any("外包" in r or "画大饼" in r or "缺失" in r for r in result.risk)


def test_analysis_filters_low_scores(tmp_path: Path):
	analysis = AnalysisAI(pass_score=90)
	jobs = [_sample_job(
		title="不限经验 轻松月入 销售岗",
		company="",
		description="急招",
		skills=["销售"],
	)]
	result = analysis.analyze(jobs, _profile())
	assert result.jobs_filtered >= 1
	assert len(result.passed_jobs) == 0


def test_cache_scout_transmitted_methods(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	job = _sample_job()
	channel = "scout:test:"
	assert cache.filter_untransmitted(channel, [job]) == ([job], 0)
	cache.record_scout_transmitted(channel, [job])
	new_items, already = cache.filter_untransmitted(channel, [job])
	assert new_items == []
	assert already == 1
	assert cache.clear_scout_transmitted(channel) == 1
