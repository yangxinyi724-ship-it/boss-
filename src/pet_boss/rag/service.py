"""RAG 索引与检索编排。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pet_boss.ai.config import (
	AIConfigStore,
	resolve_embedding_base_url,
	resolve_embedding_model,
	rag_enabled as config_rag_enabled,
)
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
	base_url = getattr(ai_service, "embedding_base_url", None) or ai_service.base_url
	api_key = getattr(ai_service, "embedding_api_key", None) or ai_service.api_key
	vectors = embed_texts(
		base_url=base_url,
		api_key=api_key,
		model=ai_service.embedding_model,
		texts=[text],
	)
	return vectors[0] if vectors else []


def _cache_for_backfill(
	profile_store: ProfileStore,
	cache: CacheStore | None,
) -> CacheStore | None:
	if cache is not None:
		return cache
	data_dir = getattr(profile_store, "_dir", None)
	if data_dir is None:
		return None
	# profile_store._dir = <data_dir>/profile
	db_path = Path(data_dir).parent / "cache" / "boss_agent.db"
	if not db_path.exists():
		return None
	try:
		return CacheStore(db_path)
	except Exception:
		return None


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
		# list_recent_analysis_records 把 payload 解析到 job 字段
		nested = rec.get("job") if isinstance(rec.get("job"), dict) else None
		job = dict(nested) if nested else {}
		job.setdefault("security_id", sid)
		job.setdefault("job_id", jid)
		job.setdefault("title", rec.get("title"))
		job.setdefault("company", rec.get("company"))
		job.setdefault("city", rec.get("city"))
		job.setdefault("salary", rec.get("salary"))
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
	hits, _meta = retrieve_similar_with_meta(
		profile_store,
		ai_service,
		job,
		top_k=top_k,
		min_score=min_score,
		search_query=search_query,
		search_city=search_city,
		exclude_security_id=exclude_security_id,
		exclude_job_id=exclude_job_id,
	)
	return hits


def retrieve_similar_with_meta(
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
) -> tuple[list[RagHit], dict[str, Any]]:
	"""检索相似历史，并返回可展示的准确原因元数据。"""
	meta: dict[str, Any] = {
		"enabled": bool(ai_service.rag_enabled),
		"min_score": min_score,
		"vector_count": 0,
		"hit_count": 0,
		"best_score": None,
		"code": "ok",
		"message": "",
	}
	if not ai_service.rag_enabled:
		meta["code"] = "rag_disabled"
		meta["message"] = "向量 RAG 未启用（当前对话平台无原生 Embedding，且未配置独立 Embedding 网关）。"
		return [], meta

	vs = _vector_store(profile_store)
	meta["vector_count"] = vs.count()
	query_text = job_query_text(job, search_query=search_query, search_city=search_city)
	try:
		query_vec = _embed_one(ai_service, query_text)
	except AIServiceError as exc:
		meta["code"] = "embed_failed"
		meta["message"] = f"Embedding 调用失败：{exc}"
		return [], meta
	if not query_vec:
		meta["code"] = "embed_failed"
		meta["message"] = "Embedding 返回空向量。"
		return [], meta

	docs = vs.list_documents(limit=3000)
	if not docs:
		meta["code"] = "empty_store"
		meta["message"] = "向量库为空，尚无成功入库的历史分析/拒绝案例。"
		return [], meta

	scored: list[tuple[float, RagHit]] = []
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
		scored.append((score, RagHit(
			doc_key=doc.doc_key,
			source_type=doc.source_type,
			score=score,
			text=doc.text,
			metadata=doc.metadata,
		)))
	if not scored:
		meta["code"] = "empty_store"
		meta["message"] = "向量库无可用向量（记录可能尚未完成 Embedding）。"
		return [], meta

	scored.sort(key=lambda x: x[0], reverse=True)
	meta["best_score"] = round(scored[0][0], 4)
	hits = [h for s, h in scored if s >= min_score][:top_k]
	meta["hit_count"] = len(hits)
	if hits:
		meta["code"] = "ok"
		meta["message"] = ""
		return hits, meta

	meta["code"] = "below_threshold"
	meta["message"] = (
		f"向量库有 {meta['vector_count']} 条案例，但与本岗最高相似度 "
		f"{meta['best_score']:.0%} 低于阈值 {min_score:.0%}，故未展示参考。"
	)
	return [], meta


def rag_miss_message_for_display(
	*,
	references: list[dict[str, Any]] | None,
	rag_meta: dict[str, Any] | None,
	current_vector_count: int | None = None,
) -> str:
	"""资料柜空参考时的准确说明文案。"""
	refs = references or []
	if refs:
		return ""
	meta = rag_meta if isinstance(rag_meta, dict) else {}
	code = str(meta.get("code") or "")
	msg = str(meta.get("message") or "").strip()
	if msg:
		return msg
	if code == "rag_disabled":
		return "分析时向量 RAG 未启用（对话平台无原生 Embedding，且未配置独立 Embedding 网关）。"
	if code == "embed_failed":
		return "分析时 Embedding 调用失败，未写入参考案例。"
	if code == "empty_store":
		return "分析时向量库为空，尚无成功入库的历史案例。"
	if code == "below_threshold":
		best = meta.get("best_score")
		thr = meta.get("min_score", 0.35)
		if best is not None:
			return (
				f"分析时向量库有案例，但最高相似度 {float(best):.0%} "
				f"低于阈值 {float(thr):.0%}。"
			)
		return "分析时相似度未达阈值，未写入参考案例。"
	# 历史空结果（当时未写 rag_meta）
	# 常见于：职业阶段评估路径曾未接入 RAG；或 Embedding 未通导致未检索。
	n = current_vector_count
	if n is None:
		n = meta.get("vector_count")
	if isinstance(n, int) and n > 0:
		return (
			"该岗位分析当时未保存 RAG 参考（职业阶段评估曾未接入向量检索，"
			"或当时 Embedding/入库异常）。"
			f"这与「分析记录多」不同：只有已 Embedding 的才算向量案例。"
			f"当前向量库有 {n} 条；重启后新分析会写入参考与准确原因。"
			"分析打分本身不受影响。"
		)
	return "本次分析未命中向量库中的相似历史案例；分析打分本身不受影响。"


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
	result = retrieve_analysis_rag_result(
		profile_store,
		ai_service,
		job,
		cache=cache,
		search_query=search_query,
		search_city=search_city,
		top_k=top_k,
	)
	return format_rag_context_from_references(result["references"])


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
	"""返回 references + meta（含准确未命中原因），供分析持久化与资料柜展示。"""
	if profile_store is None or ai_service is None:
		return {
			"references": [],
			"meta": {
				"enabled": False,
				"vector_count": 0,
				"hit_count": 0,
				"best_score": None,
				"min_score": 0.35,
				"code": "no_ai",
				"message": "分析时未配置 AI 服务，无法做向量检索。",
			},
		}
	if not ai_service.rag_enabled:
		return {
			"references": [],
			"meta": {
				"enabled": False,
				"vector_count": 0,
				"hit_count": 0,
				"best_score": None,
				"min_score": 0.35,
				"code": "rag_disabled",
				"message": "向量 RAG 未启用（当前对话平台无原生 Embedding，且未配置独立 Embedding 网关）。",
			},
		}

	owned_cache: CacheStore | None = None
	try:
		if _vector_store(profile_store).count() < 3:
			bf_cache = _cache_for_backfill(profile_store, cache)
			if bf_cache is not None and cache is None:
				owned_cache = bf_cache
			if bf_cache is not None:
				backfill_analysis_records(profile_store, bf_cache, ai_service, limit=60)
	except Exception:
		pass
	finally:
		if owned_cache is not None:
			try:
				owned_cache.close()
			except Exception:
				pass

	try:
		hits, meta = retrieve_similar_with_meta(
			profile_store,
			ai_service,
			job,
			top_k=top_k,
			search_query=search_query,
			search_city=search_city,
			exclude_security_id=str(job.get("security_id") or ""),
			exclude_job_id=str(job.get("job_id") or ""),
		)
	except Exception as exc:
		return {
			"references": [],
			"meta": {
				"enabled": True,
				"vector_count": _vector_store(profile_store).count(),
				"hit_count": 0,
				"best_score": None,
				"min_score": 0.35,
				"code": "retrieve_error",
				"message": f"向量检索异常：{exc}",
			},
		}
	return {
		"references": rag_hits_to_references(hits),
		"meta": meta,
	}


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
	"""兼容旧接口：仅返回参考案例列表。"""
	return retrieve_analysis_rag_result(
		profile_store,
		ai_service,
		job,
		cache=cache,
		search_query=search_query,
		search_city=search_city,
		top_k=top_k,
	)["references"]


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
		embedding_base_url=resolve_embedding_base_url(config),
		embedding_api_key=store.get_embedding_api_key(),
		rag_enabled=config_rag_enabled(config),
	)
