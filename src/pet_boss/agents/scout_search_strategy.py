"""侦察 AI 搜索词策略 — 基于秘书画像生成关键词组合。"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from pet_boss.ai.service import AIService
from pet_boss.profile.models import ParsedResume, UserPreferences, UserProfile
from pet_boss.profile.store import ProfileStore
from pet_boss.secretary.portrait import build_secretary_portrait, portrait_for_scout

# BOSS 等平台：毕业 2 年内仍可走「应届」岗；「校招」指未毕业在校招聘
RECENT_GRADUATE_MAX_YEARS = 2.0

_CAMPUS_QUERY_PATTERN = re.compile(r"校招|实习")
_RECENT_GRAD_QUERY_PATTERN = re.compile(r"应届生|程序员助理|\d{2}届")


def _dedupe_queries(queries: list[str]) -> list[str]:
	seen: set[str] = set()
	out: list[str] = []
	for q in queries:
		key = q.strip()
		if not key or key in seen:
			continue
		seen.add(key)
		out.append(key)
	return out


def _graduation_cohort(offset: int = 0) -> str:
	"""当前年份对应的届别，如 2025 → 25届。"""
	y = date.today().year + offset
	return f"{y % 100}届"


def _profile_text_blob(portrait: dict[str, Any], parsed: ParsedResume | None) -> str:
	scout = portrait_for_scout(portrait) if portrait.get("for_scout") else portrait
	parts = [
		str(scout.get(k) or "")
		for k in ("expected_role", "education", "summary", "school_name")
	]
	if parsed:
		parts.extend([
			parsed.education or "",
			parsed.summary or "",
			parsed.school_name or "",
		])
		for proj in parsed.projects[:3]:
			if isinstance(proj, dict):
				parts.append(str(proj.get("name") or ""))
				parts.extend(str(x) for x in (proj.get("highlights") or [])[:2])
	return " ".join(parts)


def _years_of_work(portrait: dict[str, Any], parsed: ParsedResume | None) -> float | None:
	scout = portrait_for_scout(portrait) if portrait.get("for_scout") else portrait
	years = scout.get("years_of_experience")
	if parsed and years is None:
		years = parsed.years_of_experience
	if years is None:
		return None
	try:
		return float(years)
	except (TypeError, ValueError):
		return None


def _is_campus_recruit_candidate(portrait: dict[str, Any], parsed: ParsedResume | None) -> bool:
	"""校招：未毕业、仍在校（找实习/校招渠道）。"""
	blob = _profile_text_blob(portrait, parsed)
	if re.search(r"已毕业|往届|社招", blob):
		return False
	years = _years_of_work(portrait, parsed)
	if years is not None and years >= 1:
		return False
	if re.search(
		r"在校生|在读(?!后)|未毕业|尚未毕业|"
		r"大学在读|学院在读|"
		r"(?:大[一二三四]|研[一二三]|博[一二三四])(?:在读|学生)?",
		blob,
	):
		return True
	if re.search(r"(?<![本硕博])校招", blob):
		return True
	if re.search(r"找实习|寻求实习|实习岗位", blob) and not re.search(r"已毕业", blob):
		return True
	return False


def _is_recent_graduate(portrait: dict[str, Any], parsed: ParsedResume | None) -> bool:
	"""应届：已毕业、毕业 2 年内（走应届岗，不用校招/实习词）。"""
	if _is_campus_recruit_candidate(portrait, parsed):
		return False
	blob = _profile_text_blob(portrait, parsed)
	years = _years_of_work(portrait, parsed)
	if re.search(r"往届|社招", blob):
		return False
	if years is not None and years >= RECENT_GRADUATE_MAX_YEARS:
		return False
	if re.search(r"应届", blob):
		return True
	if years is not None and years < RECENT_GRADUATE_MAX_YEARS:
		return True
	if re.search(r"已毕业", blob) and (years is None or years < RECENT_GRADUATE_MAX_YEARS):
		return True
	return False


def _filter_queries_by_audience(
	queries: list[str],
	*,
	campus: bool,
	recent_grad: bool,
) -> list[str]:
	out: list[str] = []
	for q in queries:
		if not campus and _CAMPUS_QUERY_PATTERN.search(q):
			continue
		if not recent_grad and not campus and _RECENT_GRAD_QUERY_PATTERN.search(q):
			continue
		out.append(q)
	return out


def _primary_skills(portrait: dict[str, Any], parsed: ParsedResume | None) -> list[str]:
	skills = list(portrait.get("skills") or [])
	if parsed and parsed.skills:
		for s in parsed.skills:
			if s not in skills:
				skills.append(s)
	if parsed and parsed.tools:
		for t in parsed.tools:
			if t not in skills:
				skills.append(t)
	return skills[:6]


def _heuristic_search_queries(
	portrait: dict[str, Any],
	parsed: ParsedResume | None,
	*,
	max_queries: int = 16,
) -> list[str]:
	"""规则生成搜索词（无 AI 兜底）。"""
	queries: list[str] = []
	scout = portrait_for_scout(portrait) if portrait.get("for_scout") else portrait
	skills = _primary_skills(scout, parsed)
	expected = str(scout.get("expected_role") or "").strip()
	campus = _is_campus_recruit_candidate(portrait, parsed)
	recent_grad = _is_recent_graduate(portrait, parsed)

	for skill in skills[:3]:
		s = skill.strip()
		if not s:
			continue
		if re.match(r"^[A-Za-z#.+0-9]+$", s):
			queries.extend([f"{s}开发", f"{s}工程师", f"{s}后端"])
		else:
			queries.append(s)

	if expected:
		queries.append(expected)
		if "开发" not in expected and "工程师" not in expected:
			queries.append(f"{expected}开发")

	role_blob = expected + " ".join(skills)
	if re.search(r"java", role_blob, re.I):
		queries.extend(["Java开发", "后端开发", "Java后端", "Java工程师"])
	if re.search(r"python", role_blob, re.I):
		queries.extend(["Python开发", "Python后端"])
	if re.search(r"go|golang", role_blob, re.I):
		queries.extend(["Go开发", "Golang开发"])
	if re.search(r"前端|frontend", role_blob, re.I):
		queries.extend(["前端开发", "Web前端"])

	if campus:
		cohort = _graduation_cohort()
		next_cohort = _graduation_cohort(1)
		queries.extend(["实习", "校招", "程序员助理", cohort, next_cohort])
		for skill in skills[:2]:
			s = skill.strip()
			if re.match(r"^[A-Za-z#.+0-9]+$", s):
				queries.append(f"{s}校招")
				queries.append(f"{s}实习")
		if re.search(r"java", role_blob, re.I):
			queries.extend(["Java校招", "Java实习"])

	elif recent_grad:
		cohort = _graduation_cohort()
		next_cohort = _graduation_cohort(1)
		queries.extend(["应届生", cohort, next_cohort])
		for skill in skills[:2]:
			s = skill.strip()
			if re.match(r"^[A-Za-z#.+0-9]+$", s):
				queries.append(f"{s}应届生")
		if re.search(r"java", role_blob, re.I):
			queries.extend(["Java应届生"])

	if not queries and expected:
		queries.append(expected)
	if not queries:
		queries.append("软件开发")

	return _filter_queries_by_audience(
		_dedupe_queries(queries),
		campus=campus,
		recent_grad=recent_grad,
	)[:max_queries]


def _ai_search_queries(
	svc: AIService,
	portrait: dict[str, Any],
	*,
	max_queries: int = 16,
) -> list[str]:
	prompt = f"""你是秘书 AI，请根据用户画像为 BOSS 直聘生成 {max_queries} 个以内、互不重复的中文搜索关键词。
要求：
- 覆盖主技能、岗位方向等变体
- **校招/实习**：仅「未毕业、仍在校」时使用（如 在校生、大四在读）
- **应届/XX届**：仅「已毕业、毕业 2 年内」时使用；与校招不同，**禁止**给已毕业者生成校招/实习词
- **社招**：毕业超过 2 年或有多年工作经验者，用 Java开发、后端工程师 等，禁止校招/实习/应届生
- 只输出 JSON 数组，如 ["Java开发", "后端开发"]

用户画像：
{json.dumps(portrait_for_scout(portrait), ensure_ascii=False)}
"""
	raw = svc.chat([
		{"role": "system", "content": "只输出 JSON 字符串数组。"},
		{"role": "user", "content": prompt},
	], temperature=0.4, max_tokens=512, agent="ZC")
	text = raw.strip()
	if text.startswith("```"):
		text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```")).strip()
	data = json.loads(text)
	if isinstance(data, list):
		return _dedupe_queries([str(x).strip() for x in data if str(x).strip()])[:max_queries]
	return []


def generate_search_queries_from_portrait(
	portrait: dict[str, Any] | None,
	parsed: ParsedResume | None = None,
	*,
	max_queries: int = 12,
	ai_service: AIService | None = None,
) -> list[str]:
	if not portrait and parsed:
		portrait = build_secretary_portrait(parsed)
	if not portrait:
		return []
	campus = _is_campus_recruit_candidate(portrait, parsed)
	recent_grad = _is_recent_graduate(portrait, parsed)
	heuristic = _heuristic_search_queries(portrait, parsed, max_queries=max_queries)
	if ai_service:
		try:
			ai_queries = _ai_search_queries(ai_service, portrait, max_queries=max_queries)
			if ai_queries:
				merged = _dedupe_queries([*ai_queries, *heuristic])[:max_queries]
				return _filter_queries_by_audience(
					merged, campus=campus, recent_grad=recent_grad,
				)
		except Exception:
			pass
	return heuristic


def resolve_scout_search_plan(
	profile: UserProfile,
	store: ProfileStore | None = None,
	*,
	user_query: str = "",
	auto_keywords: bool = True,
	keywords_only: bool = False,
	max_queries: int = 12,
	ai_service: AIService | None = None,
) -> dict[str, Any]:
	"""合并用户搜索词与秘书画像自动生成的关键词。"""
	user_query = user_query.strip()
	portrait = store.load_secretary_portrait() if store else None
	parsed = profile.parsed_resume

	auto: list[str] = []
	if auto_keywords and (portrait or parsed):
		auto = generate_search_queries_from_portrait(
			portrait, parsed,
			max_queries=max_queries,
			ai_service=ai_service,
		)

	if keywords_only:
		queries = auto
		source = "secretary_auto"
	elif user_query and auto_keywords:
		queries = _dedupe_queries([user_query, *auto])
		source = "user_and_secretary"
	elif user_query:
		queries = [user_query]
		source = "user"
	elif auto:
		queries = auto
		source = "secretary_auto"
	else:
		queries = []
		source = "none"

	return {
		"queries": queries[:max_queries],
		"source": source,
		"user_query": user_query,
		"auto_keywords": auto_keywords,
		"auto_generated": auto,
	}


def criteria_with_query(base: Any, query: str) -> Any:
	"""基于原 SearchFilterCriteria 替换 query 字段。"""
	from pet_boss.search_filters import SearchFilterCriteria

	if isinstance(base, SearchFilterCriteria):
		return SearchFilterCriteria(
			query=query,
			city=base.city,
			city_code=base.city_code,
			district_code=base.district_code,
			salary=base.salary,
			experience=base.experience,
			education=base.education,
			industry=base.industry,
			scale=base.scale,
			stage=base.stage,
			job_type=base.job_type,
			raw_params=dict(base.raw_params),
		)
	return base
