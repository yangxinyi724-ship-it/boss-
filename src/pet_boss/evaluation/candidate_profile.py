"""从 UserProfile / 秘书画像构建 CandidateProfile。"""

from __future__ import annotations

from typing import Any

from pet_boss.evaluation.models import CandidateProfile
from pet_boss.profile.models import UserProfile
from pet_boss.profile.store import ProfileStore


def build_candidate_profile(
	profile: UserProfile,
	*,
	store: ProfileStore | None = None,
) -> CandidateProfile:
	parsed = profile.parsed_resume
	career = profile.career
	prefs = profile.preferences
	extra = dict(prefs.extra_notes or {}) if prefs else {}

	portrait: dict[str, Any] = {}
	if store:
		raw = store.load_secretary_portrait() or {}
		portrait = raw.get("for_analysis") or raw

	career_goal = ""
	if career and career.primary_direction:
		career_goal = career.primary_direction
	if portrait.get("career_goal"):
		career_goal = str(portrait["career_goal"])
	if extra.get("career_goal"):
		career_goal = str(extra["career_goal"])

	learning = _star(extra.get("learning_priority"), default=3)
	salary = _star(extra.get("salary_priority"), default=3)
	mentor = _star(extra.get("mentor_needed"), default=3)
	if prefs and prefs.salary_vs_growth == "salary":
		salary = max(salary, 4)
	elif prefs and prefs.salary_vs_growth == "growth":
		learning = max(learning, 4)

	risk = "medium"
	if prefs and prefs.risk_tolerance:
		risk = prefs.risk_tolerance

	team_size = str(extra.get("preferred_team_size") or portrait.get("preferred_team_size") or "")
	company_types: list[str] = []
	for key in ("preferred_company_type", "preferred_company_types"):
		val = extra.get(key) or portrait.get(key)
		if isinstance(val, list):
			company_types.extend(str(v) for v in val)
		elif val:
			company_types.append(str(val))

	skills = list(parsed.skills if parsed else []) + list(parsed.tools if parsed else [])
	years = parsed.years_of_experience if parsed else None
	career_change = bool(prefs.career_change_ok) if prefs else False
	ai_interest = str(prefs.ai_app_vs_core or extra.get("ai_interest") or "")

	return CandidateProfile(
		career_goal=career_goal,
		learning_priority=learning,
		salary_priority=salary,
		mentor_needed=mentor,
		risk_preference=risk,
		preferred_team_size=team_size,
		preferred_company_types=company_types,
		skills=skills,
		years_of_experience=years,
		career_change_ok=career_change,
		ai_interest=ai_interest,
	)


def _star(value: Any, *, default: int = 3) -> int:
	try:
		n = int(value)
	except (TypeError, ValueError):
		return default
	return max(1, min(5, n))
