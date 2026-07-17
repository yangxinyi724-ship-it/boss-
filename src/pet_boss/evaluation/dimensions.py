"""各评分维度 — 独立评估模块，统一 DimensionResult 接口。"""

from __future__ import annotations

from typing import Callable

from pet_boss.evaluation.models import CandidateProfile, DimensionResult
from pet_boss.evaluation import signals as sig

EvaluatorFn = Callable[[dict, str, CandidateProfile], DimensionResult]


def _result(
	score: float,
	evidence: list[str],
	reasoning: str,
	*,
	confidence: float = 0.7,
) -> DimensionResult:
	return DimensionResult(
		score=score,
		confidence=confidence,
		evidence=evidence,
		reasoning=reasoning,
	)


def eval_skill_match(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	score, hits = sig.skill_match_score(blob, profile.skills)
	return _result(
		score, hits,
		"技能与 JD 匹配度" if hits else "JD 中未明显命中简历技能",
		confidence=0.85 if hits else 0.55,
	)


def eval_growth_fit(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	accept = sig.count_hits(blob, sig.GROWTH_ACCEPT)
	mentor = sig.count_hits(blob, sig.GROWTH_MENTOR)
	scope = sig.count_hits(blob, sig.GROWTH_SCOPE)
	score = sig.score_from_hits(accept + mentor + scope, 0, base=45, pos_weight=10)
	evidence = sig.extract_evidence(blob, sig.GROWTH_ACCEPT + sig.GROWTH_MENTOR + sig.GROWTH_SCOPE)
	if profile.career_change_ok and accept:
		score = min(100, score + 8)
	return _result(score, evidence, "评估培养空间、导师机制与业务参与深度")


def eval_learning_friendly(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	pos = sig.count_hits(blob, sig.LEARNING_FRIENDLY)
	neg = sig.count_hits(blob, sig.LEARNING_HOSTILE)
	score = sig.score_from_hits(pos, neg, base=48, pos_weight=14, neg_weight=18)
	evidence = sig.extract_evidence(blob, sig.LEARNING_FRIENDLY)
	if neg:
		evidence.extend(sig.extract_evidence(blob, sig.LEARNING_HOSTILE, limit=2))
	return _result(score, evidence, "语义分析培养友好度（非纯关键词）", confidence=0.75)


def eval_team_quality(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, sig.TEAM_QUALITY)
	score = sig.score_from_hits(hits, 0, base=42, pos_weight=13)
	evidence = sig.extract_evidence(blob, sig.TEAM_QUALITY)
	sub = []
	if any(w in blob for w in ("code review", "review")):
		sub.append("Code Review")
	if any(w in blob for w in ("技术分享", "分享")):
		sub.append("Technical Sharing")
	if any(w in blob for w in ("导师", "mentor", "带教")):
		sub.append("Mentorship")
	if any(w in blob for w in ("技术负责人", "架构师", "cto")):
		sub.append("Technical Leadership")
	reasoning = " · ".join(sub) if sub else "团队研发文化信号"
	return _result(score, evidence, reasoning)


def eval_career_potential(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	tech = sig.count_hits(blob, sig.TECH_STACK)
	crud = sig.count_hits(blob, sig.CRUD_HEAVY)
	goal = profile.career_goal.lower()
	goal_bonus = 1 if goal and any(g in blob for g in goal.split() if len(g) > 1) else 0
	score = sig.score_from_hits(tech + goal_bonus, crud, base=40, pos_weight=11, neg_weight=12)
	evidence = sig.extract_evidence(blob, sig.TECH_STACK)
	return _result(score, evidence, "关注未来竞争力积累，而非仅当前 CRUD")


def eval_culture_fit(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	pos = sig.count_hits(blob, sig.CULTURE_POS)
	neg = sig.count_hits(blob, sig.CULTURE_NEG)
	score = sig.score_from_hits(pos, neg, base=50, pos_weight=12, neg_weight=14)
	evidence = sig.extract_evidence(blob, sig.CULTURE_POS)
	return _result(score, evidence, "团队文化与协作氛围")


def eval_risk(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	"""风险维度：分数越高表示风险越低（越安全）。"""
	stack = sig.count_hits(blob, sig.RISK_STACK)
	ot = sig.count_hits(blob, sig.RISK_OVERTIME)
	desc = job.get("description") or job.get("postDescription") or ""
	stack_penalty = 2 if len(desc) > 400 and stack >= 2 else stack
	score = sig.score_from_hits(0, stack_penalty + ot, base=78, neg_weight=12)
	evidence = sig.extract_evidence(blob, sig.RISK_STACK + sig.RISK_OVERTIME)
	level = "低" if score >= 70 else ("中" if score >= 45 else "高")
	return _result(score, evidence, f"风险等级：{level}", confidence=0.65)


def eval_skill_growth(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	tech = sig.count_hits(blob, sig.TECH_STACK)
	scope = sig.count_hits(blob, sig.GROWTH_SCOPE)
	score = sig.score_from_hits(tech + scope, 0, base=45, pos_weight=11)
	evidence = sig.extract_evidence(blob, sig.TECH_STACK + sig.GROWTH_SCOPE)
	return _result(score, evidence, "技术栈成长与业务深度")


def eval_technical_depth(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, sig.TECH_DEPTH)
	score = sig.score_from_hits(hits, 0, base=44, pos_weight=14)
	evidence = sig.extract_evidence(blob, sig.TECH_DEPTH)
	return _result(score, evidence, "技术挑战与深度")


def eval_promotion_potential(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, sig.PROMOTION)
	score = sig.score_from_hits(hits, 0, base=42, pos_weight=15)
	evidence = sig.extract_evidence(blob, sig.PROMOTION)
	return _result(score, evidence, "晋升与职级成长空间")


def eval_salary_growth(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, sig.SALARY_GROWTH)
	score = sig.score_from_hits(hits, 0, base=45, pos_weight=13)
	if profile.salary_priority >= 4 and hits == 0:
		score = max(35, score - 10)
	evidence = sig.extract_evidence(blob, sig.SALARY_GROWTH)
	return _result(score, evidence, "薪资成长与激励")


def eval_engineering_culture(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	return eval_team_quality(job, blob, profile)


def eval_project_value(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, sig.PROJECT_VALUE + sig.GROWTH_SCOPE)
	score = sig.score_from_hits(hits, sig.count_hits(blob, sig.CRUD_HEAVY), base=43, pos_weight=12, neg_weight=10)
	evidence = sig.extract_evidence(blob, sig.PROJECT_VALUE)
	return _result(score, evidence, "项目价值与行业竞争力")


def eval_leadership(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, ("带团队", "技术负责人", "lead", "组长", "经理"))
	score = sig.score_from_hits(hits, 0, base=40, pos_weight=16)
	evidence = sig.extract_evidence(blob, ("带团队", "技术负责人", "lead"))
	return _result(score, evidence, "领导力与带团队机会")


def eval_platform_value(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, sig.EXPERT_PLATFORM)
	stage = str(job.get("stage") or "")
	bonus = 1 if any(s in stage for s in ("上市", "C轮", "D轮", "独角兽")) else 0
	score = sig.score_from_hits(hits + bonus, 0, base=42, pos_weight=14)
	evidence = sig.extract_evidence(blob, sig.EXPERT_PLATFORM)
	return _result(score, evidence, "平台规模与资源")


def eval_technical_influence(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, sig.EXPERT_INFLUENCE)
	score = sig.score_from_hits(hits, 0, base=40, pos_weight=13)
	evidence = sig.extract_evidence(blob, sig.EXPERT_INFLUENCE)
	return _result(score, evidence, "技术影响力与行业可见度")


def eval_architecture_opportunity(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, ("架构", "架构设计", "系统设计", "技术选型"))
	score = sig.score_from_hits(hits, 0, base=38, pos_weight=16)
	evidence = sig.extract_evidence(blob, ("架构", "架构设计", "系统设计"))
	return _result(score, evidence, "架构设计机会")


def eval_leadership_opportunity(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	return eval_leadership(job, blob, profile)


def eval_business_impact(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, ("营收", "业务增长", "核心产品", "战略", "商业化"))
	score = sig.score_from_hits(hits, 0, base=42, pos_weight=14)
	evidence = sig.extract_evidence(blob, ("营收", "业务增长", "核心产品", "战略"))
	return _result(score, evidence, "业务影响力")


def eval_innovation(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, sig.TECH_STACK + ("创新", "研发", "实验室", "前沿"))
	score = sig.score_from_hits(hits, 0, base=44, pos_weight=11)
	evidence = sig.extract_evidence(blob, ("创新", "前沿", "研发"))
	return _result(score, evidence, "创新与技术前沿")


def eval_equity_potential(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, ("期权", "股权", "esop", "合伙人"))
	score = sig.score_from_hits(hits, 0, base=38, pos_weight=18)
	evidence = sig.extract_evidence(blob, ("期权", "股权", "esop"))
	return _result(score, evidence, "长期激励与股权")


def eval_decision_power(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, ("技术决策", "主导", "负责", "决策权", "拍板"))
	score = sig.score_from_hits(hits, 0, base=38, pos_weight=15)
	evidence = sig.extract_evidence(blob, ("技术决策", "主导", "决策"))
	return _result(score, evidence, "技术决策权")


def eval_vision(job: dict, blob: str, profile: CandidateProfile) -> DimensionResult:
	hits = sig.count_hits(blob, ("愿景", "使命", "战略方向", "行业", "未来"))
	score = sig.score_from_hits(hits, 0, base=42, pos_weight=12)
	evidence = sig.extract_evidence(blob, ("愿景", "战略", "未来"))
	return _result(score, evidence, "公司愿景与方向")


DIMENSION_EVALUATORS: dict[str, EvaluatorFn] = {
	"skill_match": eval_skill_match,
	"growth_fit": eval_growth_fit,
	"learning_friendly": eval_learning_friendly,
	"team_quality": eval_team_quality,
	"career_potential": eval_career_potential,
	"culture_fit": eval_culture_fit,
	"risk_assessment": eval_risk,
	"risk": eval_risk,
	"skill_growth": eval_skill_growth,
	"technical_depth": eval_technical_depth,
	"promotion_potential": eval_promotion_potential,
	"salary_growth": eval_salary_growth,
	"engineering_culture": eval_engineering_culture,
	"project_value": eval_project_value,
	"leadership": eval_leadership,
	"platform_value": eval_platform_value,
	"technical_influence": eval_technical_influence,
	"architecture_opportunity": eval_architecture_opportunity,
	"leadership_opportunity": eval_leadership_opportunity,
	"business_impact": eval_business_impact,
	"innovation": eval_innovation,
	"equity_potential": eval_equity_potential,
	"decision_power": eval_decision_power,
	"vision": eval_vision,
}
