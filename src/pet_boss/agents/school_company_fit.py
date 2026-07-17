"""院校与公司招聘偏好匹配 — 分析 AI 依据秘书判定的院校层级评估公司友好度。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pet_boss.agents.school_tier_match import (
	detect_job_school_requirement,
	evaluate_school_tier_match,
	infer_user_school_tier,
)
from pet_boss.ai.service import AIService
from pet_boss.profile.models import UserProfile
from pet_boss.profile.prompts import COMPANY_SCHOOL_FRIENDLINESS_PROMPT


@dataclass
class SchoolCompanyFitResult:
	fit_level: str = "unknown"  # high / medium / low / unknown
	score_adjustment: int = 0
	reasons: list[str] = field(default_factory=list)
	risks: list[str] = field(default_factory=list)
	school_label: str = ""
	company: str = ""
	source: str = "heuristic"  # heuristic / ai
	exclude: bool = False


def _company_name(job: dict[str, Any]) -> str:
	return str(job.get("company") or job.get("brandName") or "").strip()


def _secretary_school_context(profile: UserProfile | None) -> dict[str, Any]:
	pr = profile.parsed_resume if profile and profile.parsed_resume else None
	if not pr:
		return {
			"school_name": "",
			"education": "",
			"school_tier": "",
			"school_tier_code": 0,
			"school_tier_reason": "",
			"from_secretary": False,
		}
	return {
		"school_name": pr.school_name or "",
		"education": pr.education or "",
		"school_tier": pr.school_tier or "",
		"school_tier_code": int(pr.school_tier_code or 0),
		"school_tier_reason": pr.school_tier_reason or "",
		"from_secretary": bool(pr.school_tier_code and pr.school_tier_code > 0),
	}


def _parse_ai_json(raw: str) -> dict[str, Any]:
	text = raw.strip()
	if text.startswith("```"):
		text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```")).strip()
	return json.loads(text)


def assess_explicit_jd_school_mismatch(
	job: dict[str, Any],
	profile: UserProfile | None,
) -> SchoolCompanyFitResult | None:
	"""JD 明文要求 985/211/一本等，且用户院校层级不满足 → 直接筛掉。"""
	job_req = detect_job_school_requirement(job)
	if job_req is None:
		return None
	user = infer_user_school_tier(profile)
	if user.tier <= 0:
		return None
	passed, _, failures, _ = evaluate_school_tier_match(job, profile)
	if passed or not failures:
		return None
	evidence = "、".join(job_req.evidence[:2])
	return SchoolCompanyFitResult(
		fit_level="low",
		score_adjustment=-35,
		reasons=[],
		risks=[
			f"JD 明确要求「{job_req.label}」院校（{evidence}），"
			f"与用户「{user.label}」不匹配，简历关难以通过"
		],
		school_label=user.label,
		company=_company_name(job),
		source="jd_explicit",
		exclude=True,
	)


def assess_school_company_fit_heuristic(
	job: dict[str, Any],
	profile: UserProfile | None,
) -> SchoolCompanyFitResult:
	"""无 AI 时依据秘书/自填院校层级做保守提示。"""
	user = infer_user_school_tier(profile)
	ctx = _secretary_school_context(profile)
	company = _company_name(job)
	result = SchoolCompanyFitResult(
		school_label=user.label,
		company=company,
		source="heuristic",
	)
	if user.tier <= 0:
		result.fit_level = "unknown"
		return result

	if not company:
		result.fit_level = "unknown"
		return result

	school_name = ctx["school_name"]

	if user.tier <= 2:
		result.fit_level = "low"
		result.score_adjustment = -15
		result.risks.append(
			f"院校层级「{user.label}」"
			f"{('（' + school_name + '）') if school_name else ''}，"
			f"投递「{company}」时简历筛选可能偏严"
		)
	elif user.tier == 3:
		result.fit_level = "medium"
		result.score_adjustment = -6
		result.risks.append(
			f"院校层级「{user.label}」，部分头部企业可能有隐性院校偏好"
		)
	else:
		result.fit_level = "medium"
	return result


def assess_school_company_fit_with_ai(
	svc: AIService,
	job: dict[str, Any],
	profile: UserProfile | None,
) -> SchoolCompanyFitResult:
	ctx = _secretary_school_context(profile)
	user = infer_user_school_tier(profile)

	if not ctx["from_secretary"] and user.tier <= 0:
		return assess_school_company_fit_heuristic(job, profile)

	school_tier = ctx["school_tier"] or user.label
	school_tier_code = ctx["school_tier_code"] or user.tier

	prompt = COMPANY_SCHOOL_FRIENDLINESS_PROMPT.format(
		school_name=ctx["school_name"] or "（未填写）",
		education=ctx["education"] or "（未填写）",
		school_tier=school_tier or "未知",
		school_tier_code=school_tier_code,
		school_tier_reason=ctx["school_tier_reason"] or "（秘书未提供依据）",
		company=_company_name(job) or "（未知）",
		job_title=str(job.get("title") or job.get("jobName") or ""),
		job_scale=str(job.get("scale") or job.get("brandScaleName") or ""),
		job_stage=str(job.get("stage") or job.get("brandStageName") or ""),
		job_education=str(job.get("education") or job.get("jobDegree") or ""),
		job_description=str(job.get("description") or job.get("postDescription") or "")[:2000],
	)
	raw = svc.chat([
		{
			"role": "system",
			"content": (
				"你是分析 AI（FX）。院校层级已由秘书 AI 判定，你只评估公司/岗位对该层级的友好度；"
				"不要重新推断院校层次；只输出 JSON。"
			),
		},
		{"role": "user", "content": prompt},
	], agent="FX", temperature=0.2, max_tokens=700)
	data = _parse_ai_json(raw)

	fit_level = str(data.get("fit_level") or "unknown").lower()
	adj = int(data.get("score_adjustment") or 0)
	adj = max(-35, min(0, adj))
	exclude = bool(data.get("exclude"))

	reasons = [str(x).strip() for x in (data.get("reasons") or []) if str(x).strip()]
	risks = [str(x).strip() for x in (data.get("risks") or []) if str(x).strip()]

	return SchoolCompanyFitResult(
		fit_level=fit_level,
		score_adjustment=adj,
		reasons=reasons[:4],
		risks=risks[:4],
		school_label=school_tier or ctx["school_name"] or "未知",
		company=_company_name(job),
		source="ai",
		exclude=exclude,
	)


def assess_school_company_fit(
	job: dict[str, Any],
	profile: UserProfile | None,
	*,
	ai_service: AIService | None = None,
) -> SchoolCompanyFitResult:
	if ai_service is not None:
		try:
			return assess_school_company_fit_with_ai(ai_service, job, profile)
		except Exception:
			pass
	return assess_school_company_fit_heuristic(job, profile)


def apply_school_company_fit_to_score(
	score: int,
	fit: SchoolCompanyFitResult,
) -> int:
	return max(0, min(100, score + fit.score_adjustment))


def apply_school_company_fit_to_enriched(
	job: dict[str, Any],
	profile: UserProfile | None,
	enriched: dict[str, Any],
	*,
	ai_service: AIService | None = None,
) -> dict[str, Any]:
	"""将院校-公司匹配评估并入分析结果（降分 + 补充 reason/risk）。"""
	explicit = assess_explicit_jd_school_mismatch(job, profile)
	fit = explicit if explicit else assess_school_company_fit(job, profile, ai_service=ai_service)
	if fit.fit_level == "unknown" and not fit.risks and not fit.reasons and not fit.exclude:
		return enriched

	score = apply_school_company_fit_to_score(
		int(enriched.get("analysis_score") or 0),
		fit,
	)
	reasons = list(enriched.get("analysis_reason") or enriched.get("profile_reason") or [])
	risks = list(enriched.get("analysis_risk") or enriched.get("profile_risk") or [])
	reasons.extend(fit.reasons)
	risks.extend(fit.risks)

	if fit.reasons or fit.risks:
		from pet_boss.agents.analysis_scoring import sanitize_risk_lists

		reasons, risks = sanitize_risk_lists(
			reasons,
			risks,
			ai_service=ai_service,
			job=job,
			stage_label=str(enriched.get("career_stage_label") or ""),
		)

	out = {**enriched}
	out["analysis_score"] = score
	out["profile_score"] = score
	out["match_score"] = score
	out["analysis_reason"] = reasons
	out["analysis_risk"] = risks
	out["profile_reason"] = reasons
	out["profile_risk"] = risks
	out["match_reasons"] = reasons
	out["school_company_fit"] = {
		"fit_level": fit.fit_level,
		"score_adjustment": fit.score_adjustment,
		"school_label": fit.school_label,
		"company": fit.company,
		"source": fit.source,
		"exclude": fit.exclude,
	}
	if fit.exclude:
		out["school_company_excluded"] = True
	return out


def should_exclude_by_school_company_fit(enriched: dict[str, Any]) -> bool:
	fit = enriched.get("school_company_fit") or {}
	return bool(fit.get("exclude") or enriched.get("school_company_excluded"))
