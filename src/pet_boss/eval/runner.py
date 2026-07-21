"""评测执行器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pet_boss.agents.scout_hard_filter import ScoutFilterConfig, evaluate_hard_criteria
from pet_boss.profile.models import UserProfile


def load_label_cases(path: Path) -> dict[str, Any]:
	data = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
		raise ValueError(f"标注集格式无效: {path}")
	return data


def _predict_scout_hard(case: dict[str, Any]) -> str:
	job = case.get("job") if isinstance(case.get("job"), dict) else {}
	flags = case.get("filters") if isinstance(case.get("filters"), dict) else {}
	cfg = ScoutFilterConfig.from_payload(flags.get("scout_filters"))
	result = evaluate_hard_criteria(job, UserProfile(), scout_filters=cfg)
	return "pass" if result.passed else "filter"


def _predict_analysis_score(case: dict[str, Any], pass_score: float) -> str:
	if "mock_score" in case:
		score = float(case["mock_score"])
		return "pass" if score >= pass_score else "filter"
	raise ValueError(f"analysis_score 用例缺少 mock_score: {case.get('id')}")


def run_eval_report(path: Path) -> dict[str, Any]:
	"""对标注 JSON 跑准确率报告。path 一般为 data/eval/eval_today.json。"""
	p = Path(path)
	if not p.exists():
		raise FileNotFoundError(
			f"标注集不存在: {p}\n请先在监控台点「抓取评测集」，或执行 boss eval --capture"
		)
	bundle = load_label_cases(p)
	pass_score = float(bundle.get("pass_score") or 60)
	cases = bundle.get("cases") or []

	tp = fp = tn = fn = 0
	details: list[dict[str, Any]] = []
	errors: list[str] = []

	for case in cases:
		if not isinstance(case, dict):
			continue
		cid = str(case.get("id") or "")
		expected = str(case.get("expected") or "").strip().lower()
		stage = str(case.get("stage") or "scout_hard").strip().lower()
		if expected not in {"pass", "filter"}:
			errors.append(f"{cid}: expected 必须是 pass/filter")
			continue
		try:
			if stage == "analysis_score":
				predicted = _predict_analysis_score(case, pass_score)
			else:
				predicted = _predict_scout_hard(case)
		except Exception as exc:
			errors.append(f"{cid}: {exc}")
			continue

		ok = predicted == expected
		if expected == "pass" and predicted == "pass":
			tp += 1
		elif expected == "filter" and predicted == "filter":
			tn += 1
		elif expected == "filter" and predicted == "pass":
			fp += 1
		else:
			fn += 1

		details.append({
			"id": cid,
			"title": (
				str((case.get("job") or {}).get("title") or "").strip()
				or str(case.get("title") or "").strip()
				or cid
			),
			"company": str(
				(case.get("job") or {}).get("company")
				or (case.get("job") or {}).get("brand_name")
				or ""
			).strip(),
			"stage": stage,
			"expected": expected,
			"predicted": predicted,
			"ok": ok,
			"note": case.get("note") or "",
		})

	total = tp + tn + fp + fn
	accuracy = (tp + tn) / total if total else 0.0
	should_pass = tp + fn
	false_reject_rate = fn / should_pass if should_pass else 0.0
	should_filter = tn + fp
	false_pass_rate = fp / should_filter if should_filter else 0.0

	return {
		"fixture": str(p),
		"pass_score": pass_score,
		"total": total,
		"accuracy": round(accuracy, 4),
		"false_reject_rate": round(false_reject_rate, 4),
		"false_pass_rate": round(false_pass_rate, 4),
		"confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
		"details": details,
		"errors": errors,
	}
