"""职业阶段配置 — 维度集合与基础权重。"""

from __future__ import annotations

from typing import Any

from pet_boss.evaluation.models import CareerStage

STAGE_LABELS: dict[CareerStage, str] = {
	"junior": "初级",
	"intermediate": "进阶",
	"expert": "专家",
}

# 各阶段维度基础权重（总和不必为 1，引擎会归一化）
STAGE_DIMENSION_WEIGHTS: dict[CareerStage, dict[str, float]] = {
	"junior": {
		"skill_match": 0.18,
		"growth_fit": 0.20,
		"learning_friendly": 0.18,
		"team_quality": 0.14,
		"career_potential": 0.16,
		"culture_fit": 0.08,
		"risk_assessment": 0.06,
	},
	"intermediate": {
		"skill_growth": 0.14,
		"technical_depth": 0.16,
		"team_quality": 0.12,
		"promotion_potential": 0.10,
		"salary_growth": 0.10,
		"engineering_culture": 0.12,
		"project_value": 0.14,
		"leadership": 0.06,
		"risk": 0.06,
	},
	"expert": {
		"platform_value": 0.14,
		"technical_influence": 0.14,
		"architecture_opportunity": 0.12,
		"leadership_opportunity": 0.10,
		"business_impact": 0.10,
		"innovation": 0.10,
		"equity_potential": 0.08,
		"team_quality": 0.08,
		"decision_power": 0.08,
		"vision": 0.08,
		"risk": 0.08,
	},
}

DIMENSION_LABELS: dict[str, str] = {
	"skill_match": "技能匹配",
	"growth_fit": "成长空间",
	"learning_friendly": "学习友好度",
	"team_quality": "团队质量",
	"career_potential": "职业潜力",
	"culture_fit": "文化契合",
	"risk_assessment": "风险评估",
	"skill_growth": "技能成长",
	"technical_depth": "技术深度",
	"promotion_potential": "晋升空间",
	"salary_growth": "薪资成长",
	"engineering_culture": "工程文化",
	"project_value": "项目价值",
	"leadership": "领导力",
	"risk": "风险评估",
	"platform_value": "平台价值",
	"technical_influence": "技术影响力",
	"architecture_opportunity": "架构机会",
	"leadership_opportunity": "带队机会",
	"business_impact": "业务影响",
	"innovation": "创新空间",
	"equity_potential": "股权潜力",
	"decision_power": "决策权",
	"vision": "愿景契合",
}


def stage_dimensions(stage: CareerStage) -> list[str]:
	return list(STAGE_DIMENSION_WEIGHTS[stage].keys())


def adjust_weights_for_profile(
	base: dict[str, float],
	stage: CareerStage,
	profile_payload: dict[str, Any],
) -> dict[str, float]:
	"""根据 Candidate Profile 动态调整权重。"""
	weights = dict(base)
	learning = int(profile_payload.get("learning_priority") or 3)
	salary = int(profile_payload.get("salary_priority") or 3)
	mentor = int(profile_payload.get("mentor_needed") or 3)
	risk_pref = str(profile_payload.get("risk_preference") or "medium")

	if stage == "junior":
		weights["growth_fit"] *= 1 + (learning - 3) * 0.12
		weights["learning_friendly"] *= 1 + (mentor - 3) * 0.15
		weights["career_potential"] *= 1 + (learning - 3) * 0.10
		if "ai" in str(profile_payload.get("career_goal") or "").lower():
			weights["career_potential"] *= 1.15
	elif stage == "intermediate":
		weights["technical_depth"] *= 1 + (learning - 3) * 0.10
		weights["project_value"] *= 1 + (learning - 3) * 0.08
		weights["salary_growth"] *= 1 + (salary - 3) * 0.12
		weights["skill_growth"] *= 1 + (learning - 3) * 0.08
		# 降低培养相关权重
		for k in ("growth_fit", "learning_friendly"):
			if k in weights:
				weights[k] *= 0.5
	elif stage == "expert":
		weights["platform_value"] *= 1.1
		weights["technical_influence"] *= 1.12
		weights["decision_power"] *= 1.1
		for k in ("growth_fit", "learning_friendly"):
			if k in weights:
				weights[k] *= 0.3

	if risk_pref == "low":
		for k in weights:
			if k.startswith("risk") or k == "risk_assessment":
				weights[k] *= 1.35
	elif risk_pref == "high":
		for k in weights:
			if k.startswith("risk") or k == "risk_assessment":
				weights[k] *= 0.75

	total = sum(weights.values()) or 1.0
	return {k: v / total for k, v in weights.items()}
