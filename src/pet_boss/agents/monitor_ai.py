"""监控 AI — 实时监测侦察运行，异常/卡住时暂停、打开 BOSS 页面、恢复后自动继续。"""

from __future__ import annotations

import queue
import threading
import time
import webbrowser
from collections.abc import Iterator
from pathlib import Path
from threading import Event
from typing import Any

from pet_boss.api.client import BossClient
from pet_boss.auth.manager import AuthManager
from pet_boss.output import Logger
from pet_boss.platforms import get_platform

if False:  # TYPE_CHECKING
	from pet_boss.ai.token_usage import TokenUsageStore

BOSS_JOB_URL = "https://www.zhipin.com/web/geek/job"
BOSS_HOME_URL = "https://www.zhipin.com/"
_PROBE_INTERVAL_SEC = 5.0
_STOP_POLL_SEC = 0.3
_STALL_CHECK_INTERVAL_SEC = 15.0
_STALL_THRESHOLD_SEC = 120.0
_NAV_STUCK_THRESHOLD_SEC = 90.0
# 深分页单次 search_fetch 可能 3～10 分钟无新事件，勿用 90 秒导航阈值
_SEARCH_FETCH_STALL_SEC = 600.0
# 页完成/翻页/心跳期间 pipeline 仍在运行，勿用 120 秒默认阈值
_BETWEEN_PAGES_EVENT_TYPES = frozenset({
	"page_done",
	"page_turn",
	"scout_heartbeat",
	"search_progress",
	"round_done",
	"round_pause",
	"round_fatigue_pause",
	"round_page_cap",
	"round_early_stop",
	"round_resume",
})
_NAV_STUCK_EVENT_TYPES = frozenset({
	"round_home_refresh",
	"page_start",
	"browser_stuck",
	"round_home_refresh_skip",
})

_ANOMALY_EVENT_TYPES = frozenset({"account_risk"})
_BLOCKED_HINTS = (
	"环境存在异常",
	"异常行为",
	"访问受限",
	"安全验证",
	"IP",
	"暂时无法访问",
)
_RISK_CODES = frozenset({"ACCOUNT_RISK", "RATE_LIMITED"})


def _is_blocked_message(message: str) -> bool:
	msg = message or ""
	return any(hint in msg for hint in _BLOCKED_HINTS)


def is_browser_navigation_error(message: str) -> bool:
	"""判断异常是否像 Playwright 页面导航/刷新卡死。"""
	msg = (message or "").lower()
	return "timeout" in msg and ("goto" in msg or "navigation" in msg or "page.goto" in msg)


def is_anomaly_event(event: dict[str, Any]) -> bool:
	"""判断侦察事件是否应触发监控中断。"""
	event_type = event.get("type", "")
	if event_type in _ANOMALY_EVENT_TYPES:
		return True
	code = str(event.get("code") or "")
	if code in _RISK_CODES:
		return True
	message = str(event.get("message") or "")
	return _is_blocked_message(message)


def probe_boss_health(data_dir: Path, *, try_browser: bool = False) -> dict[str, Any]:
	"""探测 BOSS 是否可正常访问（只读 user_info）。

	默认 try_browser=False，避免监控看门狗线程触发 patchright 跨线程错误。
	"""
	try:
		auth = AuthManager(data_dir, logger=Logger(level="error"), platform="zhipin")
		auth.ensure_session(try_browser=try_browser)
		client = BossClient(auth, delay=(0.0, 0.0))
		platform_cls = get_platform("zhipin")
		with platform_cls(client) as platform:
			resp = platform.user_info()
			if platform.is_success(resp):
				return {"ok": True, "state": "normal", "message": "BOSS 访问正常"}
			code, message = platform.parse_error(resp)
			blocked = code in _RISK_CODES or _is_blocked_message(message)
			return {
				"ok": False,
				"state": "blocked" if blocked else "degraded",
				"code": code,
				"message": message or "BOSS 返回异常",
			}
	except Exception as exc:
		msg = str(exc) or "探测失败"
		return {
			"ok": False,
			"state": "error",
			"message": msg,
			"blocked": _is_blocked_message(msg),
		}


def open_boss_browser(*, url: str = BOSS_JOB_URL) -> None:
	"""CLI 回退：打开系统默认浏览器（Web 搜岗应改用 automation 窗口）。"""
	webbrowser.open(url, new=2)


_AUTO_BROWSER_HINT = "请到自动化 Chromium 窗口查看（BOSS 登录态在此，不是 Edge）"


def _probe_is_blocked(probe: dict[str, Any]) -> bool:
	if probe.get("ok"):
		return False
	if probe.get("state") == "blocked" or probe.get("blocked"):
		return True
	code = str(probe.get("code") or "")
	if code in _RISK_CODES:
		return True
	return _is_blocked_message(str(probe.get("message") or ""))


class MonitorAI:
	"""监控 AI：异常/卡住暂停侦察 → 打开 BOSS 网页 → 轮询恢复 → 自动继续。"""

	def __init__(
		self,
		data_dir: Path,
		*,
		stop_event: Event | None = None,
		pause_event: Event | None = None,
		stall_threshold_sec: float = _STALL_THRESHOLD_SEC,
		usage_store: Any | None = None,
		browser_restart_fn: Any | None = None,
		browser_open_fn: Any | None = None,
	) -> None:
		self._data_dir = data_dir
		self._stop_event = stop_event
		self._pause_event = pause_event
		self._stall_threshold_sec = stall_threshold_sec
		self._usage_store = usage_store
		self._browser_restart_fn = browser_restart_fn
		self._browser_open_fn = browser_open_fn
		self._last_token_version = -1
		self.state = "watching"
		self._last_activity = time.time()
		self._last_event_type = ""
		self._stall_alerted = False
		self._pending: queue.Queue[dict[str, Any]] = queue.Queue()
		self._watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
		self._watchdog.start()

	def _prompt_boss_browser(self, *, url: str = BOSS_JOB_URL) -> None:
		fn = self._browser_open_fn or open_boss_browser
		try:
			fn(url=url)
		except TypeError:
			fn()
		except Exception:
			pass

	def _touch_activity(self, event: dict[str, Any]) -> None:
		self._last_activity = time.time()
		self._last_event_type = str(event.get("type") or "")
		self._stall_alerted = False
		if self.state == "stalled":
			self.state = "watching"

	def _effective_stall_threshold(self) -> float:
		if self._last_event_type == "search_fetch":
			return _SEARCH_FETCH_STALL_SEC
		if self._last_event_type in _BETWEEN_PAGES_EVENT_TYPES:
			return _SEARCH_FETCH_STALL_SEC
		if self._last_event_type in _NAV_STUCK_EVENT_TYPES:
			return _NAV_STUCK_THRESHOLD_SEC
		return self._stall_threshold_sec

	def _watchdog_loop(self) -> None:
		while True:
			if self._stop_event and self._stop_event.is_set():
				return
			time.sleep(_STALL_CHECK_INTERVAL_SEC)
			if self._stop_event and self._stop_event.is_set():
				return
			if self.state in ("paused", "recovering"):
				continue
			idle = time.time() - self._last_activity
			if idle < self._effective_stall_threshold():
				continue
			if self._stall_alerted:
				continue
			self._stall_alerted = True
			self._pending.put(self._build_stall_event(idle))

	def _build_stall_event(self, idle_sec: float) -> dict[str, Any]:
		probe = probe_boss_health(self._data_dir)
		blocked = _probe_is_blocked(probe)
		if blocked:
			self.state = "paused"
			if self._pause_event is not None:
				self._pause_event.set()
		else:
			self.state = "stalled"
		return {
			"type": "monitor_stall",
			"state": self.state,
			"idle_sec": round(idle_sec, 1),
			"probe": probe,
			"blocked": blocked,
			"needs_recovery": blocked,
			"last_event": self._last_event_type,
			"message": (
				f"监控 AI：侦察已超过 {int(idle_sec)} 秒无进展"
				f"（末次事件 {self._last_event_type or '—'}）— "
				+ (
					"BOSS 可能受限，已暂停侦察"
					if blocked
					else "可能页面卡住或 AI 阻塞，将尝试重启浏览器"
				)
			),
		}

	def _try_restart_browser(self, reason: str) -> Iterator[dict[str, Any]]:
		yield {
			"type": "browser_restart_begin",
			"state": "recovering",
			"sequence": "stall_then_close",
			"reason": reason,
			"message": f"监控 AI：侦察卡住，准备关闭并重启自动化 Chromium — {reason}",
		}
		yield {
			"type": "monitor_alert",
			"state": "recovering",
			"message": f"监控 AI：{reason}",
			"source_event": "browser_stuck",
		}
		if self._browser_restart_fn is not None:
			try:
				outcome = self._browser_restart_fn()
				if not isinstance(outcome, dict):
					outcome = {"ok": True}
				if not outcome.get("launch_ok"):
					yield {
						"type": "browser_restart_failed",
						"state": self.state,
						"sequence": outcome.get("sequence") or "stall_then_close",
						"phase": outcome.get("phase") or "launch_failed",
						"mode": outcome.get("mode") or "",
						"error": outcome.get("error") or "新 Chromium 窗口未能拉起",
						"outcome": outcome,
						"message": (
							"监控 AI：自动化 Chromium 重启失败（先关旧窗后未能拉起新窗）— "
							f"{outcome.get('error') or '请查看终端 [boss-browser] 日志'}"
						),
					}
					self._prompt_boss_browser()
					yield {
						"type": "monitor_browser_open",
						"state": self.state,
						"url": BOSS_JOB_URL,
						"message": f"{_AUTO_BROWSER_HINT}；自动化窗口需重新搜岗恢复",
					}
					return
				self.state = "watching"
				self._touch_activity({"type": "monitor_browser_restart"})
				if self._pause_event is not None:
					self._pause_event.clear()
				stoken_note = ""
				if outcome.get("stoken_ok") is False:
					stoken_note = f"（stoken 刷新失败：{outcome.get('stoken_error') or '未知'}）"
				yield {
					"type": "monitor_browser_restart",
					"state": self.state,
					"sequence": outcome.get("sequence") or "stall_then_close",
					"mode": outcome.get("mode") or "",
					"outcome": outcome,
					"message": f"监控 AI：已关闭旧窗并拉起新 Chromium，侦察继续{stoken_note}",
				}
				return
			except Exception as exc:
				yield {
					"type": "browser_restart_failed",
					"state": self.state,
					"sequence": "stall_then_close",
					"phase": "exception",
					"error": str(exc) or exc.__class__.__name__,
					"message": f"监控 AI：浏览器重启异常（{exc}），请手动检查 BOSS 页面",
				}
		self._prompt_boss_browser()
		yield {
			"type": "monitor_browser_open",
			"state": self.state,
			"url": BOSS_JOB_URL,
			"message": f"{_AUTO_BROWSER_HINT}，请处理异常（登录/验证/刷新卡住）",
		}

	def drain_auxiliary_events(self) -> Iterator[dict[str, Any]]:
		"""取出看门狗产生的卡住/辅助事件（须在主线程消费）。"""
		yield from self.drain_token_events()
		while True:
			try:
				event = self._pending.get_nowait()
			except queue.Empty:
				break
			yield event
			if event.get("type") == "monitor_stall":
				if event.get("needs_recovery") or event.get("blocked"):
					yield from self._handle_blocked_stall(event)
				elif event.get("last_event") == "search_fetch":
					# 列表拉取期间 pipeline 无事件属正常，重启浏览器会关掉用户 BOSS 登录页
					yield {
						"type": "monitor_stall",
						"state": self.state,
						"soft": True,
						"message": (
							"监控 AI：列表拉取耗时较长（深分页可能数分钟），"
							"仍在等待，不会重启浏览器"
						),
					}
				else:
					yield from self._try_restart_browser(
						event.get("message") or "侦察长时间无进展",
					)

	def drain_token_events(self) -> Iterator[dict[str, Any]]:
		"""Token 用量变化时推送 monitor_token 事件。"""
		if self._usage_store is None:
			return
		from pet_boss.ai.token_usage import get_token_usage_summary

		summary = get_token_usage_summary(self._data_dir)
		version = int(summary.get("version") or 0)
		if version <= self._last_token_version:
			return
		self._last_token_version = version
		total = summary.get("session_total") or {}
		total_tokens = int(total.get("total_tokens") or 0)
		cost = summary.get("cost") or {}
		cost_text = cost.get("formatted") or ""
		message = f"监控 AI：本次会话累计消耗 {total_tokens} tokens"
		if cost_text:
			message += f"（约 {cost_text}）"
		yield {
			"type": "monitor_token",
			"state": self.state,
			"usage": summary,
			"message": message,
		}

	def _handle_blocked_stall(self, stall_event: dict[str, Any]) -> Iterator[dict[str, Any]]:
		yield {
			"type": "monitor_alert",
			"state": self.state,
			"message": (
				f"监控 AI：长时间无响应且 BOSS 异常，已暂停侦察 — "
				f"{stall_event.get('probe', {}).get('message', '')}"
			),
			"source_event": "monitor_stall",
		}
		self._prompt_boss_browser()
		yield {
			"type": "monitor_browser_open",
			"state": self.state,
			"url": BOSS_JOB_URL,
			"message": f"{_AUTO_BROWSER_HINT}，请处理异常（登录/验证/解封）",
		}
		yield from self._wait_for_recovery()

	def wrap_event(self, event: dict[str, Any]) -> Iterator[dict[str, Any]]:
		"""透传事件；异常时暂停侦察并等待恢复。"""
		self._touch_activity(event)
		yield event

		if event.get("type") == "page_done":
			yield {
				"type": "monitor_ok",
				"state": self.state,
				"message": "监控 AI：运行正常",
				"page": event.get("page"),
				"round": event.get("round"),
			}

		if not is_anomaly_event(event):
			if event.get("type") == "browser_stuck" or (
				event.get("type") == "round_home_refresh_skip"
				and is_browser_navigation_error(str(event.get("message") or ""))
			):
				yield from self._try_restart_browser(
					str(event.get("message") or "浏览器页面导航卡住"),
				)
			return

		self.state = "paused"
		if self._pause_event is not None:
			self._pause_event.set()

		yield {
			"type": "monitor_alert",
			"state": self.state,
			"message": f"监控 AI：检测到异常，已暂停侦察 — {event.get('message', '')}",
			"source_event": event.get("type"),
			"code": event.get("code"),
		}

		self._prompt_boss_browser()
		yield {
			"type": "monitor_browser_open",
			"state": self.state,
			"url": BOSS_JOB_URL,
			"message": f"{_AUTO_BROWSER_HINT}，请处理异常（登录/验证/解封）",
		}

		yield from self._wait_for_recovery()

	def _wait_for_recovery(self) -> Iterator[dict[str, Any]]:
		self.state = "recovering"
		attempt = 0
		while True:
			if self._stop_event and self._stop_event.is_set():
				yield {
					"type": "monitor_stopped",
					"state": "stopped",
					"message": "监控 AI：用户停止，未恢复侦察",
				}
				return

			attempt += 1
			probe = probe_boss_health(self._data_dir)
			yield {
				"type": "monitor_probe",
				"state": "recovering",
				"attempt": attempt,
				"probe": probe,
				"message": (
					f"监控 AI：探测中（第 {attempt} 次）— "
					f"{'已恢复' if probe.get('ok') else probe.get('message', '仍异常')}"
				),
			}

			if probe.get("ok"):
				self.state = "watching"
				self._touch_activity({"type": "monitor_recovered"})
				if self._pause_event is not None:
					self._pause_event.clear()
				yield {
					"type": "monitor_recovered",
					"state": self.state,
					"message": "监控 AI：BOSS 已恢复正常，侦察继续运行",
					"probe": probe,
				}
				return

			deadline = time.time() + _PROBE_INTERVAL_SEC
			while time.time() < deadline:
				if self._stop_event and self._stop_event.is_set():
					yield {
						"type": "monitor_stopped",
						"state": "stopped",
						"message": "监控 AI：用户停止，未恢复侦察",
					}
					return
				time.sleep(_STOP_POLL_SEC)
