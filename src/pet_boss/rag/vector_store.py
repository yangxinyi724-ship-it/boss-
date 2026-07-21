"""SQLite 向量存储（embedding 以 JSON 数组持久化）。"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VectorDocument:
	doc_key: str
	source_type: str
	source_id: str
	text: str
	metadata: dict[str, Any]
	embedding: list[float]
	model: str
	created_at: float
	updated_at: float


class VectorStore:
	def __init__(self, conn: sqlite3.Connection) -> None:
		self._conn = conn
		self._init_tables()

	def _init_tables(self) -> None:
		self._conn.executescript("""
			CREATE TABLE IF NOT EXISTS rag_vectors (
				doc_key TEXT PRIMARY KEY,
				source_type TEXT NOT NULL,
				source_id TEXT NOT NULL DEFAULT '',
				text TEXT NOT NULL,
				metadata TEXT NOT NULL DEFAULT '{}',
				embedding TEXT NOT NULL,
				model TEXT NOT NULL,
				created_at REAL NOT NULL,
				updated_at REAL NOT NULL
			);
			CREATE INDEX IF NOT EXISTS idx_rag_vectors_source
				ON rag_vectors(source_type, updated_at DESC);
		""")
		self._conn.commit()

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
		row = self._conn.execute(
			"SELECT created_at FROM rag_vectors WHERE doc_key = ?",
			(doc_key,),
		).fetchone()
		created_at = float(row[0]) if row else now
		self._conn.execute(
			"""INSERT INTO rag_vectors
			(doc_key, source_type, source_id, text, metadata, embedding, model, created_at, updated_at)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
			ON CONFLICT(doc_key) DO UPDATE SET
				source_type=excluded.source_type,
				source_id=excluded.source_id,
				text=excluded.text,
				metadata=excluded.metadata,
				embedding=excluded.embedding,
				model=excluded.model,
				updated_at=excluded.updated_at""",
			(
				doc_key,
				source_type,
				source_id,
				text,
				json.dumps(metadata, ensure_ascii=False),
				json.dumps(embedding),
				model,
				created_at,
				now,
			),
		)
		self._conn.commit()

	def count(self) -> int:
		row = self._conn.execute("SELECT COUNT(*) FROM rag_vectors").fetchone()
		return int(row[0]) if row else 0

	def list_documents(
		self,
		*,
		source_type: str | None = None,
		limit: int = 5000,
	) -> list[VectorDocument]:
		if source_type:
			rows = self._conn.execute(
				"""SELECT doc_key, source_type, source_id, text, metadata, embedding, model, created_at, updated_at
				FROM rag_vectors WHERE source_type = ?
				ORDER BY updated_at DESC LIMIT ?""",
				(source_type, limit),
			).fetchall()
		else:
			rows = self._conn.execute(
				"""SELECT doc_key, source_type, source_id, text, metadata, embedding, model, created_at, updated_at
				FROM rag_vectors ORDER BY updated_at DESC LIMIT ?""",
				(limit,),
			).fetchall()
		return [self._row_to_doc(row) for row in rows]

	def delete_by_doc_keys(self, doc_keys: set[str]) -> int:
		if not doc_keys:
			return 0
		placeholders = ",".join("?" for _ in doc_keys)
		cursor = self._conn.execute(
			f"DELETE FROM rag_vectors WHERE doc_key IN ({placeholders})",
			tuple(doc_keys),
		)
		self._conn.commit()
		return cursor.rowcount

	def clear(self) -> int:
		cursor = self._conn.execute("DELETE FROM rag_vectors")
		self._conn.commit()
		return cursor.rowcount

	@property
	def backend_name(self) -> str:
		return "sqlite"

	def query_similar(
		self,
		query_embedding: list[float],
		*,
		top_k: int = 5,
		min_score: float = 0.0,
		limit_scan: int = 3000,
	) -> list[tuple[VectorDocument, float]]:
		docs = self.list_documents(limit=limit_scan)
		scored: list[tuple[VectorDocument, float]] = []
		for doc in docs:
			if not doc.embedding:
				continue
			score = cosine_similarity(query_embedding, doc.embedding)
			if score >= min_score:
				scored.append((doc, score))
		scored.sort(key=lambda x: x[1], reverse=True)
		return scored[:top_k]

	@staticmethod
	def _row_to_doc(row: tuple[Any, ...]) -> VectorDocument:
		meta_raw = row[4]
		try:
			metadata = json.loads(meta_raw) if meta_raw else {}
		except json.JSONDecodeError:
			metadata = {}
		try:
			embedding = json.loads(row[5])
		except json.JSONDecodeError:
			embedding = []
		return VectorDocument(
			doc_key=str(row[0]),
			source_type=str(row[1]),
			source_id=str(row[2]),
			text=str(row[3]),
			metadata=metadata if isinstance(metadata, dict) else {},
			embedding=[float(x) for x in embedding] if isinstance(embedding, list) else [],
			model=str(row[6]),
			created_at=float(row[7]),
			updated_at=float(row[8]),
		)


def cosine_similarity(a: list[float], b: list[float]) -> float:
	if not a or not b or len(a) != len(b):
		return 0.0
	dot = sum(x * y for x, y in zip(a, b))
	na = sum(x * x for x in a) ** 0.5
	nb = sum(y * y for y in b) ** 0.5
	if na <= 0 or nb <= 0:
		return 0.0
	return dot / (na * nb)
