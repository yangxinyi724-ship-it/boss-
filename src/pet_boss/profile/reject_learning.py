"""用户拒绝岗位时的偏好学习与变更记录。"""

from __future__ import annotations

import json
from typing import Any

from pet_boss.profile.learning import apply_feedback_learning
from pet_boss.profile.scout_learning import learn_from_analysis_outcome
from pet_boss.profile.store import ProfileStore
from pet_boss.secretary.feedback import parse_feedback_to_instructions, save_preference_instructions


def _compose_feedback_text(*, tags: list[str] | None, reason: str) -> str:
	parts: list[str] = []
	if tags:
		parts.append("拒绝原因：" + "、".join(tags))
	body = (reason or "").strip()
	if body:
		parts.append(body)
	return "\n".join(parts).strip()


def process_reject_with_learning(
	store: ProfileStore,
	job: dict[str, Any],
	*,
	tags: list[str] | None = None,
	reason: str = "",
	ai_service: Any = None,
) -> dict[str, Any]:
	"""根据用户拒绝理由更新偏好，并返回可写入 learning log 的变更摘要。"""
	feedback_text = _compose_feedback_text(tags=tags, reason=reason)
	title = str(job.get("title") or "")
	company = str(job.get("company") or "")

	learning = apply_feedback_learning(
		store,
		"rejected",
		title=title,
		company=company,
		user_reason=feedback_text or None,
	)
	preference_instructions_added: list[str] = []
	if feedback_text:
		old_data = store.load_preference_instructions() or {}
		old_set = set(old_data.get("instructions") or [])
		instructions = parse_feedback_to_instructions(feedback_text, ai_service=ai_service)
		if instructions:
			save_preference_instructions(
				store,
				instructions,
				raw_feedback=feedback_text,
			)
			new_data = store.load_preference_instructions() or {}
			preference_instructions_added = [
				str(x) for x in (new_data.get("instructions") or [])
				if str(x) not in old_set
			]

	analysis_job = {
		**job,
		"analysis_score": job.get("analysis_score"),
		"analysis_reason": job.get("analysis_reason") or [],
		"analysis_risk": job.get("analysis_risk") or [],
	}
	learn_from_analysis_outcome(store, analysis_job, passed=False)

	return {
		"learning_weights": learning.weights,
		"weight_changes": learning.weight_changes,
		"ai_memory_added": learning.ai_memory_added,
		"preference_instructions_added": preference_instructions_added,
		"feedback_text": feedback_text,
	}


def clear_reject_learning_memory(store: ProfileStore) -> dict[str, Any]:
	"""清空拒绝学习记录，并回滚相关权重、偏好指令与 AI 记忆。"""
	from pet_boss.cache.store import CacheStore

	logs = store.list_preference_learning_logs(limit=500)
	logs_removed = len(logs)
	if not logs:
		return {
			"logs_removed": 0,
			"memory_removed": 0,
			"weights_reverted": 0,
			"instructions_removed": 0,
			"message": "暂无拒绝与学习记录",
		}

	memory_removed = 0
	weights_reverted = 0
	instructions_to_remove: set[str] = set()
	seen_memory: set[tuple[str, str, str]] = set()
	seen_job_keys: set[str] = set()

	for log in reversed(logs):
		for chg in log.get("weight_changes") or []:
			dim = str(chg.get("dimension") or "")
			if not dim:
				continue
			before = chg.get("before")
			if before is None:
				continue
			store.set_dimension_weight(dim, float(before))
			weights_reverted += 1

		for mem in log.get("ai_memory_added") or []:
			agent = str(mem.get("agent") or "")
			category = str(mem.get("category") or "")
			content = str(mem.get("content") or "")
			key = (agent, category, content)
			if key in seen_memory:
				continue
			seen_memory.add(key)
			if store.delete_ai_memory(agent, category, content):
				memory_removed += 1

		for instr in log.get("preference_instructions") or []:
			text = str(instr).strip()
			if text:
				instructions_to_remove.add(text)

		job_key = CacheStore._make_watch_job_key(log)
		if job_key and job_key not in seen_job_keys:
			seen_job_keys.add(job_key)
			memory_removed += store.delete_ai_memory_by_job_key(job_key)

	instructions_removed = store.remove_preference_instructions(instructions_to_remove)
	store.clear_preference_learning_logs()

	return {
		"logs_removed": logs_removed,
		"memory_removed": memory_removed,
		"weights_reverted": weights_reverted,
		"instructions_removed": instructions_removed,
		"message": (
			f"已清空 {logs_removed} 条拒绝与学习记录，"
			f"回滚 {weights_reverted} 项权重调整，"
			f"移除 {memory_removed} 条 AI 记忆"
			+ (f"、{instructions_removed} 条偏好指令" if instructions_removed else "")
		),
	}
