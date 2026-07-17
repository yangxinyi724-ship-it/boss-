"""RAG 索引与检索编排。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pet_boss.ai.config import AIConfigStore, resolve_embedding_model, rag_enabled as config_rag_enabled
from pet_boss.ai.service import AIService, AIServiceError
from pet_boss.cache.store import CacheStore
from pet_boss.profile.store import ProfileStore
from pet_boss.rag.documents import (
	analysis_doc_key,
	job_document_text,
	job_query_text,
	reject_doc_key,
	reject_learning_document_text,
)
from pet_boss.rag.embeddings import embed_texts
from pet_boss.rag.vector_store import VectorStore, cosine_similarity


@dataclass(frozen=True)
class RagHit:
	doc_key: str
	source_type: str
	score: float
	text: str
	metadata: dict[str, Any]


def _vector_store(store: ProfileStore) -> VectorStore:
	return VectorStore(store._conn)


def _embed_one(ai_service: AIService, text: str) -> list[float]:
	vectors = embed_texts(
		base_url=ai_service.base_url,
		api_key=ai_service.api_key,
		model=ai_service.embedding_model,
		texts=[text],
	)
	return vectors[0] if vectors else []


def index_analysis_job(
	profile_store: ProfileStore,
	ai_service: AIService,
	job: dict[str, Any],
	*,
	status: str,
	search_query: str = "",
	search_city: str = "",
) -> bool:
	"""将分析结果写入向量库；失败时静默返回 False。"""
	if not ai_service.rag_enabled:
		return False
	sid = str(job.get("security_id") or "")
	jid = str(job.get("job_id") or "")
	if not sid or not jid:
		return False
	text = job_document_text(
		job,
		status=status,
		search_query=search_query,
		search_city=search_city,
	)
	try:
		embedding = _embed_one(ai_service, text)
	except AIServiceError:
		return False
	if not embedding:
		return False
	meta = {
		"status": status,
		"title": str(job.get("title") or ""),
		"company": str(job.get("company") or ""),
		"analysis_score": int(job.get("analysis_score") or 0),
		"security_id": sid,
		"job_id": jid,
	}
	_vector_store(profile_store).upsert(
		doc_key=analysis_doc_key(sid, jid),
		source_type="analysis",
		source_id=f"{sid}:{jid}",
		text=text,
		metadata=meta,
		embedding=embedding,
		model=ai_service.embedding_model,
	)
	return True


def index_reject_learning(
	profile_store: ProfileStore,
	ai_service: AIService,
	entry: dict[str, Any],
	*,
	log_id: int,
) -> bool:
	if not ai_service.rag_enabled:
		return False
	text = reject_learning_document_text(entry)
	try:
		embedding = _embed_one(ai_service, text)
	except AIServiceError:
		return False
	if not embedding:
		return False
	meta = {
		"status": "user_rejected",
		"title": str(entry.get("title") or ""),
		"company": str(entry.get("company") or ""),
		"analysis_score": entry.get("analysis_score"),
		"log_id": log_id,
	}
	_vector_store(profile_store).upsert(
		doc_key=reject_doc_key(log_id),
		source_type="reject",
		source_id=str(log_id),
		text=text,
		metadata=meta,
		embedding=embedding,
		model=ai_service.embedding_model,
	)
	return True


def backfill_analysis_records(
	profile_store: ProfileStore,
	cache: CacheStore,
	ai_service: AIService,
	*,
	limit: int = 80,
) -> int:
	"""补建尚未入向量库的分析记录。"""
	if not ai_service.rag_enabled:
		return 0
	vs = _vector_store(profile_store)
	existing = {doc.doc_key for doc in vs.list_documents(limit=10000)}
	records = cache.list_recent_analysis_records(limit=limit)
	indexed = 0
	for rec in records:
		sid = str(rec.get("security_id") or "")
		jid = str(rec.get("job_id") or "")
		key = analysis_doc_key(sid, jid)
		if key in existing:
			continue
		payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else rec
		job = dict(payload) if isinstance(payload, dict) else dict(rec)
		job.setdefault("security_id", sid)
		job.setdefault("job_id", jid)
		job.setdefault("title", rec.get("title"))
		job.setdefault("company", rec.get("company"))
		job.setdefault("analysis_score", rec.get("analysis_score"))
		if index_analysis_job(
			profile_store,
			ai_service,
			job,
			status=str(rec.get("status") or ""),
			search_query=str(rec.get("search_query") or ""),
			search_city=str(rec.get("search_city") or ""),
		):
			indexed += 1
	return indexed


def retrieve_similar(
	profile_store: ProfileStore,
	ai_service: AIService,
	job: dict[str, Any],
	*,
	top_k: int = 5,
	min_score: float = 0.35,
	search_query: str = "",
	search_city: str = "",
	exclude_security_id: str = "",
	exclude_job_id: str = "",
) -> list[RagHit]:
	if not ai_service.rag_enabled:
		return []
	query_text = job_query_text(job, search_query=search_query, search_city=search_city)
	try:
		query_vec = _embed_one(ai_service, query_text)
	except AIServiceError:
		return []
	if not query_vec:
		return []

	vs = _vector_store(profile_store)
	docs = vs.list_documents(limit=3000)
	if not docs:
		return []

	hits: list[RagHit] = []
	for doc in docs:
		if not doc.embedding:
			continue
		if (
			exclude_security_id
			and exclude_job_id
			and doc.metadata.get("security_id") == exclude_security_id
			and doc.metadata.get("job_id") == exclude_job_id
		):
			continue
		score = cosine_similarity(query_vec, doc.embedding)
		if score < min_score:
			continue
		hits.append(RagHit(
			doc_key=doc.doc_key,
			source_type=doc.source_type,
			score=score,
			text=doc.text,
			metadata=doc.metadata,
		))
	hits.sort(key=lambda h: h.score, reverse=True)
	return hits[:top_k]


def rag_hits_to_references(hits: list[RagHit]) -> list[dict[str, Any]]:
	refs: list[dict[str, Any]] = []
	for hit in hits:
		meta = hit.metadata
		status = str(meta.get("status") or hit.source_type)
		summary = hit.text.replace("\n", " · ")
		refs.append({
			"source_type": hit.source_type,
			"status": status,
			"title": str(meta.get("title") or ""),
			"company": str(meta.get("company") or ""),
			"similarity": round(hit.score, 4),
			"analysis_score": meta.get("analysis_score"),
			"summary": summary[:360],
			"doc_key": hit.doc_key,
		})
	return refs


def format_rag_context(hits: list[RagHit]) -> str:
	if not hits:
		return ""
	lines = [
		"向量 RAG：与当前岗位语义相似的历史案例（供参考，勿机械照搬分数）：",
	]
	for i, hit in enumerate(hits, 1):
		meta = hit.metadata
		status = meta.get("status") or hit.source_type
		title = meta.get("title") or "岗位"
		company = meta.get("company") or ""
		score_part = f"  历史分 {meta['analysis_score']}" if meta.get("analysis_score") is not None else ""
		lines.append(
			f"{i}. [{status}] {title} @ {company}（相似度 {hit.score:.2f}{score_part}）"
		)
		summary = hit.text.replace("\n", " · ")
		lines.append(f"   {summary[:320]}")
	return "\n".join(lines)


def format_rag_context_from_references(refs: list[dict[str, Any]]) -> str:
	if not refs:
		return ""
	lines = [
		"向量 RAG：与当前岗位语义相似的历史案例（供参考，勿机械照搬分数）：",
	]
	for i, ref in enumerate(refs, 1):
		status = ref.get("status") or ref.get("source_type") or "历史"
		title = ref.get("title") or "岗位"
		company = ref.get("company") or ""
		sim = float(ref.get("similarity") or 0)
		score_part = f"  历史分 {ref['analysis_score']}" if ref.get("analysis_score") is not None else ""
		lines.append(f"{i}. [{status}] {title} @ {company}（相似度 {sim:.2f}{score_part}）")
		summary = str(ref.get("summary") or "")
		if summary:
			lines.append(f"   {summary[:320]}")
	return "\n".join(lines)


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
	"""分析前检索相似历史，返回可拼入 Prompt 的文本；失败时返回空串。"""
	if profile_store is None or ai_service is None or not ai_service.rag_enabled:
		return ""
	try:
		if cache is not None and _vector_store(profile_store).count() < 3:
			backfill_analysis_records(profile_store, cache, ai_service, limit=60)
	except Exception:
		pass
	try:
		hits = retrieve_similar(
			profile_store,
			ai_service,
			job,
			top_k=top_k,
			search_query=search_query,
			search_city=search_city,
			exclude_security_id=str(job.get("security_id") or ""),
			exclude_job_id=str(job.get("job_id") or ""),
		)
	except Exception:
		return ""
	return format_rag_context_from_references(rag_hits_to_references(hits))


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
	"""返回结构化 RAG 参考案例，供分析结果持久化与资料柜展示。"""
	if profile_store is None or ai_service is None or not ai_service.rag_enabled:
		return []
	try:
		if cache is not None and _vector_store(profile_store).count() < 3:
			backfill_analysis_records(profile_store, cache, ai_service, limit=60)
	except Exception:
		pass
	try:
		hits = retrieve_similar(
			profile_store,
			ai_service,
			job,
			top_k=top_k,
			search_query=search_query,
			search_city=search_city,
			exclude_security_id=str(job.get("security_id") or ""),
			exclude_job_id=str(job.get("job_id") or ""),
		)
	except Exception:
		return []
	return rag_hits_to_references(hits)


def build_ai_service_with_embeddings(data_dir) -> AIService | None:
	"""从本地配置创建带 embedding 模型的 AIService。"""
	from pet_boss.ai.token_usage import get_token_usage_store

	store = AIConfigStore(data_dir)
	if not store.is_configured():
		return None
	config = store.load_config()
	api_key = store.get_api_key()
	base_url = store.get_base_url()
	if not api_key or not base_url:
		return None
	return AIService(
		base_url=base_url,
		api_key=api_key,
		model=config["ai_model"],
		temperature=config.get("ai_temperature", 0.7),
		max_tokens=config.get("ai_max_tokens", 4096),
		usage_store=get_token_usage_store(data_dir),
		embedding_model=resolve_embedding_model(config),
		rag_enabled=config_rag_enabled(config),
	)
