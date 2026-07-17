"""用户画像 Web API 业务层。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pet_boss.ai.config import AIConfigStore
from pet_boss.ai.service import AIService
from pet_boss.ai.token_usage import get_token_usage_store
from pet_boss.profile.career_inference import infer_career
from pet_boss.profile.memory import consolidate_memory
from pet_boss.profile.profiling import (
	ProfileInterviewAIError,
	extract_preferences_from_session,
	next_question,
	start_interview,
	submit_answer,
)
from pet_boss.profile.resume_parser import parse_resume, parse_resume_text
from pet_boss.profile.runner import _resume_is_sparse
from pet_boss.profile.store import ProfileStore
from pet_boss.resume.models import PersonalInfoSection, ResumeData, ResumeModule
from pet_boss.resume.pdf_import import import_resume_from_pdf
from pet_boss.resume.pdf_text import PdfTextExtractError
from pet_boss.resume.store import ResumeStore


class ProfileWebError(Exception):
	def __init__(self, code: str, message: str, *, status: int = 400) -> None:
		super().__init__(message)
		self.code = code
		self.message = message
		self.status = status


class ProfileWebService:
	def __init__(self, data_dir: Path) -> None:
		self._data_dir = data_dir
		self._resume_store = ResumeStore(data_dir / "resumes")

	def _ai_service(self) -> AIService | None:
		from pet_boss.ai.config import resolve_embedding_model, rag_enabled as config_rag_enabled

		store = AIConfigStore(self._data_dir)
		if not store.is_configured():
			return None
		config = store.load_config()
		api_key = store.get_api_key()
		base_url = store.get_base_url()
		if not api_key or not base_url:
			return None
		return AIService(
			base_url=base_url,
			api_key=api_key,
			model=config["ai_model"],
			temperature=config.get("ai_temperature", 0.7),
			max_tokens=config.get("ai_max_tokens", 4096),
			usage_store=get_token_usage_store(self._data_dir),
			embedding_model=resolve_embedding_model(config),
			rag_enabled=config_rag_enabled(config),
		)

	def _resume_pdf_path(self, name: str) -> Path:
		safe_name = name.strip() or "default"
		return self._data_dir / "resumes" / "uploads" / f"{safe_name}.pdf"

	def status(self) -> dict[str, Any]:
		ai_store = AIConfigStore(self._data_dir)
		config = ai_store.load_config()
		with ProfileStore(self._data_dir) as store:
			profile = store.load_profile()
			session = store.load_interview_session()
		resumes: list[dict[str, Any]] = []
		for item in self._resume_store.list_all():
			entry = dict(item)
			resume_name = str(entry.get("name") or "default").strip() or "default"
			entry["has_pdf"] = self._resume_pdf_path(resume_name).is_file()
			resumes.append(entry)
		return {
			"ai_configured": ai_store.is_configured(),
			"ai_provider": config.get("ai_provider"),
			"ai_model": config.get("ai_model"),
			"resumes": resumes,
			"has_parsed_resume": profile.parsed_resume is not None,
			"has_preferences": profile.preferences is not None,
			"has_career": profile.career is not None,
			"interview_active": bool(session and not session.completed),
		}

	def upload_pdf(
		self,
		pdf_bytes: bytes,
		*,
		filename: str,
		name: str,
		title: str = "",
		auto_parse: bool = True,
	) -> dict[str, Any]:
		if not pdf_bytes:
			raise ProfileWebError("INVALID_PARAM", "PDF 文件为空")
		if not filename.lower().endswith(".pdf"):
			raise ProfileWebError("INVALID_PARAM", "仅支持 .pdf 格式")

		safe_name = name.strip() or "default"
		pdf_path = self._resume_pdf_path(safe_name)
		pdf_path.parent.mkdir(parents=True, exist_ok=True)
		pdf_path.write_bytes(pdf_bytes)

		try:
			resume, extracted_text = import_resume_from_pdf(
				pdf_path, name=safe_name, title=title.strip(),
			)
		except PdfTextExtractError as exc:
			raise ProfileWebError("PDF_EXTRACT_FAILED", str(exc), status=422) from exc
		except ImportError as exc:
			raise ProfileWebError("DEPENDENCY_MISSING", str(exc), status=503) from exc

		self._resume_store.save(resume)
		result: dict[str, Any] = {
			"name": safe_name,
			"title": resume.title,
			"pdf_saved": str(pdf_path),
			"text_length": len(extracted_text),
			"text_preview": extracted_text[:500],
		}

		if auto_parse:
			parsed = parse_resume_text(
				extracted_text, resume_name=safe_name, ai_service=self._ai_service(),
			)
			with ProfileStore(self._data_dir) as store:
				store.save_parsed_resume(parsed)
				profile = store.load_profile()
				profile.parsed_resume = parsed
				store.save_profile(profile)
			result["parsed"] = parsed.to_dict()
			result["sparse_resume"] = _resume_is_sparse(parsed)

		return result

	def save_resume(self, *, name: str, title: str, content: str) -> dict[str, Any]:
		name = name.strip()
		if not name:
			raise ProfileWebError("INVALID_PARAM", "简历名称不能为空")
		modules: list[ResumeModule] = []
		body = content.strip()
		if body:
			modules.append(ResumeModule(
				id="experience",
				title="经历与技能",
				rows=[{"type": "richtext", "columns": 1, "content": [body]}],
			))
		resume = ResumeData(
			name=name,
			title=title.strip() or "我的简历",
			personal_info=PersonalInfoSection(items=[], layout="inline"),
			modules=modules,
		)
		self._resume_store.save(resume)
		return {"name": name, "title": resume.title, "saved": True}

	def delete_resume(self, name: str) -> dict[str, Any]:
		safe_name = name.strip() or "default"
		deleted_file = self._resume_store.delete(safe_name)
		pdf_path = self._resume_pdf_path(safe_name)
		pdf_path.unlink(missing_ok=True)

		cleared_parsed = False
		with ProfileStore(self._data_dir) as store:
			profile = store.load_profile()
			parsed = profile.parsed_resume
			if parsed is not None:
				source = parsed.source_resume or ""
				if not source or source == safe_name:
					profile.parsed_resume = None
					cleared_parsed = True
					(self._data_dir / "profile" / "parsed_resume.json").unlink(missing_ok=True)
					store.save_profile(profile)

		if not deleted_file and not cleared_parsed:
			raise ProfileWebError(
				"RESUME_NOT_FOUND",
				f"简历 '{safe_name}' 不存在",
				status=404,
			)
		return {"name": safe_name, "deleted": True}

	def get_resume_pdf_path(self, name: str) -> Path:
		safe_name = name.strip() or "default"
		pdf_path = self._resume_pdf_path(safe_name)
		if not pdf_path.is_file():
			raise ProfileWebError(
				"RESUME_NOT_FOUND",
				f"简历 PDF '{safe_name}' 不存在",
				status=404,
			)
		return pdf_path

	def parse_resume(self, resume_name: str) -> dict[str, Any]:
		resume = self._resume_store.get(resume_name)
		if resume is None:
			raise ProfileWebError("RESUME_NOT_FOUND", f"简历 '{resume_name}' 不存在", status=404)
		parsed = parse_resume(resume, resume_name=resume_name, ai_service=self._ai_service())
		with ProfileStore(self._data_dir) as store:
			store.save_parsed_resume(parsed)
			profile = store.load_profile()
			profile.parsed_resume = parsed
			store.save_profile(profile)
		return {
			"parsed": parsed.to_dict(),
			"sparse_resume": _resume_is_sparse(parsed),
		}

	def interview_start(self, *, resume_name: str, max_questions: int = 8) -> dict[str, Any]:
		with ProfileStore(self._data_dir) as store:
			parsed = store.load_parsed_resume()
			if parsed is None:
				raise ProfileWebError(
					"PROFILE_INCOMPLETE", "请先解析简历",
					status=400,
				)
			ai = self._ai_service()
			if ai is None:
				raise ProfileWebError(
					"AI_NOT_CONFIGURED",
					"请先配置 AI：boss ai config --provider deepseek --model deepseek-chat --api-key <key>",
					status=503,
				)
			session = start_interview(resume_name, max_questions=max_questions)
			session, plan = next_question(session, parsed, ai_service=ai)
			store.save_interview_session(session)
		return self._question_payload(session, plan)

	def interview_answer(self, answer: str) -> dict[str, Any]:
		text = answer.strip()
		if not text:
			raise ProfileWebError("INVALID_PARAM", "回答不能为空")
		with ProfileStore(self._data_dir) as store:
			session = store.load_interview_session()
			if session is None:
				raise ProfileWebError("INVALID_PARAM", "无进行中的访谈", status=400)
			parsed = store.load_parsed_resume()
			ai = self._ai_service()
			if not session.current_question:
				session, plan = next_question(session, parsed, ai_service=ai)
				if plan.question is None:
					session.completed = True
					store.save_interview_session(session)
					return {"completed": True, "message": "访谈已结束"}
			session = submit_answer(session, text)
			next_plan = None
			if not session.completed and session.questions_asked < session.max_questions:
				session, next_plan = next_question(session, parsed, ai_service=ai)
			else:
				session.completed = True
			store.save_interview_session(session)
		result: dict[str, Any] = {
			"answered": text,
			"completed": session.completed,
			"progress": f"{session.questions_asked}/{session.max_questions}",
			"transcript": session.transcript,
		}
		if next_plan is not None:
			result.update({
				"question": next_plan.question,
				"reasoning": next_plan.reasoning,
				"topic": next_plan.topic,
				"source": next_plan.source,
			})
		return result

	def interview_current(self) -> dict[str, Any]:
		with ProfileStore(self._data_dir) as store:
			session = store.load_interview_session()
			if session is None:
				return {"active": False}
			return {
				"active": not session.completed,
				"progress": f"{session.questions_asked}/{session.max_questions}",
				"question": session.current_question,
				"reasoning": session.last_reasoning,
				"topic": session.current_topic,
				"source": session.question_source,
				"transcript": session.transcript,
				"completed": session.completed,
			}

	def interview_finish(self) -> dict[str, Any]:
		with ProfileStore(self._data_dir) as store:
			session = store.load_interview_session()
			if session is None:
				raise ProfileWebError("INVALID_PARAM", "无进行中的访谈")
			session.completed = True
			parsed = store.load_parsed_resume()
			prefs = extract_preferences_from_session(session, parsed, ai_service=self._ai_service())
			store.save_preferences(prefs)
			store.clear_interview_session()
			profile = store.load_profile()
			profile.preferences = prefs
			store.save_profile(profile)
		return {"preferences": prefs.to_dict()}

	def infer(self) -> dict[str, Any]:
		with ProfileStore(self._data_dir) as store:
			parsed = store.load_parsed_resume()
			if parsed is None:
				raise ProfileWebError("PROFILE_INCOMPLETE", "请先解析简历")
			prefs = store.load_preferences()
			career = infer_career(parsed, prefs, ai_service=self._ai_service())
			store.save_career(career)
			profile = store.load_profile()
			profile.career = career
			summary = consolidate_memory(profile, store, ai_service=self._ai_service())
			profile.memory_summary = summary
			store.save_profile(profile)
		return {
			"career": career.to_dict(),
			"memory_summary": summary,
		}

	def get_profile(self) -> dict[str, Any]:
		with ProfileStore(self._data_dir) as store:
			profile = store.load_profile()
			feedback = store.list_feedback(20)
			weights = store.get_dimension_weights()
			ai_memory = store.list_ai_memory(limit=12)
		return {
			"profile": profile.to_dict(),
			"recent_feedback": feedback,
			"learning_weights": weights,
			"ai_memory": ai_memory,
		}

	def reset(self) -> dict[str, Any]:
		profile_dir = self._data_dir / "profile"
		for name in (
			"parsed_resume.json", "preferences.json", "career_direction.json",
			"interview_session.json", "user_profile.json",
		):
			(profile_dir / name).unlink(missing_ok=True)
		return {"message": "画像数据已清除"}

	@staticmethod
	def _question_payload(session, plan) -> dict[str, Any]:
		return {
			"question": plan.question,
			"reasoning": plan.reasoning,
			"topic": plan.topic,
			"source": plan.source,
			"completed": session.completed,
			"progress": f"{session.questions_asked}/{session.max_questions}",
		}
