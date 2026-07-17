"""双 AI 编排：侦察 AI → 分析 AI。"""

from __future__ import annotations

import random
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from threading import Event
from typing import Any

_ROUND_PAGES_MIN = 2
_ROUND_PAGES_MAX = 3
_SCOUT_DELAY_MIN_SEC = 3.0
_SCOUT_DELAY_MAX_SEC = 8.0
_BEFORE_PAGE_MIN_SEC = 2.0
_BEFORE_PAGE_MAX_SEC = 5.0
_BETWEEN_PAGES_MIN_SEC = 4.0
_BETWEEN_PAGES_MAX_SEC = 10.0
_ROUND_COOLDOWN_MIN_SEC = 60.0
_ROUND_COOLDOWN_MAX_SEC = 300.0
_ROUND_HOME_REFRESH_MIN_SEC = 2.0
_ROUND_HOME_REFRESH_MAX_SEC = 5.0
_ERROR_RETRY_SEC = 8.0
_RISK_RETRY_SEC = 90.0
_STOP_POLL_SEC = 0.2
_MAX_PAGE_RETRIES = 2
_JITTER_LONG_HIT_PROB = 0.08
_JOB_SKIP_PROB = 0.18
_JOB_SKIP_CHAIN_BOOST = 0.38
_JOB_SKIP_CHAIN_MAX_PROB = 0.72
_JOB_GLANCE_PROB = 0.30
_JOB_DEEP_PROB = 0.10
_JOB_SKIP_MIN_SEC = 0.15
_JOB_SKIP_MAX_SEC = 0.8
_JOB_SKIP_STREAK_MIN_SEC = 0.08
_JOB_SKIP_STREAK_MAX_SEC = 0.35
_JOB_GLANCE_MIN_SEC = 0.3
_JOB_GLANCE_MAX_SEC = 0.8
_JOB_DEEP_MIN_SEC = 30.0
_JOB_DEEP_MAX_SEC = 60.0
_EARLY_ROUND_STOP_PROB = 0.55
_EARLY_ROUND_MIN_RATIO = 0.5
_FATIGUE_REST_MIN_SEC = 180.0
_FATIGUE_REST_MAX_SEC = 360.0
_FATIGUE_STOP_REASONS = ("看累了", "暂时没耐心了", "先去忙别的")
_HEARTBEAT_INTERVAL_SEC = 30.0
_HEARTBEAT_MIN_SLEEP_SEC = 45.0
_RISK_ERROR_CODES = frozenset({"ACCOUNT_RISK", "RATE_LIMITED"})
_RISK_MESSAGE_HINTS = ("环境存在异常", "异常行为", "安全验证")

from pet_boss.agents.analysis_ai import (
	AnalysisAI,
	AnalysisResult,
	DEFAULT_PASS_SCORE,
	resolve_analysis_filter_reason,
)
from pet_boss.agents.analysis_store import persist_analysis_result
from pet_boss.agents.job_detail_enrich import enrich_job_post_description
from pet_boss.agents.scout_ai import ScoutAI
from pet_boss.agents.scout_memory import is_already_scouted, job_key, record_scout_outcome, should_skip_scouted_job
from pet_boss.evaluation.models import CareerStageSettings
from pet_boss.evaluation.stages import STAGE_LABELS
from pet_boss.profile.scout_learning import learn_from_analysis_outcome, learn_from_scout_hard_fail
from pet_boss.agents.scout_search_strategy import criteria_with_query
from pet_boss.agents.scout_hard_filter import ScoutFilterConfig, SCOUT_FILTER_LABELS
from pet_boss.ai.service import AIService
from pet_boss.cache.store import CacheStore
from pet_boss.output import Logger
from pet_boss.platforms.base import Platform
from pet_boss.profile.models import UserProfile
from pet_boss.profile.store import ProfileStore
from pet_boss.search_filters import (
	SearchFilterCriteria,
	SearchPipelinePlatformError,
	SearchPipelineResult,
	run_search_pipeline,
)


@dataclass
class QueryPassDepthTracker:
	"""多搜索词轮换：列表扫到末页再换词（不再按通过岗位数切词）。"""

	queries_count: int
	min_pass: int = 1
	max_pass: int = 6
	query_index: int = 0
	pass_count: int = 0
	pass_target: int = 0
	# 已取消「通过 N 个岗位换词」；保留字段仅兼容旧事件/测试
	switch_on_pass: bool = False

	def __post_init__(self) -> None:
		lo = max(1, min(self.min_pass, self.max_pass))
		hi = max(lo, self.max_pass)
		self.min_pass = lo
		self.max_pass = hi
		if self.pass_target <= 0:
			self.pass_target = random.randint(lo, hi)

	@property
	def enabled(self) -> bool:
		return self.queries_count > 1

	def _roll_target(self) -> int:
		return random.randint(self.min_pass, self.max_pass)

	def current_query(self, queries: list[str]) -> str:
		return queries[self.query_index % len(queries)]

	def record_pass(self) -> None:
		self.pass_count += 1

	def depth_met(self) -> bool:
		if not self.switch_on_pass:
			return False
		return self.enabled and self.pass_count >= self.pass_target

	def advance_after_depth_met(self, queries: list[str]) -> str | None:
		if not self.depth_met():
			return None
		finished = self.current_query(queries)
		self.query_index = (self.query_index + 1) % len(queries)
		self.pass_count = 0
		self.pass_target = self._roll_target()
		return finished

	def advance_after_list_exhausted(self, queries: list[str]) -> str | None:
		"""列表扫完时强制切换下一搜索词，不要求达到 pass_target。"""
		if not self.enabled:
			return None
		finished = self.current_query(queries)
		self.query_index = (self.query_index + 1) % len(queries)
		self.pass_count = 0
		self.pass_target = self._roll_target()
		return finished

	def advance_to_next_available(
		self,
		queries: list[str],
		*,
		cache: CacheStore,
		city: str | None,
		cooldown_sec: float,
		mark_exhausted: str | None = None,
		require_depth_met: bool = False,
		exhaust_page: int | None = None,
	) -> tuple[str, str, bool] | None:
		"""切换至下一可用搜索词；返回 (已完成词, 下一词, 是否全部在冷却)。"""
		if require_depth_met and not self.depth_met():
			return None
		finished = self.current_query(queries)
		if mark_exhausted:
			from pet_boss.agents.scout_query_memory import record_scout_query_exhausted

			record_scout_query_exhausted(
				cache, mark_exhausted, city, page=exhaust_page,
			)
		if self.enabled and cooldown_sec > 0:
			from pet_boss.agents.scout_query_memory import select_next_query_index

			next_idx, all_on_cooldown = select_next_query_index(
				queries,
				self.query_index,
				cache=cache,
				city=city,
				cooldown_sec=cooldown_sec,
			)
		elif self.enabled:
			next_idx = (self.query_index + 1) % len(queries)
			all_on_cooldown = False
		else:
			next_idx = self.query_index
			all_on_cooldown = False
		self.query_index = next_idx
		self.pass_count = 0
		self.pass_target = self._roll_target()
		return finished, queries[next_idx], all_on_cooldown

	def depth_payload(self, query: str) -> dict[str, Any]:
		return {
			"query": query,
			"query_index": self.query_index,
			"pass_count": self.pass_count,
			"pass_target": self.pass_target,
			"pass_remaining": max(0, self.pass_target - self.pass_count),
		}


@dataclass
class DualAgentPipelineResult:
	query: str
	city: str | None
	channel: str
	jobs: list[dict[str, Any]]
	total: int
	has_more: bool
	stats: dict[str, Any] = field(default_factory=dict)


def _empty_stats(
	scout_filters: ScoutFilterConfig,
	pass_score: int,
	career_stage: CareerStageSettings | None = None,
) -> dict[str, Any]:
	cs = career_stage or CareerStageSettings()
	return {
		"scout": {
			"jobs_seen": 0,
			"jobs_prefiltered": 0,
			"jobs_scout_passed": 0,
			"jobs_already_transmitted": 0,
			"jobs_new_transmitted": 0,
			"jobs_browse_skipped": 0,
			"jobs_browse_glance": 0,
			"jobs_browse_deep": 0,
			"jobs_history_skipped": 0,
			"scout_filters": scout_filters.to_dict(),
		},
		"analysis": {
			"jobs_received": 0,
			"jobs_passed": 0,
			"jobs_filtered": 0,
			"pass_score": pass_score,
			"career_stage_mode": cs.enabled,
			"career_stage": cs.stage if cs.enabled else None,
			"career_stage_label": STAGE_LABELS.get(cs.stage, "") if cs.enabled else None,
		},
		"search": {
			"pages_scanned": 0,
			"jobs_seen": 0,
			"jobs_matched": 0,
			"rounds_early_stopped": 0,
			"current_page": 0,
			"current_round": 0,
			"current_query": "",
		},
	}


def _sync_search_progress(
	stats: dict[str, Any],
	*,
	page: int | None = None,
	round_num: int | None = None,
	query: str | None = None,
) -> None:
	search = stats.setdefault("search", {})
	if page is not None:
		search["current_page"] = page
	if round_num is not None:
		search["current_round"] = round_num
	if query is not None:
		search["current_query"] = query


def _enrich_scout_event(
	payload: dict[str, Any],
	stats: dict[str, Any] | None,
	*,
	page: int | None = None,
	query: str | None = None,
	round_num: int | None = None,
) -> dict[str, Any]:
	"""为 SSE 事件补齐 page/query/round 与 stats，避免前端读到过期 stats。"""
	if stats is not None:
		payload["stats"] = stats
	search = (stats or {}).get("search") or {}
	pg = page if page is not None else payload.get("page")
	if pg is None:
		pg = search.get("current_page")
	if pg is not None and int(pg) > 0:
		payload["page"] = int(pg)
	q = query if query is not None else payload.get("query")
	if q is None:
		q = search.get("current_query")
	if q:
		payload["query"] = str(q)
	rn = round_num if round_num is not None else payload.get("round")
	if rn is None:
		rn = search.get("current_round")
	if rn is not None:
		payload["round"] = int(rn)
	return payload


_SEARCH_FETCH_HEARTBEAT_SEC = 12.0


def _iter_search_pipeline_with_progress(
	platform: Platform,
	cache: CacheStore,
	logger: Logger,
	*,
	criteria: SearchFilterCriteria,
	start_page: int,
	max_pages: int,
	stop_event: Event | None,
	pause_event: Event | None,
	stats: dict[str, Any],
	passed_jobs: list[dict[str, Any]],
	page: int,
	round_num: int,
	query: str,
) -> Iterator[dict[str, Any] | SearchPipelineResult]:
	"""在当前线程拉取列表（须与 patchright 同线程），开始前 yield 一次进度。"""
	if stop_event and stop_event.is_set():
		yield {
			"type": "stopped",
			"stats": stats,
			"jobs": passed_jobs,
			"message": "侦察 AI 已停止",
		}
		return
	if _wait_if_paused(pause_event, stop_event):
		yield {
			"type": "stopped",
			"stats": stats,
			"jobs": passed_jobs,
			"message": "侦察 AI 已停止",
		}
		return
	_sync_search_progress(stats, page=page, round_num=round_num, query=query)
	yield {
		"type": "search_progress",
		"page": page,
		"round": round_num,
		"query": query,
		"elapsed_sec": 0.0,
		"message": f"正在拉取「{query}」第 {page} 页列表…",
		"stats": stats,
	}

	def _run_search() -> SearchPipelineResult:
		return run_search_pipeline(
			platform, cache, logger,
			criteria=criteria,
			start_page=start_page,
			max_pages=max_pages,
		)

	client = getattr(platform, "_client", None)
	use_browser_fetch = getattr(client, "_dispatch_browser", False) is True
	if use_browser_fetch and max_pages == 1:
		from pet_boss.search_filters import fetch_search_page_raw, process_search_page_result
		from pet_boss.web.browser_executor import submit_browser_task

		future = submit_browser_task(
			lambda: fetch_search_page_raw(platform, criteria, start_page, logger),
		)
		started = time.time()
		last_emit = 0.0
		while not future.done():
			if stop_event and stop_event.is_set():
				break
			if _wait_if_paused(pause_event, stop_event):
				break
			now = time.time()
			if now - last_emit >= _SEARCH_FETCH_HEARTBEAT_SEC:
				elapsed = round(now - started, 1)
				last_emit = now
				_sync_search_progress(stats, page=page, round_num=round_num, query=query)
				yield {
					"type": "search_progress",
					"page": page,
					"round": round_num,
					"query": query,
					"elapsed_sec": elapsed,
					"message": f"正在拉取「{query}」第 {page} 页列表…（已 {int(elapsed)}s）",
					"stats": stats,
				}
			time.sleep(_STOP_POLL_SEC)

		if stop_event and stop_event.is_set():
			yield {
				"type": "stopped",
				"stats": stats,
				"jobs": passed_jobs,
				"message": "侦察 AI 已停止",
			}
			return
		if _wait_if_paused(pause_event, stop_event):
			yield {
				"type": "stopped",
				"stats": stats,
				"jobs": passed_jobs,
				"message": "侦察 AI 已停止",
			}
			return

		raw = future.result()
		yield process_search_page_result(platform, cache, logger, criteria, raw, start_page)
		return

	yield _run_search()


def _job_brief(job: dict[str, Any]) -> dict[str, Any]:
	return {
		"job_id": job.get("job_id", ""),
		"security_id": job.get("security_id", ""),
		"title": job.get("title", ""),
		"company": job.get("company", ""),
		"salary": job.get("salary", ""),
		"city": job.get("city", ""),
	}


def run_dual_agent_pipeline(
	platform: Platform,
	cache: CacheStore,
	logger: Logger,
	*,
	criteria: SearchFilterCriteria,
	profile: UserProfile,
	store: ProfileStore | None = None,
	ai_service: AIService | None = None,
	start_page: int = 1,
	max_pages: int = 1,
	scout_filters: ScoutFilterConfig | None = None,
	pass_score: int = DEFAULT_PASS_SCORE,
	career_stage: CareerStageSettings | None = None,
	search_queries: list[str] | None = None,
) -> DualAgentPipelineResult:
	"""侦察 AI 条件筛岗 → 去重传输 → 分析 AI 打分 → 低分 pass。"""
	queries = search_queries or [criteria.query]
	if len(queries) <= 1:
		return _run_dual_agent_pipeline_once(
			platform, cache, logger,
			criteria=criteria,
			profile=profile,
			store=store,
			ai_service=ai_service,
			start_page=start_page,
			max_pages=max_pages,
			scout_filters=scout_filters,
			pass_score=pass_score,
			career_stage=career_stage,
		)

	all_jobs: list[dict[str, Any]] = []
	merged_stats: dict[str, Any] | None = None
	last: DualAgentPipelineResult | None = None
	for q in queries:
		sub_criteria = criteria_with_query(criteria, q)
		last = _run_dual_agent_pipeline_once(
			platform, cache, logger,
			criteria=sub_criteria,
			profile=profile,
			store=store,
			ai_service=ai_service,
			start_page=start_page,
			max_pages=max_pages,
			scout_filters=scout_filters,
			pass_score=pass_score,
			career_stage=career_stage,
		)
		all_jobs.extend(last.jobs)
		if merged_stats is None:
			merged_stats = last.stats
		else:
			for key in ("scout", "analysis", "search"):
				for k, v in last.stats.get(key, {}).items():
					if isinstance(v, (int, float)):
						merged_stats[key][k] = merged_stats[key].get(k, 0) + v

	seen: set[str] = set()
	deduped: list[dict[str, Any]] = []
	for job in all_jobs:
		key = f"{job.get('security_id')}:{job.get('job_id')}"
		if key in seen:
			continue
		seen.add(key)
		deduped.append(job)

	assert last is not None and merged_stats is not None
	return DualAgentPipelineResult(
		query=queries[0],
		city=criteria.city,
		channel=last.channel,
		jobs=deduped,
		total=last.total,
		has_more=last.has_more,
		stats=merged_stats,
	)


def _run_dual_agent_pipeline_once(
	platform: Platform,
	cache: CacheStore,
	logger: Logger,
	*,
	criteria: SearchFilterCriteria,
	profile: UserProfile,
	store: ProfileStore | None = None,
	ai_service: AIService | None = None,
	start_page: int = 1,
	max_pages: int = 1,
	scout_filters: ScoutFilterConfig | None = None,
	pass_score: int = DEFAULT_PASS_SCORE,
	career_stage: CareerStageSettings | None = None,
) -> DualAgentPipelineResult:
	"""单次搜索词的双 AI 管线。"""
	channel = ScoutAI.make_channel(query=criteria.query, city=criteria.city)
	search_result = run_search_pipeline(
		platform, cache, logger,
		criteria=criteria,
		start_page=start_page,
		max_pages=max_pages,
	)

	filters = scout_filters or ScoutFilterConfig()
	scout = ScoutAI(cache, channel=channel, scout_filters=filters)
	scout_result = scout.scout(search_result.items, profile, criteria=criteria)

	transmitted = 0
	if scout_result.new_jobs:
		transmitted = scout.mark_transmitted(scout_result.new_jobs)

	analysis = AnalysisAI(pass_score=pass_score, career_stage=career_stage or CareerStageSettings())
	if scout_result.new_jobs:
		analysis_result = analysis.analyze(
			scout_result.new_jobs, profile,
			store=store, ai_service=ai_service, criteria=criteria,
		)
	else:
		analysis_result = AnalysisResult()

	persist_analysis_result(
		cache, analysis_result,
		criteria=criteria,
		channel=channel,
		store=store,
		ai_service=ai_service,
	)

	search_stats = search_result.stats
	return DualAgentPipelineResult(
		query=criteria.query,
		city=criteria.city,
		channel=channel,
		jobs=analysis_result.passed_jobs,
		total=search_result.total or len(search_result.items),
		has_more=search_result.has_more,
		stats={
			"scout": {
				"jobs_seen": scout_result.jobs_seen,
				"jobs_prefiltered": scout_result.jobs_prefiltered,
				"jobs_scout_passed": scout_result.jobs_scout_passed,
				"jobs_already_transmitted": scout_result.jobs_already_transmitted,
				"jobs_new_transmitted": transmitted,
				"scout_filters": filters.to_dict(),
			},
			"analysis": {
				"jobs_received": analysis_result.jobs_received,
				"jobs_passed": analysis_result.jobs_passed,
				"jobs_filtered": analysis_result.jobs_filtered,
				"pass_score": pass_score,
				"career_stage_mode": (career_stage or CareerStageSettings()).enabled,
				"career_stage": (career_stage.stage if career_stage and career_stage.enabled else None),
			},
			"search": {
				"pages_scanned": search_stats.pages_scanned,
				"jobs_seen": search_stats.jobs_seen,
				"jobs_matched": search_stats.jobs_matched,
			},
		},
	)


def _is_risk_error(exc: SearchPipelinePlatformError) -> bool:
	if exc.code in _RISK_ERROR_CODES:
		return True
	msg = exc.message or ""
	return any(hint in msg for hint in _RISK_MESSAGE_HINTS)


def _random_delay(min_sec: float, max_sec: float) -> float:
	return random.uniform(min_sec, max_sec)


def _jitter_wait(
	min_sec: float,
	max_sec: float,
	*,
	long_prob: float = _JITTER_LONG_HIT_PROB,
	long_extra_min: float | None = None,
	long_extra_max: float | None = None,
) -> float:
	"""WaitTime = Base + 正态抖动 + (随机命中 ? 长延迟 : 0)。"""
	base = (min_sec + max_sec) / 2
	span = max(max_sec - min_sec, 0.01)
	jitter = random.gauss(0.0, span / 4)
	wait = base + jitter
	soft_min = min_sec * 0.6
	soft_max = max_sec * 1.4
	wait = max(soft_min, min(wait, soft_max))
	if random.random() < long_prob:
		extra_min = long_extra_min if long_extra_min is not None else span * 0.8
		extra_max = long_extra_max if long_extra_max is not None else span * 2.5
		wait += random.uniform(extra_min, extra_max)
	return max(0.05, wait)


def _round_page_cap(*, max_pages: int | None, continuous: bool) -> int | None:
	if max_pages is not None:
		return max_pages
	if continuous:
		return random.randint(_ROUND_PAGES_MIN, _ROUND_PAGES_MAX)
	return None


def _plan_round_browsing(round_page_cap: int | None) -> dict[str, Any]:
	"""规划本轮浏览：可能在达到上限前提前结束，并触发疲劳长休息。"""
	if round_page_cap is None or round_page_cap <= 2:
		return {
			"planned_cap": round_page_cap,
			"effective_cap": round_page_cap,
			"early_stop": False,
			"fatigue": False,
			"stop_reason": "",
		}

	if random.random() >= _EARLY_ROUND_STOP_PROB:
		return {
			"planned_cap": round_page_cap,
			"effective_cap": round_page_cap,
			"early_stop": False,
			"fatigue": False,
			"stop_reason": "",
		}

	min_stop = max(_ROUND_PAGES_MIN, int(round_page_cap * _EARLY_ROUND_MIN_RATIO))
	min_stop = min(min_stop, round_page_cap - 1)
	if round_page_cap <= min_stop:
		effective = round_page_cap
	else:
		effective = random.randint(min_stop, round_page_cap - 1)
	fatigue = random.random() < 0.65
	return {
		"planned_cap": round_page_cap,
		"effective_cap": effective,
		"early_stop": effective < round_page_cap,
		"fatigue": fatigue,
		"stop_reason": random.choice(_FATIGUE_STOP_REASONS),
	}


def _truncate_jobs_for_fatigue_stop(jobs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
	"""最后一页疲劳停止：只浏览部分岗位，模拟看一半就划走。"""
	if len(jobs) <= 4:
		return jobs, 0
	keep_min = max(3, len(jobs) // 4)
	keep_max = max(keep_min + 1, len(jobs) * 2 // 3)
	keep = random.randint(keep_min, min(keep_max, len(jobs)))
	return jobs[:keep], len(jobs) - keep


def _human_scout_delay() -> float:
	"""每个岗位正常浏览间隔（正态抖动 + 偶发长停顿）。"""
	return _jitter_wait(_SCOUT_DELAY_MIN_SEC, _SCOUT_DELAY_MAX_SEC)


def _human_before_page_delay() -> float:
	"""翻页前间隔（正态抖动）。"""
	return _jitter_wait(_BEFORE_PAGE_MIN_SEC, _BEFORE_PAGE_MAX_SEC)


def _human_between_pages_delay() -> float:
	"""页与页之间间隔（正态抖动）。"""
	return _jitter_wait(_BETWEEN_PAGES_MIN_SEC, _BETWEEN_PAGES_MAX_SEC)


def _human_round_cooldown() -> float:
	"""每轮结束后休息（正态抖动 + 偶发长休息）。"""
	return _jitter_wait(
		_ROUND_COOLDOWN_MIN_SEC,
		_ROUND_COOLDOWN_MAX_SEC,
		long_prob=0.08,
		long_extra_min=30.0,
		long_extra_max=120.0,
	)


def _human_round_home_refresh_delay() -> float:
	"""每轮开始前回首页刷新后的短暂停留。"""
	return _jitter_wait(_ROUND_HOME_REFRESH_MIN_SEC, _ROUND_HOME_REFRESH_MAX_SEC)


def _should_refresh_home_for_round(*, current_page: int, start_page: int) -> bool:
	"""深分页续扫时跳过回首页，避免每轮强制跳转导致卡顿。"""
	return current_page <= start_page


def _refresh_browser_home_for_round(platform: Platform) -> None:
	client = getattr(platform, "_client", None)
	refresh_fn = getattr(client, "refresh_browser_home", None)
	if callable(refresh_fn):
		refresh_fn()


def _is_browser_navigation_timeout(exc: Exception) -> bool:
	from pet_boss.agents.monitor_ai import is_browser_navigation_error
	return is_browser_navigation_error(str(exc))


def _job_browse_plan(*, in_skip_streak: bool = False) -> tuple[str, float]:
	"""模拟不一致的浏览深度：跳过 / 悬停扫一眼 / 正常 / 细读 JD。"""
	skip_prob = min(
		_JOB_SKIP_PROB + (_JOB_SKIP_CHAIN_BOOST if in_skip_streak else 0.0),
		_JOB_SKIP_CHAIN_MAX_PROB,
	)
	roll = random.random()
	if roll < skip_prob:
		if in_skip_streak:
			dwell = _jitter_wait(
				_JOB_SKIP_STREAK_MIN_SEC,
				_JOB_SKIP_STREAK_MAX_SEC,
				long_prob=0.0,
			)
		else:
			dwell = _jitter_wait(_JOB_SKIP_MIN_SEC, _JOB_SKIP_MAX_SEC, long_prob=0.0)
		return "skip", dwell
	if roll < skip_prob + _JOB_GLANCE_PROB:
		return "glance", _jitter_wait(
			_JOB_GLANCE_MIN_SEC,
			_JOB_GLANCE_MAX_SEC,
			long_prob=0.0,
		)
	if roll < skip_prob + _JOB_GLANCE_PROB + _JOB_DEEP_PROB:
		return "deep", _jitter_wait(
			_JOB_DEEP_MIN_SEC,
			_JOB_DEEP_MAX_SEC,
			long_prob=0.12,
			long_extra_min=5.0,
			long_extra_max=15.0,
		)
	return "normal", _human_scout_delay()


def _yield_before_page(
	stop_event: Event | None,
	pause_event: Event | None,
	*,
	stats: dict[str, Any],
	passed_jobs: list[dict[str, Any]],
	page: int,
) -> Iterator[dict[str, Any]]:
	"""翻页前等待，透传心跳避免监控误判卡住。"""
	for ev in _yield_sleep(
		stop_event,
		_human_before_page_delay(),
		pause_event=pause_event,
		label=f"即将搜索第 {page} 页",
		stats=stats,
		passed_jobs=passed_jobs,
	):
		yield ev
		if ev.get("type") == "stopped":
			return


def _yield_between_pages(
	stop_event: Event | None,
	pause_event: Event | None,
	*,
	stats: dict[str, Any],
	passed_jobs: list[dict[str, Any]],
	next_page: int,
) -> Iterator[dict[str, Any]]:
	"""页间等待，透传心跳避免监控误判卡住。"""
	for ev in _yield_sleep(
		stop_event,
		_human_between_pages_delay(),
		pause_event=pause_event,
		label=f"翻页间隔，下一页第 {next_page} 页",
		stats=stats,
		passed_jobs=passed_jobs,
	):
		yield ev
		if ev.get("type") == "stopped":
			return


def _yield_while_paused(
	pause_event: Event | None,
	stop_event: Event | None,
	*,
	stats: dict[str, Any],
	passed_jobs: list[dict[str, Any]],
	label: str = "监控 AI 已暂停侦察",
) -> Iterator[dict[str, Any]]:
	"""监控暂停期间周期性输出心跳，避免管道静默阻塞。"""
	while pause_event and pause_event.is_set():
		if stop_event and stop_event.is_set():
			yield {
				"type": "stopped",
				"stats": stats,
				"jobs": passed_jobs,
				"message": "侦察 AI 已停止",
			}
			return
		yield {
			"type": "scout_heartbeat",
			"remaining_sec": 0,
			"message": f"{label}，等待恢复…",
			"stats": stats,
		}
		time.sleep(1.0)
	if stop_event and stop_event.is_set():
		yield {
			"type": "stopped",
			"stats": stats,
			"jobs": passed_jobs,
			"message": "侦察 AI 已停止",
		}


def _wait_if_paused(
	pause_event: Event | None,
	stop_event: Event | None,
) -> bool:
	"""暂停侦察（监控 AI 中断）。返回 True 表示应停止。"""
	while pause_event and pause_event.is_set():
		if stop_event and stop_event.is_set():
			return True
		time.sleep(_STOP_POLL_SEC)
	return stop_event is not None and stop_event.is_set()


def _sleep_until_stop(
	stop_event: Event | None,
	seconds: float,
	*,
	pause_event: Event | None = None,
) -> bool:
	"""等待若干秒；若 stop_event 被设置则返回 True（应停止）。"""
	for ev in _iter_sleep_with_heartbeats(
		stop_event, seconds, pause_event=pause_event, label="",
	):
		if ev.get("type") == "_sleep_done":
			return bool(ev.get("stopped"))
	return False


def _iter_sleep_with_heartbeats(
	stop_event: Event | None,
	seconds: float,
	*,
	pause_event: Event | None = None,
	label: str = "等待中",
) -> Iterator[dict[str, Any]]:
	"""可中断睡眠；超过阈值时周期性 yield scout_heartbeat，避免界面长时间无输出。"""
	if seconds <= 0:
		yield {"type": "_sleep_done", "stopped": False}
		return
	deadline = time.time() + seconds
	emit_heartbeats = seconds >= _HEARTBEAT_MIN_SLEEP_SEC
	next_hb = time.time() + min(_HEARTBEAT_INTERVAL_SEC, max(seconds * 0.15, 8.0))
	stopped = False
	while time.time() < deadline:
		if _wait_if_paused(pause_event, stop_event):
			stopped = True
			break
		if stop_event and stop_event.is_set():
			stopped = True
			break
		now = time.time()
		if emit_heartbeats and now >= next_hb:
			remaining = max(0.0, deadline - now)
			hint = label or "侦察节奏等待"
			yield {
				"type": "scout_heartbeat",
				"remaining_sec": round(remaining, 1),
				"message": f"{hint}，约 {int(remaining)} 秒后继续…",
			}
			next_hb = now + _HEARTBEAT_INTERVAL_SEC
		time.sleep(_STOP_POLL_SEC)
	if not stopped:
		stopped = _wait_if_paused(pause_event, stop_event) or (
			stop_event is not None and stop_event.is_set()
		)
	if emit_heartbeats and not stopped:
		hint = label or "侦察节奏等待"
		yield {
			"type": "scout_heartbeat",
			"remaining_sec": 0,
			"message": f"{hint}，即将继续…",
		}
	yield {"type": "_sleep_done", "stopped": stopped}


def _yield_work_schedule_wait(
	stop_event: Event | None,
	pause_event: Event | None,
	periods: list[dict[str, Any]],
	stats: dict[str, Any],
	passed_jobs: list[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
	"""非工作时间暂停侦察，上班后自动继续（不结束 SSE 连接）。"""
	from pet_boss.web.work_schedule import (
		format_schedule_hint,
		is_within_work_schedule,
		seconds_until_next_work_start,
	)

	if not periods or is_within_work_schedule(periods):
		return
	hint = format_schedule_hint(periods)
	wait_sec = max(60.0, seconds_until_next_work_start(periods))
	yield {
		"type": "off_hours_pause",
		"pause_sec": round(wait_sec, 1),
		"remaining_sec": round(wait_sec, 1),
		"message": f"非工作时间 · 搜岗已暂停（{hint} 上班后自动继续）",
		"stats": stats,
	}
	while not is_within_work_schedule(periods):
		if _wait_if_paused(pause_event, stop_event):
			yield {"type": "stopped", "stats": stats, "jobs": passed_jobs, "message": "侦察 AI 已停止"}
			return
		if stop_event and stop_event.is_set():
			yield {"type": "stopped", "stats": stats, "jobs": passed_jobs, "message": "侦察 AI 已停止"}
			return
		remaining = max(0.0, seconds_until_next_work_start(periods))
		# 周期性续期：避免 30s 静默睡眠无事件导致 watchdog 误判卡死
		yield {
			"type": "off_hours_pause",
			"pause_sec": round(max(remaining, 60.0), 1),
			"remaining_sec": round(remaining, 1),
			"message": (
				f"非工作时间，约 {int(remaining // 60)} 分钟后上班继续…"
				if remaining > 0
				else "非工作时间，等待上班后继续…"
			),
			"stats": stats,
		}
		chunk = min(60.0, remaining if remaining > 0 else 60.0)
		for ev in _iter_sleep_with_heartbeats(
			stop_event, chunk, pause_event=pause_event, label="非工作时间",
		):
			if ev.get("type") == "_sleep_done":
				if ev.get("stopped"):
					yield {"type": "stopped", "stats": stats, "jobs": passed_jobs, "message": "侦察 AI 已停止"}
					return
				break
			ev = {**ev, "stats": stats}
			yield ev
	yield {
		"type": "work_hours_resume",
		"message": "工作时间到 · 搜岗自动继续",
		"stats": stats,
	}


def _yield_until_query_available(
	cache: CacheStore,
	query: str,
	city: str | None,
	cooldown_sec: float,
	stop_event: Event | None,
	pause_event: Event | None,
	stats: dict[str, Any],
	passed_jobs: list[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
	"""搜索词列表扫完冷却期间等待，直至可用或用户停止。"""
	from pet_boss.agents.scout_query_memory import cooldown_remaining_sec, is_query_on_cooldown

	if cooldown_sec <= 0:
		return
	while is_query_on_cooldown(cache, query, city, cooldown_sec):
		remaining = cooldown_remaining_sec(cache, query, city, cooldown_sec)
		mins = max(1, int((remaining + 59) // 60))
		yield {
			"type": "scout_query_cooldown",
			"query": query,
			"remaining_sec": round(remaining, 1),
			"message": f"「{query}」列表已扫完，冷却中（约 {mins} 分钟后可再搜）",
			"stats": stats,
		}
		wait_sec = min(max(remaining, 1.0), 30.0)
		for ev in _yield_sleep(
			stop_event,
			wait_sec,
			pause_event=pause_event,
			label="搜索词冷却",
			stats=stats,
			passed_jobs=passed_jobs,
		):
			if ev.get("type") == "_sleep_done":
				if ev.get("stopped"):
					yield {
						"type": "stopped",
						"stats": stats,
						"jobs": passed_jobs,
						"message": "侦察 AI 已停止",
					}
				break
			yield ev


def _yield_sleep(
	stop_event: Event | None,
	seconds: float,
	*,
	pause_event: Event | None = None,
	label: str = "等待中",
	stats: dict[str, Any] | None = None,
	passed_jobs: list[dict[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
	"""在生成器中睡眠，透传心跳事件。结束时若应停止则 yield stopped。"""
	for ev in _iter_sleep_with_heartbeats(
		stop_event, seconds, pause_event=pause_event, label=label,
	):
		if ev.get("type") == "_sleep_done":
			if ev.get("stopped"):
				yield {
					"type": "stopped",
					"stats": stats or {},
					"jobs": passed_jobs or [],
					"message": "侦察 AI 已停止",
				}
			return
		if stats is not None:
			ev = {**ev, "stats": stats}
			page = stats.get("search", {}).get("current_page")
			if page is not None and int(page) > 0:
				ev["page"] = int(page)
		yield ev


def _process_scout_jobs(
	scout: ScoutAI,
	analysis: AnalysisAI,
	cache: CacheStore,
	channel: str,
	jobs: list[dict[str, Any]],
	*,
	current_page: int,
	profile: UserProfile,
	store: ProfileStore | None,
	ai_service: AIService | None,
	criteria: SearchFilterCriteria,
	scout_filters: ScoutFilterConfig,
	stats: dict[str, Any],
	passed_jobs: list[dict[str, Any]],
	stop_event: Event | None,
	pause_event: Event | None = None,
	work_schedule_periods: list[dict[str, Any]] | None = None,
	platform: Platform | None = None,
) -> Iterator[dict[str, Any]]:
	in_skip_streak = False
	periods = work_schedule_periods or []
	for job in jobs:
		if periods:
			for ev in _yield_work_schedule_wait(
				stop_event, pause_event, periods, stats, passed_jobs,
			):
				yield ev
				if ev.get("type") == "stopped":
					return
		if _wait_if_paused(pause_event, stop_event):
			yield {"type": "stopped", "stats": stats, "jobs": passed_jobs}
			return
		if stop_event and stop_event.is_set():
			yield {"type": "stopped", "stats": stats, "jobs": passed_jobs}
			return

		browse_mode, dwell_sec = _job_browse_plan(in_skip_streak=in_skip_streak)
		was_in_skip_streak = in_skip_streak
		in_skip_streak = browse_mode == "skip"
		brief = _job_brief(job)

		skip_job, skip_reason = should_skip_scouted_job(cache, job, profile_store=store)
		if skip_job:
			stats["scout"]["jobs_history_skipped"] += 1
			history_msg = f"历史已处理（{skip_reason}），快速划过：{brief['title']}"
			yield {
				"type": "scout_history_skip",
				"page": current_page,
				"job": brief,
				"prior_outcome": skip_reason,
				"interaction": "scroll",
				"dwell_sec": 0.2,
				"message": history_msg,
				"stats": stats,
			}
			for ev in _yield_sleep(
				stop_event, 0.2, pause_event=pause_event,
				label="历史岗位", stats=stats, passed_jobs=passed_jobs,
			):
				yield ev
				if ev.get("type") == "stopped":
					return
			continue

		if browse_mode == "skip":
			stats["scout"]["jobs_browse_skipped"] += 1
			record_scout_outcome(cache, job, "browse_skip", channel=channel)
			skip_msg = (
				f"快速划过一段（连续跳过）：{brief['title']}"
				if was_in_skip_streak
				else f"快速划过（未查看）：{brief['title']}"
			)
			yield {
				"type": "scout_browse_skip",
				"page": current_page,
				"job": brief,
				"browse_mode": browse_mode,
				"interaction": "scroll",
				"in_skip_streak": was_in_skip_streak,
				"dwell_sec": round(dwell_sec, 1),
				"message": skip_msg,
				"stats": stats,
			}
			for ev in _yield_sleep(
				stop_event, dwell_sec, pause_event=pause_event,
				label="快速划过", stats=stats, passed_jobs=passed_jobs,
			):
				yield ev
				if ev.get("type") == "stopped":
					return
			continue

		if browse_mode == "glance":
			stats["scout"]["jobs_browse_glance"] += 1
		elif browse_mode == "deep":
			stats["scout"]["jobs_browse_deep"] += 1

		stats["scout"]["jobs_seen"] += 1
		if browse_mode == "deep":
			seen_msg = f"点开细读 JD（{dwell_sec:.0f}s）：{brief['title']} @ {brief['company']}"
			interaction = "click_detail"
		elif browse_mode == "glance":
			seen_msg = f"悬停扫一眼（列表页 {dwell_sec:.1f}s，未点开）：{brief['title']}"
			interaction = "hover"
		else:
			seen_msg = f"浏览岗位：{brief['title']} @ {brief['company']}"
			interaction = "view"
		yield {
			"type": "scout_seen",
			"page": current_page,
			"job": brief,
			"browse_mode": browse_mode,
			"interaction": interaction,
			"dwell_sec": round(dwell_sec, 1),
			"message": seen_msg,
			"stats": stats,
		}

		for ev in _yield_sleep(
			stop_event, dwell_sec, pause_event=pause_event,
			label=seen_msg, stats=stats, passed_jobs=passed_jobs,
		):
			yield ev
			if ev.get("type") == "stopped":
				return

		scout_hard = scout.evaluate_hard(job, profile, criteria=criteria)
		yield {
			"type": "scout_filter",
			"page": current_page,
			"job": brief,
			"scout_hard_passed": scout_hard.passed,
			"scout_hard_reasons": scout_hard.reasons,
			"scout_hard_failures": scout_hard.failures,
			"scout_hard_checks": scout_hard.checks,
			"scout_filters": scout_filters.to_dict(),
			"browse_mode": browse_mode,
			"interaction": interaction,
		}

		if browse_mode == "glance":
			record_scout_outcome(cache, job, "seen", channel=channel)
			yield {
				"type": "scout_glance",
				"page": current_page,
				"job": brief,
				"scout_hard_passed": scout_hard.passed,
				"interaction": "hover",
				"browse_mode": browse_mode,
				"dwell_sec": round(dwell_sec, 1),
				"message": (
					f"悬停略读（硬条件{'通过' if scout_hard.passed else '未过'}，未点开详情）：{brief['title']}"
				),
				"stats": stats,
			}
			continue

		if not scout_hard.passed:
			fail_hint = "；".join(scout_hard.failures[:2]) or "硬性条件不符"
			record_scout_outcome(cache, job, "hard_fail", channel=channel)
			if store:
				learn_from_scout_hard_fail(store, job, scout_hard.failures)
			yield {
				"type": "scout_skip",
				"reason": "hard_fail",
				"job": brief,
				"scout_hard_failures": scout_hard.failures,
				"message": f"侦察跳过（硬性条件不符：{fail_hint}）：{brief['title']}",
				"stats": stats,
			}
			continue

		stats["scout"]["jobs_scout_passed"] += 1
		job_with_score = {
			**job,
			"scout_passed": True,
			"scout_hard_reasons": scout_hard.reasons,
			"scout_hard_failures": scout_hard.failures,
			"scout_hard_checks": scout_hard.checks,
		}
		new_jobs, already_count = cache.filter_untransmitted(channel, [job_with_score])
		if already_count:
			stats["scout"]["jobs_already_transmitted"] += 1
			stats["scout"]["jobs_history_skipped"] += 1
			history_msg = f"历史已处理（transmitted），快速划过：{brief['title']}"
			yield {
				"type": "scout_history_skip",
				"page": current_page,
				"job": brief,
				"prior_outcome": "transmitted",
				"interaction": "scroll",
				"dwell_sec": 0.2,
				"message": history_msg,
				"stats": stats,
			}
			for ev in _yield_sleep(
				stop_event, 0.2, pause_event=pause_event,
				label="历史岗位", stats=stats, passed_jobs=passed_jobs,
			):
				yield ev
				if ev.get("type") == "stopped":
					return
			continue

		scout.mark_transmitted(new_jobs)
		record_scout_outcome(cache, job_with_score, "transmitted", channel=channel)
		stats["scout"]["jobs_new_transmitted"] += 1
		stats["analysis"]["jobs_received"] += 1
		yield {
			"type": "scout_transmit",
			"job": brief,
			"message": f"传输给分析 AI：{brief['title']}（硬性条件已通过）",
			"stats": stats,
		}

		yield {
			"type": "analysis_start",
			"job": brief,
			"career_stage_mode": analysis._career_stage.enabled,
			"career_stage": analysis._career_stage.stage if analysis._career_stage.enabled else None,
			"career_stage_label": STAGE_LABELS.get(analysis._career_stage.stage, "") if analysis._career_stage.enabled else None,
			"message": (
				f"分析 AI 职业阶段评估（{STAGE_LABELS.get(analysis._career_stage.stage, analysis._career_stage.stage)}）：{brief['title']}…"
				if analysis._career_stage.enabled
				else f"分析 AI 深度评估中（匹配/前景/雷点）：{brief['title']}…"
			),
		}

		job_for_analysis = enrich_job_post_description(job_with_score, platform)
		tier_recheck = scout.evaluate_hard(
			job_for_analysis, profile, criteria=criteria,
		)
		if not tier_recheck.passed:
			fail_hint = "；".join(tier_recheck.failures[:2]) or "硬性条件不符"
			filtered_job = {
				**job_for_analysis,
				"analysis_score": 0,
				"analysis_passed": False,
				"analysis_status": "filtered",
				"analysis_filter_reason": fail_hint,
				"analysis_risk": list(tier_recheck.failures),
				"scout_hard_failures": tier_recheck.failures,
			}
			persist_analysis_result(
				cache,
				AnalysisResult(jobs_received=1, jobs_filtered=1, filtered_jobs=[filtered_job]),
				criteria=criteria,
				channel=channel,
				store=store,
				ai_service=ai_service,
			)
			stats["analysis"]["jobs_filtered"] += 1
			yield {
				"type": "job_filtered",
				"job": filtered_job,
				"score": 0,
				"filter_reason": fail_hint,
				"message": f"✗ {fail_hint}：{brief['title']}",
				"stats": stats,
			}
			continue

		analysis_result = analysis.analyze(
			[job_for_analysis], profile,
			store=store, ai_service=ai_service, criteria=criteria,
		)
		persist_analysis_result(
			cache, analysis_result,
			criteria=criteria,
			channel=channel,
			store=store,
			ai_service=ai_service,
		)

		if analysis_result.passed_jobs:
			enriched = analysis_result.passed_jobs[0]
			stats["analysis"]["jobs_passed"] += 1
			passed_jobs.append(enriched)
			risk_hint = ""
			if enriched.get("analysis_risk"):
				risk_hint = f"（需关注：{enriched['analysis_risk'][0]}）"
			yield {
				"type": "job_passed",
				"job": enriched,
				"message": f"✓ 通过 {enriched.get('analysis_score', 0)} 分{risk_hint}：{brief['title']}",
				"stats": stats,
			}
		elif analysis_result.filtered_jobs:
			filtered = analysis_result.filtered_jobs[0]
			stats["analysis"]["jobs_filtered"] += 1
			filter_reason = resolve_analysis_filter_reason(filtered, pass_score=analysis._pass_score)
			risk_hint = f" — {filter_reason}" if filter_reason else ""
			yield {
				"type": "job_filtered",
				"job": filtered,
				"score": filtered.get("analysis_score", 0),
				"filter_reason": filter_reason,
				"message": f"✗ {filtered.get('analysis_score', 0)} 分{risk_hint}：{brief['title']}",
				"stats": stats,
			}


def iter_dual_agent_pipeline(
	platform: Platform,
	cache: CacheStore,
	logger: Logger,
	*,
	criteria: SearchFilterCriteria,
	profile: UserProfile,
	store: ProfileStore | None = None,
	ai_service: AIService | None = None,
	start_page: int = 1,
	max_pages: int | None = None,
	scout_filters: ScoutFilterConfig | None = None,
	pass_score: int = DEFAULT_PASS_SCORE,
	career_stage: CareerStageSettings | None = None,
	stop_event: Event | None = None,
	pause_event: Event | None = None,
	continuous: bool = True,
	search_queries: list[str] | None = None,
	work_schedule_periods: list[dict[str, Any]] | None = None,
	query_pass_depth_min: int = 1,
	query_pass_depth_max: int = 6,
	query_exhaust_cooldown_sec: float = 4 * 3600,
) -> Iterator[dict[str, Any]]:
	"""流式双 AI 管线：逐页搜索、逐岗侦察、实时输出进度事件。

	continuous=True 时循环扫描直至 stop_event 被设置（用户停止）。
	多组 search_queries 时，每组关键词翻到末页后再切换下一组（不受通过岗位数量限制）。
	"""
	base_criteria = criteria
	queries = [q.strip() for q in (search_queries or [criteria.query]) if q.strip()]
	if not queries:
		queries = [criteria.query]
	filters = scout_filters or ScoutFilterConfig()
	analysis = AnalysisAI(pass_score=pass_score, career_stage=career_stage or CareerStageSettings())
	stats = _empty_stats(filters, pass_score, career_stage)
	passed_jobs: list[dict[str, Any]] = []
	depth = QueryPassDepthTracker(
		len(queries),
		min_pass=query_pass_depth_min,
		max_pass=query_pass_depth_max,
		switch_on_pass=False,
	)
	round_num = 1
	consecutive_errors = 0
	page_retries = 0
	last_query_index: int | None = None
	pending_query_advance = False
	pending_query_advance_on_exhaust = False
	pending_query_exhaust_page: int | None = None
	next_page_for_keyword = start_page
	scout: ScoutAI | None = None
	channel = ""

	if len(queries) > 1 or (search_queries and len(search_queries) >= 1):
		strategy_msg = f"侦察 AI 搜索词策略（共 {len(queries)} 组）：{'、'.join(queries)}"
		if depth.enabled:
			strategy_msg += "；每组关键词翻到末页后再切换下一组"
		yield {
			"type": "scout_query_strategy",
			"queries": queries,
			"message": strategy_msg,
			"stats": stats,
		}

	start_msg = (
		f"侦察 AI 已启动，按自选硬性条件筛岗（{', '.join(SCOUT_FILTER_LABELS[k] for k in sorted(filters.enabled)) or '无'}），每轮随机扫描 {_ROUND_PAGES_MIN}～{_ROUND_PAGES_MAX} 页"
		f"（随机跳过/细读岗位，正态抖动节奏）"
		if continuous and max_pages is None
		else "侦察 AI 已启动（模拟真人浏览节奏）"
	)
	if depth.enabled:
		start_msg += f"；搜索词 {len(queries)} 组，各自翻到末页后轮换"
	elif len(queries) > 1:
		start_msg += f"；搜索词 {len(queries)} 组轮换"
	if query_exhaust_cooldown_sec > 0:
		cooldown_hours = query_exhaust_cooldown_sec / 3600
		start_msg += f"；列表扫完的搜索词冷却 {cooldown_hours:g} 小时"

	if query_exhaust_cooldown_sec > 0 and len(queries) > 1:
		from pet_boss.agents.scout_query_memory import is_query_on_cooldown, select_next_query_index

		current_q = depth.current_query(queries)
		if is_query_on_cooldown(cache, current_q, base_criteria.city, query_exhaust_cooldown_sec):
			prev = current_q
			next_idx, _ = select_next_query_index(
				queries,
				depth.query_index,
				cache=cache,
				city=base_criteria.city,
				cooldown_sec=query_exhaust_cooldown_sec,
			)
			if next_idx != depth.query_index:
				depth.query_index = next_idx
				yield {
					"type": "scout_query_skip_cooldown",
					"query": prev,
					"next_query": queries[next_idx],
					"message": f"「{prev}」在冷却中，改用「{queries[next_idx]}」",
					"stats": stats,
				}

	yield {
		"type": "start",
		"query": queries[0],
		"queries": queries,
		"city": base_criteria.city,
		"channel": ScoutAI.make_channel(query=queries[0], city=base_criteria.city),
		"continuous": continuous,
		"stats": stats,
		"message": start_msg,
	}

	schedule_periods = work_schedule_periods or []

	while True:
		if _wait_if_paused(pause_event, stop_event):
			yield {"type": "stopped", "stats": stats, "jobs": passed_jobs, "message": "侦察 AI 已停止"}
			return
		if stop_event and stop_event.is_set():
			yield {"type": "stopped", "stats": stats, "jobs": passed_jobs, "message": "侦察 AI 已停止"}
			return

		yield from _yield_work_schedule_wait(
			stop_event, pause_event, schedule_periods, stats, passed_jobs,
		)

		if pending_query_advance:
			# 通过岗位数换词已取消；遗留标志直接清空
			pending_query_advance = False

		if pending_query_advance_on_exhaust:
			finished_query = depth.current_query(queries)
			if depth.enabled:
				advanced = depth.advance_to_next_available(
					queries,
					cache=cache,
					city=base_criteria.city,
					cooldown_sec=query_exhaust_cooldown_sec,
					mark_exhausted=finished_query,
					exhaust_page=pending_query_exhaust_page,
				)
				if advanced:
					_, next_query, all_on_cooldown = advanced
					cooldown_h = query_exhaust_cooldown_sec / 3600
					msg = (
						f"「{finished_query}」列表已扫完（第 {pending_query_exhaust_page or '?'} 页），"
						f"已记入冷却 {cooldown_h:g} 小时，切换至「{next_query}」"
					)
					if all_on_cooldown:
						msg += "（其余搜索词均在冷却，使用最早到期的词）"
					yield {
						"type": "scout_query_depth_met",
						"query": finished_query,
						"next_query": next_query,
						"pass_count": depth.pass_count,
						"list_exhausted": True,
						"message": msg,
						"stats": stats,
					}
			else:
				from pet_boss.agents.scout_query_memory import record_scout_query_exhausted

				record_scout_query_exhausted(
					cache,
					finished_query,
					base_criteria.city,
					page=pending_query_exhaust_page,
				)
			pending_query_advance_on_exhaust = False
			pending_query_exhaust_page = None

		round_query = depth.current_query(queries)
		for cooldown_ev in _yield_until_query_available(
			cache,
			round_query,
			base_criteria.city,
			query_exhaust_cooldown_sec,
			stop_event,
			pause_event,
			stats,
			passed_jobs,
		):
			yield cooldown_ev
			if cooldown_ev.get("type") == "stopped":
				return

		round_query = depth.current_query(queries)
		round_query_index = depth.query_index
		active_criteria = criteria_with_query(base_criteria, round_query)
		if last_query_index != round_query_index:
			channel = ScoutAI.make_channel(query=round_query, city=base_criteria.city)
			scout = ScoutAI(cache, channel=channel, scout_filters=filters)
			next_page_for_keyword = start_page
			current_page = start_page
			_sync_search_progress(
				stats,
				page=current_page,
				round_num=round_num,
				query=round_query,
			)
			if last_query_index is not None:
				yield _enrich_scout_event(
					{
						"type": "scout_query_switch",
						"query_index": round_query_index,
						"queries": queries,
						"channel": channel,
						"message": f"切换搜索词：{round_query}",
					},
					stats,
					page=current_page,
					query=round_query,
					round_num=round_num,
				)
			last_query_index = round_query_index
		else:
			current_page = next_page_for_keyword

		pages_this_round = 0
		page_retries = 0
		round_page_cap = _round_page_cap(max_pages=max_pages, continuous=continuous)
		base_plan = _plan_round_browsing(round_page_cap)
		scout_ctx = {
			"round": round_num,
			"query": round_query,
			"city": base_criteria.city,
			"stats": stats,
			"depth": {"query": round_query, "query_index": depth.query_index, "pass_count": depth.pass_count},
		}
		from pet_boss.agents.planners.scout_strategy import plan_scout_round_strategy

		round_plan = plan_scout_round_strategy(
			ai_service,
			context=scout_ctx,
			round_page_cap=round_page_cap,
			base_plan=base_plan,
		)
		# 忽略 planner 的 pass_target：换词仅以列表末页为准
		if store is not None:
			store.save_scout_strategy_plan({
				"round": round_num,
				"query": round_query,
				"city": base_criteria.city,
				"created_at": time.time(),
				"plan": round_plan,
			})
		effective_cap = round_plan["effective_cap"]
		round_page_cap = round_plan.get("planned_cap") or round_page_cap

		round_msg = f"开始第 {round_num} 轮侦察，本轮计划扫描 {round_page_cap or '∞'} 页…"
		if round_plan.get("early_stop") and effective_cap is not None:
			round_msg = (
				f"开始第 {round_num} 轮侦察，计划最多 {round_page_cap} 页"
				f"（拟浏览约 {effective_cap} 页后可能提前休息）…"
			)

		round_start_payload: dict[str, Any] = {
			"type": "round_start",
			"round": round_num,
			"page": current_page,
			"query": round_query,
			"round_page_cap": round_page_cap,
			"effective_cap": effective_cap,
			"early_stop": round_plan.get("early_stop", False),
			"message": round_msg,
			"stats": stats,
		}
		_sync_search_progress(stats, page=current_page, round_num=round_num, query=round_query)
		yield round_start_payload
		if round_plan.get("planner") == "llm" or round_plan.get("strategy_summary"):
			yield {
				"type": "scout_strategy_plan",
				"round": round_num,
				"query": round_query,
				"plan": round_plan,
				"message": round_plan.get("strategy_summary")
				or f"本轮策略：计划浏览 {effective_cap}/{round_page_cap} 页",
				"stats": stats,
			}

		if _should_refresh_home_for_round(current_page=current_page, start_page=start_page):
			yield {
				"type": "round_home_refresh",
				"round": round_num,
				"message": f"第 {round_num} 轮：回到 BOSS 首页刷新，重新进入搜岗…",
				"stats": stats,
			}
			try:
				_refresh_browser_home_for_round(platform)
			except Exception as exc:
				if _is_browser_navigation_timeout(exc):
					yield {
						"type": "browser_stuck",
						"round": round_num,
						"message": f"浏览器首页刷新卡住: {exc}",
						"stats": stats,
					}
				else:
					logger.info(f"首页刷新失败（继续侦察）: {exc}")
					yield {
						"type": "round_home_refresh_skip",
						"round": round_num,
						"message": f"首页刷新跳过：{exc}",
						"stats": stats,
					}
			if _sleep_until_stop(
				stop_event,
				_human_round_home_refresh_delay(),
				pause_event=pause_event,
			):
				yield {"type": "stopped", "stats": stats, "jobs": passed_jobs, "message": "侦察 AI 已停止"}
				return
		else:
			yield {
				"type": "round_home_refresh_skip",
				"round": round_num,
				"page": current_page,
				"message": (
					f"第 {round_num} 轮：深分页续扫第 {current_page} 页，跳过回首页刷新"
				),
				"stats": stats,
			}

		round_page_reset = False
		round_pages_exhausted = False

		while True:
			for ev in _yield_while_paused(
				pause_event, stop_event, stats=stats, passed_jobs=passed_jobs,
			):
				yield ev
				if ev.get("type") == "stopped":
					return
			if stop_event and stop_event.is_set():
				yield {"type": "stopped", "stats": stats, "jobs": passed_jobs, "message": "侦察 AI 已停止"}
				return

			for ev in _yield_before_page(
				stop_event, pause_event,
				stats=stats, passed_jobs=passed_jobs, page=current_page,
			):
				yield ev
				if ev.get("type") == "stopped":
					return

			for ev in _yield_work_schedule_wait(
				stop_event, pause_event, schedule_periods, stats, passed_jobs,
			):
				yield ev
				if ev.get("type") == "stopped":
					return

			yield _enrich_scout_event(
				{
					"type": "page_start",
					"message": f"侦察 AI 正在搜索「{round_query}」第 {current_page} 页（第 {round_num} 轮）…",
				},
				stats,
				page=current_page,
				query=round_query,
				round_num=round_num,
			)
			_sync_search_progress(stats, page=current_page, round_num=round_num, query=round_query)
			yield _enrich_scout_event(
				{
					"type": "search_fetch",
					"message": f"正在向 BOSS 拉取「{round_query}」第 {current_page} 页职位（可能需要 1～3 分钟）…",
				},
				stats,
				page=current_page,
				query=round_query,
				round_num=round_num,
			)

			search_result: SearchPipelineResult | None = None
			try:
				for item in _iter_search_pipeline_with_progress(
					platform, cache, logger,
					criteria=active_criteria,
					start_page=current_page,
					max_pages=1,
					stop_event=stop_event,
					pause_event=pause_event,
					stats=stats,
					passed_jobs=passed_jobs,
					page=current_page,
					round_num=round_num,
					query=round_query,
				):
					if isinstance(item, dict):
						if item.get("type") == "stopped":
							yield item
							return
						yield item
					else:
						search_result = item
			except SearchPipelinePlatformError as exc:
				if getattr(exc, "browser_lost", False):
					yield {
						"type": "browser_session_lost",
						"sequence": "crash_then_stall",
						"page": current_page,
						"round": round_num,
						"query": round_query,
						"message": (
							f"自动化 Chromium 已断开（先崩窗后卡）：{exc.message}。"
							"终端可能仍打印「正在搜索第 N 页」，但浏览器请求已失效。"
						),
						"stats": stats,
					}
				consecutive_errors += 1
				page_retries += 1
				is_risk = _is_risk_error(exc)
				retry_sec = _RISK_RETRY_SEC * min(consecutive_errors, 4) if is_risk else _ERROR_RETRY_SEC
				event_type = "account_risk" if is_risk else "error_retry"
				if is_risk:
					action = f"{retry_sec:.0f} 秒后从第 1 页重新开始新一轮（不再重试第 {current_page} 页）"
					hint = "BOSS 深分页风控。建议浏览器手动打开 zhipin.com 正常浏览后再继续。"
				elif page_retries >= _MAX_PAGE_RETRIES:
					action = f"本页重试 {_MAX_PAGE_RETRIES} 次仍失败，结束本轮"
					hint = ""
				else:
					action = f"{retry_sec:.0f} 秒后重试本页"
					hint = ""
				yield {
					"type": event_type,
					"code": exc.code,
					"page": current_page,
					"round": round_num,
					"message": f"搜索出错：{exc.message}，{action}{(' ' + hint) if hint else ''}",
					"retry_sec": retry_sec,
					"consecutive_errors": consecutive_errors,
					"stats": stats,
				}
				if is_risk or page_retries >= _MAX_PAGE_RETRIES:
					if is_risk:
						round_page_reset = True
					if _sleep_until_stop(stop_event, retry_sec, pause_event=pause_event):
						yield {"type": "stopped", "stats": stats, "jobs": passed_jobs, "message": "侦察 AI 已停止"}
						return
					break
				if _sleep_until_stop(stop_event, retry_sec, pause_event=pause_event):
					yield {"type": "stopped", "stats": stats, "jobs": passed_jobs, "message": "侦察 AI 已停止"}
					return
				continue

			consecutive_errors = 0
			page_retries = 0
			stats["search"]["pages_scanned"] += search_result.stats.pages_scanned
			stats["search"]["jobs_seen"] += search_result.stats.jobs_seen
			stats["search"]["jobs_matched"] += search_result.stats.jobs_matched
			has_more = search_result.has_more
			pages_this_round += 1

			jobs_to_process = list(search_result.items)
			skipped_on_page = 0
			is_last_planned_page = effective_cap is not None and pages_this_round >= effective_cap
			if is_last_planned_page and round_plan.get("early_stop") and round_plan.get("fatigue"):
				jobs_to_process, skipped_on_page = _truncate_jobs_for_fatigue_stop(jobs_to_process)
				if skipped_on_page:
					yield {
						"type": "page_partial_stop",
						"page": current_page,
						"round": round_num,
						"jobs_processed": len(jobs_to_process),
						"jobs_skipped": skipped_on_page,
						"message": (
							f"第 {current_page} 页只看了一部分（{len(jobs_to_process)} 个岗位），"
							f"剩余 {skipped_on_page} 个未浏览"
						),
						"stats": stats,
					}

			if not jobs_to_process:
				yield {
					"type": "page_empty",
					"page": current_page,
					"round": round_num,
					"message": (
						f"第 {current_page} 页无岗位，视为本词已扫完，"
						f"下一轮将从第 1 页重新搜"
					),
					"stats": stats,
				}
				round_page_reset = True
				break

			for event in _process_scout_jobs(
				scout, analysis, cache, channel, jobs_to_process,
				current_page=current_page,
				profile=profile,
				store=store,
				ai_service=ai_service,
				criteria=active_criteria,
				scout_filters=filters,
				stats=stats,
				passed_jobs=passed_jobs,
				stop_event=stop_event,
				pause_event=pause_event,
				work_schedule_periods=schedule_periods,
				platform=platform,
			):
				yield event
				if event.get("type") == "job_passed" and depth.enabled:
					depth.record_pass()
				if event.get("type") == "stopped":
					return

			yield _enrich_scout_event(
				{
					"type": "page_done",
					"has_more": has_more,
					"message": f"第 {current_page} 页侦察完成",
				},
				stats,
				page=current_page,
				query=round_query,
				round_num=round_num,
			)

			if not has_more:
				pending_query_exhaust_page = current_page
				cooldown_h = query_exhaust_cooldown_sec / 3600
				if depth.enabled:
					pending_query_advance_on_exhaust = True
					exhaust_msg = (
						f"「{round_query}」在第 {current_page} 页后 BOSS 返回无更多岗位，"
						f"列表已扫完，将记入冷却并切换下一搜索词"
					)
				elif query_exhaust_cooldown_sec > 0:
					pending_query_advance_on_exhaust = True
					exhaust_msg = (
						f"「{round_query}」在第 {current_page} 页后 BOSS 返回无更多岗位，"
						f"列表已扫完，冷却 {cooldown_h:g} 小时后再搜"
					)
				else:
					exhaust_msg = (
						f"「{round_query}」在第 {current_page} 页后 BOSS 返回无更多岗位，"
						f"本词列表已扫完，下一轮将从第 1 页重新搜"
					)
				yield {
					"type": "scout_list_exhausted",
					"page": current_page,
					"round": round_num,
					"query": round_query,
					"switch_query": depth.enabled,
					"cooldown_hours": cooldown_h if query_exhaust_cooldown_sec > 0 else 0,
					"message": exhaust_msg,
					"stats": stats,
				}
				round_pages_exhausted = True
				break

			if effective_cap is not None and pages_this_round >= effective_cap:
				if round_plan.get("early_stop"):
					stats["search"]["rounds_early_stopped"] += 1
					yield {
						"type": "round_early_stop",
						"round": round_num,
						"planned_cap": round_plan.get("planned_cap"),
						"effective_cap": effective_cap,
						"pages_scanned": pages_this_round,
						"fatigue": round_plan.get("fatigue", False),
						"stop_reason": round_plan.get("stop_reason", ""),
						"message": (
							f"本轮提前结束（{pages_this_round}/{round_plan.get('planned_cap')} 页）"
							f"：{round_plan.get('stop_reason', '看累了')}"
						),
						"stats": stats,
					}
				else:
					yield {
						"type": "round_page_cap",
						"round": round_num,
						"page_cap": effective_cap,
						"message": f"本轮已扫描 {effective_cap} 页，即将开始下一轮…",
						"stats": stats,
					}
				break

			current_page += 1
			_sync_search_progress(stats, page=current_page, round_num=round_num, query=round_query)
			yield _enrich_scout_event(
				{
					"type": "page_turn",
					"next_page": current_page,
					"message": f"第 {current_page - 1} 页完成，准备翻第 {current_page} 页…",
				},
				stats,
				page=current_page,
				query=round_query,
				round_num=round_num,
			)
			for ev in _yield_between_pages(
				stop_event, pause_event,
				stats=stats, passed_jobs=passed_jobs, next_page=current_page,
			):
				yield ev
				if ev.get("type") == "stopped":
					return

		if round_page_reset or round_pages_exhausted:
			next_page_for_keyword = start_page
		else:
			next_page_for_keyword = current_page + 1

		if not continuous:
			yield {
				"type": "done",
				"round": round_num,
				"jobs": passed_jobs,
				"stats": stats,
				"message": "侦察 AI 任务完成",
			}
			return

		if round_plan.get("early_stop") and round_plan.get("fatigue"):
			round_pause = _jitter_wait(
				_FATIGUE_REST_MIN_SEC,
				_FATIGUE_REST_MAX_SEC,
				long_prob=0.0,
			)
			pause_type = "round_fatigue_pause"
			pause_label = "疲劳休息"
		else:
			round_pause = _human_round_cooldown()
			pause_type = "round_pause"
			pause_label = "本轮休息"

		yield _enrich_scout_event(
			{
				"type": "round_done",
				"message": f"第 {round_num} 轮侦察完成，{pause_label} {round_pause:.0f} 秒后开始下一轮…",
			},
			stats,
			page=current_page,
			query=round_query,
			round_num=round_num,
		)
		round_num += 1
		yield _enrich_scout_event(
			{
				"type": pause_type,
				"pause_sec": round(round_pause, 1),
				"fatigue": round_plan.get("fatigue", False),
				"message": f"{pause_label} {round_pause:.0f} 秒后开始下一轮…",
			},
			stats,
			page=current_page,
			query=round_query,
			round_num=round_num,
		)
		for ev in _yield_sleep(
			stop_event, round_pause, pause_event=pause_event,
			label=pause_label, stats=stats, passed_jobs=passed_jobs,
		):
			yield ev
			if ev.get("type") == "stopped":
				return
		yield _enrich_scout_event(
			{
				"type": "round_resume",
				"message": "休息结束，继续搜岗",
			},
			stats,
			page=current_page,
			query=round_query,
			round_num=round_num,
		)
