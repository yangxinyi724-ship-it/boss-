"""职业阶段评估 — 可选 AI 语义增强。"""

from __future__ import annotations

import json
from typing import Any

from pet_boss.ai.service import AIService
from pet_boss.agents.analysis_scoring import localize_analysis_text
from pet_boss.evaluation.models import CandidateProfile, CareerStage, DimensionResult
from pet_boss.evaluation.stages import DIMENSION_LABELS, STAGE_LABELS

_LEVEL_ZH = {"low": "低", "medium": "中等", "high": "高"}


def _candidate_for_prompt(candidate: CandidateProfile) -> dict[str, object]:
	data = candidate.to_dict()
	rp = str(data.get("risk_preference") or "medium").lower()
	data["risk_preference"] = _LEVEL_ZH.get(rp, rp)
	return data


def score_dimensions_with_ai(
	svc: AIService,
	job: dict[str, Any],
	candidate: CandidateProfile,
	stage: CareerStage,
	dimension_keys: list[str],
) -> dict[str, DimensionResult]:
	labels = {k: DIMENSION_LABELS.get(k, k) for k in dimension_keys}
	prompt = (
		f"职业阶段：{STAGE_LABELS[stage]}（{stage}）\n"
		f"候选画像：{json.dumps(_candidate_for_prompt(candidate), ensure_ascii=False)}\n"
		f"岗位：{json.dumps(job, ensure_ascii=False)[:6000]}\n"
		f"请对以下维度评分（0-100），进行语义分析而非简单关键词：\n"
		f"{json.dumps(labels, ensure_ascii=False)}\n"
		"输出 JSON：{\"dimensions\": {\"key\": {\"score\": 0, \"confidence\": 0.0, "
		"\"evidence\": [\"...\"], \"reasoning\": \"...\"}}}\n"
		"evidence 与 reasoning 必须使用简体中文，禁止出现 medium/low/high 等英文等级词；"
		"不要复述候选人画像字段（如风险偏好）。"
	)
	raw = svc.chat([
		{"role": "system", "content": "你是分析 AI（FX），专注职业阶段匹配评估。只输出 JSON，文案用简体中文。"},
		{"role": "user", "content": prompt},
	], agent="FX", temperature=0.3, max_tokens=1200)
	text = raw.strip()
	if text.startswith("```"):
		text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```")).strip()
	data = json.loads(text)
	out: dict[str, DimensionResult] = {}
	for key in dimension_keys:
		block = (data.get("dimensions") or {}).get(key) or {}
		if not block:
			continue
		out[key] = DimensionResult(
			score=float(block.get("score") or 0),
			confidence=float(block.get("confidence") or 0.6),
			evidence=[localize_analysis_text(str(x)) for x in (block.get("evidence") or [])][:5],
			reasoning=localize_analysis_text(str(block.get("reasoning") or "")),
		)
	return out
