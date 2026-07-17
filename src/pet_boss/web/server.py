"""用户画像智能系统 Web 服务。"""

from __future__ import annotations

import asyncio
import json
import re
import time
import threading
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from pathlib import Path
from threading import Event, Thread
from typing import Any, TypeVar

from pet_boss.output import Logger
from pet_boss.web.boss_service import BossWebService
from pet_boss.web.profile_api import ProfileWebError, ProfileWebService
from pet_boss.secretary.config import SecretaryConfigStore
from pet_boss.ai.token_usage import get_token_usage_store, get_token_usage_summary, save_token_pricing

STATIC_DIR = Path(__file__).parent / "static"
PET_ASSETS_DIR = STATIC_DIR / "pet"

# SSE 订阅队列：岗位浏览信息会推送，但积压时可丢；岗位通过不可丢
_SCOUT_SSE_QUEUE_MAX = 256
_SCOUT_EVENT_RING_MAX = 48
_SCOUT_PASSED_JOBS_MAX = 200
# 岗位级浏览事件（显示跳过/发现等）；可丢，不进 ring 回放
_SCOUT_SSE_BROWSE_TYPES = frozenset({
	"scout_seen",
	"scout_glance",
	"scout_browse_skip",
	"scout_history_skip",
	"scout_filter",
	"scout_skip",
	"scout_duplicate",
})
# 允许推送到 Web SSE 的事件白名单
_SCOUT_SSE_FANOUT_TYPES = frozenset({
	"start",
	"stopped",
	"done",
	"job_passed",
	"job_filtered",
	"analysis_start",
	"account_risk",
	"round_start",
	"round_done",
	"round_pause",
	"round_fatigue_pause",
	"round_resume",
	"round_page_cap",
	"round_early_stop",
	"off_hours_pause",
	"work_hours_resume",
	"scout_query_switch",
	"scout_list_exhausted",
	"scout_query_cooldown",
	"scout_query_depth_met",
	"scout_strategy_plan",
	"page_start",
	"page_done",
	"browser_stuck",
	"browser_restart_begin",
	"browser_restart_failed",
	"browser_session_lost",
	"browser_restarted",
	"monitor_start",
	"monitor_alert",
	"monitor_stall",
	"monitor_recovered",
	"monitor_browser_restart",
	"monitor_browser_open",
	"monitor_stopped",
	"page_hidden_continue",
	"page_visible_resume",
	"boss_browser_closed",
}) | _SCOUT_SSE_BROWSE_TYPES
# 队列紧张时可丢：页码/浏览碎事件；岗位通过不可丢
_SCOUT_SSE_SOFT_TYPES = frozenset({
	"page_start",
	"page_done",
	"page_turn",
	"search_fetch",
	"search_progress",
	"monitor_ok",
	"monitor_token",
	"scout_heartbeat",
}) | _SCOUT_SSE_BROWSE_TYPES
# 兼容旧名
_SCOUT_SSE_DROPPABLE_TYPES = _SCOUT_SSE_SOFT_TYPES
_SCOUT_SSE_CRITICAL_TYPES = frozenset({
	"job_passed",
	"job_filtered",
	"analysis_start",
	"stopped",
	"done",
	"account_risk",
	"round_start",
	"round_done",
	"round_pause",
	"round_fatigue_pause",
	"round_resume",
	"scout_query_switch",
	"scout_list_exhausted",
	"off_hours_pause",
	"work_hours_resume",
})
# ring 回放只留关键事件，避免浏览碎事件冲掉 job_passed
_SCOUT_SSE_RING_TYPES = _SCOUT_SSE_CRITICAL_TYPES | frozenset({
	"start",
	"page_start",
	"page_done",
	"round_page_cap",
	"round_early_stop",
	"scout_strategy_plan",
	"browser_stuck",
	"browser_restart_begin",
	"browser_restart_failed",
	"browser_session_lost",
	"browser_restarted",
	"monitor_alert",
	"monitor_stall",
	"monitor_recovered",
	"monitor_browser_restart",
})
# ack 仅表示 Web UI 在线；超过此秒数标 ui_offline，不停管道
_SCOUT_UI_ACK_ONLINE_SEC = 90.0
_SCOUT_PAUSE_ACK_GRACE_SEC = 45.0  # 计划休息剩余时间之外再留宽限（watchdog 豁免）
# 后端 watchdog：非休息期无进展超时 → 判定真卡死并停止
_SCOUT_WATCHDOG_IDLE_SEC = 180.0
_SCOUT_WATCHDOG_POLL_SEC = 5.0
_SCOUT_PAGE_SYNC_TYPES = frozenset({
	"page_start",
	"search_fetch",
	"search_progress",
	"page_done",
	"page_turn",
	"round_start",
	"round_resume",
	"scout_query_switch",
})
_SCOUT_PAUSE_EVENT_TYPES = frozenset({
	"round_pause",
	"round_pause_tick",
	"round_fatigue_pause",
	"fatigue_rest",
	"off_hours_pause",
	"work_hours_pause",  # 兼容旧名
	"work_hours_wait",
	"scout_query_cooldown",
})
# 下班等不定长暂停：无 pause_sec 时也要豁免 watchdog（默认按到次日上班估算）
_SCOUT_INDEFINITE_PAUSE_TYPES = frozenset({
	"off_hours_pause",
	"work_hours_pause",
	"work_hours_wait",
})
_SCOUT_INDEFINITE_PAUSE_DEFAULT_SEC = 14 * 3600.0
# 兼容旧测试名
_SCOUT_WEB_ACK_STALE_SEC = _SCOUT_UI_ACK_ONLINE_SEC
_SCOUT_WEB_ACK_STALE_HIDDEN_SEC = 1800.0

_scout_live_lock = threading.Lock()
_scout_launch_lock = threading.Lock()
_scout_live: dict[str, Any] = {
	"active": False,
	"run_id": "",
	"ack_at": 0.0,
	"server_page": 0,
	"server_query": "",
	"server_type": "",
	"server_at": 0.0,
	"client_page": 0,
	"client_query": "",
	"client_type": "",
	"desync_since": 0.0,
	"page_hidden": False,
	"pause_until": 0.0,
	"pause_event": None,
	"stop_event": None,
	"subscribers": [],  # list[{"queue", "loop"}]
	"event_ring": deque(maxlen=_SCOUT_EVENT_RING_MAX),
	"last_progress_at": 0.0,
	"ui_stale": False,
	"last_warn": "",
	"last_error": "",
	"last_message": "",
	"producer_thread": None,
	"watchdog_stop": None,
	"passed_jobs": [],
	"stats": None,
}


def _start_scout_live(*, run_id: str = "") -> None:
	now = time.time()
	with _scout_live_lock:
		_scout_live["active"] = True
		_scout_live["run_id"] = run_id or uuid.uuid4().hex[:12]
		_scout_live["ack_at"] = now
		_scout_live["server_page"] = 0
		_scout_live["client_page"] = 0
		_scout_live["desync_since"] = 0.0
		_scout_live["page_hidden"] = False
		_scout_live["pause_until"] = 0.0
		_scout_live["last_warn"] = ""
		_scout_live["last_error"] = ""
		_scout_live["last_message"] = ""
		_scout_live["last_progress_at"] = now
		_scout_live["ui_stale"] = False
		_scout_live["event_ring"] = deque(maxlen=_SCOUT_EVENT_RING_MAX)
		_scout_live["subscribers"] = []
		_scout_live["passed_jobs"] = []
		_scout_live["stats"] = None


def _stop_scout_live() -> None:
	with _scout_live_lock:
		_scout_live["active"] = False
		_scout_live["pause_event"] = None
		_scout_live["stop_event"] = None
		_scout_live["producer_thread"] = None
		wd = _scout_live.get("watchdog_stop")
		_scout_live["watchdog_stop"] = None
		_scout_live["subscribers"] = []
	if isinstance(wd, Event):
		wd.set()


def _bind_scout_control(
	*,
	pause_event: Event | None,
	stop_event: Event | None = None,
	sse_queue: Any = None,
	sse_loop: Any = None,
) -> None:
	"""绑定管道控制事件；可选附带单个 SSE 订阅者（兼容旧路径）。"""
	with _scout_live_lock:
		_scout_live["pause_event"] = pause_event
		if stop_event is not None:
			_scout_live["stop_event"] = stop_event
		if sse_queue is not None and sse_loop is not None:
			subs = _scout_live.setdefault("subscribers", [])
			subs.append({"queue": sse_queue, "loop": sse_loop})


def _request_stop_scout(msg: str, *, code: str = "SCOUT_STOPPED") -> bool:
	"""请求停止搜岗任务（用户停止 / watchdog）。返回是否成功发出停止信号。"""
	with _scout_live_lock:
		stop_event = _scout_live.get("stop_event")
		if not _scout_live.get("active") or stop_event is None:
			return False
		_scout_live["last_error"] = msg
		_scout_live["last_message"] = msg
	if not stop_event.is_set():
		Logger(level="info").info(f"[scout] {msg}")
		stop_event.set()
		_fanout_scout_item(("error", ProfileWebError(code, msg, status=503)))
	return True


def _queue_put_sync(queue: asyncio.Queue, item: tuple[str, Any]) -> bool:
	"""在事件循环线程入队；满则优先丢 soft 事件，再丢最旧；尽量保留 job_passed。"""
	try:
		queue.put_nowait(item)
		return False
	except asyncio.QueueFull:
		pass

	buf: list[tuple[str, Any]] = []
	while True:
		try:
			buf.append(queue.get_nowait())
		except asyncio.QueueEmpty:
			break

	dropped = False
	maxsize = queue.maxsize if queue.maxsize > 0 else _SCOUT_SSE_QUEUE_MAX
	while len(buf) >= maxsize:
		drop_idx = next(
			(i for i, existing in enumerate(buf) if _scout_sse_item_droppable(existing)),
			None,
		)
		if drop_idx is None:
			if _scout_sse_item_droppable(item):
				for existing in buf:
					try:
						queue.put_nowait(existing)
					except asyncio.QueueFull:
						break
				return True
			buf.pop(0)
		else:
			buf.pop(drop_idx)
		dropped = True

	if dropped and _scout_sse_item_droppable(item) and len(buf) >= max(1, maxsize - 16):
		for existing in buf:
			try:
				queue.put_nowait(existing)
			except asyncio.QueueFull:
				break
		return True

	buf.append(item)
	for existing in buf:
		try:
			queue.put_nowait(existing)
		except asyncio.QueueFull:
			dropped = True
			break
	return dropped


async def _queue_put_drop_oldest(queue: asyncio.Queue, item: tuple[str, Any]) -> bool:
	"""兼容旧测试：异步包装同步入队。"""
	return _queue_put_sync(queue, item)


def _scout_sse_item_droppable(item: tuple[str, Any]) -> bool:
	kind, payload = item
	if kind != "event":
		return False
	if not isinstance(payload, dict):
		return True
	etype = str(payload.get("type") or "")
	if etype in _SCOUT_SSE_CRITICAL_TYPES:
		return False
	return etype in _SCOUT_SSE_DROPPABLE_TYPES or etype in _SCOUT_SSE_SOFT_TYPES


def _scout_should_fanout(item: tuple[str, Any]) -> bool:
	"""决定是否推入 Web SSE：岗位浏览信息会推；心跳等仍不推。"""
	kind, payload = item
	if kind != "event":
		return True
	if not isinstance(payload, dict):
		return True
	etype = str(payload.get("type") or "")
	if etype in _SCOUT_SSE_FANOUT_TYPES:
		return True
	if etype.startswith("monitor_") and etype not in ("monitor_ok", "monitor_token", "monitor_probe"):
		return True
	return False


def _mark_scout_ui_stale(msg: str = "") -> None:
	with _scout_live_lock:
		_scout_live["ui_stale"] = True
		_scout_live["last_warn"] = msg or (
			"Web SSE 消费落后，已丢弃部分浏览/页码事件（岗位通过已优先保留，可从快照补拉）"
		)


def _fanout_scout_item(item: tuple[str, Any]) -> None:
	"""向所有 SSE 订阅者广播；非阻塞入队；积压时优先跳过浏览碎事件。"""
	if not _scout_should_fanout(item):
		return
	with _scout_live_lock:
		subs = list(_scout_live.get("subscribers") or [])
		qsize_hint = 0
		for sub in subs:
			queue = sub.get("queue")
			if queue is not None:
				try:
					qsize_hint = max(qsize_hint, queue.qsize())
				except Exception:
					pass
	if not subs:
		return
	kind, payload = item
	etype = str(payload.get("type") or "") if kind == "event" and isinstance(payload, dict) else ""
	# 队列稍有积压就先停塞浏览碎事件，保住岗位通过/分析
	browse_threshold = max(12, _SCOUT_SSE_QUEUE_MAX // 8)
	soft_threshold = max(24, _SCOUT_SSE_QUEUE_MAX // 4)
	if etype in _SCOUT_SSE_BROWSE_TYPES and qsize_hint >= browse_threshold:
		return
	if qsize_hint >= soft_threshold and _scout_sse_item_droppable(item):
		_mark_scout_ui_stale()
		return

	for sub in subs:
		queue = sub.get("queue")
		loop = sub.get("loop")
		if queue is None or loop is None:
			continue

		def _enqueue(q: asyncio.Queue = queue, it: tuple[str, Any] = item) -> None:
			try:
				if _queue_put_sync(q, it):
					_mark_scout_ui_stale()
			except Exception:
				_mark_scout_ui_stale("Web SSE 入队失败（搜岗继续，岗位可从快照补拉）")

		try:
			loop.call_soon_threadsafe(_enqueue)
		except Exception:
			_mark_scout_ui_stale()


def _push_scout_ui_event(event: dict[str, Any]) -> None:
	"""向 SSE 订阅者注入 UI 事件（页面隐藏提示等）。"""
	_fanout_scout_item(("event", event))


def _attach_scout_subscriber(queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> list[dict[str, Any]]:
	"""注册 SSE 订阅者，返回 ring 缓冲里的历史事件供重放。"""
	with _scout_live_lock:
		subs = _scout_live.setdefault("subscribers", [])
		subs.append({"queue": queue, "loop": loop})
		ring = list(_scout_live.get("event_ring") or [])
		_scout_live["ui_stale"] = False
	return ring


def _detach_scout_subscriber(queue: asyncio.Queue) -> None:
	with _scout_live_lock:
		subs = _scout_live.get("subscribers") or []
		_scout_live["subscribers"] = [s for s in subs if s.get("queue") is not queue]


def _set_scout_page_hidden(hidden: bool) -> dict[str, Any]:
	"""记录页面是否隐藏。隐藏时不暂停管道（搜岗继续）。"""
	with _scout_live_lock:
		was = bool(_scout_live.get("page_hidden"))
		_scout_live["page_hidden"] = hidden
	changed = was != hidden
	if changed:
		if hidden:
			msg = "页面已隐藏/最小化，搜岗继续在后台运行（回到页面后会同步进度）"
			with _scout_live_lock:
				_scout_live["last_warn"] = ""
				_scout_live["last_message"] = msg
			_push_scout_ui_event({
				"type": "page_hidden_continue",
				"message": msg,
			})
		else:
			msg = "页面已恢复显示，正在同步搜岗进度…"
			with _scout_live_lock:
				_scout_live["last_message"] = msg
			_push_scout_ui_event({
				"type": "page_visible_resume",
				"message": msg,
			})
	return {"changed": changed, "hidden": hidden}


def _touch_scout_ack(body: dict[str, Any] | None = None) -> None:
	"""更新 Web UI 在线状态与客户端页码；绝不停止搜岗。"""
	with _scout_live_lock:
		_scout_live["ack_at"] = time.time()
		if not body:
			return
		page = body.get("page")
		if page is not None:
			try:
				_scout_live["client_page"] = int(page)
			except (TypeError, ValueError):
				pass
		query = body.get("query")
		if isinstance(query, str) and query.strip():
			_scout_live["client_query"] = query.strip()
		ev_type = body.get("type")
		if isinstance(ev_type, str) and ev_type.strip():
			_scout_live["client_type"] = ev_type.strip()
	if body and "hidden" in body:
		_set_scout_page_hidden(bool(body.get("hidden")))


def _scout_live_snapshot() -> dict[str, Any]:
	with _scout_live_lock:
		ack_at = float(_scout_live.get("ack_at") or 0.0)
		ack_age = max(0.0, time.time() - ack_at) if _scout_live.get("active") else 0.0
		progress_at = float(_scout_live.get("last_progress_at") or 0.0)
		stats = _scout_live.get("stats")
		passed = list(_scout_live.get("passed_jobs") or [])
		return {
			"active": bool(_scout_live.get("active")),
			"run_id": str(_scout_live.get("run_id") or ""),
			"page_hidden": bool(_scout_live.get("page_hidden")),
			"server_page": int(_scout_live.get("server_page") or 0),
			"server_query": str(_scout_live.get("server_query") or ""),
			"server_type": str(_scout_live.get("server_type") or ""),
			"client_page": int(_scout_live.get("client_page") or 0),
			"client_query": str(_scout_live.get("client_query") or ""),
			"ack_age_sec": ack_age,
			"ui_online": bool(_scout_live.get("active")) and ack_age < _SCOUT_UI_ACK_ONLINE_SEC,
			"ui_stale": bool(_scout_live.get("ui_stale")),
			"progress_age_sec": max(0.0, time.time() - progress_at) if progress_at else 0.0,
			"subscriber_count": len(_scout_live.get("subscribers") or []),
			"last_warn": str(_scout_live.get("last_warn") or ""),
			"last_error": str(_scout_live.get("last_error") or ""),
			"last_message": str(_scout_live.get("last_message") or ""),
			"paused_for_hidden": False,
			"stats": stats if isinstance(stats, dict) else None,
			"passed_jobs": passed,
			"passed_count": len(passed),
		}


def _extend_scout_pause_until(event: dict[str, Any] | None) -> None:
	"""计划休息期内豁免 watchdog 无进展超时。"""
	if not event:
		return
	etype = str(event.get("type") or "")
	if etype == "round_resume" or etype == "work_hours_resume":
		with _scout_live_lock:
			_scout_live["pause_until"] = 0.0
		return
	if etype not in _SCOUT_PAUSE_EVENT_TYPES:
		return
	pause_sec = event.get("pause_sec")
	if pause_sec is None:
		pause_sec = event.get("remaining_sec")
	try:
		sec = float(pause_sec or 0)
	except (TypeError, ValueError):
		sec = 0.0
	# 下班暂停等不定长：事件常无 pause_sec，仍须整段豁免，否则 ~180s 被误杀
	if sec <= 0 and etype in _SCOUT_INDEFINITE_PAUSE_TYPES:
		sec = _SCOUT_INDEFINITE_PAUSE_DEFAULT_SEC
	if sec <= 0:
		return
	until = time.time() + sec + _SCOUT_PAUSE_ACK_GRACE_SEC
	with _scout_live_lock:
		prev = float(_scout_live.get("pause_until") or 0.0)
		if until > prev:
			_scout_live["pause_until"] = until


def _scout_ack_stale_limit_sec() -> float:
	"""兼容旧测试：返回 UI 在线判定阈值（不再用于停管道）。"""
	with _scout_live_lock:
		if _scout_live.get("page_hidden"):
			return _SCOUT_WEB_ACK_STALE_HIDDEN_SEC
		return _SCOUT_WEB_ACK_STALE_SEC


def _scout_in_planned_pause() -> bool:
	with _scout_live_lock:
		until = float(_scout_live.get("pause_until") or 0.0)
		return until > 0.0 and time.time() < until


def _note_server_scout_event(event: dict[str, Any]) -> None:
	etype = str(event.get("type") or "")
	now = time.time()
	stats = event.get("stats") if isinstance(event.get("stats"), dict) else None
	job = event.get("job") if isinstance(event.get("job"), dict) else None

	with _scout_live_lock:
		_scout_live["last_progress_at"] = now
		# ring 只留关键事件，浏览碎事件不进回放缓冲
		ring = _scout_live.get("event_ring")
		if isinstance(ring, deque) and etype in _SCOUT_SSE_RING_TYPES:
			ring.append(event)
		if stats is not None:
			_scout_live["stats"] = stats
			search = stats.get("search") or {}
			page_from_stats = search.get("current_page")
			query_from_stats = search.get("current_query")
			if page_from_stats is not None:
				try:
					pg = int(page_from_stats)
				except (TypeError, ValueError):
					pg = 0
				if pg > 0:
					_scout_live["server_page"] = pg
			if query_from_stats:
				_scout_live["server_query"] = str(query_from_stats)
		if etype == "job_passed" and job:
			jobs = _scout_live.setdefault("passed_jobs", [])
			if not isinstance(jobs, list):
				jobs = []
				_scout_live["passed_jobs"] = jobs
			jobs.append(job)
			if len(jobs) > _SCOUT_PASSED_JOBS_MAX:
				del jobs[:-_SCOUT_PASSED_JOBS_MAX]

	if etype not in _SCOUT_PAGE_SYNC_TYPES:
		msg = event.get("message")
		if isinstance(msg, str) and msg.strip():
			with _scout_live_lock:
				_scout_live["last_message"] = msg.strip()
				_scout_live["server_type"] = etype
				_scout_live["server_at"] = now
		return

	search = (stats or {}).get("search") or {}
	page = event.get("page")
	if page is None:
		page = search.get("current_page")
	query = event.get("query") or search.get("current_query")
	with _scout_live_lock:
		if page is not None:
			try:
				pg = int(page)
			except (TypeError, ValueError):
				pg = 0
			if pg > 0:
				_scout_live["server_page"] = pg
		if query:
			_scout_live["server_query"] = str(query)
		_scout_live["server_type"] = etype
		_scout_live["server_at"] = now
		msg = event.get("message")
		if isinstance(msg, str) and msg.strip():
			_scout_live["last_message"] = msg.strip()


def _scout_ack_age_sec() -> float:
	with _scout_live_lock:
		if not _scout_live["active"]:
			return 0.0
		return max(0.0, time.time() - _scout_live["ack_at"])


def _scout_watchdog_loop(stop_flag: Event) -> None:
	"""后端 watchdog：休息期豁免；否则无进展超时则停任务。"""
	log = Logger(level="info")
	while not stop_flag.wait(_SCOUT_WATCHDOG_POLL_SEC):
		with _scout_live_lock:
			if not _scout_live.get("active"):
				continue
			stop_event = _scout_live.get("stop_event")
			if stop_event is not None and stop_event.is_set():
				continue
			progress_at = float(_scout_live.get("last_progress_at") or 0.0)
		if _scout_in_planned_pause():
			continue
		if progress_at <= 0:
			continue
		idle = time.time() - progress_at
		if idle < _SCOUT_WATCHDOG_IDLE_SEC:
			continue
		msg = (
			f"搜岗无进展超过 {idle:.0f}s（后端 watchdog），"
			f"判定任务卡死，已自动停止"
		)
		log.info(f"[scout] {msg}")
		_request_stop_scout(msg, code="SCOUT_WATCHDOG_IDLE")
		break


def _collect_pet_asset_mtimes() -> dict[str, int]:
	"""返回 pet 素材相对路径 → 修改时间(ms)，供前端 cache bust。"""
	if not PET_ASSETS_DIR.is_dir():
		return {}
	out: dict[str, int] = {}
	for path in PET_ASSETS_DIR.rglob("*"):
		if not path.is_file() or path.name == "desks.json":
			continue
		rel = path.relative_to(PET_ASSETS_DIR).as_posix()
		out[rel] = int(path.stat().st_mtime * 1000)
	return out


def _ensure_multipart() -> None:
	try:
		import multipart  # noqa: F401
	except ImportError as exc:
		raise ImportError(
			"文件上传需要 python-multipart：pip install python-multipart  或  pip install 'boss-agent-cli[web]'"
		) from exc


def _json_response(data: dict[str, Any], *, status: int = 200):
	from starlette.responses import JSONResponse
	return JSONResponse(data, status_code=status)


def _ok(data: Any) -> dict[str, Any]:
	return {"ok": True, "data": data}


def _err(exc: ProfileWebError) -> dict[str, Any]:
	return {
		"ok": False,
		"error": {"code": exc.code, "message": exc.message},
	}


def _web_ai_service(data_dir: Path):
	from pet_boss.ai.config import AIConfigStore, resolve_embedding_model, rag_enabled as config_rag_enabled
	from pet_boss.ai.service import AIService
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
		rag_enabled=config_rag_enabled(config),
	)


def _secretary_parse_uploaded_pdf(data_dir: Path, resume_name: str) -> dict[str, Any]:
	from pet_boss.agents.secretary_ai import SecretaryAI
	from pet_boss.cache.store import CacheStore
	from pet_boss.profile.store import ProfileStore
	from pet_boss.secretary.resume_intake import SecretaryIntakeError

	safe_name = resume_name.strip() or "default"
	pdf_path = data_dir / "resumes" / "uploads" / f"{safe_name}.pdf"
	if not pdf_path.is_file():
		raise ProfileWebError("NOT_FOUND", f"未找到已上传的简历 PDF：{safe_name}", status=404)

	pstore = ProfileStore(data_dir)
	try:
		with CacheStore(data_dir / "cache" / "boss_agent.db") as cache:
			secretary = SecretaryAI(
				cache,
				SecretaryConfigStore(data_dir),
				data_dir=data_dir,
				ai_service=_web_ai_service(data_dir),
				profile_store=pstore,
			)
			return secretary.parse_resume_pdf(pdf_path, resume_name=safe_name)
	except SecretaryIntakeError as exc:
		raise ProfileWebError("SECRETARY_INTAKE_FAILED", str(exc), status=422) from exc


def _secretary_daily_action_plan(data_dir: Path, *, refresh: bool = False) -> dict[str, Any]:
	from pet_boss.agents.secretary_ai import SecretaryAI
	from pet_boss.cache.store import CacheStore
	from pet_boss.profile.store import ProfileStore
	from pet_boss.secretary.config import SecretaryConfigStore

	cache_path = data_dir / "cache" / "boss_agent.db"
	with CacheStore(cache_path) as cache, ProfileStore(data_dir) as profile_store:
		secretary = SecretaryAI(
			cache,
			SecretaryConfigStore(data_dir),
			data_dir=data_dir,
			ai_service=_web_ai_service(data_dir),
			profile_store=profile_store,
		)
		if not refresh:
			cached = secretary.load_daily_action_plan()
			if cached:
				return cached
		return secretary.build_daily_action_plan()


def _secretary_scout_strategy_plan(data_dir: Path) -> dict[str, Any]:
	from pet_boss.profile.store import ProfileStore

	with ProfileStore(data_dir) as profile_store:
		plan = profile_store.load_scout_strategy_plan()
	return {"plan": plan}


def _secretary_daily_report(data_dir: Path, date_param: str) -> dict[str, Any]:
	from datetime import date as date_cls

	from pet_boss.agents.secretary_ai import SecretaryAI, resolve_report_date
	from pet_boss.cache.store import CacheStore
	from pet_boss.profile.store import ProfileStore

	if date_param == "today":
		target = date_cls.today()
	else:
		target = resolve_report_date(date_param)
	with CacheStore(data_dir / "cache" / "boss_agent.db") as cache:
		pstore = ProfileStore(data_dir)
		secretary = SecretaryAI(
			cache,
			SecretaryConfigStore(data_dir),
			data_dir=data_dir,
			profile_store=pstore,
		)
		report = secretary.build_report(target)
		data = report["data"]
		return {
			"date": data["date"],
			"summary": data["summary"],
			"daily_picks": data.get("daily_picks") or [],
			"markdown": report["markdown"],
			"has_picks": bool(data.get("daily_picks")),
		}


def _secretary_daily_pick_dates(data_dir: Path, limit: int = 120) -> dict[str, Any]:
	from datetime import date as date_cls

	from pet_boss.agents.secretary_ai import SecretaryAI
	from pet_boss.cache.store import CacheStore
	from pet_boss.profile.store import ProfileStore

	with CacheStore(data_dir / "cache" / "boss_agent.db") as cache:
		pstore = ProfileStore(data_dir)
		secretary = SecretaryAI(
			cache,
			SecretaryConfigStore(data_dir),
			data_dir=data_dir,
			profile_store=pstore,
		)
		dates = secretary.list_report_dates(limit=limit)
	return {
		"today": date_cls.today().isoformat(),
		"dates": dates,
	}


def _secretary_send_daily_email(data_dir: Path, date_param: str = "today") -> dict[str, Any]:
	from datetime import date as date_cls

	from pet_boss.agents.secretary_ai import SecretaryAI, resolve_report_date
	from pet_boss.cache.store import CacheStore
	from pet_boss.profile.store import ProfileStore
	from pet_boss.secretary.config import SecretaryConfigStore
	from pet_boss.secretary.email_sender import EmailSendError

	cfg_store = SecretaryConfigStore(data_dir)
	cfg = cfg_store.load()
	if not cfg_store.is_email_configured(cfg):
		raise ProfileWebError(
			"EMAIL_NOT_CONFIGURED",
			"请先在秘书 AI 工位配置收件邮箱与 SMTP 授权码",
			status=400,
		)

	if date_param == "today":
		target = date_cls.today()
	else:
		target = resolve_report_date(date_param)

	with CacheStore(data_dir / "cache" / "boss_agent.db") as cache:
		with ProfileStore(data_dir) as pstore:
			secretary = SecretaryAI(
				cache,
				cfg_store,
				data_dir=data_dir,
				profile_store=pstore,
			)
			report = secretary.build_report(target)
			data = report["data"]
			summary = data.get("summary") or {}
			has_content = bool(data.get("daily_picks")) or int(summary.get("passed_count") or 0) > 0
			if not has_content:
				return {
					"sent": False,
					"skipped": True,
					"reason": "no_content",
					"date": data["date"],
					"summary": summary,
				}
			try:
				result = secretary.send_daily_email(target, markdown=report["markdown"])
			except EmailSendError as exc:
				raise ProfileWebError(
					"EMAIL_FAILED",
					str(exc) or "日报邮件发送失败",
					status=502,
				) from exc
			return {
				"sent": True,
				"skipped": False,
				"date": data["date"],
				"summary": summary,
				**result,
			}


_T = TypeVar("_T")


async def _run_blocking(func: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
	"""在默认线程池执行普通阻塞逻辑（文件/DB/httpx，不涉及 patchright）。"""
	if kwargs:
		return await asyncio.to_thread(lambda: func(*args, **kwargs))
	return await asyncio.to_thread(func, *args)


async def _run_browser_blocking(func: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
	"""在 patchright 专用单线程中执行，避免 greenlet 跨线程错误。"""
	from pet_boss.web.browser_executor import _BROWSER_EXECUTOR

	loop = asyncio.get_running_loop()
	if kwargs:
		return await loop.run_in_executor(_BROWSER_EXECUTOR, lambda: func(*args, **kwargs))
	return await loop.run_in_executor(_BROWSER_EXECUTOR, func, *args)


def _stream_scout_events(
	boss_svc: BossWebService,
	*,
	query: str,
	city: str | None,
	city_code: str | None = None,
	district_code: str | None = None,
	page: int,
	scout_filters: dict[str, bool] | list[str] | None,
	pass_score: int,
	career_stage: dict[str, Any] | None = None,
	stop_event: Event,
	pause_event: Event | None = None,
	auto_keywords: bool = True,
	keywords_only: bool = False,
) -> Iterator[dict[str, Any]]:
	yield from boss_svc.stream_search_jobs(
		query=query,
		city=city,
		city_code=city_code,
		district_code=district_code,
		page=page,
		scout_filters=scout_filters,
		pass_score=pass_score,
		career_stage=career_stage,
		stop_event=stop_event,
		pause_event=pause_event,
		auto_keywords=auto_keywords,
		keywords_only=keywords_only,
	)


def create_app(data_dir: Path):
	from starlette.applications import Starlette
	from starlette.requests import Request
	from starlette.responses import FileResponse, RedirectResponse
	from starlette.routing import Mount, Route
	from starlette.staticfiles import StaticFiles

	profile_svc = ProfileWebService(data_dir)
	boss_svc = BossWebService(data_dir)
	secretary_cfg = SecretaryConfigStore(data_dir)
	token_usage_store = get_token_usage_store(data_dir)

	async def index(_: Request):
		return RedirectResponse(url="/pet", status_code=302)

	async def pet_office(_: Request):
		from starlette.responses import HTMLResponse

		html = (STATIC_DIR / "pet.html").read_text(encoding="utf-8")
		css_v = int((STATIC_DIR / "pet.css").stat().st_mtime * 1000)
		js_v = int((STATIC_DIR / "pet.js").stat().st_mtime * 1000)
		html = re.sub(
			r'(/static/pet\.css)(?:\?v=[^"\']*)?',
			rf"\1?v={css_v}",
			html,
			count=1,
		)
		html = re.sub(
			r'(/static/pet\.js)(?:\?v=[^"\']*)?',
			rf"\1?v={js_v}",
			html,
			count=1,
		)
		return HTMLResponse(html, headers={"Cache-Control": "no-store"})

	async def api_status(request: Request):
		status = profile_svc.status()
		boss_sync = str(request.query_params.get("boss_sync", "")).lower() in ("1", "true", "yes")
		if boss_sync:
			status["boss"] = await _run_browser_blocking(boss_svc.auth_status, sync=True)
		else:
			status["boss"] = await _run_blocking(boss_svc.auth_status, sync=False)
		return _json_response(_ok(status))

	async def api_upload_pdf(request: Request):
		try:
			_ensure_multipart()
			form = await request.form()
			upload = form.get("file")
			if upload is None:
				raise ProfileWebError("INVALID_PARAM", "缺少 file 字段")
			filename = getattr(upload, "filename", "") or "resume.pdf"
			content = await upload.read()
			name = str(form.get("name") or "default")
			title = str(form.get("title") or "")
			auto_parse = str(form.get("auto_parse", "true")).lower() != "false"
			data = profile_svc.upload_pdf(
				content,
				filename=filename,
				name=name,
				title=title,
				auto_parse=auto_parse,
			)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)
		except ImportError as exc:
			return _json_response(_err(ProfileWebError(
				"DEPENDENCY_MISSING", str(exc), status=503,
			)), status=503)
		except Exception as exc:
			return _json_response({
				"ok": False,
				"error": {
					"code": "INTERNAL_ERROR",
					"message": str(exc) or "服务器内部错误",
				},
			}, status=500)

	async def api_delete_resume(request: Request):
		try:
			name = str(request.query_params.get("name") or "default")
			data = profile_svc.delete_resume(name)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_resume_pdf(request: Request):
		try:
			name = str(request.query_params.get("name") or "default")
			pdf_path = profile_svc.get_resume_pdf_path(name)
			return FileResponse(
				pdf_path,
				media_type="application/pdf",
				filename=f"{name}.pdf",
				content_disposition_type="inline",
				headers={"Cache-Control": "no-store"},
			)
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_interview_start(request: Request):
		try:
			body = await request.json()
			data = profile_svc.interview_start(
				resume_name=str(body.get("resume_name", "default")),
				max_questions=int(body.get("max_questions", 8)),
			)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_interview_answer(request: Request):
		try:
			body = await request.json()
			data = profile_svc.interview_answer(str(body.get("answer", "")))
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_interview_current(_: Request):
		return _json_response(_ok(profile_svc.interview_current()))

	async def api_interview_finish(_: Request):
		try:
			data = profile_svc.interview_finish()
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_infer(_: Request):
		try:
			data = profile_svc.infer()
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_profile(_: Request):
		return _json_response(_ok(profile_svc.get_profile()))

	async def api_boss_cities(_: Request):
		return _json_response(_ok(boss_svc.list_cities()))

	async def api_boss_regions(_: Request):
		return _json_response(_ok(boss_svc.list_regions()))

	async def api_boss_login(request: Request):
		try:
			body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
			timeout = int(body.get("timeout", 120)) if isinstance(body, dict) else 120
			data = await _run_browser_blocking(boss_svc.login, timeout=timeout)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)
		except Exception as exc:
			return _json_response({
				"ok": False,
				"error": {"code": "LOGIN_FAILED", "message": str(exc) or "登录失败"},
			}, status=500)

	async def api_boss_sync(_: Request):
		try:
			data = await _run_browser_blocking(boss_svc.sync_from_browser)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_boss_logout(_: Request):
		return _json_response(_ok(boss_svc.logout()))

	async def api_boss_scout_history(_: Request):
		return _json_response(_ok(boss_svc.scout_history_summary()))

	async def api_boss_scout_history_clear(_: Request):
		return _json_response(_ok(await _run_blocking(boss_svc.clear_scout_history)))

	async def api_boss_scout_ack(request: Request):
		try:
			body = await request.json()
		except Exception:
			body = {}
		if not isinstance(body, dict):
			body = {}
		_touch_scout_ack(body)
		snap = _scout_live_snapshot()
		return _json_response(_ok({"acked": True, **snap}))

	async def api_boss_scout_live(_: Request):
		return _json_response(_ok(_scout_live_snapshot()))

	def _parse_scout_start_body(body: dict[str, Any]) -> dict[str, Any]:
		return {
			"query": str(body.get("query", "")).strip(),
			"city": body.get("city") or None,
			"city_code": str(body["city_code"]).strip() if body.get("city_code") else None,
			"district_code": str(body["district_code"]).strip() if body.get("district_code") else None,
			"page": int(body.get("page", 1)),
			"scout_filters": body.get("scout_filters"),
			"pass_score": int(body.get("pass_score", 60)),
			"career_stage": body.get("career_stage") if isinstance(body.get("career_stage"), dict) else None,
			"auto_keywords": body.get("auto_keywords", True),
			"keywords_only": bool(body.get("keywords_only", False)),
		}

	def _launch_scout_session(params: dict[str, Any]) -> dict[str, Any]:
		"""启动进程级搜岗任务；若已在跑则返回 already_running。"""
		with _scout_launch_lock:
			with _scout_live_lock:
				already = bool(_scout_live.get("active"))
			if already:
				return {
					"started": False,
					"already_running": True,
					**_scout_live_snapshot(),
				}

			stop_event = Event()
			pause_event = Event()
			run_id = uuid.uuid4().hex[:12]
			watchdog_stop = Event()
			_start_scout_live(run_id=run_id)
			with _scout_live_lock:
				_scout_live["stop_event"] = stop_event
				_scout_live["pause_event"] = pause_event
				_scout_live["watchdog_stop"] = watchdog_stop
			scout_log = Logger(level="info")

			def producer() -> None:
				try:
					for event in _stream_scout_events(
						boss_svc,
						query=params["query"],
						city=params["city"],
						city_code=params["city_code"],
						district_code=params["district_code"],
						page=params["page"],
						scout_filters=params["scout_filters"],
						pass_score=params["pass_score"],
						career_stage=params["career_stage"],
						stop_event=stop_event,
						pause_event=pause_event,
						auto_keywords=params["auto_keywords"],
						keywords_only=params["keywords_only"],
					):
						if stop_event.is_set():
							break
						_extend_scout_pause_until(event)
						_note_server_scout_event(event)
						_fanout_scout_item(("event", event))
				except ProfileWebError as exc:
					with _scout_live_lock:
						_scout_live["last_error"] = exc.message
						_scout_live["last_message"] = exc.message
					_fanout_scout_item(("error", exc))
				except Exception as exc:
					msg = str(exc) or "侦察失败"
					with _scout_live_lock:
						_scout_live["last_error"] = msg
						_scout_live["last_message"] = msg
					_fanout_scout_item(("error", ProfileWebError("SCOUT_FAILED", msg, status=500)))
				finally:
					_fanout_scout_item(("done", None))
					_stop_scout_live()
					scout_log.info("[scout] 搜岗任务已结束")

			thread = Thread(target=producer, name="pet-scout-pipeline", daemon=True)
			with _scout_live_lock:
				_scout_live["producer_thread"] = thread
			thread.start()
			Thread(
				target=_scout_watchdog_loop,
				args=(watchdog_stop,),
				name="pet-scout-watchdog",
				daemon=True,
			).start()
			scout_log.info(f"[scout] 搜岗任务已启动 run_id={run_id}")
			return {"started": True, "already_running": False, **_scout_live_snapshot()}

	async def _sse_subscribe(request: Request):
		"""纯状态订阅：断开/刷新不停止搜岗。"""
		from starlette.responses import StreamingResponse

		queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=_SCOUT_SSE_QUEUE_MAX)
		loop = asyncio.get_running_loop()
		replay = _attach_scout_subscriber(queue, loop)
		scout_log = Logger(level="info")

		async def generate():
			try:
				# 先推 snapshot，再重放 ring，便于刷新后恢复
				snap = _scout_live_snapshot()
				yield f"data: {json.dumps({'ok': True, 'snapshot': snap}, ensure_ascii=False)}\n\n"
				for ev in replay:
					yield f"data: {json.dumps({'ok': True, 'event': ev, 'replay': True}, ensure_ascii=False)}\n\n"
				while True:
					if await request.is_disconnected():
						scout_log.info("[scout] Web SSE 订阅断开（搜岗任务继续）")
						break
					try:
						kind, payload = await asyncio.wait_for(queue.get(), timeout=0.5)
					except asyncio.TimeoutError:
						if await request.is_disconnected():
							scout_log.info("[scout] Web SSE 订阅断开（搜岗任务继续）")
							break
						yield ": keepalive\n\n"
						continue
					if kind == "done":
						yield f"data: {json.dumps({'ok': True, 'done': True}, ensure_ascii=False)}\n\n"
						break
					if kind == "error":
						err_payload = _err(payload) if isinstance(payload, ProfileWebError) else {
							"ok": False,
							"error": {"code": "SCOUT_FAILED", "message": str(payload)},
						}
						if isinstance(payload, ProfileWebError):
							scout_log.info(f"[scout] 搜岗异常结束：{payload.message}")
						yield f"data: {json.dumps(err_payload, ensure_ascii=False)}\n\n"
						break
					yield f"data: {json.dumps({'ok': True, 'event': payload}, ensure_ascii=False)}\n\n"
					yield ": flush\n\n"
			finally:
				_detach_scout_subscriber(queue)

		return StreamingResponse(
			generate(),
			media_type="text/event-stream",
			headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
		)

	async def api_boss_scout_start(request: Request):
		try:
			body = await request.json()
		except Exception:
			body = {}
		if not isinstance(body, dict):
			body = {}
		try:
			params = _parse_scout_start_body(body)
		except (TypeError, ValueError) as exc:
			return _json_response(_err(ProfileWebError("INVALID_PARAM", str(exc), status=400)), status=400)
		data = await _run_blocking(_launch_scout_session, params)
		return _json_response(_ok(data))

	async def api_boss_scout_stop(_: Request):
		ok = _request_stop_scout("用户手动停止搜岗", code="SCOUT_USER_STOP")
		return _json_response(_ok({"stopped": ok, **_scout_live_snapshot()}))

	async def api_boss_scout_events(request: Request):
		snap = _scout_live_snapshot()
		if not snap.get("active"):
			# 无任务时仍返回短流，前端可区分
			from starlette.responses import StreamingResponse

			async def empty_gen():
				yield f"data: {json.dumps({'ok': True, 'snapshot': snap, 'idle': True}, ensure_ascii=False)}\n\n"

			return StreamingResponse(
				empty_gen(),
				media_type="text/event-stream",
				headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
			)
		return await _sse_subscribe(request)

	async def api_boss_scout_stream(request: Request):
		"""兼容旧入口：启动任务（若未跑）并订阅 SSE；断开不杀任务。"""
		try:
			body = await request.json()
		except Exception:
			body = {}
		if not isinstance(body, dict):
			body = {}
		try:
			params = _parse_scout_start_body(body)
		except (TypeError, ValueError) as exc:
			return _json_response(_err(ProfileWebError("INVALID_PARAM", str(exc), status=400)), status=400)
		await _run_blocking(_launch_scout_session, params)
		return await _sse_subscribe(request)

	async def api_boss_shortlist(request: Request):
		if request.method == "GET":
			return _json_response(_ok(boss_svc.list_shortlist()))
		try:
			body = await request.json()
			data = boss_svc.shortlist_job(
				security_id=str(body.get("security_id", "")),
				job_id=str(body.get("job_id", "")),
				title=str(body.get("title", "")),
				company=str(body.get("company", "")),
				city=str(body.get("city", "")),
				salary=str(body.get("salary", "")),
			)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_boss_analysis_filtered(request: Request):
		limit = 200
		try:
			raw = request.query_params.get("limit")
			if raw:
				limit = int(raw)
		except (TypeError, ValueError):
			pass
		return _json_response(_ok(boss_svc.list_filtered_analysis(limit=limit)))

	async def api_boss_shortlist_remove(request: Request):
		try:
			body = await request.json()
			data = boss_svc.remove_shortlist_item(
				security_id=str(body.get("security_id", "")),
				job_id=str(body.get("job_id", "")),
			)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_boss_reject(request: Request):
		try:
			body = await request.json()
			raw_tags = body.get("tags")
			tags = raw_tags if isinstance(raw_tags, list) else []
			raw_reason = body.get("analysis_reason")
			raw_risk = body.get("analysis_risk")
			data = boss_svc.reject_job(
				security_id=str(body.get("security_id", "")),
				job_id=str(body.get("job_id", "")),
				title=str(body.get("title", "")),
				company=str(body.get("company", "")),
				reason=str(body.get("reason", "")),
				tags=[str(t) for t in tags],
				analysis_score=int(body["analysis_score"]) if body.get("analysis_score") is not None else None,
				analysis_reason=[str(x) for x in raw_reason] if isinstance(raw_reason, list) else None,
				analysis_risk=[str(x) for x in raw_risk] if isinstance(raw_risk, list) else None,
			)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)
		except (TypeError, ValueError) as exc:
			return _json_response(_err(ProfileWebError("INVALID_PARAM", str(exc), status=400)), status=400)

	async def api_profile_learning_log(request: Request):
		if request.method == "DELETE":
			return _json_response(_ok(await _run_blocking(boss_svc.clear_preference_learning_memory)))
		limit = 100
		try:
			raw = request.query_params.get("limit")
			if raw:
				limit = int(raw)
		except (TypeError, ValueError):
			pass
		return _json_response(_ok(boss_svc.list_preference_learning_logs(limit=limit)))

	async def api_boss_open_job(request: Request):
		try:
			body = await request.json()
			data = await _run_browser_blocking(
				boss_svc.open_job,
				job_id=str(body.get("job_id", "")),
				security_id=str(body.get("security_id", "")),
			)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)
		except ValueError as exc:
			return _json_response(_err(ProfileWebError("INVALID_PARAM", str(exc))), status=400)
		except Exception as exc:
			return _json_response({
				"ok": False,
				"error": {"code": "OPEN_JOB_FAILED", "message": str(exc) or "打开岗位失败"},
			}, status=500)

	async def api_pet_asset_mtimes(_: Request):
		return _json_response(_ok(_collect_pet_asset_mtimes()))

	async def api_secretary_email_get(_: Request):
		cfg = await _run_blocking(secretary_cfg.load)
		configured = secretary_cfg.is_email_configured(cfg)
		from pet_boss.secretary.config import secretary_email_api_view
		return _json_response(_ok(secretary_email_api_view(cfg, configured=configured)))

	async def api_secretary_email_save(request: Request):
		from pet_boss.secretary.config import apply_secretary_email_settings, secretary_email_api_view

		try:
			body = await request.json()
		except Exception:
			body = {}
		try:
			email = str(body.get("recipient_email", "")).strip()
			if email and "@" not in email:
				raise ProfileWebError("INVALID_PARAM", "邮箱格式不正确")
			cfg = await _run_blocking(secretary_cfg.load)
			max_daily_picks = None
			if "max_daily_picks" in body:
				try:
					max_daily_picks = int(body.get("max_daily_picks"))
				except (TypeError, ValueError) as exc:
					raise ProfileWebError(
						"INVALID_PARAM", "每日精选数量须为整数", status=400,
					) from exc
			smtp_auth_code = body.get("smtp_auth_code")
			if smtp_auth_code is not None:
				smtp_auth_code = str(smtp_auth_code)
			try:
				apply_secretary_email_settings(
					cfg,
					recipient_email=email,
					smtp_auth_code=smtp_auth_code,
					max_daily_picks=max_daily_picks,
				)
			except ValueError as exc:
				raise ProfileWebError("INVALID_PARAM", str(exc), status=400) from exc
			if email and not (cfg.get("smtp") or {}).get("password"):
				raise ProfileWebError(
					"INVALID_PARAM",
					"请填写邮箱 SMTP 授权码（QQ/163 等需在邮箱设置中开启 SMTP 并生成授权码）",
					status=400,
				)
			await _run_blocking(secretary_cfg.save, cfg)
			configured = secretary_cfg.is_email_configured(cfg)
			return _json_response(_ok(secretary_email_api_view(cfg, configured=configured)))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_secretary_portrait(_: Request):
		def _load() -> dict[str, Any]:
			from pet_boss.profile.store import ProfileStore

			with ProfileStore(data_dir) as store:
				portrait = store.load_secretary_portrait()
				profile = store.load_profile()
				return {
					"portrait": portrait,
					"profile": profile.to_dict(),
					"has_portrait": portrait is not None,
				}

		return _json_response(_ok(await _run_blocking(_load)))

	async def api_secretary_daily_action_plan(request: Request):
		try:
			refresh = str(request.query_params.get("refresh") or "").lower() in {"1", "true", "yes"}
			data = await _run_blocking(_secretary_daily_action_plan, data_dir, refresh=refresh)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_secretary_scout_strategy_plan(_: Request):
		data = await _run_blocking(_secretary_scout_strategy_plan, data_dir)
		return _json_response(_ok(data))

	async def api_secretary_daily_report(request: Request):
		try:
			date_param = str(request.query_params.get("date") or "today")
			data = await _run_blocking(_secretary_daily_report, data_dir, date_param)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)
		except ValueError as exc:
			return _json_response(_err(ProfileWebError(
				"INVALID_PARAM", str(exc), status=400,
			)), status=400)

	async def api_secretary_daily_pick_dates(request: Request):
		try:
			limit = int(request.query_params.get("limit") or 120)
			limit = max(1, min(limit, 365))
			data = await _run_blocking(_secretary_daily_pick_dates, data_dir, limit)
			return _json_response(_ok(data))
		except ValueError as exc:
			return _json_response(_err(ProfileWebError(
				"INVALID_PARAM", str(exc), status=400,
			)), status=400)

	async def api_secretary_send_daily_email(request: Request):
		try:
			try:
				body = await request.json()
			except Exception:
				body = {}
			date_param = str(body.get("date") or "today")
			data = await _run_blocking(_secretary_send_daily_email, data_dir, date_param)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_secretary_parse_resume(request: Request):
		try:
			body = await request.json()
			resume_name = str(body.get("resume_name", "default"))
			data = await _run_blocking(_secretary_parse_uploaded_pdf, data_dir, resume_name)
			return _json_response(_ok(data))
		except ProfileWebError as exc:
			return _json_response(_err(exc), status=exc.status)

	async def api_monitor_token_usage(_: Request):
		return _json_response(_ok(await _run_blocking(get_token_usage_summary, data_dir)))

	async def api_monitor_token_pricing_get(_: Request):
		from pet_boss.ai.token_usage import get_token_pricing
		return _json_response(_ok(await _run_blocking(get_token_pricing, data_dir)))

	async def api_monitor_token_pricing_save(request: Request):
		try:
			body = await request.json()
		except Exception:
			body = {}
		try:
			input_per_m = float(body.get("input_per_m", 0))
			output_per_m = float(body.get("output_per_m", 0))
		except (TypeError, ValueError):
			return _json_response(_err(ProfileWebError(
				"INVALID_PARAM", "单价必须为数字", status=400,
			)), status=400)
		pricing = await _run_blocking(
			save_token_pricing,
			data_dir,
			input_per_m=input_per_m,
			output_per_m=output_per_m,
		)
		return _json_response(_ok({
			"pricing": pricing,
			"usage": get_token_usage_summary(data_dir),
		}))

	async def on_exception(request: Request, exc: Exception):
		if isinstance(exc, ProfileWebError):
			return _json_response(_err(exc), status=exc.status)
		return _json_response({
			"ok": False,
			"error": {
				"code": "INTERNAL_ERROR",
				"message": str(exc) or "服务器内部错误",
			},
		}, status=500)

	routes = [
		Route("/", index),
		Route("/pet", pet_office),
		Route("/api/status", api_status, methods=["GET"]),
		Route("/api/resume/upload-pdf", api_upload_pdf, methods=["POST"]),
		Route("/api/resume/pdf", api_resume_pdf, methods=["GET"]),
		Route("/api/resume", api_delete_resume, methods=["DELETE"]),
		Route("/api/interview/start", api_interview_start, methods=["POST"]),
		Route("/api/interview/answer", api_interview_answer, methods=["POST"]),
		Route("/api/interview/current", api_interview_current, methods=["GET"]),
		Route("/api/interview/finish", api_interview_finish, methods=["POST"]),
		Route("/api/infer", api_infer, methods=["POST"]),
		Route("/api/profile", api_profile, methods=["GET"]),
		Route("/api/profile/learning-log", api_profile_learning_log, methods=["GET", "DELETE"]),
		Route("/api/boss/cities", api_boss_cities, methods=["GET"]),
		Route("/api/boss/regions", api_boss_regions, methods=["GET"]),
		Route("/api/boss/login", api_boss_login, methods=["POST"]),
		Route("/api/boss/sync", api_boss_sync, methods=["POST"]),
		Route("/api/boss/logout", api_boss_logout, methods=["POST"]),
		Route("/api/boss/scout/history", api_boss_scout_history, methods=["GET"]),
		Route("/api/boss/scout/history/clear", api_boss_scout_history_clear, methods=["POST"]),
		Route("/api/boss/scout/ack", api_boss_scout_ack, methods=["POST"]),
		Route("/api/boss/scout/live", api_boss_scout_live, methods=["GET"]),
		Route("/api/boss/scout/start", api_boss_scout_start, methods=["POST"]),
		Route("/api/boss/scout/stop", api_boss_scout_stop, methods=["POST"]),
		Route("/api/boss/scout/events", api_boss_scout_events, methods=["GET"]),
		Route("/api/boss/scout/stream", api_boss_scout_stream, methods=["POST"]),
		Route("/api/boss/shortlist", api_boss_shortlist, methods=["GET", "POST"]),
		Route("/api/boss/analysis/filtered", api_boss_analysis_filtered, methods=["GET"]),
		Route("/api/boss/shortlist/remove", api_boss_shortlist_remove, methods=["POST"]),
		Route("/api/boss/reject", api_boss_reject, methods=["POST"]),
		Route("/api/boss/open-job", api_boss_open_job, methods=["POST"]),
		Route("/api/pet/asset-mtimes", api_pet_asset_mtimes, methods=["GET"]),
		Route("/api/secretary/email", api_secretary_email_get, methods=["GET"]),
		Route("/api/secretary/email", api_secretary_email_save, methods=["POST"]),
		Route("/api/secretary/portrait", api_secretary_portrait, methods=["GET"]),
		Route("/api/secretary/daily-action-plan", api_secretary_daily_action_plan, methods=["GET"]),
		Route("/api/secretary/scout-strategy-plan", api_secretary_scout_strategy_plan, methods=["GET"]),
		Route("/api/secretary/daily-report", api_secretary_daily_report, methods=["GET"]),
		Route("/api/secretary/daily-picks/dates", api_secretary_daily_pick_dates, methods=["GET"]),
		Route("/api/secretary/send-daily-email", api_secretary_send_daily_email, methods=["POST"]),
		Route("/api/secretary/parse-resume", api_secretary_parse_resume, methods=["POST"]),
		Route("/api/monitor/token-usage", api_monitor_token_usage, methods=["GET"]),
		Route("/api/monitor/token-pricing", api_monitor_token_pricing_get, methods=["GET"]),
		Route("/api/monitor/token-pricing", api_monitor_token_pricing_save, methods=["POST"]),
		Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
	]
	return Starlette(routes=routes, exception_handlers={Exception: on_exception})


def run_server(*, data_dir: Path, host: str = "127.0.0.1", port: int = 8787) -> None:
	try:
		import uvicorn
	except ImportError as exc:
		raise ImportError(
			"Web 界面需要安装可选依赖：pip install 'boss-agent-cli[web]'"
		) from exc
	app = create_app(data_dir)
	try:
		uvicorn.run(app, host=host, port=port, log_level="info")
	except OSError as exc:
		win_in_use = getattr(exc, "winerror", None) == 10048
		addr_in_use = exc.errno in (98, 10048) or win_in_use
		if addr_in_use:
			raise SystemExit(
				f"端口 {host}:{port} 已被占用，无法启动 Web 服务。\n"
				f"请先关闭旧的 boss web（运行窗口按 Ctrl+C），或在 PowerShell 执行：\n"
				f"  netstat -ano | findstr \":{port}\"\n"
				f"  taskkill /PID <上一步的PID> /F\n"
				f"也可换端口启动：boss web --port {port + 1}"
			) from exc
		raise
