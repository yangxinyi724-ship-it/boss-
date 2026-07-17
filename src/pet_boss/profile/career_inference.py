"""Step 3: Career Direction Inference — 职业方向推理。"""

from __future__ import annotations

import json

from pet_boss.ai.service import AIService
from pet_boss.profile.models import CareerDirection, ParsedResume, UserPreferences
from pet_boss.profile.prompts import CAREER_INFERENCE_PROMPT


def infer_career_heuristic(
	parsed: ParsedResume,
	prefs: UserPreferences | None,
) -> CareerDirection:
	skills_text = " ".join(parsed.skills + parsed.tools).lower()
	primary = "后端开发"
	if any(k in skills_text for k in ("agent", "llm", "ai", "gpt")):
		primary = "AI应用开发"
	elif any(k in skills_text for k in ("go", "golang")):
		primary = "Go后端开发"
	elif any(k in skills_text for k in ("python", "django", "flask")):
		primary = "Python后端开发"

	avoid: list[str] = []
	if prefs and prefs.sales_role_ok is False:
		avoid.append("高销售性质岗位")
	if prefs and prefs.ai_app_vs_core == "application":
		avoid.append("纯算法研究")

	startup_fit = prefs.startup_fit if prefs and prefs.startup_fit is not None else True
	remote_fit = prefs.remote_ok if prefs and prefs.remote_ok is not None else False
	risk = prefs.risk_tolerance if prefs else "medium"

	return CareerDirection(
		primary_direction=primary,
		secondary_direction="AI工作流自动化" if "ai" in skills_text else "全栈开发",
		avoid_direction=avoid,
		risk_tolerance=risk,
		startup_fit=startup_fit,
		remote_fit=remote_fit,
		strengths=parsed.real_capabilities[:5] or parsed.skills[:5],
		gaps=["待补充领域经验"] if not parsed.years_of_experience else [],
		growth_paths=[primary, "技术负责人"],
		realistic_path=f"以{primary}为主，匹配当前经验与偏好",
		long_term_path="技术专家或架构师方向",
	)


def infer_career_with_ai(
	svc: AIService,
	parsed: ParsedResume,
	prefs: UserPreferences | None,
) -> CareerDirection:
	prompt = CAREER_INFERENCE_PROMPT.format(
		parsed_resume_json=json.dumps(parsed.to_dict(), ensure_ascii=False),
		preferences_json=json.dumps(prefs.to_dict() if prefs else {}, ensure_ascii=False),
	)
	raw = svc.chat([
		{"role": "system", "content": "你是职业规划师。只输出 JSON。"},
		{"role": "user", "content": prompt},
	], agent="MS")
	text = raw.strip()
	if text.startswith("```"):
		text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```")).strip()
	data = json.loads(text)
	return CareerDirection.from_dict(data)


def infer_career(
	parsed: ParsedResume,
	prefs: UserPreferences | None,
	*,
	ai_service: AIService | None = None,
) -> CareerDirection:
	if ai_service is not None:
		try:
			return infer_career_with_ai(ai_service, parsed, prefs)
		except Exception:
			pass
	return infer_career_heuristic(parsed, prefs)
