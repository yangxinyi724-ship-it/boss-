"""Planner 公共工具。"""

from __future__ import annotations

import json
import re
from typing import Any


def parse_llm_json_object(raw: str) -> dict[str, Any]:
	text = raw.strip()
	if text.startswith("```"):
		text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```")).strip()
	# 容错：截取第一个 { ... }
	if not text.startswith("{"):
		match = re.search(r"\{[\s\S]*\}", text)
		if match:
			text = match.group(0)
	data = json.loads(text)
	if not isinstance(data, dict):
		raise ValueError("Planner 输出须为 JSON 对象")
	return data


def clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
	try:
		num = int(value)
	except (TypeError, ValueError):
		return default
	return max(lo, min(hi, num))
