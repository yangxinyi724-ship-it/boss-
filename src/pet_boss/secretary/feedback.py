"""秘书 AI 反馈收集 — 整理为用户偏好指令传递给分析 AI。"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from pet_boss.ai.service import AIService
from pet_boss.profile.models import UserPreferences
from pet_boss.profile.store import ProfileStore


def _split_feedback_lines(text: str) -> list[str]:
	parts = re.split(r"[\n；;。]+", text)
	return [p.strip() for p in parts if p.strip()]


def parse_feedback_to_instructions(
	text: str,
	*,
	ai_service: AIService | None = None,
) -> list[str]:
	body = text.strip()
	if not body:
		return []
	if ai_service is None:
		return _split_feedback_lines(body)
	prompt = f"""你是秘书 AI。将用户求职反馈整理为简洁的「用户偏好指令」列表（每条一句，可直接给分析 AI 执行）。
只输出 JSON 数组，例如：["不接受单休", "优先远程", "薪资期望25K以上"]

用户反馈：
{body}
"""
	try:
		raw = ai_service.chat([
			{"role": "system", "content": "只输出 JSON 数组。"},
			{"role": "user", "content": prompt},
		], temperature=0.3, max_tokens=512, agent="MS")
		clean = raw.strip()
		if clean.startswith("```"):
			clean = "\n".join(ln for ln in clean.split("\n") if not ln.startswith("```"))
		data = json.loads(clean)
		if isinstance(data, list):
			return [str(x).strip() for x in data if str(x).strip()]
	except Exception:
		pass
	return _split_feedback_lines(body)


def save_preference_instructions(
	store: ProfileStore,
	instructions: list[str],
	*,
	raw_feedback: str = "",
) -> dict[str, Any]:
	payload = {
		"updated_at": time.time(),
		"raw_feedback": raw_feedback,
		"instructions": instructions,
		"source": "secretary",
	}
	store.save_preference_instructions(payload)

	prefs = store.load_preferences() or UserPreferences()
	notes = dict(prefs.extra_notes or {})
	existing = list(notes.get("secretary_instructions") or [])
	merged = list(dict.fromkeys([*instructions, *existing]))[:50]
	notes["secretary_instructions"] = merged
	prefs.extra_notes = notes
	store.save_preferences(prefs)
	return payload


def load_preference_instructions_text(store: ProfileStore) -> str:
	data = store.load_preference_instructions()
	if not data:
		notes = (store.load_preferences() or UserPreferences()).extra_notes or {}
		instr = notes.get("secretary_instructions") or []
		if not instr:
			return "（暂无用户偏好指令）"
		return "\n".join(f"- {x}" for x in instr)
	instr = data.get("instructions") or []
	if not instr:
		return "（暂无用户偏好指令）"
	return "\n".join(f"- {x}" for x in instr)
