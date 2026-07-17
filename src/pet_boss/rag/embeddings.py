"""OpenAI 兼容 Embedding API。"""

from __future__ import annotations

from typing import Any, cast

import httpx

from pet_boss.ai.service import AIServiceError


def embed_texts(
	*,
	base_url: str,
	api_key: str,
	model: str,
	texts: list[str],
	timeout: float = 60.0,
) -> list[list[float]]:
	"""调用 /embeddings，返回与 texts 等长的向量列表。"""
	if not texts:
		return []
	url = f"{base_url.rstrip('/')}/embeddings"
	headers = {
		"Authorization": f"Bearer {api_key}",
		"Content-Type": "application/json",
	}
	payload: dict[str, Any] = {
		"model": model,
		"input": texts,
	}
	try:
		response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
		response.raise_for_status()
	except httpx.HTTPStatusError as exc:
		raise AIServiceError(
			f"Embedding API 请求失败: HTTP {exc.response.status_code}",
			status_code=exc.response.status_code,
		) from exc
	except httpx.RequestError as exc:
		raise AIServiceError(f"Embedding 网络请求失败: {exc}") from exc

	try:
		data = response.json()
		items = data["data"]
		items = sorted(items, key=lambda x: int(x.get("index", 0)))
		return [cast(list[float], item["embedding"]) for item in items]
	except (KeyError, IndexError, TypeError) as exc:
		raise AIServiceError(f"Embedding 响应格式异常: {exc}") from exc
