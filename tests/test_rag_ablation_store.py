"""RAG 消融报告加载（无 AI 时）。"""

from __future__ import annotations

from pathlib import Path

from pet_boss.eval.rag_ablation import load_latest_rag_ablation, save_latest_rag_ablation


def test_rag_ablation_persist_roundtrip(tmp_path: Path) -> None:
	report = {
		"ok": True,
		"total": 2,
		"flip_rate": 0.5,
		"cases": [{"title": "t", "flipped": True}],
	}
	save_latest_rag_ablation(tmp_path, report)
	loaded = load_latest_rag_ablation(tmp_path)
	assert loaded is not None
	assert loaded["flip_rate"] == 0.5
	assert loaded["total"] == 2
