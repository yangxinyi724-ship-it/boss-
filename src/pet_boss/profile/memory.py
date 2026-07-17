"""长期记忆 — 画像摘要 consolidation。"""

from __future__ import annotations

from pet_boss.ai.service import AIService
from pet_boss.profile.learning import feedback_summary_for_prompt
from pet_boss.profile.models import UserProfile
from pet_boss.profile.prompts import MEMORY_CONSOLIDATE_PROMPT
from pet_boss.profile.scout_learning import ai_memory_summary_for_prompt
from pet_boss.profile.store import ProfileStore


def build_memory_heuristic(profile: UserProfile, store: ProfileStore) -> str:
	parts: list[str] = []
	if profile.parsed_resume:
		parts.append(f"技能: {', '.join(profile.parsed_resume.skills[:8])}")
		if profile.parsed_resume.city:
			parts.append(f"目标城市: {profile.parsed_resume.city}")
	if profile.career:
		parts.append(f"主方向: {profile.career.primary_direction}")
		if profile.career.avoid_direction:
			parts.append(f"避开: {', '.join(profile.career.avoid_direction[:3])}")
	if profile.preferences:
		if profile.preferences.salary_vs_growth:
			parts.append(f"偏好: {profile.preferences.salary_vs_growth}")
		if profile.preferences.job_seeking_stage:
			parts.append(f"阶段: {profile.preferences.job_seeking_stage}")
	feedback = store.list_feedback(10)
	if feedback:
		parts.append(f"近期反馈 {len(feedback)} 条")
	ai_mem = ai_memory_summary_for_prompt(store, limit=8)
	if ai_mem:
		parts.append(ai_mem.replace("\n", " · "))
	return "；".join(parts) if parts else "用户画像已建立，待补充更多反馈。"


def consolidate_memory(
	profile: UserProfile,
	store: ProfileStore,
	*,
	ai_service: AIService | None = None,
) -> str:
	if ai_service is not None:
		try:
			prompt = MEMORY_CONSOLIDATE_PROMPT.format(
				profile_json=str(profile.to_dict()),
				feedback_summary=feedback_summary_for_prompt(store),
			)
			return ai_service.chat([
				{"role": "system", "content": "你是职业顾问。输出简洁中文摘要。"},
				{"role": "user", "content": prompt},
			], agent="MS").strip()
		except Exception:
			pass
	return build_memory_heuristic(profile, store)
