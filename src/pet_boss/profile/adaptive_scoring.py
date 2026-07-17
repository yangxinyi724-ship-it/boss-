"""Step 4: Adaptive Job Scoring — 自适应岗位评分。"""

from __future__ import annotations

import json
from typing import Any

from pet_boss.ai.service import AIService
from pet_boss.match_score import score_job_dict
from pet_boss.profile.learning import feedback_summary_for_prompt
from pet_boss.profile.models import AdaptiveScore, CareerDirection, ParsedResume, UserPreferences, UserProfile
from pet_boss.profile.prompts import ADAPTIVE_SCORE_PROMPT
from pet_boss.profile.store import ProfileStore
from pet_boss.search_filters import SearchFilterCriteria


def _text_blob(job: dict[str, Any]) -> str:
	parts = [
		job.get("title", ""),
		job.get("company", ""),
		" ".join(job.get("skills") or []),
		job.get("industry", ""),
		job.get("stage", ""),
		job.get("scale", ""),
	]
	return " ".join(str(p) for p in parts).lower()


def _score_dimension(
	job: dict[str, Any],
	profile: UserProfile,
	weights: dict[str, float],
) -> dict[str, int]:
	parsed = profile.parsed_resume
	prefs = profile.preferences
	career = profile.career
	blob = _text_blob(job)

	dims: dict[str, int] = {}

	# 技能匹配
	skills = (parsed.skills if parsed else []) + (parsed.tools if parsed else [])
	hits = sum(1 for s in skills if s.lower() in blob)
	dims["skill_match"] = min(100, 40 + hits * 12) if skills else 50

	# 行业
	industries = parsed.industries if parsed else []
	dims["industry_match"] = 75 if any(i.lower() in blob for i in industries) else 55

	# 成长 / 公司阶段
	stage = job.get("stage", "") or ""
	if "天使" in stage or "A轮" in stage or "B轮" in stage:
		dims["company_stage"] = 85 if (prefs and prefs.startup_fit) or (career and career.startup_fit) else 40
	elif "已上市" in stage or "不需要融资" in stage:
		dims["company_stage"] = 85 if prefs and prefs.stability_priority == "high" else 65
	else:
		dims["company_stage"] = 60

	# 城市
	city = parsed.city if parsed else ""
	dims["city_match"] = 90 if city and city in job.get("city", "") else 55

	# 职业目标
	primary = career.primary_direction if career else ""
	dims["career_goal"] = 88 if primary and any(k in blob for k in primary.lower().split()) else 50

	# 偏好契合
	pref_score = 70
	if prefs:
		if prefs.sales_role_ok is False and any(w in blob for w in ("销售", "商务", "bd")):
			pref_score -= 30
		if prefs.remote_ok and "远程" in blob:
			pref_score += 15
		if prefs.overtime_tolerance == "no" and any(w in blob for w in ("大小周", "996", "加班")):
			pref_score -= 25
	dims["preference_fit"] = max(0, min(100, pref_score))

	# 工作强度（反向：加班越多分越低）
	intensity = 70
	if any(w in blob for w in ("大小周", "996", "加班")):
		intensity = 35
	elif "双休" in blob:
		intensity = 90
	dims["work_intensity"] = intensity

	# 薪资（沿用基础分）
	base = score_job_dict(job, criteria=None, expect_data=None)
	dims["salary"] = base.get("match_score") or 50

	# 成长性
	dims["growth"] = 80 if any(w in blob for w in ("ai", "agent", "增长", "0-1", "创业")) else 60

	# 应用学习权重
	weighted_sum = 0.0
	weight_total = 0.0
	for dim, val in dims.items():
		w = weights.get(dim, 1.0)
		weighted_sum += val * w
		weight_total += w
	dims["_weighted_avg"] = int(weighted_sum / weight_total) if weight_total else 50
	return dims


def _priority_from_score(score: int) -> str:
	if score >= 80:
		return "high"
	if score >= 60:
		return "medium"
	return "low"


def score_job_adaptive_heuristic(
	job: dict[str, Any],
	profile: UserProfile,
	*,
	store: ProfileStore | None = None,
) -> AdaptiveScore:
	weights = store.get_dimension_weights() if store else {}
	dims = _score_dimension(job, profile, weights)
	score = dims.pop("_weighted_avg", 50)

	reason: list[str] = []
	risk: list[str] = []
	blob = _text_blob(job)
	career = profile.career
	prefs = profile.preferences

	if dims.get("skill_match", 0) >= 75:
		reason.append("技能栈与岗位高度重合")
	if career and career.primary_direction and career.primary_direction.lower() in blob:
		reason.append(f"与职业方向「{career.primary_direction}」一致")
	if dims.get("city_match", 0) >= 85:
		reason.append("城市匹配")
	if dims.get("company_stage", 0) >= 80:
		reason.append("公司阶段符合你的偏好")
	if any(w in blob for w in ("996", "大小周", "加班")):
		risk.append("岗位描述暗示较高工作强度")
	if career and career.avoid_direction:
		for avoid in career.avoid_direction:
			if avoid and avoid[:2] in blob:
				risk.append(f"可能接近你希望避开的方向：{avoid}")
				score = max(0, score - 15)

	if not reason:
		reason.append("基础条件部分匹配，建议查看详情确认")

	return AdaptiveScore(
		score=min(100, max(0, score)),
		reason=reason,
		risk=risk,
		priority=_priority_from_score(score),
		dimensions={k: v for k, v in dims.items() if isinstance(v, int)},
	)


def score_job_adaptive_with_ai(
	svc: AIService,
	job: dict[str, Any],
	profile: UserProfile,
	*,
	store: ProfileStore | None = None,
) -> AdaptiveScore:
	learning_hints = feedback_summary_for_prompt(store) if store else ""
	prompt = ADAPTIVE_SCORE_PROMPT.format(
		profile_json=json.dumps(profile.to_dict(), ensure_ascii=False),
		learning_hints=learning_hints,
		job_json=json.dumps(job, ensure_ascii=False),
	)
	raw = svc.chat([
		{"role": "system", "content": "你是求职匹配专家。只输出 JSON。"},
		{"role": "user", "content": prompt},
	], agent="FX")
	text = raw.strip()
	if text.startswith("```"):
		text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```")).strip()
	data = json.loads(text)
	return AdaptiveScore(
		score=int(data.get("score", 0)),
		reason=list(data.get("reason") or []),
		risk=list(data.get("risk") or []),
		priority=data.get("priority") or "medium",
		dimensions=dict(data.get("dimensions") or {}),
	)


def score_job_adaptive(
	job: dict[str, Any],
	profile: UserProfile,
	*,
	store: ProfileStore | None = None,
	ai_service: AIService | None = None,
	criteria: SearchFilterCriteria | None = None,
) -> AdaptiveScore:
	# 合并基础规则分
	base = score_job_dict(job, criteria=criteria, expect_data=None)
	heuristic = score_job_adaptive_heuristic(job, profile, store=store)
	# 与旧 match_score 加权融合
	blended = int(heuristic.score * 0.75 + base.get("match_score", 0) * 0.25)
	heuristic.score = min(100, blended)
	for r in base.get("match_reasons") or []:
		if r not in heuristic.reason:
			heuristic.reason.append(r)

	if ai_service is not None:
		try:
			return score_job_adaptive_with_ai(ai_service, job, profile, store=store)
		except Exception:
			pass
	return heuristic


def enrich_job_with_profile_score(
	job: dict[str, Any],
	profile: UserProfile,
	*,
	store: ProfileStore | None = None,
	ai_service: AIService | None = None,
	criteria: SearchFilterCriteria | None = None,
) -> dict[str, Any]:
	adaptive = score_job_adaptive(
		job, profile, store=store, ai_service=ai_service, criteria=criteria,
	)
	return {
		**job,
		"profile_score": adaptive.score,
		"profile_reason": adaptive.reason,
		"profile_risk": adaptive.risk,
		"profile_priority": adaptive.priority,
		"profile_dimensions": adaptive.dimensions,
		"match_score": adaptive.score,
		"match_reasons": adaptive.reason,
	}
