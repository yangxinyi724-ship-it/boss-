"""Planner 单元测试（不调用真实 LLM API）。"""

from __future__ import annotations

import json

import pytest

from pet_boss.agents.planners.analysis_review import (
	is_borderline_score,
	maybe_review_borderline_score,
)
from pet_boss.agents.planners.base import clamp_int, parse_llm_json_object
from pet_boss.agents.planners.daily_action import plan_daily_actions
from pet_boss.agents.planners.scout_strategy import plan_scout_round_strategy
from pet_boss.ai.service import AIService
from pet_boss.profile.models import AdaptiveScore, UserProfile


class _FakeAIService(AIService):
	def __init__(self, *, reply: str = "") -> None:
		super().__init__(
			base_url="http://fake",
			api_key="test",
			model="fake-chat",
			embedding_model="fake-embed",
			rag_enabled=False,
		)
		self.reply = reply
		self.calls: list[list[dict[str, str]]] = []

	def chat(self, messages, **kwargs):  # noqa: ANN001
		self.calls.append(messages)
		return self.reply


def test_parse_llm_json_object_with_fence():
	raw = '```json\n{"a": 1}\n```'
	assert parse_llm_json_object(raw) == {"a": 1}


def test_clamp_int():
	assert clamp_int("3", 1, 5, 2) == 3
	assert clamp_int("99", 1, 5, 2) == 5
	assert clamp_int("x", 1, 5, 2) == 2


def test_is_borderline_score():
	assert is_borderline_score(58, 60) is True
	assert is_borderline_score(65, 60) is True
	assert is_borderline_score(40, 60) is False
	assert is_borderline_score(80, 60) is False


def test_plan_scout_round_strategy_heuristic_fallback():
	base = {"planned_cap": 3, "effective_cap": 3, "early_stop": False, "stop_reason": "默认"}
	plan = plan_scout_round_strategy(None, context={"round": 1}, round_page_cap=3, base_plan=base)
	assert plan["planner"] == "heuristic"
	assert plan["fatigue"] is False
	assert plan["effective_cap"] == 3


def test_plan_scout_round_strategy_llm():
	ai = _FakeAIService(
		reply=json.dumps({
			"round_page_cap": 4,
			"effective_cap": 2,
			"early_stop": True,
			"pass_target": 3,
			"strategy_summary": "保守浏览两页",
			"focus_notes": ["优先看标题匹配度"],
		}, ensure_ascii=False),
	)
	base = {"planned_cap": 3, "effective_cap": 3, "early_stop": False}
	plan = plan_scout_round_strategy(
		ai,
		context={"round": 2, "query": "C++", "city": "广州"},
		round_page_cap=3,
		base_plan=base,
	)
	assert plan["planner"] == "llm"
	assert plan["planned_cap"] == 4
	assert plan["effective_cap"] == 2
	assert plan["early_stop"] is True
	assert plan["pass_target"] == 3
	assert plan["fatigue"] is False


def test_plan_daily_actions_heuristic():
	plan = plan_daily_actions(None, context={"date": "2026-07-02", "summary": {"filtered_count": 8}})
	assert plan["planner"] == "heuristic"
	assert plan["priorities"]
	assert "休息" in plan["risk_notes"][0]


def test_plan_daily_actions_llm():
	ai = _FakeAIService(
		reply=json.dumps({
			"headline": "先看已通过岗位",
			"priorities": ["处理候选池"],
			"apply_today": [{"title": "C++开发", "company": "ACME", "reason": "高分匹配"}],
			"review_filtered": [],
			"profile_actions": [],
			"risk_notes": [],
		}, ensure_ascii=False),
	)
	plan = plan_daily_actions(ai, context={"date": "2026-07-02", "summary": {}, "daily_picks": []})
	assert plan["planner"] == "llm"
	assert plan["headline"] == "先看已通过岗位"
	assert plan["apply_today"][0]["title"] == "C++开发"


def test_maybe_review_borderline_score_pass(monkeypatch):
	ai = _FakeAIService(
		reply=json.dumps({
			"final_score": 64,
			"decision": "pass",
			"review_reason": ["RAG 显示同类岗位曾通过"],
			"review_risk": [],
		}, ensure_ascii=False),
	)
	monkeypatch.setattr(
		"pet_boss.agents.planners.analysis_review.retrieve_analysis_rag_hits",
		lambda *a, **k: [],
	)
	profile = UserProfile()
	result = AdaptiveScore(score=58, reason=["初始偏低"], risk=[], priority=1, dimensions={})
	job = {"title": "C++", "company": "ACME", "description": "嵌入式开发"}
	reviewed = maybe_review_borderline_score(ai, result, job, profile, pass_score=60)
	assert reviewed.score >= 60
	assert reviewed.review_plan is not None
	assert reviewed.review_plan["decision"] == "pass"


def test_maybe_review_borderline_score_skips_far_score():
	ai = _FakeAIService(reply="{}")
	result = AdaptiveScore(score=30, reason=[], risk=[], priority=1, dimensions={})
	out = maybe_review_borderline_score(ai, result, {"title": "Go"}, UserProfile(), pass_score=60)
	assert out.score == 30
	assert out.review_plan is None
	assert not ai.calls
