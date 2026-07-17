"""秘书 AI 简历接收 — PDF / 文字 / 图片。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pet_boss.ai.service import AIService
from pet_boss.profile.models import ParsedResume
from pet_boss.profile.resume_parser import parse_resume_text
from pet_boss.resume.pdf_text import PdfTextExtractError, extract_text_from_pdf
from pet_boss.secretary.portrait import (
	apply_secretary_enrichment,
	apply_secretary_school_tier,
	build_secretary_portrait,
	enrich_parsed_for_secretary,
	infer_school_tier_with_secretary_ai,
)

ResumeSource = Literal["pdf", "text", "image"]


class SecretaryIntakeError(Exception):
	pass


def intake_resume_text(
	text: str,
	*,
	resume_name: str = "secretary-intake",
	ai_service: AIService | None = None,
) -> tuple[ParsedResume, dict[str, Any]]:
	body = text.strip()
	if not body:
		raise SecretaryIntakeError("简历文字为空")
	parsed = parse_resume_text(body, resume_name=resume_name, ai_service=ai_service)
	expected_role = ""
	if ai_service:
		try:
			extra = enrich_parsed_for_secretary(ai_service, body)
			apply_secretary_enrichment(parsed, extra)
			expected_role = str(extra.get("expected_role") or "")
		except Exception:
			pass
		try:
			school = infer_school_tier_with_secretary_ai(ai_service, body, parsed)
			apply_secretary_school_tier(parsed, school)
		except Exception:
			pass
	portrait = build_secretary_portrait(parsed, expected_role=expected_role)
	return parsed, portrait


def intake_resume_pdf(
	path: Path,
	*,
	resume_name: str = "",
	ai_service: AIService | None = None,
) -> tuple[ParsedResume, dict[str, Any]]:
	try:
		text = extract_text_from_pdf(path)
	except PdfTextExtractError as exc:
		raise SecretaryIntakeError(str(exc)) from exc
	if not text.strip():
		raise SecretaryIntakeError("PDF 未提取到文字，请使用可选中文字的 PDF 或改用 --text")
	name = resume_name or path.stem
	return intake_resume_text(text, resume_name=name, ai_service=ai_service)


def intake_resume_image(
	path: Path,
	*,
	ai_service: AIService | None = None,
) -> tuple[ParsedResume, dict[str, Any]]:
	"""图片简历：当前需用户 OCR 后走 --text；此处给出明确指引。"""
	suffix = path.suffix.lower()
	if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
		raise SecretaryIntakeError(f"不支持的图片格式: {suffix}")
	raise SecretaryIntakeError(
		"图片简历请先 OCR 为文字后使用 boss agent secretary parse-resume --text，"
		"或转换为 PDF 后使用 --pdf"
	)
