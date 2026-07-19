"""AI service client for OpenAI-compatible APIs.

Provides a simple interface for chat completions with error handling.
"""

from typing import Any, cast

import httpx

from pet_boss.ai.token_usage import TokenUsageStore


class AIServiceError(Exception):
	"""Raised when an AI service call fails."""

	def __init__(self, message: str, *, status_code: int | None = None):
		super().__init__(message)
		self.status_code = status_code


class AIService:
	"""Client for OpenAI-compatible chat completion APIs."""

	def __init__(
		self,
		base_url: str,
		api_key: str,
		model: str,
		temperature: float = 0.7,
		max_tokens: int = 4096,
		*,
		embedding_model: str = "text-embedding-3-small",
		embedding_base_url: str | None = None,
		embedding_api_key: str | None = None,
		rag_enabled: bool = True,
		usage_store: TokenUsageStore | None = None,
	):
		# Normalize base_url: strip trailing slash
		self.base_url = base_url.rstrip("/")
		self.api_key = api_key
		self.model = model
		self.embedding_model = embedding_model
		self.embedding_base_url = (
			embedding_base_url.rstrip("/") if embedding_base_url else None
		)
		self.embedding_api_key = embedding_api_key or None
		self.rag_enabled = rag_enabled
		self.temperature = temperature
		self.max_tokens = max_tokens
		self.usage_store = usage_store

	def chat(
		self,
		messages: list[dict[str, Any]],
		*,
		temperature: float | None = None,
		max_tokens: int | None = None,
		agent: str = "other",
		purpose: str = "",
	) -> str:
		"""Send a chat completion request and return the assistant's reply text.

		Args:
			messages: List of message dicts with 'role' and 'content' keys.
			temperature: Override default temperature for this call.
			max_tokens: Override default max_tokens for this call.

		Returns:
			The assistant's reply text.

		Raises:
			AIServiceError: On HTTP errors, network errors, or unexpected response format.
		"""
		url = f"{self.base_url}/chat/completions"
		headers = {
			"Authorization": f"Bearer {self.api_key}",
			"Content-Type": "application/json",
		}
		payload = {
			"model": self.model,
			"messages": messages,
			"temperature": temperature if temperature is not None else self.temperature,
			"max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
		}

		try:
			response = httpx.post(url, json=payload, headers=headers, timeout=60)
			response.raise_for_status()
		except httpx.HTTPStatusError as exc:
			raise AIServiceError(
				f"API 请求失败: HTTP {exc.response.status_code}",
				status_code=exc.response.status_code,
			) from exc
		except httpx.RequestError as exc:
			raise AIServiceError(f"网络请求失败: {exc}") from exc

		try:
			data = response.json()
			content = cast("str", data["choices"][0]["message"]["content"])
			self._record_usage(data, agent=agent)
			return content
		except (KeyError, IndexError, TypeError) as exc:
			raise AIServiceError(f"响应格式异常: {exc}") from exc

	def _record_usage(self, data: dict[str, Any], *, agent: str) -> None:
		if self.usage_store is None:
			return
		usage = data.get("usage")
		if not isinstance(usage, dict):
			return
		prompt = int(usage.get("prompt_tokens") or 0)
		completion = int(usage.get("completion_tokens") or 0)
		total = int(usage.get("total_tokens") or prompt + completion)
		if total <= 0 and prompt <= 0 and completion <= 0:
			return
		cache_hit = int(usage.get("prompt_cache_hit_tokens") or 0)
		cache_miss = int(usage.get("prompt_cache_miss_tokens") or 0)
		details = usage.get("prompt_tokens_details")
		if isinstance(details, dict):
			cache_hit = cache_hit or int(details.get("cached_tokens") or 0)
		if cache_hit and not cache_miss and prompt > cache_hit:
			cache_miss = prompt - cache_hit
		self.usage_store.record(
			agent=agent,
			prompt_tokens=prompt,
			completion_tokens=completion,
			total_tokens=total,
			prompt_cache_hit_tokens=cache_hit,
			prompt_cache_miss_tokens=cache_miss,
			model=self.model,
		)
