"""从 PDF 导入本地简历。"""

from __future__ import annotations

import re
from pathlib import Path

from pet_boss.resume.models import PersonalInfoSection, ResumeData, ResumeModule
from pet_boss.resume.pdf_text import PdfTextExtractError, extract_text_from_pdf


def _guess_title(text: str) -> str:
	for line in text.splitlines()[:8]:
		line = line.strip()
		if not line or len(line) > 40:
			continue
		if any(k in line for k in ("工程师", "开发", "经理", "专员", "设计师", "分析师")):
			return line
	return "我的简历"


def resume_from_pdf_text(
	text: str,
	*,
	name: str,
	title: str = "",
) -> ResumeData:
	return ResumeData(
		name=name,
		title=title or _guess_title(text),
		personal_info=PersonalInfoSection(items=[], layout="inline"),
		modules=[
			ResumeModule(
				id="pdf_import",
				title="PDF 简历原文",
				rows=[{"type": "richtext", "columns": 1, "content": [text]}],
			),
		],
	)


def import_resume_from_pdf(
	path: Path,
	*,
	name: str,
	title: str = "",
) -> tuple[ResumeData, str]:
	"""从 PDF 路径导入简历，返回 (ResumeData, 提取的纯文本)。"""
	text = extract_text_from_pdf(path)
	text = re.sub(r"\n{3,}", "\n\n", text)
	resume = resume_from_pdf_text(text, name=name, title=title)
	return resume, text
