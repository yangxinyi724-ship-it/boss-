"""评测样例与向量后端基础测试。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pet_boss.eval import run_eval_report
from pet_boss.rag.vector_store import VectorStore, cosine_similarity


def test_eval_report_runs_on_labels_file(tmp_path: Path) -> None:
	labels = tmp_path / "eval_today.json"
	labels.write_text(
		json.dumps({
			"pass_score": 60,
			"cases": [
				{
					"id": "a",
					"expected": "pass",
					"stage": "analysis_score",
					"mock_score": 80,
					"job": {"title": "AI工程师"},
				},
				{
					"id": "b",
					"expected": "filter",
					"stage": "analysis_score",
					"mock_score": 40,
					"job": {"title": "销售"},
				},
				{
					"id": "c",
					"expected": "filter",
					"stage": "scout_hard",
					"job": {
						"title": "架构师",
						"brand_name": "某某人力资源",
						"boss_title": "猎头顾问",
					},
				},
				{
					"id": "d",
					"expected": "filter",
					"stage": "scout_hard",
					"job": {
						"title": "Python开发",
						"activeTimeDesc": "2月内活跃",
					},
				},
			],
		}, ensure_ascii=False),
		encoding="utf-8",
	)
	report = run_eval_report(labels)
	assert report["total"] >= 4
	assert "accuracy" in report
	assert "false_reject_rate" in report
	assert "false_pass_rate" in report
	assert not report["errors"]


def test_sqlite_vector_query_similar() -> None:
	conn = sqlite3.connect(":memory:")
	vs = VectorStore(conn)
	assert vs.backend_name == "sqlite"
	v1 = [1.0, 0.0, 0.0]
	v2 = [0.9, 0.1, 0.0]
	v3 = [0.0, 1.0, 0.0]
	vs.upsert(
		doc_key="a",
		source_type="analysis",
		source_id="1",
		text="ai engineer",
		metadata={"job_id": "1"},
		embedding=v1,
		model="test",
	)
	vs.upsert(
		doc_key="b",
		source_type="analysis",
		source_id="2",
		text="unrelated",
		metadata={"job_id": "2"},
		embedding=v3,
		model="test",
	)
	hits = vs.query_similar(v2, top_k=2, min_score=0.5)
	assert hits
	assert hits[0][0].doc_key == "a"
	assert cosine_similarity(v1, v2) >= 0.5
