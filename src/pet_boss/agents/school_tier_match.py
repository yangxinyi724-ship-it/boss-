"""院校层级匹配 — 侦察阶段仅依据用户自填层级与 JD 显性表述，不维护院校名录。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pet_boss.profile.models import UserProfile

# 岗位 JD 中的院校门槛信号：(最低用户 tier, 正则)
_JOB_TIER_PATTERNS: tuple[tuple[int, re.Pattern[str]], ...] = (
	(6, re.compile(
		r"985(?!\s*/\s*211)|"
		r"c9(?:联盟|院校)?|"
		r"清北复交|清华|北大(?!\s*青鸟)|"
		r"顶尖(?:高校|院校|学府)|"
		r"顶级(?:高校|院校|学府)|"
		r"仅(?:限)?985|"
		r"985(?:及以上|院校|高校|大学)(?!/211)",
		re.I,
	)),
	(5, re.compile(
		r"(?<![/\d])211(?!\d)|"
		r"双一流(?:建设)?(?:高校|大学|院校)?|"
		r"985\s*/\s*211|"
		r"211\s*/\s*985|"
		r"985/211|"
		r"211(?:及以上|院校|高校|大学)|"
		r"重点(?:院校|高校|学府|大学)|"
		r"名校(?:背景|优先|出身)?|"
		r"头部(?:院校|高校|学府)|"
		r"第一梯队(?:院校|高校)?|"
		r"院校(?:层次|背景)(?:要求)?(?:较高|优先)",
		re.I,
	)),
	(4, re.compile(
		r"(?<![二三])一本(?:院校|大学|高校|本科)?|"
		r"重点本科|"
		r"统招一本|"
		r"全日制一本",
		re.I,
	)),
	(3, re.compile(
		r"统招(?:全日制)?本科|"
		r"全日制(?:统招)?本科|"
		r"正规(?:全日制)?本科|"
		r"(?:非|不要|拒)(?:三本|专科|大专|民办)",
		re.I,
	)),
)

_USER_TIER_LABELS: dict[int, str] = {
	0: "未知",
	1: "专科",
	2: "三本/民办本科",
	3: "二本",
	4: "一本",
	5: "211/双一流",
	6: "985",
}

_TIER_FROM_LABEL: dict[str, int] = {
	"985": 6,
	"211": 5,
	"双一流": 5,
	"一本": 4,
	"二本": 3,
	"三本": 2,
	"民办": 2,
	"专科": 1,
	"大专": 1,
}


def _tier_from_label(label: str) -> int:
	text = (label or "").strip().lower()
	if not text:
		return 0
	for key, tier in _TIER_FROM_LABEL.items():
		if key in text:
			return tier
	return 0


@dataclass(frozen=True)
class SchoolTierInfo:
	tier: int
	label: str
	evidence: tuple[str, ...] = ()


def _profile_text_blob(profile: UserProfile | None) -> str:
	if not profile:
		return ""
	parts: list[str] = []
	if profile.parsed_resume:
		pr = profile.parsed_resume
		parts.extend([
			pr.education,
			pr.school_name,
			pr.school_tier,
			pr.summary,
			" ".join(pr.skills),
			" ".join(pr.industries),
		])
		for proj in pr.projects:
			if isinstance(proj, dict):
				parts.append(json.dumps(proj, ensure_ascii=False))
			else:
				parts.append(str(proj))
	if profile.preferences:
		parts.append(profile.preferences.role_preference)
		notes = profile.preferences.extra_notes
		if notes:
			parts.append(json.dumps(notes, ensure_ascii=False))
		for turn in profile.preferences.interview_transcript:
			parts.append(str(turn.get("content") or turn.get("answer") or ""))
	if profile.memory_summary:
		parts.append(profile.memory_summary)
	return " ".join(str(p) for p in parts if p)


def _job_text_blob(job: dict[str, Any]) -> str:
	welfare = " ".join(job.get("welfare") or job.get("welfareList") or [])
	parts = [
		job.get("title", ""),
		job.get("company", ""),
		job.get("brandName", ""),
		job.get("education", "") or job.get("jobDegree", ""),
		job.get("description", "") or job.get("postDescription", ""),
		job.get("jobLabels", ""),
		welfare,
	]
	return " ".join(str(p) for p in parts if p)


def infer_user_school_tier(profile: UserProfile | None) -> SchoolTierInfo:
	"""从用户自填字段与简历文本表述推断院校层级；仅凭校名不做名录匹配。

	具体院校层次（如某商学院是否为民办三本）由分析 AI 在 school_company_fit 中判断。
	"""
	if profile and profile.parsed_resume:
		pr = profile.parsed_resume
		if pr.school_tier_code and pr.school_tier_code > 0:
			evidence = [f"秘书 AI 判定院校层级：{pr.school_tier or _USER_TIER_LABELS.get(pr.school_tier_code, '')}"]
			if pr.school_tier_reason:
				evidence.append(pr.school_tier_reason)
			if pr.school_name:
				evidence.append(f"院校：{pr.school_name}")
			return SchoolTierInfo(
				pr.school_tier_code,
				pr.school_tier or _USER_TIER_LABELS.get(pr.school_tier_code, str(pr.school_tier_code)),
				tuple(evidence),
			)
		tier_from_field = _tier_from_label(pr.school_tier)
		if tier_from_field > 0:
			evidence = [f"简历标注院校层级：{pr.school_tier}"]
			if pr.school_name:
				evidence.append(f"院校：{pr.school_name}")
			return SchoolTierInfo(
				tier_from_field,
				pr.school_tier or _USER_TIER_LABELS[tier_from_field],
				tuple(evidence),
			)
		if pr.school_name:
			return SchoolTierInfo(
				0,
				"未知（待分析）",
				(f"毕业院校：{pr.school_name}（层次由分析 AI 判断）",),
			)

	blob = _profile_text_blob(profile)
	if not blob.strip():
		return SchoolTierInfo(0, _USER_TIER_LABELS[0])

	evidence: list[str] = []
	tier = 0

	if re.search(r"三本|民办(?:本科|院校|大学)|独立学院|二级学院", blob):
		return SchoolTierInfo(2, _USER_TIER_LABELS[2], ("简历含三本/民办本科表述",))
	if re.search(r"二本|普通(?:公办)?本科|二批(?:本科)?", blob):
		return SchoolTierInfo(3, _USER_TIER_LABELS[3], ("简历含二本/普通本科表述",))
	if re.search(r"(?<![二三])一本|重点本科|一批(?:本科)?", blob):
		tier = max(tier, 4)
		evidence.append("简历含一本表述")

	if re.search(r"\b985\b|985院校|985高校|985大学", blob):
		tier = max(tier, 6)
		evidence.append("简历标注 985")
	if re.search(r"\b211\b|211院校|211高校|双一流", blob):
		tier = max(tier, 5)
		evidence.append("简历标注 211/双一流")

	if tier > 0:
		return SchoolTierInfo(tier, _USER_TIER_LABELS[tier], tuple(evidence))

	if re.search(r"本科|学士|bachelor", blob, re.I):
		if re.search(r"专科|大专|高职|中专", blob):
			return SchoolTierInfo(1, _USER_TIER_LABELS[1], ("简历为专科层次",))
		return SchoolTierInfo(
			3,
			"本科（按二本预估）",
			("仅标注本科学历、未识别具体院校层级，按二本院校保守匹配",),
		)

	if re.search(r"专科|大专|高职", blob):
		return SchoolTierInfo(1, _USER_TIER_LABELS[1], ("简历为专科层次",))

	return SchoolTierInfo(0, _USER_TIER_LABELS[0])


def detect_job_school_requirement(job: dict[str, Any]) -> SchoolTierInfo | None:
	"""检测岗位 JD 是否**明确**写出 985/211/一本等院校要求。无显性要求则返回 None。

	隐性门槛由分析 AI 在 school_company_fit 中评估，不在侦察阶段硬筛。
	"""
	blob = _job_text_blob(job)
	if not blob.strip():
		return None

	req_tier = 0
	evidence: list[str] = []
	for min_tier, pattern in _JOB_TIER_PATTERNS:
		m = pattern.search(blob)
		if m:
			req_tier = max(req_tier, min_tier)
			evidence.append(m.group(0))

	if req_tier <= 0:
		return None

	return SchoolTierInfo(
		req_tier,
		_USER_TIER_LABELS.get(req_tier, str(req_tier)),
		tuple(evidence[:3]),
	)


def evaluate_school_tier_match(
	job: dict[str, Any],
	profile: UserProfile | None,
) -> tuple[bool, list[str], list[str], dict[str, bool]]:
	"""返回 (passed, reasons, failures, checks)。"""
	user = infer_user_school_tier(profile)
	job_req = detect_job_school_requirement(job)

	if job_req is None:
		return True, ["岗位未标注 985/211/一本等院校门槛"], [], {"school_tier": True}

	if user.tier <= 0:
		return True, ["用户院校层级未知，暂不按院校门槛否决"], [], {"school_tier": True}

	passed = user.tier >= job_req.tier
	checks = {"school_tier": passed}

	if passed:
		reasons = [
			f"院校层级匹配：用户「{user.label}」满足岗位「{job_req.label}」要求"
		]
		if user.evidence:
			reasons.append(f"依据：{user.evidence[0]}")
		return True, reasons, [], checks

	failures = [
		f"岗位倾向「{job_req.label}」院校（{', '.join(job_req.evidence[:2])}），"
		f"与用户「{user.label}」不匹配"
	]
	if user.evidence:
		failures.append(f"用户依据：{user.evidence[0]}")
	return False, [], failures, checks
