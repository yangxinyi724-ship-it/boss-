"""秘书 AI — 简历解析、画像、六维日报、反馈收集。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from pet_boss.agents.analysis_store import day_record_summary
from pet_boss.ai.service import AIService
from pet_boss.cache.store import CacheStore
from pet_boss.profile.models import ParsedResume
from pet_boss.profile.store import ProfileStore
from pet_boss.secretary.config import SecretaryConfigStore
from pet_boss.secretary.email_sender import EmailSendError, send_markdown_email
from pet_boss.secretary.feedback import (
	parse_feedback_to_instructions,
	save_preference_instructions,
)
from pet_boss.secretary.report import render_analysis_daily_markdown
from pet_boss.secretary.resume_intake import (
	intake_resume_pdf,
	intake_resume_text,
)
from pet_boss.secretary.six_dim_score import (
	compile_passed_jobs_with_scores,
	select_daily_picks,
)


def resolve_report_date(value: str | None = None) -> date:
	if not value or value == "yesterday":
		return date.today() - timedelta(days=1)
	return date.fromisoformat(value)


def day_bounds(report_date: date) -> tuple[float, float]:
	start = datetime.combine(report_date, time.min).timestamp()
	end = datetime.combine(report_date + timedelta(days=1), time.min).timestamp()
	return start, end


@dataclass
class SecretaryDutyResult:
	report_date: str
	summary: dict[str, Any] = field(default_factory=dict)
	markdown: str = ""
	jobs_json: list[dict[str, Any]] = field(default_factory=list)
	email: dict[str, Any] = field(default_factory=dict)
	errors: list[str] = field(default_factory=list)


class SecretaryAI:
	"""秘书 AI：简历解析 → 结构化画像 → 六维日报 → 邮件 / 反馈指令。"""

	def __init__(
		self,
		cache: CacheStore,
		config_store: SecretaryConfigStore,
		*,
		data_dir: Path | None = None,
		ai_service: AIService | None = None,
		profile_store: ProfileStore | None = None,
	) -> None:
		self._cache = cache
		self._config_store = config_store
		self._data_dir = data_dir
		self._ai_service = ai_service
		self._profile_store = profile_store

	def parse_resume_pdf(self, path: Path, *, resume_name: str = "") -> dict[str, Any]:
		parsed, portrait = intake_resume_pdf(
			path, resume_name=resume_name, ai_service=self._ai_service,
		)
		return self._persist_intake(parsed, portrait)

	def parse_resume_text(self, text: str, *, resume_name: str = "secretary-intake") -> dict[str, Any]:
		parsed, portrait = intake_resume_text(
			text, resume_name=resume_name, ai_service=self._ai_service,
		)
		return self._persist_intake(parsed, portrait)

	def _persist_intake(self, parsed: ParsedResume, portrait: dict[str, Any]) -> dict[str, Any]:
		if self._profile_store:
			self._profile_store.save_parsed_resume(parsed)
			self._profile_store.save_secretary_portrait(portrait)
			profile = self._profile_store.load_profile()
			profile.parsed_resume = parsed
			self._profile_store.save_profile(profile)
		return {
			"parsed_resume": parsed.to_dict(),
			"portrait": portrait,
			"for_scout": portrait.get("for_scout"),
			"for_analysis": portrait.get("for_analysis"),
		}

	def load_portrait(self) -> dict[str, Any] | None:
		if not self._profile_store:
			return None
		return self._profile_store.load_secretary_portrait()

	def collect_feedback(self, feedback_text: str) -> dict[str, Any]:
		instructions = parse_feedback_to_instructions(
			feedback_text, ai_service=self._ai_service,
		)
		if not self._profile_store:
			return {"instructions": instructions, "persisted": False}
		payload = save_preference_instructions(
			self._profile_store,
			instructions,
			raw_feedback=feedback_text,
		)
		return {"instructions": instructions, "persisted": True, "payload": payload}

	def build_daily_action_plan(self, report_date: date | None = None) -> dict[str, Any]:
		target = report_date or date.today()
		data = self.load_day_data(target)
		learning_logs: list[dict[str, Any]] = []
		shortlist_count = 0
		if self._profile_store:
			learning_logs = self._profile_store.list_preference_learning_logs(limit=12)
		try:
			shortlist_count = len(self._cache.list_shortlist())
		except Exception:
			shortlist_count = 0
		context = {
			"date": data["date"],
			"summary": data.get("summary") or {},
			"daily_picks": data.get("daily_picks") or [],
			"recent_learning": learning_logs[:8],
			"shortlist_count": shortlist_count,
			"portrait": self.load_portrait() or {},
		}
		from pet_boss.agents.planners.daily_action import plan_daily_actions

		plan = plan_daily_actions(self._ai_service, context=context)
		payload = {"generated_at": time.time(), **plan}
		if self._profile_store:
			self._profile_store.save_daily_action_plan(payload)
		return payload

	def load_daily_action_plan(self) -> dict[str, Any] | None:
		if not self._profile_store:
			return None
		return self._profile_store.load_daily_action_plan()

	def load_scout_strategy_plan(self) -> dict[str, Any] | None:
		if not self._profile_store:
			return None
		return self._profile_store.load_scout_strategy_plan()

	def list_report_dates(self, *, limit: int = 120) -> list[dict[str, Any]]:
		return self._cache.list_analysis_days(limit=limit)

	def load_day_data(self, report_date: date) -> dict[str, Any]:
		since, until = day_bounds(report_date)
		passed = self._cache.list_analysis_records(since, until, status="passed")
		filtered = self._cache.list_analysis_records(since, until, status="filtered")
		portrait = self.load_portrait()
		compiled = compile_passed_jobs_with_scores(passed, portrait=portrait)
		config = self._config_store.load()
		report_cfg = config.get("report") or {}
		max_daily_picks = int(report_cfg.get("max_daily_picks") or 5)
		daily_picks = select_daily_picks(compiled, max_count=max_daily_picks)
		jobs_json = []
		for row in compiled:
			job = row.get("job") or row
			jobs_json.append({
				"job_id": job.get("job_id"),
				"title": row.get("title") or job.get("title"),
				"company": row.get("company") or job.get("company"),
				"scores": row.get("scores"),
				"archetype": row.get("archetype"),
				"commentary": row.get("commentary"),
			})
		return {
			"date": report_date.isoformat(),
			"passed": passed,
			"filtered": filtered,
			"compiled_passed": compiled,
			"daily_picks": daily_picks,
			"jobs_json": jobs_json,
			"summary": day_record_summary([*passed, *filtered]),
		}

	def build_report(self, report_date: date) -> dict[str, Any]:
		data = self.load_day_data(report_date)
		markdown = render_analysis_daily_markdown(data)
		if self._data_dir:
			out_dir = self._data_dir / "exports" / "reports"
			out_dir.mkdir(parents=True, exist_ok=True)
			json_path = out_dir / f"daily-report-{data['date']}.json"
			json_path.write_text(
				json.dumps(
					{
						"date": data["date"],
						"jobs": data["jobs_json"],
						"daily_picks": data.get("daily_picks") or [],
						"summary": data["summary"],
					},
					ensure_ascii=False,
					indent=2,
				),
				encoding="utf-8",
			)
			data["json_export_path"] = str(json_path)
		return {"data": data, "markdown": markdown}

	def send_daily_email(
		self,
		report_date: date,
		*,
		markdown: str | None = None,
		dry_run: bool = False,
	) -> dict[str, Any]:
		config = self._config_store.load()
		if dry_run:
			return {
				"sent": False,
				"dry_run": True,
				"to": config.get("recipient_email"),
			}
		if not self._config_store.is_email_configured(config):
			raise EmailSendError(
				"邮件未配置：请在 data/secretary.json 填写 recipient_email 与 smtp"
			)
		if markdown is None:
			markdown = self.build_report(report_date)["markdown"]
		report_cfg = config.get("report") or {}
		prefix = report_cfg.get("title_prefix") or "【AI 办公室】岗位筛选日报"
		subject = f"{prefix} · {report_date.isoformat()}"
		return send_markdown_email(config=config, subject=subject, markdown_body=markdown)

	def run_daily_duties(
		self,
		report_date: date,
		*,
		send_email: bool = True,
		dry_run: bool = False,
	) -> SecretaryDutyResult:
		result = SecretaryDutyResult(report_date=report_date.isoformat())
		report = self.build_report(report_date)
		result.summary = report["data"]["summary"]
		result.markdown = report["markdown"]
		result.jobs_json = report["data"].get("jobs_json") or []

		if send_email:
			try:
				result.email = self.send_daily_email(
					report_date, markdown=result.markdown, dry_run=dry_run,
				)
			except EmailSendError as exc:
				result.errors.append(str(exc))

		return result
