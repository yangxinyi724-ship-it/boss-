from pathlib import Path

from pet_boss.profile.adaptive_scoring import score_job_adaptive_heuristic
from pet_boss.profile.learning import apply_feedback_learning
from pet_boss.profile.models import (
	CareerDirection,
	ParsedResume,
	UserPreferences,
	UserProfile,
)
from pet_boss.profile.profiling import (
	ProfileInterviewAIError,
	next_question,
	start_interview,
	submit_answer,
)
from pet_boss.profile.runner import _ensure_resume, _resume_is_sparse
from pet_boss.profile.store import ProfileStore
from pet_boss.resume.store import ResumeStore


def _sample_profile() -> UserProfile:
	return UserProfile(
		parsed_resume=ParsedResume(
			skills=["Golang", "Python", "AI Agent"],
			tools=["Docker", "Kubernetes"],
			industries=["互联网"],
			city="广州",
			years_of_experience=5.0,
			source_resume="main",
		),
		preferences=UserPreferences(
			role_preference="技术",
			startup_fit=True,
			remote_ok=True,
			overtime_tolerance="no",
			sales_role_ok=False,
			stability_priority="medium",
		),
		career=CareerDirection(
			primary_direction="AI应用开发",
			secondary_direction="AI工作流自动化",
			avoid_direction=["纯算法研究", "高销售岗位"],
			startup_fit=True,
			remote_fit=True,
		),
	)


def test_parsed_resume_roundtrip():
	parsed = ParsedResume(skills=["Go"], city="广州", years_of_experience=3.0)
	data = parsed.to_dict()
	restored = ParsedResume.from_dict(data)
	assert restored.skills == ["Go"]
	assert restored.city == "广州"
	assert restored.years_of_experience == 3.0


def test_profile_store_persistence(tmp_path: Path):
	with ProfileStore(tmp_path) as store:
		parsed = ParsedResume(skills=["Python"], city="深圳")
		store.save_parsed_resume(parsed)
		store.save_preferences(UserPreferences(role_preference="技术"))
		store.save_career(CareerDirection(primary_direction="后端开发"))
		profile = store.load_profile()
		assert profile.parsed_resume is not None
		assert profile.parsed_resume.skills == ["Python"]
		assert profile.preferences is not None
		assert profile.preferences.role_preference == "技术"
		assert profile.career is not None
		assert profile.career.primary_direction == "后端开发"


def test_adaptive_scoring_prefers_matching_job(tmp_path: Path):
	profile = _sample_profile()
	job = {
		"title": "AI Agent 后端开发",
		"company": "初创科技",
		"skills": ["Golang", "AI Agent"],
		"city": "广州",
		"stage": "A轮",
		"salary": "25-40K",
	}
	with ProfileStore(tmp_path) as store:
		result = score_job_adaptive_heuristic(job, profile, store=store)
	assert result.score >= 65
	assert result.priority in ("high", "medium")
	assert any("技能" in r or "方向" in r or "城市" in r for r in result.reason)


def test_adaptive_scoring_flags_overtime_risk():
	profile = _sample_profile()
	job = {
		"title": "Golang 开发",
		"company": "TestCo",
		"skills": ["Golang"],
		"city": "广州",
		"stage": "已上市",
	}
	result = score_job_adaptive_heuristic(
		job, profile, store=None,
	)
	# 无加班关键词时不应误报
	assert not any("加班" in r for r in result.risk)

	job_overtime = {**job, "title": "Golang 开发 996 大小周"}
	result2 = score_job_adaptive_heuristic(job_overtime, profile, store=None)
	assert any("强度" in r or "加班" in r for r in result2.risk)


def test_feedback_learning_adjusts_weights(tmp_path: Path):
	with ProfileStore(tmp_path) as store:
		before = store.get_dimension_weights()["skill_match"]
		learning = apply_feedback_learning(store, "applied")
		after = learning.weights["skill_match"]
		assert after > before


def test_interview_session_flow():
	session = start_interview("main", max_questions=8)
	assert session.max_questions == 8
	session.current_question = "你更看重薪资还是成长？"
	session.current_topic = "salary_vs_growth"
	session.last_reasoning = "需要了解用户优先级"
	session = submit_answer(session, "更看重成长空间")
	assert session.questions_asked == 1
	assert len(session.transcript) == 1
	assert session.transcript[0]["answer"] == "更看重成长空间"
	assert session.transcript[0]["topic"] == "salary_vs_growth"
	assert session.transcript[0]["reasoning"] == "需要了解用户优先级"


class _MockAI:
	def __init__(self, responses: list[str]) -> None:
		self._responses = list(responses)
		self.calls = 0

	def chat(self, messages, *, temperature=None, max_tokens=None, agent=None, **kwargs) -> str:
		self.calls += 1
		return self._responses.pop(0)


def test_next_question_uses_ai_reasoning():
	parsed = ParsedResume(skills=["Go"], summary="后端开发 5 年", city="广州")
	session = start_interview("main", max_questions=10)
	ai = _MockAI([
		'{"reasoning": "简历显示后端经验，需确认是否想转 AI", "topic": "ai_direction", '
		'"question": "看到你有 Go 经验，最近有考虑往 AI 应用方向深入吗？", "done": false}',
	])
	session, plan = next_question(session, parsed, ai_service=ai)
	assert plan.source == "ai"
	assert plan.reasoning
	assert "AI" in plan.question or "ai" in plan.question.lower() or "Go" in plan.question
	assert session.current_question == plan.question
	assert ai.calls == 1


def test_next_question_requires_ai_without_fallback():
	session = start_interview("main")
	try:
		next_question(session, None, ai_service=None, allow_fallback=False)
	except ProfileInterviewAIError:
		pass
	else:
		raise AssertionError("expected ProfileInterviewAIError")


def test_next_question_fallback_when_allowed():
	session = start_interview("main", max_questions=10)
	session, plan = next_question(session, None, ai_service=None, allow_fallback=True)
	assert plan.source == "fallback"
	assert plan.question


def test_ensure_resume_auto_init(tmp_path: Path):
	store = ResumeStore(tmp_path / "resumes")
	resume, action = _ensure_resume(store, "auto", init=True, import_path=None)
	assert action == "init"
	assert resume.name == "auto"
	assert store.exists("auto")


def test_resume_is_sparse_detects_empty():
	assert _resume_is_sparse(ParsedResume(summary="简历内容为空或为占位文本"))
	assert not _resume_is_sparse(ParsedResume(skills=["Go"], summary="后端开发"))
