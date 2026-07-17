"""Step 2: Interactive User Profiling — 交互式画像访谈。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pet_boss.ai.service import AIService
from pet_boss.profile.models import InterviewSession, ParsedResume, UserPreferences
from pet_boss.profile.prompts import INTERVIEW_EXTRACT_PREFERENCES_PROMPT, INTERVIEW_NEXT_QUESTION_PROMPT

# 仅在没有配置 AI 时的兜底题库（配置 AI 后不会使用）
_FALLBACK_QUESTIONS: list[tuple[str, str]] = [
	("role_preference", "你更倾向做纯技术、技术+产品，还是偏运营/业务方向？"),
	("salary_vs_growth", "现阶段你更看重薪资回报，还是成长空间？可以二选一或说平衡。"),
	("overtime_tolerance", "对加班的接受度如何？完全不接受、偶尔可以，还是项目紧可以配合？"),
	("startup_fit", "你是否愿意加入创业公司或早期团队？"),
	("remote_ok", "是否接受远程或 hybrid 办公？"),
	("ai_app_vs_core", "如果做 AI 相关，你更想做应用层（Agent/工作流）还是底层（训练/推理）？"),
	("product_vs_engineering", "你更希望偏产品定义，还是偏工程实现？"),
	("career_change_ok", "是否接受一定程度的转行或新领域？"),
	("stability_priority", "对稳定性要求高吗？比如大厂/已上市 vs 高成长初创。"),
	("job_seeking_stage", "你现在的求职阶段是？随便看看、积极找、还是 urgent 换工作？"),
]

_INTERVIEW_SYSTEM_PROMPT = (
	"你是资深职业顾问。先在 reasoning 中分析已知信息与盲区，再提出一个自然的中文问题。"
	"只输出 JSON，不要 markdown。"
)


class ProfileInterviewAIError(Exception):
	"""AI 生成访谈问题时失败。"""


@dataclass
class NextQuestionResult:
	"""下一个访谈问题的规划结果。"""

	question: str | None
	reasoning: str = ""
	topic: str = ""
	done: bool = False
	source: str = "ai"  # ai | fallback


def _transcript_text(transcript: list[dict[str, str]]) -> str:
	if not transcript:
		return "（尚无对话，这是第一个问题）"
	lines = []
	for turn in transcript:
		q = turn.get("question", "")
		a = turn.get("answer", "")
		topic = turn.get("topic", "")
		if q:
			prefix = f"[{topic}] " if topic else ""
			lines.append(f"Q: {prefix}{q}")
		if a:
			lines.append(f"A: {a}")
	return "\n".join(lines)


def _strip_json_fence(text: str) -> str:
	text = text.strip()
	if text.startswith("```"):
		text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```")).strip()
	return text


def _parse_ai_question_payload(raw: str) -> dict[str, Any]:
	data = json.loads(_strip_json_fence(raw))
	if not isinstance(data, dict):
		raise ValueError("AI 返回非对象 JSON")
	return data


def start_interview(resume_name: str, *, max_questions: int = 10) -> InterviewSession:
	return InterviewSession(
		resume_name=resume_name,
		questions_asked=0,
		max_questions=min(max(max_questions, 5), 15),
		completed=False,
		current_question="",
		transcript=[],
	)


def _next_fallback_question(session: InterviewSession) -> NextQuestionResult:
	asked_topics = {t.get("topic", "") for t in session.transcript}
	for topic, question in _FALLBACK_QUESTIONS:
		if topic not in asked_topics and session.questions_asked < session.max_questions:
			return NextQuestionResult(
				question=question,
				topic=topic,
				reasoning="（未配置 AI，使用预设兜底问题）",
				source="fallback",
			)
	return NextQuestionResult(question=None, done=True, source="fallback")


def _plan_next_question_with_ai(
	ai_service: AIService,
	session: InterviewSession,
	parsed: ParsedResume | None,
) -> NextQuestionResult:
	parsed_json = json.dumps(parsed.to_dict() if parsed else {}, ensure_ascii=False, indent=2)
	prompt = INTERVIEW_NEXT_QUESTION_PROMPT.format(
		questions_asked=session.questions_asked,
		max_questions=session.max_questions,
		parsed_resume_json=parsed_json,
		transcript=_transcript_text(session.transcript),
	)
	last_error: Exception | None = None
	for _ in range(2):
		try:
			raw = ai_service.chat(
				[
					{"role": "system", "content": _INTERVIEW_SYSTEM_PROMPT},
					{"role": "user", "content": prompt},
				],
				temperature=0.5,
				agent="MS",
			)
			data = _parse_ai_question_payload(raw)
			if data.get("done"):
				return NextQuestionResult(
					question=None,
					reasoning=str(data.get("reasoning") or ""),
					done=True,
					source="ai",
				)
			question = str(data.get("question") or "").strip()
			if not question:
				raise ValueError("AI 未返回有效 question")
			return NextQuestionResult(
				question=question,
				reasoning=str(data.get("reasoning") or ""),
				topic=str(data.get("topic") or ""),
				source="ai",
			)
		except Exception as exc:
			last_error = exc
	raise ProfileInterviewAIError(str(last_error) if last_error else "AI 生成问题失败")


def _apply_question_plan(session: InterviewSession, plan: NextQuestionResult) -> InterviewSession:
	if plan.done or not plan.question:
		session.completed = True
		session.current_question = ""
		session.current_topic = ""
		session.last_reasoning = plan.reasoning
		session.question_source = plan.source
		return session
	session.current_question = plan.question
	session.current_topic = plan.topic
	session.last_reasoning = plan.reasoning
	session.question_source = plan.source
	return session


def next_question(
	session: InterviewSession,
	parsed: ParsedResume | None,
	*,
	ai_service: AIService | None = None,
	allow_fallback: bool = False,
) -> tuple[InterviewSession, NextQuestionResult]:
	"""生成下一个问题。配置 AI 时由 AI 思考后提问；未配置且 allow_fallback 时用兜底题库。"""
	if session.completed or session.questions_asked >= session.max_questions:
		session.completed = True
		session.current_question = ""
		return session, NextQuestionResult(question=None, done=True)

	if ai_service is not None:
		plan = _plan_next_question_with_ai(ai_service, session, parsed)
	elif allow_fallback:
		plan = _next_fallback_question(session)
	else:
		raise ProfileInterviewAIError(
			"访谈需要 AI 动态提问，请先配置：boss ai config --provider deepseek --model deepseek-chat --api-key <key>"
		)

	session = _apply_question_plan(session, plan)
	return session, plan


def submit_answer(session: InterviewSession, answer: str) -> InterviewSession:
	if not session.current_question:
		return session
	session.transcript.append({
		"topic": session.current_topic or f"q{session.questions_asked + 1}",
		"question": session.current_question,
		"answer": answer.strip(),
		"reasoning": session.last_reasoning,
	})
	session.questions_asked += 1
	session.current_question = ""
	session.current_topic = ""
	return session


def _parse_bool_answer(text: str) -> bool | None:
	lower = text.lower()
	if any(w in lower for w in ("是", "愿意", "可以", "yes", "ok", "接受")):
		if any(w in lower for w in ("不", "否", "no")):
			return False
		return True
	if any(w in lower for w in ("不", "否", "no", "拒绝")):
		return False
	return None


def extract_preferences_heuristic(session: InterviewSession) -> UserPreferences:
	prefs = UserPreferences(interview_transcript=session.transcript)
	for turn in session.transcript:
		q = turn.get("question", "")
		a = turn.get("answer", "")
		topic = turn.get("topic", "")
		if topic == "role_preference" or "技术" in q or "运营" in q:
			prefs.role_preference = a
		elif topic == "salary_vs_growth" or "薪资" in q or "成长" in q:
			prefs.salary_vs_growth = a
		elif topic == "overtime_tolerance" or "加班" in q:
			prefs.overtime_tolerance = a
		elif topic == "startup_fit" or "创业" in q or "初创" in q:
			prefs.startup_fit = _parse_bool_answer(a)
		elif topic == "remote_ok" or "远程" in q:
			prefs.remote_ok = _parse_bool_answer(a)
		elif topic == "ai_app_vs_core" or "AI" in q:
			prefs.ai_app_vs_core = a
		elif topic == "product_vs_engineering" or ("产品" in q and "工程" in q):
			prefs.product_vs_engineering = a
		elif topic == "career_change_ok" or "转行" in q:
			prefs.career_change_ok = _parse_bool_answer(a)
		elif topic == "stability_priority" or "稳定" in q:
			prefs.stability_priority = a
		elif topic == "job_seeking_stage" or "求职阶段" in q or "阶段" in q:
			prefs.job_seeking_stage = "active"
	return prefs


def extract_preferences_from_session(
	session: InterviewSession,
	parsed: ParsedResume | None,
	*,
	ai_service: AIService | None = None,
) -> UserPreferences:
	if ai_service is not None and session.transcript:
		try:
			prompt = INTERVIEW_EXTRACT_PREFERENCES_PROMPT.format(
				resume_summary=parsed.summary if parsed else "",
				transcript=_transcript_text(session.transcript),
			)
			raw = ai_service.chat([
				{"role": "system", "content": "只输出 JSON。"},
				{"role": "user", "content": prompt},
			], agent="MS")
			data = json.loads(_strip_json_fence(raw))
			prefs = UserPreferences.from_dict(data)
			prefs.interview_transcript = session.transcript
			return prefs
		except Exception:
			pass
	return extract_preferences_heuristic(session)
