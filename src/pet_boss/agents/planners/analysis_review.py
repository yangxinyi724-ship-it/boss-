"""分析 AI 边界复核 Planner — 针对接近通过线的岗位二次推理。"""

from __future__ import annotations

import json
from typing import Any

from pet_boss.agents.planners.base import clamp_int, parse_llm_json_object
from pet_boss.ai.service import AIService
from pet_boss.profile.models import AdaptiveScore, UserProfile
from pet_boss.profile.store import ProfileStore
from pet_boss.rag.retriever import retrieve_analysis_rag_hits

REVIEW_PROMPT = """你是分析 AI 复核员。初始评分接近通过线，请结合 RAG 历史案例做二次判断。

输出 JSON（只输出 JSON）：
{{
  "final_score": 0-100 整数,
  "decision": "pass" | "filter" | "unchanged",
  "review_reason": ["最多3条复核理由"],
  "review_risk": ["最多3条补充风险"]
}}

通过线：{pass_score}
初始分数：{initial_score}
岗位：{job_json}
画像摘要：{profile_json}
RAG参考：{rag_json}
初始理由：{reason_json}
初始风险：{risk_json}
"""


def is_borderline_score(score: int, pass_score: int, *, margin_low: int = 12, margin_high: int = 5) -> bool:
	lo = max(0, pass_score - margin_low)
	hi = min(100, pass_score + margin_high)
	return lo <= score <= hi


def maybe_review_borderline_score(
	ai_service: AIService | None,
	result: AdaptiveScore,
	job: dict[str, Any],
	profile: UserProfile,
	*,
	store: ProfileStore | None = None,
	pass_score: int = 60,
) -> AdaptiveScore:
	if ai_service is None or not is_borderline_score(result.score, pass_score):
		return result

	rag_refs = retrieve_analysis_rag_hits(store, ai_service, job, top_k=4)
	prompt = REVIEW_PROMPT.format(
		pass_score=pass_score,
		initial_score=result.score,
		job_json=json.dumps({
			"title": job.get("title"),
			"company": job.get("company"),
			"salary": job.get("salary"),
			"city": job.get("city"),
			"skills": job.get("skills"),
			"description": (job.get("description") or job.get("postDescription") or "")[:1200],
		}, ensure_ascii=False),
		profile_json=json.dumps(profile.to_dict(), ensure_ascii=False)[:4000],
		rag_json=json.dumps(rag_refs, ensure_ascii=False),
		reason_json=json.dumps(result.reason, ensure_ascii=False),
		risk_json=json.dumps(result.risk, ensure_ascii=False),
	)
	try:
		raw = ai_service.chat([
			{"role": "system", "content": "你是分析 AI 复核员。只输出 JSON，中文。"},
			{"role": "user", "content": prompt},
		], agent="FX", temperature=0.2, max_tokens=700)
		data = parse_llm_json_object(raw)
	except Exception:
		return result

	final_score = clamp_int(data.get("final_score"), 0, 100, result.score)
	decision = str(data.get("decision") or "unchanged").strip().lower()
	review_reason = [str(x).strip() for x in (data.get("review_reason") or []) if str(x).strip()][:3]
	review_risk = [str(x).strip() for x in (data.get("review_risk") or []) if str(x).strip()][:3]

	review_plan = {
		"planner": "llm",
		"initial_score": result.score,
		"final_score": final_score,
		"decision": decision,
		"pass_score": pass_score,
		"review_reason": review_reason,
		"review_risk": review_risk,
		"rag_references": rag_refs,
	}

	new_score = result.score
	if decision == "pass" and final_score >= pass_score:
		new_score = max(final_score, pass_score)
	elif decision == "filter" and final_score < pass_score:
		new_score = min(final_score, pass_score - 1)
	elif decision != "unchanged":
		new_score = final_score

	merged_reason = list(dict.fromkeys([*result.reason, *review_reason]))
	merged_risk = list(dict.fromkeys([*result.risk, *review_risk]))

	return AdaptiveScore(
		score=new_score,
		reason=merged_reason,
		risk=merged_risk,
		priority=result.priority,
		dimensions=result.dimensions,
		rag_references=result.rag_references or rag_refs,
		review_plan=review_plan,
	)
