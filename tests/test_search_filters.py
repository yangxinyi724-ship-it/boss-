"""Tests for search_filters module — list-page prefiltering and pipeline."""
import pytest

from pet_boss.search_filters import (
	SearchFilterCriteria,
	SearchUrlParseError,
	parse_salary_range,
	parse_boss_search_url,
	meets_experience_threshold,
	meets_education_threshold,
	education_in_range,
	experience_in_range,
	salary_overlaps_user_range,
	prefilter_job,
	resolve_search_code_params,
)


# ── Salary parsing ──────────────────────────────────────────────────

class TestParseSalaryRange:
	def test_standard(self):
		assert parse_salary_range("20-50K") == (20, 50)

	def test_with_bonus(self):
		assert parse_salary_range("25-50K·15薪") == (25, 50)

	def test_single_value(self):
		assert parse_salary_range("20K") == (20, 20)

	def test_mianyi(self):
		assert parse_salary_range("面议") is None

	def test_empty(self):
		assert parse_salary_range("") is None

	def test_garbage(self):
		assert parse_salary_range("日薪200") is None

	def test_below_range(self):
		assert parse_salary_range("3K以下") == (0, 3)


# ── URL and code parsing ────────────────────────────────────────────

class TestSearchUrlParsing:
	def test_parse_boss_search_url_with_filters(self):
		parsed = parse_boss_search_url(
			"https://www.zhipin.com/web/geek/jobs?query=Python&city=101280100&experience=102,104&degree=203&page=2"
		)
		assert parsed.query == "Python"
		assert parsed.params == {
			"city": "101280100",
			"experience": "102,104",
			"degree": "203",
		}
		assert parsed.page == 2

	def test_parse_boss_search_url_allows_filter_only_url(self):
		parsed = parse_boss_search_url("https://www.zhipin.com/web/geek/job?city=101280100&salary=406")
		assert parsed.query == ""
		assert parsed.params == {"city": "101280100", "salary": "406"}

	def test_parse_boss_search_url_rejects_external_host(self):
		with pytest.raises(SearchUrlParseError):
			parse_boss_search_url("https://example.com/web/geek/jobs?query=Python")

	def test_resolve_search_code_params_supports_multiselect(self):
		params = resolve_search_code_params(experience="应届,3-5年", education="本科,硕士", job_type="全职,实习")
		assert params["experience"] == "108,104"
		assert params["degree"] == "203,204"
		assert params["jobType"] == "1901,1903"


# ── Experience threshold ────────────────────────────────────────────

class TestExperienceThreshold:
	def test_no_requirement(self):
		assert meets_experience_threshold("应届", None) is True

	def test_meets(self):
		assert meets_experience_threshold("3-5年", "1-3年") is True

	def test_below(self):
		assert meets_experience_threshold("应届", "3-5年") is False

	def test_equal(self):
		assert meets_experience_threshold("3-5年", "3-5年") is True

	def test_above(self):
		assert meets_experience_threshold("5-10年", "3-5年") is True

	def test_unknown_candidate(self):
		# Unknown experience strings should pass (no filtering)
		assert meets_experience_threshold("经验不限", "3-5年") is True


# ── Education threshold ─────────────────────────────────────────────

class TestEducationThreshold:
	def test_no_requirement(self):
		assert meets_education_threshold("大专", None) is True

	def test_meets(self):
		assert meets_education_threshold("本科", "本科") is True

	def test_above(self):
		assert meets_education_threshold("硕士", "本科") is True

	def test_below(self):
		assert meets_education_threshold("大专", "本科") is False

	def test_unknown(self):
		# Unknown should pass
		assert meets_education_threshold("学历不限", "本科") is True


class TestEducationExperienceRange:
	def test_education_in_range(self):
		assert education_in_range("本科", "大专", "硕士") is True
		assert education_in_range("硕士", "大专", "本科") is False

	def test_experience_in_range(self):
		assert experience_in_range("3-5年", "1-3年", "5-10年") is True
		assert experience_in_range("10年以上", "1-3年", "3-5年") is False

	def test_salary_overlap(self):
		assert salary_overlaps_user_range("20-35K", "15", "30") is True
		assert salary_overlaps_user_range("3-5K", "15", "30") is False
		assert salary_overlaps_user_range("15-25K", "6", "10") is True
		assert salary_overlaps_user_range("3-5K", "6", "10") is False
		assert salary_overlaps_user_range("8-12K", "6", "10") is True


# ── List-page prefilter ─────────────────────────────────────────────

def _make_raw(
	salary="20-50K",
	city="广州",
	experience="3-5年",
	education="本科",
):
	return {
		"salaryDesc": salary,
		"cityName": city,
		"jobExperience": experience,
		"jobDegree": education,
	}


class TestPrefilterJob:
	def test_all_pass(self):
		raw = _make_raw()
		criteria = SearchFilterCriteria(
			query="go",
			city="广州",
			salary="10-20K",
			experience="3-5年",
			education="本科",
		)
		ok, reasons = prefilter_job(raw, criteria)
		assert ok is True
		assert reasons == []

	def test_city_mismatch(self):
		raw = _make_raw(city="上海")
		criteria = SearchFilterCriteria(query="go", city="广州")
		ok, reasons = prefilter_job(raw, criteria)
		assert ok is False
		assert any("城市" in r for r in reasons)

	def test_salary_below(self):
		raw = _make_raw(salary="3-5K")
		criteria = SearchFilterCriteria(query="go", salary="20-50K")
		ok, reasons = prefilter_job(raw, criteria)
		assert ok is False
		assert any("薪资" in r for r in reasons)

	def test_salary_mianyi_pass(self):
		"""面议的薪资应该通过（无法判断）"""
		raw = _make_raw(salary="面议")
		criteria = SearchFilterCriteria(query="go", salary="20-50K")
		ok, reasons = prefilter_job(raw, criteria)
		assert ok is True

	def test_education_job_too_high(self):
		"""岗位要求高于用户学历时应拒绝。"""
		raw = _make_raw(education="硕士")
		criteria = SearchFilterCriteria(query="go", education="本科")
		ok, reasons = prefilter_job(raw, criteria)
		assert ok is False
		assert any("学历" in r for r in reasons)

	def test_education_user_qualifies_for_lower_job(self):
		"""用户本科可满足岗位要求大专。"""
		raw = _make_raw(education="大专")
		criteria = SearchFilterCriteria(query="go", education="本科")
		ok, reasons = prefilter_job(raw, criteria)
		assert ok is True
		assert reasons == []

	def test_experience_job_too_high(self):
		raw = _make_raw(experience="5-10年")
		criteria = SearchFilterCriteria(query="go", experience="3-5年")
		ok, reasons = prefilter_job(raw, criteria)
		assert ok is False
		assert any("经验" in r for r in reasons)

	def test_no_criteria_all_pass(self):
		"""No filter criteria means everything passes"""
		raw = _make_raw()
		criteria = SearchFilterCriteria(query="go")
		ok, reasons = prefilter_job(raw, criteria)
		assert ok is True
