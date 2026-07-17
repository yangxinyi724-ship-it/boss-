"""秘书 AI 六维岗位评分 — 技能/薪资/福利/经验/发展/通勤。"""

from __future__ import annotations

import hashlib
import re
from typing import Any

SIX_DIM_KEYS = ("skill", "salary", "benefits", "experience", "development", "commute")
SIX_DIM_LABELS = {
	"skill": "技能",
	"salary": "薪资",
	"benefits": "福利",
	"experience": "经验",
	"development": "发展",
	"commute": "通勤",
}

_ARCHETYPE_BY_PAIR: dict[frozenset[str], str] = {
	frozenset({"skill", "benefits"}): "稳健型",
	frozenset({"skill", "development"}): "成长型",
	frozenset({"salary", "benefits"}): "性价比型",
	frozenset({"development", "experience"}): "进阶型",
	frozenset({"salary", "development"}): "高薪成长型",
	frozenset({"commute", "benefits"}): "舒适平衡型",
	frozenset({"skill", "salary"}): "硬核匹配型",
	frozenset({"experience", "benefits"}): "资历福利型",
}


def _stable_jitter(seed: str, dim: str, spread: int = 11) -> int:
	digest = hashlib.md5(f"{seed}:{dim}".encode()).hexdigest()
	return (int(digest[:8], 16) % (spread * 2 + 1)) - spread


def _clamp(value: int) -> int:
	return max(0, min(100, value))


def _parse_salary_mid(salary: str) -> int | None:
	text = salary or ""
	nums = [int(x) for x in re.findall(r"(\d+)", text.replace("K", "k"))]
	if not nums:
		return None
	if len(nums) >= 2:
		return (nums[0] + nums[1]) // 2
	return nums[0]


def _benefits_hint(job: dict[str, Any]) -> int:
	text = " ".join(
		str(job.get(k) or "")
		for k in ("description", "welfare", "tags", "skills", "title")
	).lower()
	score = 52
	for kw, pts in (
		("五险一金", 12), ("六险一金", 14), ("双休", 10), ("弹性", 6),
		("餐补", 5), ("年终奖", 8), ("带薪年假", 6), ("补充医疗", 5),
	):
		if kw in text:
			score += pts
	if re.search(r"单休|大小周|996|加班严重", text):
		score -= 12
	return _clamp(score)


def _experience_fit(job: dict[str, Any], years: float | None) -> int:
	exp = str(job.get("experience") or job.get("job_experience") or "")
	base = 62
	if "不限" in exp or "经验不限" in exp:
		base = 70
	elif "应届" in exp:
		base = 55 if (years or 0) > 1 else 78
	elif "1-3" in exp or "1年" in exp:
		base = 72
	elif "3-5" in exp:
		base = 68 if (years or 0) >= 3 else 58
	elif "5-10" in exp or "5年" in exp:
		base = 65 if (years or 0) >= 5 else 52
	dims = job.get("analysis_dimensions") or {}
	if isinstance(dims, dict) and dims.get("career_fit"):
		base = int((base + int(dims["career_fit"])) / 2)
	return _clamp(base)


def _detect_archetype(scores: dict[str, int]) -> str:
	ranked = sorted(SIX_DIM_KEYS, key=lambda k: scores.get(k, 0), reverse=True)
	top2 = frozenset(ranked[:2])
	if top2 in _ARCHETYPE_BY_PAIR:
		return _ARCHETYPE_BY_PAIR[top2]
	spread = max(scores.values()) - min(scores.values()) if scores else 0
	if spread <= 12:
		return "综合均衡型"
	return "特色突出型"


def _build_commentary(scores: dict[str, int], archetype: str) -> str:
	labels = SIX_DIM_LABELS
	ranked = sorted(SIX_DIM_KEYS, key=lambda k: scores[k], reverse=True)
	top, second = ranked[0], ranked[1]
	weak = ranked[-1]
	text = (
		f"{archetype}岗位：{labels[top]}{scores[top]}分、{labels[second]}{scores[second]}分较突出，"
		f"{labels[weak]}{scores[weak]}分相对短板，建议结合通勤与福利综合决策。"
	)
	return text[:100]


def score_job_six_dimensions(
	job: dict[str, Any],
	*,
	portrait: dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""对单个岗位输出差异化六维评分 JSON（含 scores / archetype / commentary）。"""
	seed = str(job.get("job_id") or job.get("security_id") or job.get("title") or "job")
	analysis_score = int(job.get("analysis_score") or job.get("profile_score") or 65)
	dims = job.get("analysis_dimensions") or {}

	years = None
	if portrait:
		years = portrait.get("years_of_experience")

	skill_base = int(dims.get("skill_match") or analysis_score)
	salary_mid = _parse_salary_mid(str(job.get("salary") or ""))
	salary_base = 58
	if salary_mid:
		if salary_mid >= 30:
			salary_base = 82
		elif salary_mid >= 20:
			salary_base = 72
		elif salary_mid >= 15:
			salary_base = 64
		else:
			salary_base = 54

	dev_base = int(dims.get("growth_prospect") or dims.get("career_fit") or (analysis_score - 4))
	commute_base = 68
	if portrait and portrait.get("city") and job.get("city"):
		if portrait["city"] in str(job["city"]) or str(job["city"]) in portrait["city"]:
			commute_base = 82
		else:
			commute_base = 52

	scores = {
		"skill": _clamp(skill_base + _stable_jitter(seed, "skill")),
		"salary": _clamp(salary_base + _stable_jitter(seed, "salary")),
		"benefits": _clamp(_benefits_hint(job) + _stable_jitter(seed, "benefits", 7)),
		"experience": _clamp(_experience_fit(job, years) + _stable_jitter(seed, "experience", 8)),
		"development": _clamp(dev_base + _stable_jitter(seed, "development")),
		"commute": _clamp(commute_base + _stable_jitter(seed, "commute", 9)),
	}

	# 确保各维度不完全相同
	vals = list(scores.values())
	if len(set(vals)) <= 2:
		scores["benefits"] = _clamp(scores["benefits"] + 6)
		scores["commute"] = _clamp(scores["commute"] - 5)

	archetype = _detect_archetype(scores)
	commentary = _build_commentary(scores, archetype)

	return {
		"scores": scores,
		"scores_labeled": {SIX_DIM_LABELS[k]: scores[k] for k in SIX_DIM_KEYS},
		"archetype": archetype,
		"commentary": commentary,
	}


def compile_passed_jobs_with_scores(
	passed_rows: list[dict[str, Any]],
	*,
	portrait: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
	compiled: list[dict[str, Any]] = []
	for row in passed_rows:
		job = row.get("job") if isinstance(row.get("job"), dict) else row
		six = score_job_six_dimensions(job, portrait=portrait)
		compiled.append({
			**row,
			"job": job,
			"scores": six["scores"],
			"scores_labeled": six["scores_labeled"],
			"archetype": six["archetype"],
			"commentary": six["commentary"],
		})
	return compiled


def _daily_pick_rank(row: dict[str, Any]) -> float:
	job = row.get("job") or row
	analysis = float(job.get("analysis_score") or job.get("profile_score") or 0)
	scores = row.get("scores") or {}
	if scores:
		six_avg = sum(scores.get(k, 0) for k in SIX_DIM_KEYS) / len(SIX_DIM_KEYS)
	else:
		six_avg = analysis
	return analysis * 0.6 + six_avg * 0.4


def select_daily_picks(
	compiled_passed: list[dict[str, Any]],
	*,
	max_count: int = 5,
) -> list[dict[str, Any]]:
	"""从当日通过岗中选出最值得优先查看的 Top N。"""
	if not compiled_passed or max_count <= 0:
		return []
	ranked = sorted(compiled_passed, key=_daily_pick_rank, reverse=True)
	picks: list[dict[str, Any]] = []
	for row in ranked[:max_count]:
		job = row.get("job") or row
		picks.append({
			"title": row.get("title") or job.get("title") or "",
			"company": row.get("company") or job.get("company") or "",
			"salary": job.get("salary") or "",
			"city": job.get("city") or "",
			"analysis_score": int(job.get("analysis_score") or job.get("profile_score") or 0),
			"archetype": row.get("archetype") or "",
			"commentary": row.get("commentary") or "",
			"scores": row.get("scores") or {},
			"scores_labeled": row.get("scores_labeled") or {},
			"pick_score": round(_daily_pick_rank(row), 1),
			"job_id": job.get("job_id") or "",
			"security_id": job.get("security_id") or "",
			"boss_url": job.get("boss_url") or job.get("url") or "",
			"analysis_reason": job.get("analysis_reason") or job.get("profile_reason") or [],
		})
	return picks
