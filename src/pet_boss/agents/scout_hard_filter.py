"""侦察 AI 硬性条件筛选 — 用户自选启用哪些条件及具体范围。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pet_boss.agents.school_tier_match import evaluate_school_tier_match
from pet_boss.agents.scout_quality_filter import (
	_active_desc,
	evaluate_agency_filter,
	is_long_inactive_boss,
)
from pet_boss.profile.models import UserProfile
from pet_boss.search_filters import (
	SearchFilterCriteria,
	education_in_range,
	experience_in_range,
	salary_overlaps_user_range,
)

_OVERTIME_BAD = ("996", "997", "加班严重", "通宵")
_WEEKEND_MODES: dict[str, tuple[str, ...]] = {
	"双休": ("双休", "周末双休", "五天工作制", "5天工作制"),
	"单休": ("单休",),
	"大小周": ("大小周",),
}
_INSURANCE_TYPES: dict[str, tuple[str, ...]] = {
	"五险一金": ("五险一金",),
	"有社保": ("社保", "五险", "五险一金"),
}

SCOUT_FILTER_KEYS: tuple[str, ...] = (
	"education",
	"experience",
	"salary",
	"overtime",
	"weekend",
	"insurance",
)

SCOUT_FILTER_LABELS: dict[str, str] = {
	"education": "学历",
	"experience": "工作经验",
	"salary": "薪资",
	"overtime": "加班要求",
	"weekend": "休息制度",
	"insurance": "社保福利",
}

WEEKEND_MODE_OPTIONS: tuple[str, ...] = ("单休", "双休", "大小周")
INSURANCE_TYPE_OPTIONS: tuple[str, ...] = ("五险一金", "有社保")


@dataclass(frozen=True)
class ScoutFilterConfig:
	"""用户启用的侦察硬性条件及具体筛选参数。"""

	enabled: frozenset[str] = frozenset()
	salary_min: str = ""
	salary_max: str = ""
	education_min: str = ""
	education_max: str = ""
	experience_min: str = ""
	experience_max: str = ""
	weekend_modes: frozenset[str] = frozenset()
	insurance_types: frozenset[str] = frozenset()

	@classmethod
	def from_payload(cls, data: Any = None) -> ScoutFilterConfig:
		if data is None:
			return cls()
		if isinstance(data, list):
			valid = {k for k in data if k in SCOUT_FILTER_KEYS}
			return cls(enabled=frozenset(valid))
		if not isinstance(data, dict):
			return cls()

		enabled: set[str] = set()
		for key in SCOUT_FILTER_KEYS:
			if data.get(key) is True:
				enabled.add(key)

		salary_range = data.get("salary_range") or {}
		edu_range = data.get("education_range") or {}
		exp_range = data.get("experience_range") or {}
		weekend_modes = data.get("weekend_modes") or []
		insurance_types = data.get("insurance_types") or []

		return cls(
			enabled=frozenset(enabled),
			salary_min=str(salary_range.get("min", "") or ""),
			salary_max=str(salary_range.get("max", "") or ""),
			education_min=str(edu_range.get("min", "") or ""),
			education_max=str(edu_range.get("max", "") or ""),
			experience_min=str(exp_range.get("min", "") or ""),
			experience_max=str(exp_range.get("max", "") or ""),
			weekend_modes=frozenset(
				m for m in weekend_modes if m in WEEKEND_MODE_OPTIONS
			),
			insurance_types=frozenset(
				t for t in insurance_types if t in INSURANCE_TYPE_OPTIONS
			),
		)

	def to_dict(self) -> dict[str, Any]:
		base = {k: k in self.enabled for k in SCOUT_FILTER_KEYS}
		base.update({
			"salary_range": {"min": self.salary_min, "max": self.salary_max},
			"education_range": {"min": self.education_min, "max": self.education_max},
			"experience_range": {"min": self.experience_min, "max": self.experience_max},
			"weekend_modes": sorted(self.weekend_modes),
			"insurance_types": sorted(self.insurance_types),
		})
		return base

	def is_enabled(self, key: str) -> bool:
		return key in self.enabled


@dataclass
class ScoutHardResult:
	passed: bool
	checks: dict[str, bool] = field(default_factory=dict)
	reasons: list[str] = field(default_factory=list)
	failures: list[str] = field(default_factory=list)
	skipped: list[str] = field(default_factory=list)


def _job_text_blob(job: dict[str, Any]) -> str:
	welfare = " ".join(job.get("welfare") or job.get("welfareList") or [])
	parts = [
		job.get("title", ""),
		job.get("company", ""),
		job.get("city", "") or job.get("cityName", ""),
		job.get("experience", "") or job.get("jobExperience", ""),
		job.get("education", "") or job.get("jobDegree", ""),
		job.get("salary", "") or job.get("salaryDesc", ""),
		job.get("description", "") or job.get("postDescription", ""),
		welfare,
	]
	return " ".join(str(p) for p in parts)


def _detect_weekend_mode(blob: str, welfare_text: str) -> str | None:
	text = welfare_text + blob
	for mode in ("大小周", "单休", "双休"):
		if mode == "双休":
			if any(k in text for k in _WEEKEND_MODES["双休"]):
				return "双休"
		elif mode in text:
			return mode
	return None


def _matches_insurance_type(blob: str, welfare_text: str, ins_type: str) -> bool:
	keywords = _INSURANCE_TYPES.get(ins_type, ())
	text = welfare_text + blob
	return any(k in text for k in keywords)


def evaluate_hard_criteria(
	job: dict[str, Any],
	profile: UserProfile | None,
	*,
	criteria: SearchFilterCriteria | None = None,
	scout_filters: ScoutFilterConfig | None = None,
) -> ScoutHardResult:
	"""按用户启用的硬性条件筛选岗位。

	院校层级：仅当 JD **明确**写出 985/211/一本等要求时侦察阶段硬性否决；
	名企隐性门槛（如华为）交由分析 AI 评估院校-公司匹配。
	"""
	filters = scout_filters or ScoutFilterConfig()

	tier_passed, tier_reasons, tier_failures, tier_checks = evaluate_school_tier_match(
		job, profile,
	)
	if not tier_passed:
		return ScoutHardResult(
			passed=False,
			checks=tier_checks,
			reasons=tier_reasons,
			failures=tier_failures,
		)

	agency_passed, agency_reasons, agency_failures, agency_checks = (
		evaluate_agency_filter(job)
	)
	checks: dict[str, bool] = {**tier_checks, **agency_checks}
	reasons: list[str] = list(tier_reasons) + agency_reasons
	failures: list[str] = list(tier_failures) + agency_failures
	if not agency_passed:
		return ScoutHardResult(
			passed=False,
			checks=checks,
			reasons=reasons,
			failures=failures,
		)

	if not filters.enabled:
		return _apply_boss_activity_gate(
			job,
			ScoutHardResult(
				passed=True,
				checks=checks,
				reasons=reasons or ["非猎头代招，院校层级已匹配"],
			),
			evaluated_filter_count=0,
		)

	blob = _job_text_blob(job).lower()
	welfare_text = " ".join(job.get("welfare") or job.get("welfareList") or [])
	checks = dict(checks)
	reasons = list(reasons)
	failures = list(failures)
	skipped: list[str] = []

	prefs = profile.preferences if profile else None

	# 薪资：用户自定义 K 范围
	if filters.is_enabled("salary"):
		if not filters.salary_min or not filters.salary_max:
			skipped.append("salary")
		else:
			job_salary = job.get("salary", "") or job.get("salaryDesc", "")
			ok = salary_overlaps_user_range(
				job_salary, filters.salary_min, filters.salary_max,
			)
			checks["salary"] = ok
			if ok:
				reasons.append(
					f"薪资满足期望（≥{filters.salary_min}K）：{job_salary}"
				)
			else:
				failures.append(
					f"薪资低于期望（<{filters.salary_min}K）：{job_salary}"
				)

	# 学历：岗位要求落在用户设定区间
	if filters.is_enabled("education"):
		if not filters.education_min or not filters.education_max:
			skipped.append("education")
		else:
			job_edu = job.get("education", "") or job.get("jobDegree", "")
			if not job_edu:
				checks["education"] = True
				reasons.append("岗位未标注学历要求")
			else:
				ok = education_in_range(
					job_edu, filters.education_min, filters.education_max,
				)
				checks["education"] = ok
				if ok:
					reasons.append(
						f"岗位学历 {job_edu} 在范围 {filters.education_min}～{filters.education_max}"
					)
				else:
					failures.append(
						f"岗位学历 {job_edu} 不在范围 {filters.education_min}～{filters.education_max}"
					)

	# 工作经验：岗位要求落在用户设定区间
	if filters.is_enabled("experience"):
		if not filters.experience_min or not filters.experience_max:
			skipped.append("experience")
		else:
			job_exp = job.get("experience", "") or job.get("jobExperience", "")
			if not job_exp:
				checks["experience"] = True
				reasons.append("岗位未标注经验要求")
			else:
				ok = experience_in_range(
					job_exp, filters.experience_min, filters.experience_max,
				)
				checks["experience"] = ok
				if ok:
					reasons.append(
						f"岗位经验 {job_exp} 在范围 {filters.experience_min}～{filters.experience_max}"
					)
				else:
					failures.append(
						f"岗位经验 {job_exp} 不在范围 {filters.experience_min}～{filters.experience_max}"
					)

	# 加班（仍参考画像偏好）
	if filters.is_enabled("overtime"):
		if not prefs or not prefs.overtime_tolerance:
			skipped.append("overtime")
		elif prefs.overtime_tolerance == "no":
			has_bad = any(k in blob for k in _OVERTIME_BAD)
			checks["overtime"] = not has_bad
			if has_bad:
				failures.append("岗位暗示高强度加班，与用户「不接受加班」冲突")
			else:
				reasons.append("未发现明显加班要求")
		elif prefs.overtime_tolerance == "occasional":
			has_severe = any(k in blob for k in ("996", "997", "通宵"))
			checks["overtime"] = not has_severe
			if has_severe:
				failures.append("岗位暗示极端加班")
			else:
				reasons.append("未发现极端加班要求")
		else:
			checks["overtime"] = True
			reasons.append("用户可接受加班")

	# 休息制度：用户勾选可接受的 单休/双休/大小周
	if filters.is_enabled("weekend"):
		if not filters.weekend_modes:
			skipped.append("weekend")
		else:
			mode = _detect_weekend_mode(blob, welfare_text)
			if mode is None:
				checks["weekend"] = True
				reasons.append("未标注休息制度，暂不否决")
			else:
				ok = mode in filters.weekend_modes
				checks["weekend"] = ok
				if ok:
					reasons.append(f"休息制度符合：{mode}")
				else:
					failures.append(
						f"休息制度为 {mode}，不在可接受范围（{', '.join(sorted(filters.weekend_modes))}）"
					)

	# 社保福利：五险一金 / 有社保
	if filters.is_enabled("insurance"):
		if not filters.insurance_types:
			skipped.append("insurance")
		else:
			matched = [
				t for t in filters.insurance_types
				if _matches_insurance_type(blob, welfare_text, t)
			]
			ok = bool(matched)
			checks["insurance"] = ok
			if ok:
				reasons.append(f"福利匹配：{', '.join(matched)}")
			else:
				failures.append(
					f"未满足社保福利要求（{', '.join(sorted(filters.insurance_types))}）"
				)

	evaluated = [k for k in filters.enabled if k not in skipped]
	if not evaluated:
		return _apply_boss_activity_gate(
			job,
			ScoutHardResult(
				passed=True,
				skipped=skipped,
				checks=checks,
				reasons=reasons or ["已启用条件但缺少具体筛选参数，院校层级已匹配"],
			),
			evaluated_filter_count=0,
		)

	passed = all(checks.get(k, True) for k in evaluated)
	return _apply_boss_activity_gate(
		job,
		ScoutHardResult(
			passed=passed,
			checks=checks,
			reasons=reasons,
			failures=failures,
			skipped=skipped,
		),
		evaluated_filter_count=len(evaluated),
	)


def _apply_boss_activity_gate(
	job: dict[str, Any],
	result: ScoutHardResult,
	*,
	evaluated_filter_count: int,
) -> ScoutHardResult:
	"""半个月以上未活跃 HR 需筛；岗位硬性条件高度匹配时可酌情保留。"""
	inactive, inactive_msg = is_long_inactive_boss(job)
	if not inactive:
		active = _active_desc(job)
		if active and active != "离线":
			result.reasons.append(f"招聘者活跃：{active}")
		result.checks["boss_active"] = True
		return result

	result.checks["boss_active"] = False
	excellent_match = result.passed and evaluated_filter_count >= 1
	if excellent_match:
		active = _active_desc(job)
		result.reasons.append(
			f"招聘者较久未活跃（{active}），岗位硬性条件高度匹配，酌情保留"
		)
		result.checks["boss_active"] = True
		return result

	result.failures.append(inactive_msg)
	result.passed = False
	return result
