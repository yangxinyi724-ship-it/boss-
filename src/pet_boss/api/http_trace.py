"""BOSS HTTP 请求/响应终端追踪（排查用，由环境变量 BOSS_HTTP_TRACE 开启）。"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import urlencode

_TRACE_VALUES = frozenset({"1", "true", "yes", "on"})


def is_http_trace_enabled() -> bool:
	return os.environ.get("BOSS_HTTP_TRACE", "").strip().lower() in _TRACE_VALUES


def _max_body_chars() -> int:
	raw = os.environ.get("BOSS_HTTP_TRACE_MAX", "12000").strip()
	try:
		return max(500, int(raw))
	except ValueError:
		return 12000


def _dump(obj: Any) -> str:
	try:
		text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
	except TypeError:
		text = repr(obj)
	limit = _max_body_chars()
	if len(text) > limit:
		return f"{text[:limit]}\n... [truncated, total {len(text)} chars, set BOSS_HTTP_TRACE_MAX to raise]"
	return text


def _emit(title: str, body: str) -> None:
	sep = "=" * 72
	print(f"\n{sep}\n[BOSS HTTP TRACE] {title}\n{sep}\n{body}\n", file=sys.stderr, flush=True)


def log_outgoing_request(
	*,
	channel: str,
	method: str,
	url: str,
	params: dict[str, Any] | None = None,
	data: dict[str, Any] | None = None,
	headers: dict[str, Any] | None = None,
	cookies: dict[str, Any] | None = None,
	extra: dict[str, Any] | None = None,
) -> None:
	if not is_http_trace_enabled():
		return
	full_url = url
	if params:
		qs = urlencode({k: v for k, v in params.items() if v is not None})
		joiner = "&" if "?" in full_url else "?"
		full_url = f"{full_url}{joiner}{qs}" if qs else full_url
	payload = {
		"channel": channel,
		"method": method.upper(),
		"url": full_url,
		"params": params or {},
		"body": data or {},
		"headers": headers or {},
		"cookies": cookies or {},
	}
	if extra:
		payload["extra"] = extra
	_emit("REQUEST", _dump(payload))


def log_incoming_response(*, channel: str, label: str, body: Any) -> None:
	if not is_http_trace_enabled():
		return
	_emit(f"RESPONSE ({channel}) {label}", _dump(body))
