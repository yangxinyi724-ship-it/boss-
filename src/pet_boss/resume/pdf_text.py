"""从 PDF 简历提取纯文本。"""

from __future__ import annotations

from pathlib import Path


class PdfTextExtractError(Exception):
	"""PDF 文本提取失败。"""


def extract_text_from_pdf(path: Path) -> str:
	"""从 PDF 文件提取文本（适用于可选中文字的数字版 PDF）。"""
	try:
		from pypdf import PdfReader
	except ImportError as exc:
		raise ImportError(
			"PDF 解析需要安装依赖：pip install pypdf  或  pip install 'boss-agent-cli[web]'"
		) from exc

	if not path.exists():
		raise PdfTextExtractError(f"文件不存在: {path}")
	if path.suffix.lower() != ".pdf":
		raise PdfTextExtractError("仅支持 .pdf 文件")

	try:
		reader = PdfReader(str(path))
	except Exception as exc:
		raise PdfTextExtractError(f"无法读取 PDF: {exc}") from exc

	if reader.is_encrypted:
		try:
			reader.decrypt("")
		except Exception as exc:
			raise PdfTextExtractError("PDF 已加密，请先解密后再上传") from exc

	parts: list[str] = []
	for i, page in enumerate(reader.pages):
		try:
			text = page.extract_text() or ""
		except Exception as exc:
			raise PdfTextExtractError(f"第 {i + 1} 页提取失败: {exc}") from exc
		cleaned = text.strip()
		if cleaned:
			parts.append(cleaned)

	result = "\n\n".join(parts).strip()
	if not result:
		raise PdfTextExtractError(
			"未能从 PDF 提取到文字。若为扫描件/图片简历，请先 OCR 或粘贴文字版简历"
		)
	return result
