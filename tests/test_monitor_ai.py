from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

from pet_boss.agents.monitor_ai import (
	MonitorAI,
	is_anomaly_event,
	is_browser_navigation_error,
	probe_boss_health,
)


def test_is_anomaly_event_detects_risk():
	assert is_anomaly_event({"type": "account_risk", "message": "环境存在异常"})
	assert is_anomaly_event({"type": "error_retry", "message": "访问受限"})
	assert not is_anomaly_event({"type": "scout_seen", "message": "发现岗位"})


def test_monitor_pauses_and_recovers(tmp_path: Path):
	stop_event = Event()
	pause_event = Event()
	monitor = MonitorAI(tmp_path, stop_event=stop_event, pause_event=pause_event)

	with patch("pet_boss.agents.monitor_ai.open_boss_browser") as mock_open:
		with patch(
			"pet_boss.agents.monitor_ai.probe_boss_health",
			side_effect=[
				{"ok": False, "state": "blocked", "message": "环境存在异常"},
				{"ok": True, "state": "normal", "message": "BOSS 访问正常"},
			],
		):
			events = list(monitor.wrap_event({
				"type": "account_risk",
				"code": "ACCOUNT_RISK",
				"message": "您的环境存在异常",
			}))

	types = [e["type"] for e in events]
	assert "account_risk" in types or events[0]["type"] == "account_risk"
	assert "monitor_alert" in types
	assert "monitor_browser_open" in types
	assert "monitor_recovered" in types
	mock_open.assert_called_once()
	assert not pause_event.is_set()


def test_is_browser_navigation_error():
	assert is_browser_navigation_error("Page.goto: Timeout 15000ms exceeded")
	assert not is_browser_navigation_error("connection refused")


def test_monitor_detects_stall(tmp_path: Path):
	stop_event = Event()
	restart = MagicMock(return_value={"ok": True, "launch_ok": True, "mode": "patchright"})
	monitor = MonitorAI(
		tmp_path,
		stop_event=stop_event,
		stall_threshold_sec=60.0,
		browser_restart_fn=restart,
	)
	monitor._touch_activity({"type": "page_start"})
	monitor._last_activity = 0.0
	monitor._stall_alerted = False

	with patch(
		"pet_boss.agents.monitor_ai.probe_boss_health",
		return_value={"ok": True, "state": "normal", "message": "BOSS 访问正常"},
	):
		stall = monitor._build_stall_event(301.0)

	assert stall["type"] == "monitor_stall"
	assert stall["blocked"] is False
	assert "无进展" in stall["message"] or "卡住" in stall["message"]
	assert monitor.state == "stalled"

	events = list(monitor.drain_auxiliary_events())
	assert events == []

	monitor._pending.put(stall)
	with patch("pet_boss.agents.monitor_ai.open_boss_browser"):
		drained = list(monitor.drain_auxiliary_events())
	types = [e["type"] for e in drained]
	assert "monitor_stall" in types
	assert "browser_restart_begin" in types
	assert "monitor_browser_restart" in types
	restart.assert_called_once()


def test_search_fetch_stall_threshold(tmp_path: Path):
	monitor = MonitorAI(tmp_path)
	monitor._touch_activity({"type": "search_fetch"})
	assert monitor._effective_stall_threshold() == 600.0
	monitor._touch_activity({"type": "page_start"})
	assert monitor._effective_stall_threshold() == 90.0


def test_search_fetch_stall_does_not_restart_browser(tmp_path: Path):
	restart = MagicMock()
	monitor = MonitorAI(tmp_path, browser_restart_fn=restart)
	monitor._touch_activity({"type": "search_fetch"})
	stall = {
		"type": "monitor_stall",
		"state": "stalled",
		"blocked": False,
		"needs_recovery": False,
		"last_event": "search_fetch",
		"message": "test",
	}
	monitor._pending.put(stall)
	types = [e["type"] for e in monitor.drain_auxiliary_events()]
	assert "monitor_stall" in types
	assert "monitor_browser_restart" not in types
	restart.assert_not_called()


def test_monitor_browser_stuck_restarts(tmp_path: Path):
	restart = MagicMock(return_value={"ok": True, "launch_ok": True, "mode": "patchright"})
	monitor = MonitorAI(tmp_path, browser_restart_fn=restart)
	events = list(monitor.wrap_event({
		"type": "browser_stuck",
		"message": "Page.goto: Timeout 15000ms exceeded",
	}))
	types = [e["type"] for e in events]
	assert "browser_stuck" in types
	assert "browser_restart_begin" in types
	assert "monitor_browser_restart" in types
	assert "browser_restart_failed" not in types
	restart.assert_called_once()


def test_monitor_browser_restart_launch_failure(tmp_path: Path):
	restart = MagicMock(return_value={
		"ok": False,
		"launch_ok": False,
		"phase": "launch_failed",
		"error": "Chromium 启动后页面未就绪",
	})
	monitor = MonitorAI(tmp_path, browser_restart_fn=restart)
	with patch("pet_boss.agents.monitor_ai.open_boss_browser"):
		events = list(monitor._try_restart_browser("测试卡住"))
	types = [e["type"] for e in events]
	assert types[0] == "browser_restart_begin"
	assert "browser_restart_failed" in types
	assert "monitor_browser_restart" not in types


def test_monitor_stall_blocked_triggers_recovery(tmp_path: Path):
	stop_event = Event()
	pause_event = Event()
	monitor = MonitorAI(tmp_path, stop_event=stop_event, pause_event=pause_event)

	with patch("pet_boss.agents.monitor_ai.open_boss_browser") as mock_open:
		with patch(
			"pet_boss.agents.monitor_ai.probe_boss_health",
			side_effect=[
				{"ok": False, "state": "blocked", "message": "环境存在异常"},
				{"ok": True, "state": "normal", "message": "BOSS 访问正常"},
			],
		):
			stall = monitor._build_stall_event(400.0)
			monitor._pending.put(stall)
			events = list(monitor.drain_auxiliary_events())

	types = [e["type"] for e in events]
	assert "monitor_stall" in types
	assert "monitor_alert" in types
	assert "monitor_browser_open" in types
	assert "monitor_recovered" in types
	mock_open.assert_called_once()
	assert not pause_event.is_set()


def test_activity_resets_stall_alert(tmp_path: Path):
	monitor = MonitorAI(tmp_path, stall_threshold_sec=60.0)
	monitor._stall_alerted = True
	monitor.state = "stalled"
	monitor._touch_activity({"type": "scout_heartbeat"})
	assert not monitor._stall_alerted
	assert monitor.state == "watching"


def test_probe_boss_health_success(tmp_path: Path):
	mock_platform = MagicMock()
	mock_platform.is_success.return_value = True
	mock_platform.__enter__ = MagicMock(return_value=mock_platform)
	mock_platform.__exit__ = MagicMock(return_value=False)

	with patch("pet_boss.agents.monitor_ai.AuthManager") as mock_auth:
		mock_auth.return_value.ensure_session.return_value = {"cookies": {"wt2": "x"}}
		with patch("pet_boss.agents.monitor_ai.get_platform") as mock_get:
			mock_get.return_value.return_value = mock_platform
			result = probe_boss_health(tmp_path)
	assert result["ok"] is True
