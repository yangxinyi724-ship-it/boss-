"""Chroma 向量后端（可选依赖 chromadb）。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pet_boss.rag.vector_store import VectorDocument


class ChromaVectorStore:
	"""持久化 Chroma collection，接口对齐 VectorStore。"""

	backend_name = "chroma"

	def __init__(self, persist_dir: Path, *, collection_name: str = "boss_rag") -> None:
		try:
			import chromadb
			from chromadb.config import Settings
		except ImportError as exc:
			raise ImportError(
				"Chroma 后端需要：pip install 'boss-agent-cli[rag]' 或 pip install chromadb"
			) from exc

		self._dir = persist_dir
		self._dir.mkdir(parents=True, exist_ok=True)
		self._client = chromadb.PersistentClient(
			path=str(self._dir),
			settings=Settings(anonymized_telemetry=False),
		)
		self._col = self._client.get_or_create_collection(
			name=collection_name,
			metadata={"hnsw:space": "cosine"},
		)

	def upsert(
		self,
		*,
		doc_key: str,
		source_type: str,
		source_id: str,
		text: str,
		metadata: dict[str, Any],
		embedding: list[float],
		model: str,
	) -> None:
		now = time.time()
		meta = {
			"source_type": source_type,
			"source_id": source_id or "",
			"model": model or "",
			"created_at": now,
			"updated_at": now,
			"metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
		}
		# Chroma metadata 值需为标量；复杂字段放 metadata_json
		self._col.upsert(
			ids=[doc_key],
			embeddings=[embedding],
			documents=[text],
			metadatas=[meta],
		)

	def count(self) -> int:
		return int(self._col.count())

	def list_documents(
		self,
		*,
		source_type: str | None = None,
		limit: int = 5000,
	) -> list[VectorDocument]:
		kwargs: dict[str, Any] = {"include": ["documents", "metadatas", "embeddings"]}
		if source_type:
			kwargs["where"] = {"source_type": source_type}
		# chroma get 无绝对 limit 语义时用 peek / get
		n = min(limit, max(self.count(), 1))
		raw = self._col.get(limit=n, **{k: v for k, v in kwargs.items() if k != "include"}, include=kwargs["include"])
		return self._rows_to_docs(raw)

	def delete_by_doc_keys(self, doc_keys: set[str]) -> int:
		if not doc_keys:
			return 0
		keys = list(doc_keys)
		self._col.delete(ids=keys)
		return len(keys)

	def clear(self) -> int:
		n = self.count()
		if n <= 0:
			return 0
		# 删集合重建
		name = self._col.name
		self._client.delete_collection(name)
		self._col = self._client.get_or_create_collection(
			name=name,
			metadata={"hnsw:space": "cosine"},
		)
		return n

	def query_similar(
		self,
		query_embedding: list[float],
		*,
		top_k: int = 5,
		min_score: float = 0.0,
		limit_scan: int = 3000,
	) -> list[tuple[VectorDocument, float]]:
		del limit_scan  # chroma 用 ANN，不需全表扫描
		if self.count() <= 0:
			return []
		raw = self._col.query(
			query_embeddings=[query_embedding],
			n_results=min(top_k * 3, max(top_k, 1)),
			include=["documents", "metadatas", "embeddings", "distances"],
		)
		docs = self._rows_to_docs_from_query(raw)
		# chroma cosine distance → similarity ≈ 1 - distance（取决于实现）
		out: list[tuple[VectorDocument, float]] = []
		distances = (raw.get("distances") or [[]])[0]
		for doc, dist in zip(docs, distances):
			try:
				score = 1.0 - float(dist)
			except (TypeError, ValueError):
				score = 0.0
			if score >= min_score:
				out.append((doc, score))
		out.sort(key=lambda x: x[1], reverse=True)
		return out[:top_k]

	@staticmethod
	def _parse_meta(raw_meta: dict[str, Any] | None) -> tuple[dict[str, Any], str, str, str, float, float]:
		meta = raw_meta or {}
		try:
			inner = json.loads(str(meta.get("metadata_json") or "{}"))
		except json.JSONDecodeError:
			inner = {}
		if not isinstance(inner, dict):
			inner = {}
		return (
			inner,
			str(meta.get("source_type") or ""),
			str(meta.get("source_id") or ""),
			str(meta.get("model") or ""),
			float(meta.get("created_at") or 0),
			float(meta.get("updated_at") or 0),
		)

	def _rows_to_docs(self, raw: dict[str, Any]) -> list[VectorDocument]:
		ids = raw.get("ids") or []
		docs = raw.get("documents") or []
		metas = raw.get("metadatas") or []
		embs = raw.get("embeddings") or []
		out: list[VectorDocument] = []
		for i, doc_key in enumerate(ids):
			inner, source_type, source_id, model, created, updated = self._parse_meta(
				metas[i] if i < len(metas) else None
			)
			emb = embs[i] if i < len(embs) and embs[i] is not None else []
			out.append(
				VectorDocument(
					doc_key=str(doc_key),
					source_type=source_type,
					source_id=source_id,
					text=str(docs[i] if i < len(docs) else ""),
					metadata=inner,
					embedding=[float(x) for x in emb] if emb else [],
					model=model,
					created_at=created,
					updated_at=updated,
				)
			)
		return out

	def _rows_to_docs_from_query(self, raw: dict[str, Any]) -> list[VectorDocument]:
		# query 结果多层 list
		flat = {
			"ids": (raw.get("ids") or [[]])[0],
			"documents": (raw.get("documents") or [[]])[0],
			"metadatas": (raw.get("metadatas") or [[]])[0],
			"embeddings": (raw.get("embeddings") or [[]])[0] if raw.get("embeddings") else [],
		}
		return self._rows_to_docs(flat)
