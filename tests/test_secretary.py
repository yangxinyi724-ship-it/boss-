"""秘书 AI 与 analysis_records 持久化测试。"""

from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path

from pet_boss.agents.analysis_store import persist_analysis_result, day_record_summary
from pet_boss.agents.analysis_ai import AnalysisResult
from pet_boss.agents.secretary_ai import SecretaryAI, day_bounds, resolve_report_date
from pet_boss.cache.store import CacheStore
from pet_boss.profile.models import ParsedResume
from pet_boss.profile.store import ProfileStore
from pet_boss.secretary.config import SecretaryConfigStore
from pet_boss.secretary.feedback import parse_feedback_to_instructions, save_preference_instructions
from pet_boss.secretary.portrait import build_secretary_portrait
from pet_boss.secretary.six_dim_score import score_job_six_dimensions


def _sample_job(title: str, score: int, *, passed: bool = True) -> dict:
	return {
		"security_id": f"sec-{title}",
		"job_id": f"job-{title}",
		"title": title,
		"company": "测试公司",
		"city": "杭州",
		"salary": "20-30K",
		"analysis_score": score,
		"analysis_status": "passed" if passed else "filtered",
		"analysis_reason": ["技能匹配"],
		"analysis_risk": [] if passed else ["加班风险"],
		"analysis_dimensions": {"skill_match": score, "growth_prospect": score - 5},
	}


def test_analysis_records_persist_and_query(tmp_path: Path):
	store = CacheStore(tmp_path / "test.db")
	job = _sample_job("Go开发", 85)
	store.record_analysis_job(job, "passed", search_query="golang", search_city="杭州")
	rows = store.list_analysis_records(0, time.time() + 1, status="passed")
	assert len(rows) == 1
	assert rows[0]["title"] == "Go开发"
	assert rows[0]["analysis_score"] == 85


def test_persist_analysis_result_from_analysis_ai(tmp_path: Path):
	store = CacheStore(tmp_path / "test.db")
	result = AnalysisResult(
		jobs_received=2,
		jobs_passed=1,
		jobs_filtered=1,
		passed_jobs=[_sample_job("A", 90)],
		filtered_jobs=[_sample_job("B", 40, passed=False)],
	)
	count, _ablation = persist_analysis_result(store, result, channel="scout:golang:")
	assert count == 2
	all_rows = store.list_analysis_records(0, time.time() + 1)
	assert len(all_rows) == 2


def test_six_dim_scores_are_differentiated():
	job_a = _sample_job("Python", 88)
	job_b = _sample_job("Java", 88)
	sa = score_job_six_dimensions(job_a)
	sb = score_job_six_dimensions(job_b)
	assert "scores" in sa
	assert len(sa["scores"]) == 6
	assert sa["scores"] != sb["scores"]
	assert sa["archetype"]
	assert len(sa["commentary"]) <= 100


def test_secretary_portrait_and_feedback(tmp_path: Path):
	parsed = ParsedResume(
		skills=["Python", "Go"],
		years_of_experience=4,
		education="本科",
		school_name="某大学",
		school_tier="二本",
		school_tier_code=3,
		gender="女",
		age=28,
		real_capabilities=["后端架构"],
		summary="后端开发",
	)
	portrait = build_secretary_portrait(parsed, expected_role="后端开发")
	assert portrait["expected_role"] == "后端开发"
	assert portrait["for_scout"]["skills"] == ["Python", "Go"]
	assert portrait["for_scout"]["gender"] == "女"
	assert portrait["for_analysis"]["basics"]["school_tier_code"] == 3

	pstore = ProfileStore(tmp_path)
	payload = save_preference_instructions(
		pstore,
		parse_feedback_to_instructions("不要单休；希望远程"),
		raw_feedback="不要单休；希望远程",
	)
	assert payload["instructions"]
	assert pstore.load_preference_instructions()


def test_secretary_daily_report_with_six_dim(tmp_path: Path):
	store = CacheStore(tmp_path / "test.db")
	pstore = ProfileStore(tmp_path)
	pstore.save_secretary_portrait(build_secretary_portrait(
		ParsedResume(skills=["Python"], city="杭州"),
		expected_role="Python开发",
	))
	yesterday = date.today() - timedelta(days=1)
	since, until = day_bounds(yesterday)
	ts = since + 3600
	store.record_analysis_job(_sample_job("Python", 88), "passed", analyzed_at=ts)

	config_store = SecretaryConfigStore(tmp_path)
	secretary = SecretaryAI(
		store, config_store, data_dir=tmp_path, profile_store=pstore,
	)
	report = secretary.build_report(yesterday)
	assert "Python" in report["markdown"]
	assert "六维" in report["markdown"]
	assert "每日精选" in report["markdown"]
	assert report["data"]["jobs_json"][0]["scores"]
	assert report["data"]["summary"]["passed_count"] == 1
	assert len(report["data"]["daily_picks"]) == 1
	assert report["data"]["daily_picks"][0]["title"] == "Python"


def test_resolve_report_date_yesterday():
	assert resolve_report_date("yesterday") == date.today() - timedelta(days=1)
	assert resolve_report_date("2026-06-01") == date(2026, 6, 1)


def test_day_record_summary():
	records = [
		{"status": "passed", "analysis_score": 80},
		{"status": "passed", "analysis_score": 60},
		{"status": "filtered", "analysis_score": 30},
	]
	summary = day_record_summary(records)
	assert summary["passed_count"] == 2
	assert summary["filtered_count"] == 1
	assert summary["avg_pass_score"] == 70.0
