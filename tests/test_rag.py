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


def test_rag_miss_message_prefers_meta_message():
	from pet_boss.rag.service import rag_miss_message_for_display

	msg = rag_miss_message_for_display(
		references=[],
		rag_meta={"code": "below_threshold", "message": "相似度过低", "best_score": 0.1},
	)
	assert msg == "相似度过低"


def test_rag_miss_message_legacy_empty_when_store_has_vectors():
	from pet_boss.rag.service import rag_miss_message_for_display

	msg = rag_miss_message_for_display(
		references=[],
		rag_meta={},
		current_vector_count=85,
	)
	assert "未保存 RAG 参考" in msg or "未接入" in msg
	assert "85" in msg


def test_retrieve_analysis_rag_result_returns_meta(profile_store, monkeypatch):
	from pet_boss.rag.service import retrieve_analysis_rag_result

	ai = _FakeAIService()
	monkeypatch.setattr(
		"pet_boss.rag.service._embed_one",
		lambda svc, text: ai._fake_vector(text),
	)
	job = {
		"security_id": "s1",
		"job_id": "j1",
		"title": "C++开发工程师",
		"company": "某科技",
		"description": "负责嵌入式 C++ 开发",
		"analysis_score": 82,
	}
	assert index_analysis_job(profile_store, ai, job, status="passed") is True

	query = {
		"security_id": "s9",
		"job_id": "j9",
		"title": "C++开发",
		"description": "C++ 嵌入式方向",
	}
	bundle = retrieve_analysis_rag_result(profile_store, ai, query, top_k=2)
	assert "references" in bundle
	assert "meta" in bundle
	assert bundle["meta"]["code"] in {"ok", "below_threshold"}
	assert isinstance(bundle["meta"].get("vector_count"), int)


def test_select_rag_hits_threshold_and_expand():
	from pet_boss.rag.service import select_rag_hits

	# 高相似：最多 top_k=5
	scored = [(0.9 - i * 0.01, f"h{i}") for i in range(10)]
	hits, info = select_rag_hits(scored, top_k=5, expand_k=8, min_score=0.35, low_sim_score=0.45)
	assert len(hits) == 5
	assert info["expanded"] is False
	assert info["best_score"] == 0.9

	# 勉强过线：扩到 8
	scored_low = [(0.40 - i * 0.005, f"l{i}") for i in range(10)]
	hits2, info2 = select_rag_hits(
		scored_low, top_k=5, expand_k=8, min_score=0.35, low_sim_score=0.45,
	)
	assert len(hits2) == 8
	assert info2["expanded"] is True
	assert 0.35 <= info2["best_score"] < 0.45

	# 低于阈值：全部丢弃
	scored_bad = [(0.2, "a"), (0.1, "b")]
	hits3, info3 = select_rag_hits(scored_bad, top_k=5, expand_k=8, min_score=0.35)
	assert hits3 == []
	assert info3["above_threshold"] == 0
	assert info3["best_score"] == 0.2

	# 过线不足 top_k：扩上限，但仍只返回实际过线条数
	scored_few = [(0.6, "a"), (0.55, "b"), (0.2, "noise")]
	hits4, info4 = select_rag_hits(scored_few, top_k=5, expand_k=8, min_score=0.35)
	assert hits4 == ["a", "b"]
	assert info4["expanded"] is True
