"""BOSS 直聘 Web 集成 — 搜索、登录态、画像评分、候选池。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from threading import Event
from typing import Any

from pet_boss.ai.config import AIConfigStore
from pet_boss.ai.service import AIService
from pet_boss.api.client import BossClient
from pet_boss.evaluation.models import CareerStageSettings
from pet_boss.auth.health import assess_auth_health
from pet_boss.auth.manager import AuthManager, AuthRequired
from pet_boss.auth.token_store import TokenStore
from pet_boss.cache.store import CacheStore
from pet_boss.index_cache import try_save_index
from pet_boss.output import Logger
from pet_boss.platforms import get_platform
from pet_boss.agents.analysis_ai import resolve_analysis_filter_reason
from pet_boss.agents.monitor_ai import MonitorAI
from pet_boss.ai.token_usage import get_token_usage_store
from pet_boss.agents.pipeline import iter_dual_agent_pipeline
from pet_boss.web.work_schedule import (
	load_scout_query_exhaust_cooldown_hours,
	load_scout_query_pass_depth,
	load_work_schedule_periods,
)
from pet_boss.agents.scout_memory import record_scout_outcome
from pet_boss.agents.scout_hard_filter import ScoutFilterConfig
from pet_boss.profile.learning import apply_feedback_learning
from pet_boss.profile.reject_learning import clear_reject_learning_memory, process_reject_with_learning
from pet_boss.profile.store import ProfileStore
from pet_boss.search_filters import SearchFilterCriteria
from pet_boss.api.endpoints import CITY_CODES
from pet_boss.api.regions import city_code_map, load_region_tree, resolve_location
from pet_boss.web.profile_api import ProfileWebError


_POPULAR_CITIES = [
	"北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "苏州",
	"东莞", "佛山", "中山", "珠海", "惠州",
]


def _ai_service(data_dir: Path) -> AIService | None:
	from pet_boss.ai.config import (
		resolve_embedding_base_url,
		resolve_embedding_model,
		rag_enabled as config_rag_enabled,
	)
	from pet_boss.ai.token_usage import get_token_usage_store

	store = AIConfigStore(data_dir)
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
		usage_store=get_token_usage_store(data_dir),
		embedding_model=resolve_embedding_model(config),
		embedding_base_url=resolve_embedding_base_url(config),
		embedding_api_key=store.get_embedding_api_key(),
		rag_enabled=config_rag_enabled(config),
	)


def _parse_career_stage(payload: dict[str, Any] | None) -> CareerStageSettings:
	if not isinstance(payload, dict):
		return CareerStageSettings()
	return CareerStageSettings.from_payload(payload)


def _resolve_scout_start_page(requested: int) -> int:
	"""调试：环境变量 BOSS_SCOUT_START_PAGE 可强制起始页（如直接测 page=6）。"""
	import os

	raw = os.environ.get("BOSS_SCOUT_START_PAGE", "").strip()
	if raw.isdigit():
		return max(1, int(raw))
	return max(1, int(requested))


class BossWebService:
	def __init__(self, data_dir: Path) -> None:
		self._data_dir = data_dir
		self._logger = Logger(level="error")

	def auth_status(self, *, sync: bool = False) -> dict[str, Any]:
		"""返回 BOSS 登录态。sync=True 时在线校验（与搜岗/侦察同一套 ensure_session 逻辑）。"""
		auth_dir = self._data_dir / "auth"
		session_path = auth_dir / "session.enc"
		persisted = session_path.exists()
		auth = AuthManager(self._data_dir, logger=self._logger, platform="zhipin")
		persisted_token = auth.check_status()
		session_load_failed = persisted and persisted_token is None

		if sync:
			token, verified = auth.resolve_session(try_browser=True)
		else:
			token = persisted_token
			verified = False

		health = assess_auth_health(self._data_dir, platform="zhipin", token=token)
		cookies = token.get("cookies", {}) if isinstance(token, dict) else {}
		has_wt2 = bool(cookies.get("wt2")) if isinstance(cookies, dict) else False
		if sync:
			logged_in = verified and has_wt2
		else:
			logged_in = bool(persisted and not session_load_failed and has_wt2)
		session_stale = persisted and not logged_in

		session_age_hours: float | None = None
		if session_path.exists():
			import time
			session_age_hours = max(0.0, (time.time() - session_path.stat().st_mtime) / 3600)

		if logged_in:
			if verified:
				login_hint = "登录态已加密保存在本地，下次打开会自动恢复"
			else:
				login_hint = "本地登录态有效（未在线验证，开始搜岗时会自动校验）"
		elif session_load_failed:
			login_hint = (
				"本地登录态文件无法解密（可能换了机器或密钥损坏），"
				"请重新登录；也可设置环境变量 BOSS_AGENT_MACHINE_ID 固定密钥"
			)
		elif session_stale:
			login_hint = (
				"本地登录态已失效或无法验证，请点击「从浏览器同步」"
				"（需浏览器已登录 zhipin.com）或重新登录"
			)
		else:
			login_hint = "点击下方「登录 BOSS 直聘」或「从浏览器同步」；也可在终端执行 boss login"

		return {
			"logged_in": logged_in,
			"verified": verified,
			"session_stale": session_stale,
			"session_load_failed": session_load_failed,
			"persisted": persisted,
			"session_path": str(session_path),
			"auth_state": health.auth_state,
			"auth_summary": health.summary,
			"session_age_hours": round(session_age_hours, 1) if session_age_hours is not None else None,
			"login_hint": login_hint,
			"platform": "zhipin",
		}

	def login(self, *, timeout: int = 120) -> dict[str, Any]:
		"""扫码/Cookie 登录并持久化到本地 session.enc。"""
		auth = AuthManager(self._data_dir, logger=Logger(level="info"), platform="zhipin")
		token = auth.login(timeout=timeout)
		method = token.pop("_method", "未知")
		return {
			"message": f"登录成功（{method}），登录态已保存",
			"method": method,
			"persisted": True,
		}

	def sync_from_browser(self) -> dict[str, Any]:
		"""从本地 Chrome/Edge 等浏览器同步 BOSS Cookie，无需重新扫码。"""
		auth = AuthManager(self._data_dir, logger=Logger(level="info"), platform="zhipin")
		try:
			token = auth.ensure_session(try_browser=True)
		except AuthRequired as exc:
			raise ProfileWebError(
				"AUTH_REQUIRED",
				"未能从浏览器同步登录态，请先在浏览器登录 zhipin.com 或点击「登录 BOSS 直聘」",
				status=401,
			) from exc
		health = assess_auth_health(self._data_dir, platform="zhipin", token=token)
		return {
			"message": "已从本地浏览器同步登录态",
			"auth_state": health.auth_state,
			"persisted": True,
		}

	def logout(self) -> dict[str, Any]:
		AuthManager(self._data_dir, logger=self._logger, platform="zhipin").logout()
		return {"message": "已退出登录，本地保存的登录态已清除"}

	def list_cities(self) -> list[str]:
		"""返回可选城市：热门城市优先，其余按拼音顺序追加（含地区树全部城市）。"""
		all_cities = set(CITY_CODES) | set(city_code_map())
		popular = [c for c in _POPULAR_CITIES if c in all_cities]
		rest = sorted(c for c in all_cities if c not in popular)
		return popular + rest

	def list_regions(self) -> list[dict[str, Any]]:
		"""返回省 → 市 → 区三级地区树。"""
		return load_region_tree()

	def stream_search_jobs(
		self,
		*,
		query: str,
		city: str | None = None,
		city_code: str | None = None,
		district_code: str | None = None,
		page: int = 1,
		scout_filters: dict[str, bool] | list[str] | None = None,
		pass_score: int = 60,
		career_stage: dict[str, Any] | None = None,
		stop_event: Event | None = None,
		pause_event: Event | None = None,
		auto_keywords: bool = True,
		keywords_only: bool = False,
	) -> Iterator[dict[str, Any]]:
		"""流式侦察：逐页搜索、逐岗输出进度事件（供 SSE 使用）。"""
		page = _resolve_scout_start_page(page)
		query = query.strip()
		if not query and not auto_keywords:
			raise ProfileWebError("INVALID_PARAM", "请输入搜索关键词，或开启自动搜索词")

		resolved = resolve_location(
			city=city,
			city_code=city_code,
			district_code=district_code,
		)
		resolved_city = resolved.city_name or (city.strip() if city else None)
		resolved_city_code = resolved.city_code or (str(city_code).strip() if city_code else None)
		resolved_district_code = resolved.district_code or (str(district_code).strip() if district_code else None)

		if resolved_city in ("选择城市", "先选省份"):
			resolved_city = None

		if resolved_city or resolved_city_code:
			from pet_boss.api.regions import city_name_by_code

			name_map = city_name_by_code()
			code_map = city_code_map()
			if resolved_city_code and resolved_city_code not in name_map and resolved_city_code not in set(CITY_CODES.values()):
				raise ProfileWebError("INVALID_PARAM", f"未知城市码: {resolved_city_code}")
			if resolved_city and resolved_city not in code_map and resolved_city not in CITY_CODES and not resolved_city_code:
				raise ProfileWebError("INVALID_PARAM", f"未知城市: {resolved_city}")
			if not resolved_city and resolved_city_code:
				resolved_city = name_map.get(resolved_city_code) or resolved_city
			if resolved_city and not resolved_city_code:
				resolved_city_code = code_map.get(resolved_city) or CITY_CODES.get(resolved_city)

		pass_score = max(0, min(100, pass_score))
		stage_settings = _parse_career_stage(career_stage)
		filters = ScoutFilterConfig.from_payload(scout_filters)

		auth = AuthManager(self._data_dir, logger=self._logger, platform="zhipin")
		_, verified = auth.resolve_session(try_browser=True)
		if not verified:
			raise ProfileWebError(
				"AUTH_REQUIRED",
				"BOSS 登录态无效或已过期，请点击「从浏览器同步」或「登录 BOSS 直聘」",
				status=401,
			)

		client = BossClient(auth, delay=(0.5, 2.0))
		client._dispatch_browser = True
		scout_log = Logger(level="info")
		try:
			from pet_boss.web.browser_executor import run_browser_blocking

			run_browser_blocking(lambda: client._get_browser()._ensure_started())

			platform_cls = get_platform("zhipin")

			with CacheStore(self._data_dir / "cache" / "boss_agent.db") as cache:
				with ProfileStore(self._data_dir) as pstore:
					profile = pstore.load_profile()
					if profile.parsed_resume is None:
						raise ProfileWebError(
							"PROFILE_INCOMPLETE",
							"请先完成用户画像（上传简历 → 秘书解析 → 访谈）",
							status=400,
						)
					from pet_boss.agents.scout_search_strategy import resolve_scout_search_plan

					plan = resolve_scout_search_plan(
						profile,
						pstore,
						user_query=query,
						auto_keywords=auto_keywords,
						keywords_only=keywords_only,
						ai_service=_ai_service(self._data_dir),
					)
					search_queries = plan.get("queries") or []
					if not search_queries:
						raise ProfileWebError(
							"INVALID_PARAM",
							"无法生成搜索词：请手动输入关键词，或先执行秘书简历解析",
						)
					existing = pstore.load_secretary_portrait() or {}
					pstore.save_secretary_portrait({**existing, "last_search_plan": plan})
					base_query = search_queries[0]
					criteria = SearchFilterCriteria(
						query=base_query,
						city=resolved_city,
						city_code=resolved_city_code,
						district_code=resolved_district_code or None,
					)
					# 用户手动输入关键词开搜：清掉该词冷却，避免误判「扫完」后锁 48 小时
					if str(query or "").strip():
						cache.clear_scout_query_exhausted_one(str(query).strip(), resolved_city)
					depth_min, depth_max = load_scout_query_pass_depth()
					cooldown_hours = load_scout_query_exhaust_cooldown_hours()
					with platform_cls(client) as platform:
						passed_jobs: list[dict[str, Any]] = []
						if pause_event is None:
							pause_event = Event()

						def _restart_scout_browser() -> dict[str, Any]:
							restart_fn = getattr(client, "restart_browser", None)
							if callable(restart_fn):
								outcome = restart_fn()
								if isinstance(outcome, dict):
									return outcome
							return {"ok": False, "launch_ok": False, "error": "restart_browser 不可用"}

						def _focus_scout_browser(*, url: str = "") -> None:
							from pet_boss.agents.monitor_ai import BOSS_JOB_URL

							target = url or BOSS_JOB_URL
							focus_fn = getattr(client, "focus_automation_browser", None)
							if callable(focus_fn):
								ok = focus_fn(url=target)
								if ok:
									scout_log.info("[boss-browser] 已聚焦自动化 Chromium 窗口（非 Edge）")
									return
							scout_log.info(
								f"[boss-browser] 请到自动化 Chromium 窗口查看（登录态在此，勿用 Edge）：{target}"
							)

						monitor = MonitorAI(
							self._data_dir,
							stop_event=stop_event,
							pause_event=pause_event,
							usage_store=get_token_usage_store(self._data_dir),
							browser_restart_fn=_restart_scout_browser,
							browser_open_fn=_focus_scout_browser,
						)
						yield {
							"type": "monitor_start",
							"state": "watching",
							"message": "监控 AI 已启动，实时监测侦察运行状况",
						}
						pipeline = iter_dual_agent_pipeline(
							platform, cache, Logger(level="info"),
							criteria=criteria,
							profile=profile,
							store=pstore,
							ai_service=_ai_service(self._data_dir),
							start_page=page,
							scout_filters=filters,
							pass_score=pass_score,
							career_stage=stage_settings,
							stop_event=stop_event,
							pause_event=pause_event,
							continuous=True,
							search_queries=search_queries,
							work_schedule_periods=load_work_schedule_periods(),
							query_pass_depth_min=depth_min,
							query_pass_depth_max=depth_max,
							query_exhaust_cooldown_sec=cooldown_hours * 3600,
						)
						from pet_boss.observability import record_scout_event

						for event in pipeline:
							record_scout_event(self._data_dir, event)
							for aux in monitor.drain_auxiliary_events():
								yield aux
							if event.get("type") == "job_passed" and event.get("job"):
								passed_jobs.append(event["job"])
							for out in monitor.wrap_event(event):
								yield out
							for aux in monitor.drain_auxiliary_events():
								yield aux
							if stop_event and stop_event.is_set():
								scout_log.info(
									"[scout] 搜岗管道收到停止信号（Web 断开 / 用户停止 / SSE 消费停滞），正在退出…"
								)
								yield {
									"type": "stopped",
									"message": "搜岗已停止（Web 连接断开、用户手动停止或前端消费停滞）",
									"jobs": passed_jobs,
								}
								break
						if passed_jobs:
							try_save_index(
								self._data_dir, passed_jobs,
								source=f"web-scout:{base_query}",
								logger=self._logger,
							)
						yield {
							"type": "monitor_stopped",
							"state": "stopped",
							"message": "监控 AI：搜岗结束",
						}
					yield {
						"type": "boss_browser_closed",
						"message": "搜岗结束，已关闭 BOSS 页面",
					}
		finally:
			client.close_browser_session()

	def shortlist_job(
		self,
		*,
		security_id: str,
		job_id: str,
		title: str = "",
		company: str = "",
		city: str = "",
		salary: str = "",
	) -> dict[str, Any]:
		job = {
			"security_id": security_id,
			"job_id": job_id,
			"title": title,
			"company": company,
			"city": city,
			"salary": salary,
		}
		with CacheStore(self._data_dir / "cache" / "boss_agent.db") as cache:
			cache.add_shortlist({
				**job,
				"source": "web-profile",
			})
			record_scout_outcome(cache, job, "shortlisted")
		with ProfileStore(self._data_dir) as store:
			store.record_feedback(
				security_id=security_id,
				job_id=job_id,
				action="shortlisted",
				title=title,
				company=company,
			)
			learning = apply_feedback_learning(
				store, "shortlisted", title=title, company=company,
			)
		return {"shortlisted": True, "learning_weights": learning.weights}

	def list_shortlist(self) -> dict[str, Any]:
		with CacheStore(self._data_dir / "cache" / "boss_agent.db") as cache:
			items = cache.list_shortlist()
		return {"items": items, "total": len(items)}

	def list_filtered_analysis(self, *, limit: int = 200) -> dict[str, Any]:
		"""分析 AI 筛掉的岗位（资料柜）。"""
		from pet_boss.rag.service import rag_miss_message_for_display
		from pet_boss.rag.vector_store import VectorStore

		with ProfileStore(self._data_dir) as pstore:
			vector_count = VectorStore(pstore._conn).count()
		with CacheStore(self._data_dir / "cache" / "boss_agent.db") as cache:
			rows = cache.list_recent_analysis_records(status="filtered", limit=limit)
		items = []
		for row in rows:
			job = row.get("job") if isinstance(row.get("job"), dict) else {}
			refs = list(job.get("rag_references") or [])[:8]
			rag_meta = job.get("rag_meta") if isinstance(job.get("rag_meta"), dict) else {}
			items.append({
				"id": row.get("id"),
				"security_id": row.get("security_id") or job.get("security_id") or "",
				"job_id": row.get("job_id") or job.get("job_id") or "",
				"title": row.get("title") or job.get("title") or "",
				"company": row.get("company") or job.get("company") or "",
				"city": row.get("city") or job.get("city") or "",
				"salary": row.get("salary") or job.get("salary") or "",
				"analysis_score": row.get("analysis_score") or job.get("analysis_score") or 0,
				"filter_reason": resolve_analysis_filter_reason(job),
				"analysis_risk": list(job.get("analysis_risk") or job.get("profile_risk") or [])[:4],
				"rag_references": refs,
				"rag_meta": rag_meta,
				"rag_miss_message": rag_miss_message_for_display(
					references=refs,
					rag_meta=rag_meta,
					current_vector_count=vector_count,
				),
				"analysis_review_plan": job.get("analysis_review_plan") or None,
				"school_company_fit": job.get("school_company_fit") or {},
				"analyzed_at": row.get("analyzed_at"),
				"job": job,
			})
		return {"items": items, "total": len(items), "rag_vector_count": vector_count}

	def list_passed_analysis(self, *, limit: int = 200) -> dict[str, Any]:
		"""分析 AI 历史通过岗位（资料柜）。"""
		from pet_boss.rag.service import rag_miss_message_for_display
		from pet_boss.rag.vector_store import VectorStore

		with ProfileStore(self._data_dir) as pstore:
			vector_count = VectorStore(pstore._conn).count()
		with CacheStore(self._data_dir / "cache" / "boss_agent.db") as cache:
			rows = cache.list_recent_analysis_records(status="passed", limit=limit)
		items = []
		for row in rows:
			job = row.get("job") if isinstance(row.get("job"), dict) else {}
			reasons = list(
				job.get("analysis_reason")
				or job.get("profile_reason")
				or job.get("match_reasons")
				or []
			)[:6]
			refs = list(job.get("rag_references") or [])[:8]
			rag_meta = job.get("rag_meta") if isinstance(job.get("rag_meta"), dict) else {}
			items.append({
				"id": row.get("id"),
				"security_id": row.get("security_id") or job.get("security_id") or "",
				"job_id": row.get("job_id") or job.get("job_id") or "",
				"title": row.get("title") or job.get("title") or "",
				"company": row.get("company") or job.get("company") or "",
				"city": row.get("city") or job.get("city") or "",
				"salary": row.get("salary") or job.get("salary") or "",
				"experience": job.get("experience") or "",
				"analysis_score": row.get("analysis_score") or job.get("analysis_score") or 0,
				"analysis_reason": reasons,
				"analysis_risk": list(job.get("analysis_risk") or job.get("profile_risk") or [])[:4],
				"rag_references": refs,
				"rag_meta": rag_meta,
				"rag_miss_message": rag_miss_message_for_display(
					references=refs,
					rag_meta=rag_meta,
					current_vector_count=vector_count,
				),
				"analysis_review_plan": job.get("analysis_review_plan") or None,
				"school_company_fit": job.get("school_company_fit") or {},
				"search_query": row.get("search_query") or "",
				"search_city": row.get("search_city") or "",
				"analyzed_at": row.get("analyzed_at"),
				"job": job,
			})
		return {"items": items, "total": len(items), "rag_vector_count": vector_count}

	def remove_shortlist_item(
		self,
		*,
		security_id: str,
		job_id: str,
	) -> dict[str, Any]:
		security_id = str(security_id or "").strip()
		job_id = str(job_id or "").strip()
		if not security_id or not job_id:
			raise ProfileWebError("INVALID_PARAM", "缺少 security_id 或 job_id")
		with CacheStore(self._data_dir / "cache" / "boss_agent.db") as cache:
			removed = cache.remove_shortlist(security_id, job_id)
		if not removed:
			raise ProfileWebError("NOT_FOUND", "候选池中无此岗位", status=404)
		return {"removed": True}

	def reject_job(
		self,
		*,
		security_id: str,
		job_id: str,
		title: str = "",
		company: str = "",
		reason: str = "",
		tags: list[str] | None = None,
		analysis_score: int | None = None,
		analysis_reason: list[str] | None = None,
		analysis_risk: list[str] | None = None,
		remove_from_passed: bool = False,
	) -> dict[str, Any]:
		import time

		security_id = str(security_id or "").strip()
		job_id = str(job_id or "").strip()
		if not security_id or not job_id:
			raise ProfileWebError("INVALID_PARAM", "缺少 security_id 或 job_id")

		job = {
			"security_id": security_id,
			"job_id": job_id,
			"title": title,
			"company": company,
			"analysis_score": analysis_score,
			"analysis_reason": analysis_reason or [],
			"analysis_risk": analysis_risk or [],
		}
		tag_list = [str(t).strip() for t in (tags or []) if str(t).strip()]
		notes_payload = {
			"tags": tag_list,
			"reason": (reason or "").strip(),
		}
		import json as _json
		notes = _json.dumps(notes_payload, ensure_ascii=False) if notes_payload["tags"] or notes_payload["reason"] else ""

		removed_passed = 0
		with CacheStore(self._data_dir / "cache" / "boss_agent.db") as cache:
			record_scout_outcome(cache, job, "rejected")
			if remove_from_passed:
				removed_passed = cache.remove_analysis_records(
					security_id, job_id, status="passed",
				)

		learning_summary: dict[str, Any] = {}
		log_id = 0
		with ProfileStore(self._data_dir) as store:
			store.record_feedback(
				security_id=security_id,
				job_id=job_id,
				action="rejected",
				title=title,
				company=company,
				notes=notes,
			)
			learning_summary = process_reject_with_learning(
				store,
				job,
				tags=tag_list,
				reason=reason,
				ai_service=_ai_service(self._data_dir),
			)
			log_id = store.add_preference_learning_log({
				"security_id": security_id,
				"job_id": job_id,
				"title": title,
				"company": company,
				"user_tags": tag_list,
				"user_reason": (reason or "").strip(),
				"analysis_score": analysis_score,
				"analysis_reason": analysis_reason or [],
				"analysis_risk": analysis_risk or [],
				"weight_changes": learning_summary.get("weight_changes") or [],
				"preference_instructions": learning_summary.get("preference_instructions_added") or [],
				"ai_memory_added": learning_summary.get("ai_memory_added") or [],
				"created_at": time.time(),
			})
			ai_svc = _ai_service(self._data_dir)
			if ai_svc and log_id:
				from pet_boss.rag.service import index_reject_learning

				index_reject_learning(
					store,
					ai_svc,
					{
						"title": title,
						"company": company,
						"user_tags": tag_list,
						"user_reason": (reason or "").strip(),
						"analysis_score": analysis_score,
						"analysis_reason": analysis_reason or [],
						"analysis_risk": analysis_risk or [],
					},
					log_id=log_id,
				)
			if remove_from_passed:
				from pet_boss.rag.documents import analysis_doc_key
				from pet_boss.rag.vector_store import VectorStore

				VectorStore(store._conn).delete_by_doc_keys({
					analysis_doc_key(security_id, job_id),
				})

		return {
			"rejected": True,
			"removed_from_passed": removed_passed,
			"learning_log_id": log_id,
			"learning_weights": learning_summary.get("learning_weights") or {},
			"weight_changes": learning_summary.get("weight_changes") or [],
			"preference_instructions_added": learning_summary.get("preference_instructions_added") or [],
			"ai_memory_added": learning_summary.get("ai_memory_added") or [],
		}

	def list_preference_learning_logs(self, *, limit: int = 100) -> dict[str, Any]:
		with ProfileStore(self._data_dir) as store:
			items = store.list_preference_learning_logs(limit=limit)
		return {"items": items, "total": len(items)}

	def clear_preference_learning_memory(self) -> dict[str, Any]:
		with ProfileStore(self._data_dir) as store:
			return clear_reject_learning_memory(store)

	def open_job(
		self,
		*,
		job_id: str,
		security_id: str = "",
	) -> dict[str, Any]:
		"""在已登录浏览器中打开岗位详情页。"""
		job_id = str(job_id or "").strip()
		if not job_id:
			raise ProfileWebError("INVALID_PARAM", "缺少 job_id")
		auth = AuthManager(self._data_dir, logger=self._logger, platform="zhipin")
		# 打开岗位只需本地 cookie；不要 try_browser，避免与搜岗争用 Playwright
		token, verified = auth.resolve_session(try_browser=False)
		if not verified:
			# cookie 在线校验失败时仍允许带着本地 wt2 打开（浏览器里可再登录）
			token = auth.check_status()
		cookies = token.get("cookies", {}) if isinstance(token, dict) else {}
		if not isinstance(cookies, dict) or not cookies.get("wt2"):
			raise ProfileWebError(
				"AUTH_REQUIRED",
				"BOSS 登录态无效，请重新登录或「从浏览器同步」",
				status=401,
			)
		from pet_boss.api.browser_client import build_job_detail_page_url, open_zhipin_job_page

		url = build_job_detail_page_url(job_id, security_id)
		# open_zhipin_job_page 内部已在隔离线程跑 Playwright，勿再进搜岗专用执行器
		return open_zhipin_job_page(
			url,
			cookies=cookies,
			user_agent=str(token.get("user_agent") or ""),
			logger=self._logger,
		)

	def scout_history_summary(self) -> dict[str, Any]:
		with CacheStore(self._data_dir / "cache" / "boss_agent.db") as cache:
			return cache.scout_history_summary()

	def clear_scout_history(self) -> dict[str, Any]:
		with CacheStore(self._data_dir / "cache" / "boss_agent.db") as cache:
			removed = cache.clear_all_scout_history()
		with ProfileStore(self._data_dir) as store:
			feedback_removed = store.clear_scout_job_feedback()
			memory_removed = store.clear_analysis_ai_memory()
		total = (
			removed["history_removed"]
			+ removed["transmitted_removed"]
			+ removed["analysis_removed"]
			+ removed["shortlist_removed"]
			+ feedback_removed
			+ memory_removed
		)
		return {
			"message": (
				f"已全部重置搜岗记录（共 {total} 条）· "
				"侦察历史、分析记录、候选池已清空，所有岗位可重新搜岗"
			),
			**removed,
			"feedback_removed": feedback_removed,
			"analysis_memory_removed": memory_removed,
		}
