"""搜岗 Web：ack 仅表示 UI 在线；生命周期由后端管理。"""

import time
from threading import Event

from pet_boss.web import server as web_server


def test_ack_stale_limit_longer_when_page_hidden():
	"""兼容：隐藏时 UI 在线阈值更长（不再用于停管道）。"""
	web_server._start_scout_live()
	web_server._touch_scout_ack({"hidden": True, "page": 3})
	assert web_server._scout_ack_stale_limit_sec() == web_server._SCOUT_WEB_ACK_STALE_HIDDEN_SEC
	web_server._touch_scout_ack({"hidden": False, "page": 3})
	assert web_server._scout_ack_stale_limit_sec() == web_server._SCOUT_WEB_ACK_STALE_SEC


def test_planned_pause_extends_until():
	web_server._start_scout_live()
	web_server._extend_scout_pause_until({"type": "round_pause", "pause_sec": 120})
	assert web_server._scout_in_planned_pause() is True
	with web_server._scout_live_lock:
		until = float(web_server._scout_live["pause_until"])
	assert until >= time.time() + 120
	web_server._extend_scout_pause_until({"type": "round_resume"})
	assert web_server._scout_in_planned_pause() is False


def test_off_hours_pause_exempts_watchdog_without_pause_sec():
	"""下班暂停事件常无 pause_sec，仍须豁免 watchdog，否则约 180s 误杀。"""
	web_server._start_scout_live()
	web_server._extend_scout_pause_until({
		"type": "off_hours_pause",
		"message": "非工作时间 · 搜岗已暂停",
	})
	assert web_server._scout_in_planned_pause() is True
	with web_server._scout_live_lock:
		until = float(web_server._scout_live["pause_until"])
	assert until >= time.time() + 3600
	web_server._extend_scout_pause_until({"type": "work_hours_resume"})
	assert web_server._scout_in_planned_pause() is False


def test_off_hours_pause_uses_explicit_pause_sec():
	web_server._start_scout_live()
	web_server._extend_scout_pause_until({
		"type": "off_hours_pause",
		"pause_sec": 900,
	})
	with web_server._scout_live_lock:
		until = float(web_server._scout_live["pause_until"])
	assert until >= time.time() + 900
	assert until < time.time() + 900 + web_server._SCOUT_PAUSE_ACK_GRACE_SEC + 5


def test_touch_ack_updates_hidden_flag():
	web_server._start_scout_live()
	web_server._touch_scout_ack({"hidden": True})
	with web_server._scout_live_lock:
		assert web_server._scout_live["page_hidden"] is True
	web_server._touch_scout_ack({"hidden": False})
	with web_server._scout_live_lock:
		assert web_server._scout_live["page_hidden"] is False


def test_page_hidden_does_not_pause_pipeline():
	web_server._start_scout_live()
	pe = Event()
	web_server._bind_scout_control(pause_event=pe)
	web_server._set_scout_page_hidden(True)
	assert not pe.is_set()
	assert web_server._scout_live_snapshot()["page_hidden"] is True
	web_server._set_scout_page_hidden(False)
	assert not pe.is_set()
	assert web_server._scout_live_snapshot()["page_hidden"] is False


def test_live_snapshot_fields():
	web_server._start_scout_live()
	web_server._touch_scout_ack({"page": 5, "query": "Python", "hidden": False})
	with web_server._scout_live_lock:
		web_server._scout_live["server_page"] = 8
		web_server._scout_live["server_query"] = "Golang"
		web_server._scout_live["last_warn"] = "test warn"
	snap = web_server._scout_live_snapshot()
	assert snap["active"] is True
	assert snap["client_page"] == 5
	assert snap["server_page"] == 8
	assert snap["last_warn"] == "test warn"
	assert "ui_online" in snap
	assert "subscriber_count" in snap


def test_ack_does_not_stop_scout():
	"""ack 超时只影响 ui_online，不设置 stop_event。"""
	web_server._start_scout_live()
	stop_event = Event()
	web_server._bind_scout_control(pause_event=Event(), stop_event=stop_event)
	with web_server._scout_live_lock:
		web_server._scout_live["ack_at"] = time.time() - 9999
	snap = web_server._scout_live_snapshot()
	assert snap["ui_online"] is False
	assert not stop_event.is_set()


def test_request_stop_sets_stop_event():
	web_server._start_scout_live()
	stop_event = Event()
	web_server._bind_scout_control(pause_event=Event(), stop_event=stop_event)
	ok = web_server._request_stop_scout("用户手动停止搜岗", code="SCOUT_USER_STOP")
	assert ok is True
	assert stop_event.is_set()
	snap = web_server._scout_live_snapshot()
	assert "手动停止" in snap["last_error"]


def test_note_event_updates_progress():
	web_server._start_scout_live()
	with web_server._scout_live_lock:
		web_server._scout_live["last_progress_at"] = 0.0
	web_server._note_server_scout_event({
		"type": "page_start",
		"page": 3,
		"query": "Python",
		"message": "正在搜索第 3 页",
	})
	with web_server._scout_live_lock:
		assert web_server._scout_live["server_page"] == 3
		assert web_server._scout_live["last_progress_at"] > 0
		assert len(web_server._scout_live["event_ring"]) == 1


def test_sse_queue_prefers_keeping_job_passed():
	"""队列满时优先丢 soft 页码事件，保留 job_passed。"""
	import asyncio

	async def _run():
		q = asyncio.Queue(maxsize=3)
		await web_server._queue_put_drop_oldest(q, ("event", {"type": "page_start", "page": 1}))
		await web_server._queue_put_drop_oldest(q, ("event", {"type": "page_done", "page": 1}))
		await web_server._queue_put_drop_oldest(q, ("event", {"type": "page_start", "page": 2}))
		dropped = await web_server._queue_put_drop_oldest(
			q, ("event", {"type": "job_passed", "job": {"title": "后端"}, "message": "通过"}),
		)
		assert dropped is True
		items = []
		while not q.empty():
			items.append(q.get_nowait())
		types = [p.get("type") for _, p in items]
		assert "job_passed" in types
		assert types.count("job_passed") == 1
		assert len(items) <= 3

	asyncio.run(_run())


def test_sse_droppable_helper():
	assert web_server._scout_sse_item_droppable(("event", {"type": "scout_heartbeat"})) is True
	assert web_server._scout_sse_item_droppable(("event", {"type": "page_start"})) is True
	assert web_server._scout_sse_item_droppable(("event", {"type": "job_passed"})) is False
	assert web_server._scout_sse_item_droppable(("error", "x")) is False
	assert web_server._scout_sse_item_droppable(("done", None)) is False


def test_scout_should_fanout_skips_browse_noise():
	# 浏览岗位信息会推送；心跳仍不推
	assert web_server._scout_should_fanout(("event", {"type": "scout_seen"})) is True
	assert web_server._scout_should_fanout(("event", {"type": "scout_filter"})) is True
	assert web_server._scout_should_fanout(("event", {"type": "scout_skip"})) is True
	assert web_server._scout_should_fanout(("event", {"type": "scout_heartbeat"})) is False
	assert web_server._scout_should_fanout(("event", {"type": "job_passed"})) is True
	assert web_server._scout_should_fanout(("event", {"type": "page_start"})) is True
	assert web_server._scout_should_fanout(("done", None)) is True
	assert "scout_seen" in web_server._SCOUT_SSE_BROWSE_TYPES
	assert "scout_seen" not in web_server._SCOUT_SSE_RING_TYPES



def test_note_event_keeps_passed_jobs_and_stats():
	web_server._start_scout_live()
	web_server._note_server_scout_event({
		"type": "job_passed",
		"job": {"job_id": "j1", "title": "后端"},
		"stats": {
			"scout": {"jobs_seen": 10, "jobs_scout_passed": 3},
			"analysis": {"jobs_passed": 1},
			"search": {"current_page": 4, "current_query": "Python"},
		},
		"message": "通过",
	})
	snap = web_server._scout_live_snapshot()
	assert snap["server_page"] == 4
	assert snap["server_query"] == "Python"
	assert snap["passed_count"] == 1
	assert snap["passed_jobs"][0]["title"] == "后端"
	assert snap["stats"]["scout"]["jobs_seen"] == 10
