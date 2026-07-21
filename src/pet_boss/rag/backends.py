"""向量库后端抽象：sqlite（默认）/ chroma（可选）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pet_boss.rag.vector_store import VectorDocument, VectorStore


class VectorStoreBackend(Protocol):
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
	) -> None: ...

	def count(self) -> int: ...

	def list_documents(
		self,
		*,
		source_type: str | None = None,
		limit: int = 5000,
	) -> list[VectorDocument]: ...

	def delete_by_doc_keys(self, doc_keys: set[str]) -> int: ...

	def clear(self) -> int: ...

	def query_similar(
		self,
		query_embedding: list[float],
		*,
		top_k: int = 5,
		min_score: float = 0.0,
		limit_scan: int = 3000,
	) -> list[tuple[VectorDocument, float]]: ...

	@property
	def backend_name(self) -> str: ...


def resolve_vector_backend_name(config: dict[str, Any] | None = None) -> str:
	cfg = config or {}
	raw = str(cfg.get("ai_rag_vector_backend") or "sqlite").strip().lower()
	if raw in {"chroma", "chromadb"}:
		return "chroma"
	return "sqlite"


def open_vector_store(
	*,
	profile_store: Any,
	data_dir: Path | None = None,
	backend: str | None = None,
	config: dict[str, Any] | None = None,
) -> VectorStoreBackend:
	"""按配置打开向量后端；chroma 不可用时回退 sqlite。"""
	name = (backend or resolve_vector_backend_name(config)).lower()
	root = data_dir
	if root is None:
		# profile_store._dir = <data_dir>/profile
		root = Path(getattr(profile_store, "_dir")).parent

	if name == "chroma":
		try:
			from pet_boss.rag.chroma_store import ChromaVectorStore

			return ChromaVectorStore(root / "rag" / "chroma")
		except Exception:
			# 缺 chromadb 或初始化失败 → sqlite
			pass

	conn = getattr(profile_store, "_conn", None)
	if conn is None:
		raise RuntimeError("ProfileStore 无可用 SQLite 连接，无法打开 sqlite 向量库")
	return VectorStore(conn)
