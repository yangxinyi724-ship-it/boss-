"""JD 文本信号库 — 供各维度评估器复用。"""

from __future__ import annotations

import re
from typing import Iterable

# Growth / Learning friendly
GROWTH_ACCEPT = (
	"应届", "无经验", "转行", "经验不足", "经验不限", "0-1年", "1年以内",
	"欢迎应届", "可接受应届", "接受转行", "零基础", "培养", "带教",
)
GROWTH_MENTOR = (
	"mentor", "导师", "培训", "技术分享", "code review", "pair programming",
	"结对编程", "review", "带教", "一对一", "成长路径", "新人培养",
)
GROWTH_SCOPE = (
	"核心业务", "完整模块", "0-1", "0到1", "从0到1", "模型开发", "大模型",
	"llm", "agent", "机器人", "robotics", "参与核心", "独立负责",
)
LEARNING_FRIENDLY = (
	"欢迎应届", "接受经验不足", "学习能力强", "提供培训", "导师带教",
	"技术分享", "一起成长", "年轻团队", "可培养", "培养体系", "成长空间",
)
LEARNING_HOSTILE = (
	"必须独立完成", "立即上手", "无需培训", "最好来自大厂", "必须3年以上",
	"3年+", "5年+", "高压交付", "快速产出", "独当一面", "来了就干",
)

# Team / Engineering culture
TEAM_QUALITY = (
	"技术负责人", "研发文化", "code review", "技术分享", "ai团队", "算法团队",
	"技术总监", "架构师", "engineering", "研发流程", "协作", "团队成长",
	"技术氛围", "技术驱动",
)

# Career potential tech stack
TECH_STACK = (
	"llm", "大模型", "agent", "智能体", "robotics", "机器人", "cv", "计算机视觉",
	"nlp", "rag", "mcp", "多模态", "自动化", "aigc", "深度学习", "强化学习",
)
CRUD_HEAVY = ("crud", "增删改查", "纯业务", "外包项目", "维护为主", "重复性")

# Risk signals
RISK_STACK = (
	"全栈+产品+运营", "一人多岗", "996", "大小周", "单休", "长期招聘",
	"急招", "画大饼", "包教包会", "无责底薪", "责任重大", "全能",
)
RISK_OVERTIME = ("996", "大小周", "单休", "加班多", "高强度", "抗压")

# Intermediate / Expert
TECH_DEPTH = (
	"架构", "系统设计", "高并发", "分布式", "性能优化", "技术难点",
	"复杂业务", "核心模块", "技术决策", "技术选型",
)
PROMOTION = ("晋升", "职级", "成长路径", "技术专家", "高级工程师", "带团队")
SALARY_GROWTH = ("期权", "股权", "奖金", "13薪", "14薪", "15薪", "涨薪", "薪酬体系")
PROJECT_VALUE = ("核心产品", "战略项目", "行业领先", "标杆", "从0到1", "创新业务")

EXPERT_INFLUENCE = (
	"技术决策", "主导", "架构设计", "技术战略", "cto", "技术vp", "团队管理",
	"预算", "资源", "行业影响力", "技术品牌", "开源", "专利", "标准制定",
)
EXPERT_PLATFORM = (
	"行业头部", "独角兽", "上市公司", "融资", "资源支持", "技术委员会",
	"研发中心", "研究院", "实验室",
)

# Culture
CULTURE_POS = ("扁平", "开放", "透明", "尊重", "创新", "试错", "氛围好", "工程师文化")
CULTURE_NEG = ("狼性", "高压", "末位淘汰", "加班文化")


def job_text_blob(job: dict) -> str:
	parts = [
		job.get("title", ""),
		job.get("company", ""),
		job.get("description", "") or job.get("postDescription", ""),
		job.get("industry", ""),
		job.get("stage", ""),
		job.get("scale", ""),
		" ".join(job.get("skills") or []),
	]
	return " ".join(str(p) for p in parts).lower()


def count_hits(blob: str, phrases: Iterable[str]) -> int:
	return sum(1 for p in phrases if p.lower() in blob)


def score_from_hits(
	pos_hits: int,
	neg_hits: int,
	*,
	base: float = 50,
	pos_weight: float = 12,
	neg_weight: float = 15,
	max_score: float = 100,
) -> float:
	raw = base + pos_hits * pos_weight - neg_hits * neg_weight
	return max(0.0, min(max_score, raw))


def extract_evidence(blob: str, phrases: Iterable[str], limit: int = 4) -> list[str]:
	found: list[str] = []
	for p in phrases:
		if p.lower() in blob:
			found.append(p)
			if len(found) >= limit:
				break
	return found


def skill_match_score(blob: str, skills: list[str]) -> tuple[float, list[str]]:
	if not skills:
		return 55.0, []
	hits = [s for s in skills if s.lower() in blob]
	if not hits:
		return 40.0, []
	score = min(100.0, 35 + len(hits) * 14)
	return score, hits[:5]
