from pathlib import Path
from threading import Event
from unittest.mock import MagicMock

import pytest

from pet_boss.agents.pipeline import (
	_human_scout_delay,
	_jitter_wait,
	_job_browse_plan,
	_plan_round_browsing,
	_round_page_cap,
	_should_refresh_home_for_round,
	iter_dual_agent_pipeline,
)
from pet_boss.agents.scout_hard_filter import ScoutFilterConfig
from pet_boss.cache.store import CacheStore
from pet_boss.profile.models import ParsedResume, UserProfile
from pet_boss.search_filters import SearchFilterCriteria, SearchPipelineResult, SearchPipelineStats


def _profile() -> UserProfile:
	return UserProfile(
		parsed_resume=ParsedResume(
			skills=["Golang"],
			tools=["K8s"],
			city="广州",
			summary="后端",
		),
	)


def _job(title: str, *, job_id: str, security_id: str) -> dict:
	return {
		"job_id": job_id,
		"security_id": security_id,
		"title": title,
		"company": "测试公司",
		"salary": "20-30K",
		"city": "广州",
		"skills": ["Golang"],
	}


def test_enrich_scout_event_prefers_explicit_page_and_query():
	from pet_boss.agents.pipeline import _enrich_scout_event

	stats = {"search": {"current_page": 3, "current_query": "旧词", "current_round": 2}}
	payload = _enrich_scout_event(
		{"type": "page_start", "message": "test"},
		stats,
		page=16,
		query="后端开发",
		round_num=10,
	)
	assert payload["page"] == 16
	assert payload["query"] == "后端开发"
	assert payload["round"] == 10
	assert payload["stats"]["search"]["current_page"] == 3


def test_yield_sleep_heartbeat_includes_page_from_stats(monkeypatch):
	from pet_boss.agents.pipeline import _yield_sleep

	def fake_sleep(_stop, _seconds, *, pause_event=None, label=""):
		yield {"type": "scout_heartbeat", "remaining_sec": 12, "message": f"{label}…"}
		yield {"type": "_sleep_done", "stopped": False}

	monkeypatch.setattr("pet_boss.agents.pipeline._iter_sleep_with_heartbeats", fake_sleep)
	stats = {"search": {"current_page": 20, "current_query": "AI应用开发"}}
	events = list(_yield_sleep(None, 60, label="本轮休息", stats=stats))
	heartbeats = [e for e in events if e.get("type") == "scout_heartbeat"]
	assert heartbeats
	assert heartbeats[0]["page"] == 20
	assert heartbeats[0]["stats"]["search"]["current_page"] == 20


def test_iter_search_pipeline_emits_progress_while_fetching(monkeypatch):
	import time
	from concurrent.futures import Future
	from pet_boss.agents.pipeline import _iter_search_pipeline_with_progress

	stats = {"search": {"current_page": 4, "current_query": "后端开发", "current_round": 2}}
	result = SearchPipelineResult(
		items=[],
		has_more=False,
		stats=SearchPipelineStats(),
	)
	client = MagicMock()
	client._dispatch_browser = True
	platform = MagicMock()
	platform._client = client
	future: Future[dict] = Future()

	def fake_submit(func, /, *args, **kwargs):
		future.set_result(func(*args, **kwargs))
		return future

	monkeypatch.setattr("pet_boss.web.browser_executor.submit_browser_task", fake_submit)
	monkeypatch.setattr(
		"pet_boss.search_filters.fetch_search_page_raw",
		lambda *a, **k: {"code": 0, "zpData": {"jobList": [], "hasMore": False}},
	)
	monkeypatch.setattr(
		"pet_boss.search_filters.process_search_page_result",
		lambda *a, **k: result,
	)

	events = list(_iter_search_pipeline_with_progress(
		platform, MagicMock(), MagicMock(),
		criteria=SearchFilterCriteria(query="后端开发"),
		start_page=4,
		max_pages=1,
		stop_event=None,
		pause_event=None,
		stats=stats,
		passed_jobs=[],
		page=4,
		round_num=2,
		query="后端开发",
	))
	progress = [e for e in events if isinstance(e, dict) and e.get("type") == "search_progress"]
	assert len(progress) >= 1
	assert progress[0]["page"] == 4
	assert events[-1] is result


def test_round_page_cap_random_range():
	for _ in range(30):
		cap = _round_page_cap(max_pages=None, continuous=True)
		assert cap is not None
		assert 2 <= cap <= 10


def test_jitter_wait_base_range_without_long_pause():
	for _ in range(50):
		d = _jitter_wait(3.0, 8.0, long_prob=0.0)
		assert 1.8 <= d <= 11.2


def test_human_scout_delay_can_include_long_pause():
	for _ in range(30):
		d = _human_scout_delay()
		assert d >= 1.79


def test_job_browse_plan_modes():
	modes = {_job_browse_plan()[0] for _ in range(200)}
	assert modes <= {"skip", "glance", "normal", "deep"}
	assert len(modes) >= 3


def test_job_browse_plan_skip_streak_boost():
	skip_base = sum(1 for _ in range(800) if _job_browse_plan(in_skip_streak=False)[0] == "skip")
	skip_chain = sum(1 for _ in range(800) if _job_browse_plan(in_skip_streak=True)[0] == "skip")
	assert skip_chain > skip_base * 1.4


def test_glance_dwell_is_hover_range():
	for _ in range(30):
		mode, dwell = _job_browse_plan()
		if mode == "glance":
			assert 0.18 <= dwell <= 1.12
			return
	pytest.skip("no glance sample in 30 draws")


def test_plan_round_browsing_never_early_stops():
	plans = [_plan_round_browsing(10) for _ in range(50)]
	assert all(p["early_stop"] is False for p in plans)
	assert all(p["effective_cap"] == p["planned_cap"] == 10 for p in plans)
	assert all(p["fatigue"] is False for p in plans)


def test_iter_pipeline_emits_progress_events(tmp_path: Path, monkeypatch):
	cache = CacheStore(tmp_path / "boss_agent.db")
	platform = MagicMock()
	logger = MagicMock()

	def fake_search(*_args, **_kwargs):
		return SearchPipelineResult(
			items=[_job("Golang 工程师", job_id="j1", security_id="s1")],
			has_more=False,
			total=1,
			stats=SearchPipelineStats(pages_scanned=1, jobs_seen=1, jobs_matched=1),
		)

	monkeypatch.setattr(
		"pet_boss.agents.pipeline.run_search_pipeline",
		fake_search,
	)
	monkeypatch.setattr(
		"pet_boss.agents.pipeline._job_browse_plan",
		lambda in_skip_streak=False: ("normal", 0.01),
	)
	monkeypatch.setattr(
		"pet_boss.agents.pipeline._plan_round_browsing",
		lambda cap: {
			"planned_cap": cap,
			"effective_cap": cap,
			"early_stop": False,
			"fatigue": False,
			"stop_reason": "",
		},
	)

	events = list(iter_dual_agent_pipeline(
		platform, cache, logger,
		criteria=SearchFilterCriteria(query="Golang", city="广州"),
		profile=_profile(),
		store=None,
		ai_service=None,
		scout_filters=ScoutFilterConfig.from_payload({
			"salary": True,
			"salary_range": {"min": "10", "max": "50"},
		}),
		pass_score=50,
		max_pages=1,
		continuous=False,
	))

	types = [e["type"] for e in events]
	assert "start" in types
	assert "page_start" in types
	assert "scout_seen" in types
	assert "done" in types


def test_pipeline_resumes_page_after_fatigue_round(tmp_path: Path, monkeypatch):
	"""疲劳休息后应从上一轮结束页的下一页继续，而非回到第 1 页。"""
	cache = CacheStore(tmp_path / "boss_agent.db")
	platform = MagicMock()
	logger = MagicMock()
	stop = Event()
	page_starts: list[int] = []

	def fake_search(*_args, **kwargs):
		return SearchPipelineResult(
			items=[_job("Golang 工程师", job_id="j1", security_id="s1")],
			has_more=True,
			total=30,
			stats=SearchPipelineStats(pages_scanned=1, jobs_seen=1, jobs_matched=1),
		)

	def fake_process(*_args, **_kwargs):
		yield {"type": "scout_browse_skip", "stats": {}}

	monkeypatch.setattr("pet_boss.agents.pipeline.run_search_pipeline", fake_search)
	monkeypatch.setattr("pet_boss.agents.pipeline._round_page_cap", lambda **_k: 5)
	monkeypatch.setattr(
		"pet_boss.agents.pipeline._plan_round_browsing",
		lambda _cap: {
			"planned_cap": 5,
			"effective_cap": 2,
			"early_stop": True,
			"fatigue": True,
			"stop_reason": "看累了",
		},
	)
	monkeypatch.setattr("pet_boss.agents.pipeline._process_scout_jobs", fake_process)
	monkeypatch.setattr("pet_boss.agents.pipeline._refresh_browser_home_for_round", lambda _p: None)
	monkeypatch.setattr("pet_boss.agents.pipeline._human_round_home_refresh_delay", lambda: 0)
	monkeypatch.setattr("pet_boss.agents.pipeline._human_round_cooldown", lambda: 0)
	monkeypatch.setattr("pet_boss.agents.pipeline._jitter_wait", lambda *_a, **_k: 0)
	monkeypatch.setattr("pet_boss.agents.pipeline._sleep_until_stop", lambda *_a, **_k: False)
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_before_page", lambda *_a, **_k: iter(()))
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_between_pages", lambda *_a, **_k: iter(()))
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_while_paused", lambda *_a, **_k: iter(()))
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_sleep", lambda *_a, **_k: iter(()))

	for ev in iter_dual_agent_pipeline(
		platform, cache, logger,
		criteria=SearchFilterCriteria(query="Golang", city="广州"),
		profile=_profile(),
		store=None,
		ai_service=None,
		scout_filters=ScoutFilterConfig(),
		pass_score=50,
		continuous=True,
		stop_event=stop,
	):
		if ev.get("type") == "page_start":
			page_starts.append(ev["page"])
			if len(page_starts) >= 3:
				stop.set()
		if ev.get("type") == "stopped":
			break

	assert page_starts[:3] == [1, 2, 3]


def test_should_refresh_home_only_at_start_page():
	assert _should_refresh_home_for_round(current_page=1, start_page=1) is True
	assert _should_refresh_home_for_round(current_page=13, start_page=1) is False


def test_pipeline_skips_home_refresh_on_deep_page_round(tmp_path: Path, monkeypatch):
	cache = CacheStore(tmp_path / "boss_agent.db")
	platform = MagicMock()
	logger = MagicMock()
	stop = Event()
	refresh_calls = 0

	def fake_search(*_args, **_kwargs):
		return SearchPipelineResult(
			items=[_job("Golang 工程师", job_id="j1", security_id="s1")],
			has_more=True,
			total=30,
			stats=SearchPipelineStats(pages_scanned=1, jobs_seen=1, jobs_matched=1),
		)

	def fake_process(*_args, **_kwargs):
		yield {"type": "scout_browse_skip", "stats": {}}

	def track_refresh(_platform):
		nonlocal refresh_calls
		refresh_calls += 1

	monkeypatch.setattr("pet_boss.agents.pipeline.run_search_pipeline", fake_search)
	monkeypatch.setattr("pet_boss.agents.pipeline._round_page_cap", lambda **_k: 5)
	monkeypatch.setattr(
		"pet_boss.agents.pipeline._plan_round_browsing",
		lambda _cap: {
			"planned_cap": 5,
			"effective_cap": 1,
			"early_stop": False,
			"fatigue": False,
			"stop_reason": "",
		},
	)
	monkeypatch.setattr("pet_boss.agents.pipeline._process_scout_jobs", fake_process)
	monkeypatch.setattr("pet_boss.agents.pipeline._refresh_browser_home_for_round", track_refresh)
	monkeypatch.setattr("pet_boss.agents.pipeline._human_round_home_refresh_delay", lambda: 0)
	monkeypatch.setattr("pet_boss.agents.pipeline._human_round_cooldown", lambda: 0)
	monkeypatch.setattr("pet_boss.agents.pipeline._jitter_wait", lambda *_a, **_k: 0)
	monkeypatch.setattr("pet_boss.agents.pipeline._sleep_until_stop", lambda *_a, **_k: False)
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_before_page", lambda *_a, **_k: iter(()))
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_between_pages", lambda *_a, **_k: iter(()))
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_while_paused", lambda *_a, **_k: iter(()))
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_sleep", lambda *_a, **_k: iter(()))

	skip_events: list[dict] = []
	for ev in iter_dual_agent_pipeline(
		platform, cache, logger,
		criteria=SearchFilterCriteria(query="Golang", city="广州"),
		profile=_profile(),
		store=None,
		ai_service=None,
		scout_filters=ScoutFilterConfig(),
		pass_score=50,
		continuous=True,
		stop_event=stop,
	):
		if ev.get("type") == "round_home_refresh_skip" and ev.get("page", 0) > 1:
			skip_events.append(ev)
		if ev.get("type") == "page_start" and ev.get("page") == 2:
			stop.set()
		if ev.get("type") == "stopped":
			break

	assert refresh_calls == 1
	assert len(skip_events) >= 1
	assert skip_events[0]["page"] == 2


def test_pipeline_switches_query_when_list_exhausted(tmp_path: Path, monkeypatch):
	"""多搜索词时列表扫完应记入冷却并切换下一词。"""
	cache = CacheStore(tmp_path / "boss_agent.db")
	platform = MagicMock()
	logger = MagicMock()
	stop = Event()

	def fake_search(*_args, **_kwargs):
		return SearchPipelineResult(
			items=[_job("Golang 工程师", job_id="j1", security_id="s1")],
			has_more=False,
			total=1,
			stats=SearchPipelineStats(pages_scanned=1, jobs_seen=1, jobs_matched=1),
		)

	def fake_process(*_args, **_kwargs):
		yield {"type": "scout_browse_skip", "stats": {}}

	monkeypatch.setattr("pet_boss.agents.pipeline.run_search_pipeline", fake_search)
	monkeypatch.setattr("pet_boss.agents.pipeline._round_page_cap", lambda **_k: 1)
	monkeypatch.setattr(
		"pet_boss.agents.pipeline._plan_round_browsing",
		lambda _cap: {
			"planned_cap": 1,
			"effective_cap": 1,
			"early_stop": False,
			"fatigue": False,
			"stop_reason": "",
		},
	)
	monkeypatch.setattr("pet_boss.agents.pipeline._process_scout_jobs", fake_process)
	monkeypatch.setattr("pet_boss.agents.pipeline._refresh_browser_home_for_round", lambda _p: None)
	monkeypatch.setattr("pet_boss.agents.pipeline._human_round_home_refresh_delay", lambda: 0)
	monkeypatch.setattr("pet_boss.agents.pipeline._human_round_cooldown", lambda: 0)
	monkeypatch.setattr("pet_boss.agents.pipeline._jitter_wait", lambda *_a, **_k: 0)
	monkeypatch.setattr("pet_boss.agents.pipeline._sleep_until_stop", lambda *_a, **_k: False)
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_before_page", lambda *_a, **_k: iter(()))
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_between_pages", lambda *_a, **_k: iter(()))
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_while_paused", lambda *_a, **_k: iter(()))
	monkeypatch.setattr("pet_boss.agents.pipeline._yield_sleep", lambda *_a, **_k: iter(()))

	events: list[dict] = []
	for ev in iter_dual_agent_pipeline(
		platform, cache, logger,
		criteria=SearchFilterCriteria(query="词A", city="广州"),
		profile=_profile(),
		store=None,
		ai_service=None,
		scout_filters=ScoutFilterConfig(),
		pass_score=50,
		continuous=True,
		stop_event=stop,
		search_queries=["词A", "词B"],
		query_pass_depth_min=5,
		query_pass_depth_max=5,
		query_exhaust_cooldown_sec=3600,
	):
		events.append(ev)
		if ev.get("type") == "round_start" and ev.get("query") == "词B":
			stop.set()
			break

	exhausted = [e for e in events if e.get("type") == "scout_list_exhausted"]
	assert exhausted and exhausted[0].get("switch_query") is True
	depth_met = [e for e in events if e.get("type") == "scout_query_depth_met" and e.get("list_exhausted")]
	assert depth_met
	assert any(e.get("type") == "scout_query_switch" and e.get("query") == "词B" for e in events)
