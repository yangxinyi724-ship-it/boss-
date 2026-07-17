"""RAG 文档构建 — 将岗位/拒绝记录转为可索引文本。"""

from __future__ import annotations

import json
from typing import Any


def _clip(text: str, limit: int = 600) -> str:
	s = " ".join(str(text or "").split())
	return s[:limit] + ("…" if len(s) > limit else "")


def _join_items(items: Any, limit: int = 4) -> str:
	if not items:
		return ""
	if isinstance(items, str):
		return _clip(items, 240)
	parts = [str(x).strip() for x in items if str(x).strip()]
	return "；".join(parts[:limit])


def job_document_text(
	job: dict[str, Any],
	*,
	status: str = "",
	search_query: str = "",
	search_city: str = "",
) -> str:
	title = str(job.get("title") or "")
	company = str(job.get("company") or "")
	city = str(job.get("city") or search_city or "")
	salary = str(job.get("salary") or "")
	score = job.get("analysis_score")
	reason = _join_items(job.get("analysis_reason") or job.get("profile_reason"))
	risk = _join_items(job.get("analysis_risk") or job.get("profile_risk"))
	desc = _clip(job.get("description") or job.get("postDescription") or "", 500)
	skills = _join_items(job.get("skills") or [], limit=8)
	lines = [
		f"岗位：{title} @ {company}",
		f"城市：{city}  薪资：{salary}",
	]
	if status:
		lines.append(f"评估结果：{status}" + (f"  分数：{score}" if score is not None else ""))
	if search_query:
		lines.append(f"搜索词：{search_query}")
	if skills:
		lines.append(f"技能标签：{skills}")
	if desc:
		lines.append(f"JD摘要：{desc}")
	if reason:
		lines.append(f"分析亮点：{reason}")
	if risk:
		lines.append(f"分析风险：{risk}")
	return "\n".join(lines)


def job_query_text(job: dict[str, Any], *, search_query: str = "", search_city: str = "") -> str:
	return job_document_text(job, search_query=search_query, search_city=search_city)


def analysis_doc_key(security_id: str, job_id: str) -> str:
	return f"analysis:{security_id}:{job_id}"


def reject_doc_key(log_id: int | str) -> str:
	return f"reject:{log_id}"


def reject_learning_document_text(entry: dict[str, Any]) -> str:
	title = str(entry.get("title") or "")
	company = str(entry.get("company") or "")
	tags = entry.get("user_tags") or []
	if isinstance(tags, str):
		try:
			tags = json.loads(tags)
		except json.JSONDecodeError:
			tags = [tags]
	tag_text = "、".join(str(t).strip() for t in tags if str(t).strip())
	reason = str(entry.get("user_reason") or "").strip()
	score = entry.get("analysis_score")
	analysis_reason = _join_items(entry.get("analysis_reason"))
	analysis_risk = _join_items(entry.get("analysis_risk"))
	lines = [
		f"用户拒绝岗位：{title} @ {company}",
	]
	if tag_text:
		lines.append(f"拒绝标签：{tag_text}")
	if reason:
		lines.append(f"用户补充：{reason}")
	if score is not None:
		lines.append(f"当时分析分数：{score}")
	if analysis_reason:
		lines.append(f"当时分析亮点：{analysis_reason}")
	if analysis_risk:
		lines.append(f"当时分析风险：{analysis_risk}")
	return "\n".join(lines)
