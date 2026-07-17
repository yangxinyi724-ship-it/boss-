"""向量 RAG 单元测试（不调用真实 Embedding API）。"""

from __future__ import annotations

import pytest

from pet_boss.ai.service import AIService
from pet_boss.profile.store import ProfileStore
from pet_boss.rag.documents import analysis_doc_key, job_document_text
from pet_boss.rag.service import format_rag_context, index_analysis_job, retrieve_similar
from pet_boss.rag.vector_store import VectorStore, cosine_similarity


class _FakeAIService(AIService):
	def __init__(self) -> None:
		super().__init__(
			base_url="http://fake",
			api_key="test",
			model="fake-chat",
			embedding_model="fake-embed",
			rag_enabled=True,
		)
		self._calls = 0

	def _fake_vector(self, text: str) -> list[float]:
		self._calls += 1
		base = float(len(text) % 17) / 17.0
		return [base, 1.0 - base, 0.5]


@pytest.fixture
def profile_store(tmp_path):
	store = ProfileStore(tmp_path)
	yield store
	store.close()


def test_cosine_similarity_identical():
	vec = [0.2, 0.5, 0.9]
	assert cosine_similarity(vec, vec) == pytest.approx(1.0)


def test_index_and_retrieve_similar(profile_store, monkeypatch):
	ai = _FakeAIService()
	monkeypatch.setattr(
		"pet_boss.rag.service._embed_one",
		lambda svc, text: ai._fake_vector(text),
	)

	job_a = {
		"security_id": "s1",
		"job_id": "j1",
		"title": "C++开发工程师",
		"company": "某科技",
		"city": "广州",
		"salary": "20-30K",
		"analysis_score": 82,
		"analysis_reason": ["技能匹配"],
		"analysis_risk": [],
		"description": "负责嵌入式 C++ 开发",
	}
	job_b = {
		"security_id": "s2",
		"job_id": "j2",
		"title": "C++ 后端开发",
		"company": "另一家公司",
		"city": "广州",
		"salary": "18-28K",
		"description": "C++ 服务端开发",
	}
	job_query = {
		"security_id": "s9",
		"job_id": "j9",
		"title": "C++开发",
		"company": "新公司",
		"description": "C++ 嵌入式方向",
	}

	assert index_analysis_job(profile_store, ai, job_a, status="passed") is True
	assert index_analysis_job(profile_store, ai, job_b, status="filtered") is True

	vs = VectorStore(profile_store._conn)
	assert vs.count() == 2

	hits = retrieve_similar(profile_store, ai, job_query, top_k=2, min_score=0.0)
	assert hits
	assert hits[0].metadata.get("title")

	ctx = format_rag_context(hits)
	assert "向量 RAG" in ctx
	assert "相似度" in ctx


def test_job_document_text_includes_status():
	text = job_document_text(
		{"title": "Go", "company": "ACME", "analysis_score": 70},
		status="passed",
		search_query="Golang",
	)
	assert "Go" in text
	assert "passed" in text
	assert "Golang" in text


def test_rag_hits_to_references():
	from pet_boss.rag.service import RagHit, rag_hits_to_references

	hits = [
		RagHit(
			doc_key="analysis:s1:j1",
			source_type="analysis",
			score=0.88,
			text="岗位：C++ @ ACME\n评估结果：passed",
			metadata={"status": "passed", "title": "C++", "company": "ACME", "analysis_score": 80},
		),
	]
	refs = rag_hits_to_references(hits)
	assert refs[0]["title"] == "C++"
	assert refs[0]["similarity"] == 0.88
