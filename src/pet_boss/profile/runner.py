"""User Profile Intelligence System — 一键启动编排。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
from rich.console import Console

from pet_boss.ai.service import AIService
from pet_boss.profile.career_inference import infer_career
from pet_boss.profile.memory import consolidate_memory
from pet_boss.profile.profiling import (
	ProfileInterviewAIError,
	extract_preferences_from_session,
	next_question,
	start_interview,
	submit_answer,
)
from pet_boss.profile.resume_parser import parse_resume
from pet_boss.profile.store import ProfileStore
from pet_boss.resume.models import PersonalInfoSection, ResumeData
from pet_boss.resume.store import ResumeStore

_console = Console(stderr=True)


def _resume_is_sparse(parsed) -> bool:
	if parsed is None:
		return True
	if parsed.skills or parsed.projects or parsed.real_capabilities:
		return False
	summary = (parsed.summary or "").strip()
	return not summary or "为空" in summary or "占位" in summary


def _ensure_resume(
	resume_store: ResumeStore,
	name: str,
	*,
	init: bool,
	import_path: Path | None,
) -> tuple[ResumeData, str | None]:
	"""返回 (简历, 准备动作: import|init|None)。"""
	if import_path is not None:
		return resume_store.import_file(import_path), "import"
	if resume_store.exists(name):
		resume = resume_store.get(name)
		if resume is None:
			raise ValueError(f"简历 '{name}' 读取失败")
		return resume, None
	if init:
		resume = ResumeData(
			name=name,
			title="我的简历",
			center_title=False,
			personal_info=PersonalInfoSection(items=[], layout="inline"),
			job_intention=None,
			modules=[],
			avatar="",
		)
		resume_store.save(resume)
		return resume, "init"
	raise FileNotFoundError(
		f"简历 '{name}' 不存在。请使用 --init 自动创建，或 boss resume init --name {name}"
	)


def _run_interactive_interview(
	*,
	session,
	parsed,
	ai_service: AIService | None,
	allow_fallback: bool,
) -> Any:
	_console.print("\n[bold]Step 2/4 · AI 画像访谈[/bold] [dim](输入 quit 可提前结束)[/dim]\n")
	plan = None
	while not session.completed and session.questions_asked < session.max_questions:
		session, plan = next_question(
			session, parsed,
			ai_service=ai_service,
			allow_fallback=allow_fallback,
		)
		if plan.done or not plan.question:
			session.completed = True
			break
		idx = session.questions_asked + 1
		_console.print(f"[cyan]── 问题 {idx}/{session.max_questions}[/cyan] [dim]({plan.source})[/dim]")
		if plan.reasoning:
			_console.print(f"[dim]💭 {plan.reasoning}[/dim]")
		_console.print(f"[bold yellow]AI:[/bold yellow] {plan.question}\n")
		try:
			answer = click.prompt("你", prompt_suffix=": ")
		except (click.Abort, EOFError):
			session.completed = True
			break
		if answer.strip().lower() in ("quit", "exit", "q", "结束", "退出"):
			session.completed = True
			break
		session = submit_answer(session, answer)
	return session, plan


def run_profile_pipeline(
	*,
	data_dir: Path,
	resume_name: str,
	ai_service: AIService | None,
	init_resume: bool = False,
	import_path: Path | None = None,
	max_questions: int = 8,
	allow_fallback: bool = False,
	skip_interview: bool = False,
) -> dict[str, Any]:
	"""执行 parse → interview → infer 全流程，返回结构化结果。"""
	resume_store = ResumeStore(data_dir / "resumes")
	steps: list[dict[str, Any]] = []

	resume, prepare_action = _ensure_resume(
		resume_store, resume_name, init=init_resume, import_path=import_path,
	)
	if prepare_action:
		steps.append({"step": prepare_action, "status": "ok", "resume": resume_name})

	_console.print("[bold cyan]用户画像智能系统[/bold cyan] 启动中...\n")
	_console.print("[bold]Step 1/4 · 解析简历[/bold]")
	parsed = parse_resume(resume, resume_name=resume_name, ai_service=ai_service)
	sparse = _resume_is_sparse(parsed)
	if sparse:
		_console.print(
			"[yellow]⚠ 简历内容较少，访谈将偏泛；建议事后 boss resume edit 补充经历[/yellow]"
		)
	summary_preview = (parsed.summary or "无摘要")[:60]
	_console.print(
		f"[green]✓[/green] 技能 {len(parsed.skills)} 项 · "
		f"城市 {parsed.city or '未知'} · {summary_preview}"
	)
	steps.append({"step": "parse", "status": "ok", "sparse_resume": sparse})

	with ProfileStore(data_dir) as store:
		store.save_parsed_resume(parsed)
		profile = store.load_profile()
		profile.parsed_resume = parsed

		session = None
		prefs = store.load_preferences()
		if skip_interview and prefs is not None:
			_console.print("\n[dim]跳过访谈（使用已有偏好）[/dim]")
			steps.append({"step": "interview", "status": "skipped"})
		else:
			session = start_interview(resume_name, max_questions=max_questions)
			if ai_service is None and not allow_fallback:
				raise ProfileInterviewAIError(
					"访谈需要 AI，请先：boss ai config --provider deepseek --model deepseek-chat --api-key <key>"
				)
			session, _ = _run_interactive_interview(
				session=session,
				parsed=parsed,
				ai_service=ai_service,
				allow_fallback=allow_fallback,
			)
			prefs = extract_preferences_from_session(session, parsed, ai_service=ai_service)
			store.save_preferences(prefs)
			store.clear_interview_session()
			profile.preferences = prefs
			steps.append({
				"step": "interview",
				"status": "ok",
				"questions_answered": session.questions_asked,
				"transcript_length": len(session.transcript),
			})

		_console.print("\n[bold]Step 3/4 · 职业方向推理[/bold]")
		career = infer_career(parsed, prefs, ai_service=ai_service)
		store.save_career(career)
		profile.career = career
		summary = consolidate_memory(profile, store, ai_service=ai_service)
		profile.memory_summary = summary
		store.save_profile(profile)
		_console.print(f"[green]✓[/green] 主方向: [bold]{career.primary_direction or '待明确'}[/bold]")
		if career.avoid_direction:
			_console.print(f"[dim]  避开: {', '.join(career.avoid_direction[:3])}[/dim]")
		steps.append({"step": "infer", "status": "ok"})

		feedback = store.list_feedback(10)
		weights = store.get_dimension_weights()

	_console.print("\n[bold]Step 4/4 · 完成[/bold]")
	_console.print("[green]✓ 用户画像已就绪[/green]")
	_console.print("[dim]下一步: boss search \"关键词\" --city 城市 --profile-score[/dim]\n")

	return {
		"resume_name": resume_name,
		"steps": steps,
		"parsed_resume": parsed.to_dict(),
		"preferences": prefs.to_dict() if prefs else None,
		"career": career.to_dict(),
		"memory_summary": summary,
		"profile": profile.to_dict(),
		"learning_weights": weights,
		"recent_feedback": feedback,
	}
