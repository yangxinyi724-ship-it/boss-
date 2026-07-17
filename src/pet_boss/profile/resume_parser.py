"""Step 1: Resume Parsing — 简历深度解析。"""

from __future__ import annotations

import json
import re
from typing import Any

from pet_boss.ai.service import AIService
from pet_boss.profile.models import ParsedResume
from pet_boss.profile.prompts import RESUME_PARSE_PROMPT
from pet_boss.resume.models import ResumeData, resume_to_text


def _extract_tags(resume: ResumeData) -> list[str]:
	tags: list[str] = []
	for mod in resume.modules:
		for row in mod.rows:
			if row.get("type") == "tags":
				tags.extend(row.get("tags") or [])
	return tags


def _extract_city(resume: ResumeData) -> str:
	for item in resume.personal_info.items:
		label = item.label.lower()
		if "城市" in item.label or "city" in label or "所在地" in item.label:
			return item.value
	if resume.job_intention:
		for item in resume.job_intention.items:
			if "城市" in item.label or "地点" in item.label:
				return item.value
	return ""


def _guess_years(text: str) -> float | None:
	match = re.search(r"(\d+(?:\.\d+)?)\s*年", text)
	if match:
		return float(match.group(1))
	return None


def parse_resume_heuristic(resume: ResumeData, *, resume_name: str = "") -> ParsedResume:
	"""无 AI 时的规则解析兜底。"""
	text = resume_to_text(resume)
	tags = _extract_tags(resume)
	skills = list(dict.fromkeys(tags))
	tools = [t for t in skills if re.match(r"^[A-Za-z#.+0-9]+$", t)]
	years = _guess_years(text)
	education = ""
	for item in resume.personal_info.items:
		if "学历" in item.label or "教育" in item.label:
			education = item.value
			break
	return ParsedResume(
		skills=skills,
		tools=tools,
		years_of_experience=years,
		education=education,
		city=_extract_city(resume),
		summary=resume.title or resume.name,
		real_capabilities=skills[:5],
		source_resume=resume_name,
	)


def _parse_ai_json(raw: str) -> dict[str, Any]:
	text = raw.strip()
	if text.startswith("```"):
		lines = [ln for ln in text.split("\n") if not ln.startswith("```")]
		text = "\n".join(lines).strip()
	return json.loads(text)


def parse_resume_with_ai(
	svc: AIService,
	resume_text: str,
	*,
	resume_name: str = "",
) -> ParsedResume:
	raw = svc.chat([
		{"role": "system", "content": "你是 HR 与技术招聘专家。只输出 JSON。"},
		{"role": "user", "content": RESUME_PARSE_PROMPT.format(resume_text=resume_text)},
	], agent="MS")
	data = _parse_ai_json(raw)
	parsed = ParsedResume.from_dict(data)
	parsed.source_resume = resume_name
	return parsed


def parse_resume_text(
	text: str,
	*,
	resume_name: str = "",
	ai_service: AIService | None = None,
) -> ParsedResume:
	"""从纯文本（如 PDF 提取结果）解析简历。"""
	body = text.strip()
	if not body:
		return ParsedResume(
			summary="简历内容为空",
			source_resume=resume_name,
		)
	if ai_service is not None:
		try:
			return parse_resume_with_ai(ai_service, body, resume_name=resume_name)
		except Exception:
			pass
	# 规则兜底：从纯文本粗略提取
	years = _guess_years(body)
	return ParsedResume(
		skills=[],
		years_of_experience=years,
		summary=body[:200] + ("…" if len(body) > 200 else ""),
		real_capabilities=[],
		source_resume=resume_name,
	)


def parse_resume(
	resume: ResumeData,
	*,
	resume_name: str = "",
	ai_service: AIService | None = None,
) -> ParsedResume:
	text = resume_to_text(resume)
	if ai_service is not None:
		try:
			return parse_resume_with_ai(ai_service, text, resume_name=resume_name)
		except Exception:
			pass
	return parse_resume_heuristic(resume, resume_name=resume_name)
