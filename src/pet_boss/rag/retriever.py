"""分析 AI 向量 RAG 检索入口。"""

from __future__ import annotations

from typing import Any

from pet_boss.ai.service import AIService
from pet_boss.cache.store import CacheStore
from pet_boss.profile.store import ProfileStore
from pet_boss.rag.service import (
	retrieve_analysis_rag_context as _retrieve_context,
	retrieve_analysis_rag_hits as _retrieve_hits,
	retrieve_analysis_rag_result as _retrieve_result,
)


def retrieve_analysis_rag_context(
	profile_store: ProfileStore | None,
	ai_service: AIService | None,
	job: dict[str, Any],
	*,
	cache: CacheStore | None = None,
	search_query: str = "",
	search_city: str = "",
	top_k: int = 5,
) -> str:
	return _retrieve_context(
		profile_store,
		ai_service,
		job,
		cache=cache,
		search_query=search_query,
		search_city=search_city,
		top_k=top_k,
	)


def retrieve_analysis_rag_hits(
	profile_store: ProfileStore | None,
	ai_service: AIService | None,
	job: dict[str, Any],
	*,
	cache: CacheStore | None = None,
	search_query: str = "",
	search_city: str = "",
	top_k: int = 5,
) -> list[dict[str, Any]]:
	return _retrieve_hits(
		profile_store,
		ai_service,
		job,
		cache=cache,
		search_query=search_query,
		search_city=search_city,
		top_k=top_k,
	)


def retrieve_analysis_rag_result(
	profile_store: ProfileStore | None,
	ai_service: AIService | None,
	job: dict[str, Any],
	*,
	cache: CacheStore | None = None,
	search_query: str = "",
	search_city: str = "",
	top_k: int = 5,
) -> dict[str, Any]:
	return _retrieve_result(
		profile_store,
		ai_service,
		job,
		cache=cache,
		search_query=search_query,
		search_city=search_city,
		top_k=top_k,
	)
