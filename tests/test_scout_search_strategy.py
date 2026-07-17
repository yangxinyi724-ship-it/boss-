"""侦察 AI 搜索词策略测试。"""

from __future__ import annotations

from pet_boss.agents.scout_search_strategy import (
	generate_search_queries_from_portrait,
	resolve_scout_search_plan,
)
from pet_boss.profile.models import ParsedResume, UserProfile
from pet_boss.secretary.portrait import build_secretary_portrait


def _java_fresh_portrait() -> dict:
	parsed = ParsedResume(
		skills=["Java", "Spring"],
		years_of_experience=0,
		education="本科应届",
		summary="Java应届生，已毕业",
		real_capabilities=["Java基础扎实"],
	)
	return build_secretary_portrait(parsed, expected_role="Java开发")


def test_recent_graduate_gets_yingjie_not_xiaozhao():
	"""已毕业应届：要应届生词，不要校招/实习。"""
	portrait = _java_fresh_portrait()
	parsed = ParsedResume(
		skills=["Java"],
		years_of_experience=0,
		education="本科应届",
		summary="Java应届生，已毕业",
	)
	queries = generate_search_queries_from_portrait(portrait, parsed=parsed)
	joined = " ".join(queries)
	assert "Java开发" in queries
	assert "应届生" in joined or any("应届生" in q for q in queries)
	assert "校招" not in joined
	assert "实习" not in joined


def test_in_school_gets_campus_not_yingjie():
	"""在校未毕业：要校招/实习，不要应届生。"""
	parsed = ParsedResume(
		skills=["Java"],
		years_of_experience=0,
		education="本科在读",
		summary="某大学大四在校生，找Java实习",
	)
	portrait = build_secretary_portrait(parsed, expected_role="Java开发")
	queries = generate_search_queries_from_portrait(portrait, parsed=parsed)
	joined = " ".join(queries)
	assert any("校招" in q or "实习" in q for q in queries)
	assert "应届生" not in joined


def test_resolve_merges_user_and_auto():
	profile = UserProfile(
		parsed_resume=ParsedResume(skills=["Python"], years_of_experience=2, summary="后端"),
	)
	portrait = build_secretary_portrait(profile.parsed_resume, expected_role="Python开发")
	plan = resolve_scout_search_plan(
		profile,
		store=None,
		user_query="Django",
		auto_keywords=True,
	)
	assert plan["queries"][0] == "Django"
	assert plan["source"] == "user_and_secretary"
	assert len(plan["queries"]) >= 2


def test_keywords_only_ignores_empty_user():
	profile = UserProfile(
		parsed_resume=ParsedResume(skills=["Go"], years_of_experience=1, summary="Go开发"),
	)
	portrait = build_secretary_portrait(profile.parsed_resume)
	plan = resolve_scout_search_plan(
		profile,
		store=None,
		user_query="",
		auto_keywords=True,
		keywords_only=True,
	)
	assert plan["source"] == "secretary_auto"
	assert plan["queries"]


def test_graduated_with_experience_no_campus_or_yingjie():
	parsed = ParsedResume(
		skills=["Java", "Spring"],
		years_of_experience=3,
		education="本科",
		summary="3年Java后端开发经验，已毕业",
		real_capabilities=["Java后端"],
	)
	portrait = build_secretary_portrait(parsed, expected_role="Java开发")
	queries = generate_search_queries_from_portrait(portrait, parsed=parsed)
	joined = " ".join(queries)
	assert "校招" not in joined
	assert "实习" not in joined
	assert "应届生" not in joined
	assert any("Java" in q for q in queries)


def test_one_year_graduate_still_yingjie():
	"""毕业 1 年内仍算应届，但不走校招。"""
	parsed = ParsedResume(
		skills=["Python"],
		years_of_experience=1,
		education="本科",
		summary="1年Python开发，已毕业",
	)
	portrait = build_secretary_portrait(parsed, expected_role="Python开发")
	queries = generate_search_queries_from_portrait(portrait, parsed=parsed)
	assert any("应届生" in q for q in queries)
	assert not any("校招" in q for q in queries)
