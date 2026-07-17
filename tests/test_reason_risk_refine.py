"""AI 归类推荐理由与风险提示的测试。"""

import json

from pet_boss.agents.analysis_scoring import (
	localize_analysis_text,
	refine_reason_risk_with_ai,
	sanitize_risk_lists,
)


class _FakeRefineAI:
	"""模拟 AI 按语义重分区 reason / risk。"""

	def __init__(self, reason: list[str], risk: list[str]) -> None:
		self._reason = reason
		self._risk = risk

	def chat(self, messages, **kwargs):
		return json.dumps({"reason": self._reason, "risk": self._risk}, ensure_ascii=False)


def test_refine_moves_positive_from_risk_to_reason():
	svc = _FakeRefineAI(
		reason=["技能较匹配", "公司不需要融资，财务风险较低"],
		risk=["JD职责堆叠，一人多岗"],
	)
	reason, risk = refine_reason_risk_with_ai(
		svc,
		reason=["技能较匹配"],
		risk=["公司不需要融资，财务风险较低", "JD职责堆叠，一人多岗"],
		job={"title": "工程师", "company": "测试科技"},
		stage_label="初级",
	)
	assert any("财务风险较低" in r for r in reason)
	assert any("一人多岗" in r for r in risk)
	assert not any("财务风险较低" in r for r in risk)


def test_sanitize_with_ai_classifies_salary_attractiveness():
	svc = _FakeRefineAI(
		reason=["薪资11-22K，对初级岗位有吸引力"],
		risk=[],
	)
	reason, risk = sanitize_risk_lists(
		[],
		["薪资11-22K，对初级岗位有吸引力"],
		ai_service=svc,
		job={"title": "AI工程师"},
	)
	assert risk == []
	assert any("吸引力" in r for r in reason)


def test_sanitize_without_ai_does_not_reclassify():
	reason, risk = sanitize_risk_lists(
		[],
		["薪资11-22K，对初级岗位有吸引力"],
	)
	assert len(risk) == 1
	assert reason == []


def test_sanitize_filters_profile_echo_without_ai():
	reason, risk = sanitize_risk_lists(
		[],
		["候选人风险偏好为medium，能接受一定风险"],
	)
	assert risk == []
	assert "中等" in localize_analysis_text("medium")
