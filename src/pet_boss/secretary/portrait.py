"""秘书 AI 结构化画像 — 传递给侦察 AI 与分析 AI。"""

from __future__ import annotations

import json
from typing import Any

from pet_boss.ai.service import AIService
from pet_boss.profile.models import ParsedResume, UserPreferences
from pet_boss.profile.prompts import (
	SECRETARY_PROFILE_ENRICH_PROMPT,
	SECRETARY_SCHOOL_TIER_PROMPT,
)


def _infer_expected_role(parsed: ParsedResume) -> str:
	if parsed.summary:
		for kw in ("开发", "工程师", "产品", "运营", "设计", "测试", "算法", "前端", "后端"):
			if kw in parsed.summary:
				return parsed.summary[:24]
	if parsed.skills:
		return f"{parsed.skills[0]}相关岗位"
	return ""


def _parse_ai_json(raw: str) -> dict[str, Any]:
	text = raw.strip()
	if text.startswith("```"):
		text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```")).strip()
	return json.loads(text)


def _basics_from_parsed(parsed: ParsedResume) -> dict[str, Any]:
	return {
		"gender": parsed.gender or "未知",
		"age": parsed.age,
		"education": parsed.education,
		"years_of_experience": parsed.years_of_experience,
		"school_name": parsed.school_name,
		"school_tier": parsed.school_tier,
		"school_tier_code": parsed.school_tier_code,
		"school_tier_reason": parsed.school_tier_reason,
	}


def build_secretary_portrait(
	parsed: ParsedResume,
	*,
	expected_role: str = "",
	preferences: UserPreferences | None = None,
) -> dict[str, Any]:
	"""将简历解析结果转为秘书 JSON 画像，供侦察/分析 AI 消费。"""
	role = expected_role or _infer_expected_role(parsed)
	strengths = list(parsed.real_capabilities or parsed.skills[:5])
	basics = _basics_from_parsed(parsed)
	portrait = {
		"portrait_version": 2,
		"source": "secretary",
		"skills": list(parsed.skills),
		"years_of_experience": parsed.years_of_experience,
		"expected_role": role,
		"education": parsed.education,
		"core_strengths": strengths,
		"city": parsed.city,
		"tools": list(parsed.tools),
		"summary": parsed.summary,
		"basics": basics,
		"parsed_resume": parsed.to_dict(),
	}
	if preferences:
		portrait["preferences_hint"] = {
			"role_preference": preferences.role_preference,
			"salary_vs_growth": preferences.salary_vs_growth,
			"overtime_tolerance": preferences.overtime_tolerance,
			"remote_ok": preferences.remote_ok,
		}
	portrait["for_scout"] = {
		**basics,
		"skills": portrait["skills"],
		"expected_role": portrait["expected_role"],
		"city": portrait["city"],
	}
	portrait["for_analysis"] = {
		"basics": basics,
		"core_strengths": portrait["core_strengths"],
		"expected_role": portrait["expected_role"],
		"parsed_resume": portrait["parsed_resume"],
		"preferences_hint": portrait.get("preferences_hint"),
	}
	return portrait


def portrait_for_scout(portrait: dict[str, Any]) -> dict[str, Any]:
	return portrait.get("for_scout") or portrait


def portrait_for_analysis(portrait: dict[str, Any]) -> dict[str, Any]:
	return portrait.get("for_analysis") or portrait


def apply_secretary_enrichment(parsed: ParsedResume, extra: dict[str, Any]) -> None:
	"""合并秘书 enrich 结果到 ParsedResume。"""
	parsed.skills = list(dict.fromkeys([*(extra.get("skills") or []), *parsed.skills]))
	if extra.get("years_of_experience") is not None:
		parsed.years_of_experience = extra["years_of_experience"]
	if extra.get("education"):
		parsed.education = str(extra["education"])
	if extra.get("school_name"):
		parsed.school_name = str(extra["school_name"])
	if extra.get("gender"):
		parsed.gender = str(extra["gender"])
	if extra.get("age") is not None:
		try:
			parsed.age = int(extra["age"])
		except (TypeError, ValueError):
			pass
	if extra.get("core_strengths"):
		parsed.real_capabilities = list(extra["core_strengths"])
	if extra.get("summary"):
		parsed.summary = str(extra["summary"])


def apply_secretary_school_tier(parsed: ParsedResume, data: dict[str, Any]) -> None:
	"""写入秘书 AI 判定的院校层级。"""
	if data.get("school_name"):
		parsed.school_name = str(data["school_name"])
	if data.get("education"):
		parsed.education = str(data["education"])
	if data.get("school_tier"):
		parsed.school_tier = str(data["school_tier"])
	try:
		parsed.school_tier_code = int(data.get("school_tier_code") or 0)
	except (TypeError, ValueError):
		parsed.school_tier_code = 0
	if data.get("school_tier_reason"):
		parsed.school_tier_reason = str(data["school_tier_reason"])


def enrich_parsed_for_secretary(
	svc: AIService,
	resume_text: str,
) -> dict[str, Any]:
	"""AI 提取秘书职责所需的简历关键字段（含基础人口统计）。"""
	prompt = SECRETARY_PROFILE_ENRICH_PROMPT.format(resume_text=resume_text[:12000])
	raw = svc.chat([
		{"role": "system", "content": "只输出 JSON，不要 markdown。"},
		{"role": "user", "content": prompt},
	], temperature=0.2, max_tokens=1024, agent="MS")
	return _parse_ai_json(raw)


def infer_school_tier_with_secretary_ai(
	svc: AIService,
	resume_text: str,
	parsed: ParsedResume | None = None,
) -> dict[str, Any]:
	"""秘书 AI 分析毕业院校层次，写入求职画像。"""
	school_name = ""
	education = ""
	if parsed:
		school_name = parsed.school_name or ""
		education = parsed.education or ""
	prompt = SECRETARY_SCHOOL_TIER_PROMPT.format(
		resume_text=resume_text[:12000],
		school_name=school_name or "（未识别）",
		education=education or "（未识别）",
	)
	raw = svc.chat([
		{
			"role": "system",
			"content": (
				"你是秘书 AI（MS），熟悉中国高等教育体系。"
				"根据院校名称自行判断层次，不使用预设院校名单；只输出 JSON。"
			),
		},
		{"role": "user", "content": prompt},
	], temperature=0.2, max_tokens=600, agent="MS")
	return _parse_ai_json(raw)
