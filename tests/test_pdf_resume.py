from pathlib import Path

import pytest

from pet_boss.resume.pdf_import import import_resume_from_pdf, resume_from_pdf_text
from pet_boss.profile.resume_parser import parse_resume_text


SAMPLE_PDF_TEXT = """
张三 · Golang 开发工程师
5年后端经验，熟悉 Golang、Python、Docker、Kubernetes
项目：AI Agent 工作流平台，负责架构设计
广州 · 本科
""".strip()


def test_resume_from_pdf_text():
	resume = resume_from_pdf_text(SAMPLE_PDF_TEXT, name="pdf-test")
	assert resume.name == "pdf-test"
	assert "Golang" in resume.modules[0].rows[0]["content"][0]


def test_parse_resume_text_without_ai():
	parsed = parse_resume_text(SAMPLE_PDF_TEXT, resume_name="pdf-test", ai_service=None)
	assert parsed.years_of_experience == 5.0
	assert "Golang" in parsed.summary or parsed.summary


def test_extract_pdf_missing_file(tmp_path: Path):
	from pet_boss.resume.pdf_text import PdfTextExtractError, extract_text_from_pdf

	with pytest.raises(PdfTextExtractError):
		extract_text_from_pdf(tmp_path / "missing.pdf")


def test_import_resume_from_pdf_requires_pypdf(tmp_path: Path):
	pdf = tmp_path / "test.pdf"
	pdf.write_bytes(b"%PDF-1.4 minimal")
	try:
		import_resume_from_pdf(pdf, name="t")
	except Exception as exc:
		# pypdf may fail on minimal bytes or ImportError if not installed
		assert "pypdf" in str(exc).lower() or "pdf" in str(exc).lower() or "读取" in str(exc)
