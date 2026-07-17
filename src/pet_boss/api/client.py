import atexit
import random
import time
import weakref
from collections.abc import Callable
from types import TracebackType
from typing import TYPE_CHECKING, Any, TypeVar, cast

import httpx

_T = TypeVar("_T")

import httpx

from pet_boss.api import endpoints
from pet_boss.api.http_trace import is_http_trace_enabled, log_incoming_response, log_outgoing_request
from pet_boss.api.httpx_helpers import (
	add_stoken_to_get_params,
	browser_headers,
	merge_response_cookies,
	referer_header,
)
from pet_boss.api.throttle import RequestThrottle

if TYPE_CHECKING:
	from pet_boss.api.browser_client import BrowserSession
	from pet_boss.auth.manager import AuthManager

_MAX_RETRIES = 3
_STOKEN_SEARCH_BATCH = 5  # BOSS 同 stoken 约 5 次搜岗后需刷新

# atexit safeguard: close any BossClient instances not explicitly closed
_OPEN_CLIENTS: weakref.WeakSet["BossClient"] = weakref.WeakSet()


def _close_open_clients() -> None:
	for client in list(_OPEN_CLIENTS):
		try:
			client.close()
		except Exception:
			pass


atexit.register(_close_open_clients)


class AuthError(Exception):
	pass


class AccountRiskError(Exception):
	"""BOSS 直聘风控拦截（code 36）：检测到异常行为。"""

	def __init__(self, message: str = "", is_cdp: bool = False):
		self.is_cdp = is_cdp
		super().__init__(message)


class BossClient:
	"""Hybrid API client: browser channel for high-risk ops, httpx for low-risk ops."""

	def __init__(self, auth_manager: "AuthManager", *, delay: tuple[float, float] = (1.5, 3.0), cdp_url: str | None = None) -> None:
		self._auth = auth_manager
		self._delay = delay
		self._client: httpx.Client | None = None
		self._browser_session: "BrowserSession | None" = None
		self._throttle = RequestThrottle(delay)
		self._cdp_url = cdp_url
		self._closed = False
		self._browser_search_since_refresh = 0
		self._dispatch_browser = False
		_OPEN_CLIENTS.add(self)

	def _run_browser_op(self, func: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
		"""Web 模式下将 patchright 调用切到专用浏览器线程。"""
		if not self._dispatch_browser:
			return func(*args, **kwargs)
		from pet_boss.web.browser_executor import run_browser_blocking

		return run_browser_blocking(lambda: func(*args, **kwargs))

	def _get_client(self) -> httpx.Client:
		if self._client is None:
			token = self._auth.get_token()
			headers = browser_headers(endpoints.DEFAULT_HEADERS, token)
			self._client = httpx.Client(
				base_url=endpoints.BASE_URL,
				cookies=token.get("cookies", {}),
				headers=headers,
				follow_redirects=True,
				timeout=30,
			)
		return self._client

	def _create_browser_session(self) -> "BrowserSession":
		from pet_boss.api.browser_client import BrowserSession

		token = self._auth.get_token()
		return BrowserSession(
			cookies=token.get("cookies", {}),
			user_agent=token.get("user_agent", ""),
			delay=self._delay,
			cdp_url=self._cdp_url,
			logger=getattr(self._auth, "_logger", None),
		)

	def _get_browser(self) -> "BrowserSession":
		if self._browser_session is None:
			if self._dispatch_browser:
				self._browser_session = self._run_browser_op(self._create_browser_session)
			else:
				self._browser_session = self._create_browser_session()
		return self._browser_session

	def _apply_stoken_refresh_from_browser(self) -> None:
		def _refresh() -> None:
			new_stoken = self._get_browser().refresh_stoken_in_page()
			self._auth.update_stoken(new_stoken)
			self._browser_search_since_refresh = 0

		self._run_browser_op(_refresh)

	def _maybe_refresh_stoken_before_search(self) -> None:
		"""每连续 N 次搜岗前主动刷新 stoken，避免 BOSS 第 6 次起返回 code 37。"""
		if self._browser_search_since_refresh < _STOKEN_SEARCH_BATCH:
			return
		logger = getattr(self._auth, "_logger", None)
		if logger:
			logger.info(
				f"搜岗已连续 {_STOKEN_SEARCH_BATCH} 次，正在当前浏览器内刷新 stoken…"
			)
		self._apply_stoken_refresh_from_browser()
		if logger:
			logger.info("stoken 已刷新并同步至浏览器与本地登录态")

	def _should_retry_search_after_stoken_refresh(self, result: dict[str, Any]) -> bool:
		code = result.get("code")
		if code in (0, endpoints.CODE_ACCOUNT_RISK):
			return False
		msg = str(result.get("message") or "")
		if code == endpoints.CODE_STOKEN_EXPIRED:
			return True
		return "环境存在异常" in msg

	# ── Anti-detection delays (httpx channel) ────────────────────────

	def _headers_for(self, url: str) -> dict[str, str]:
		return referer_header(url, endpoints.REFERER_MAP, f"{endpoints.BASE_URL}/")

	def _merge_cookies(self, resp: httpx.Response) -> None:
		merge_response_cookies(self._get_client(), resp)

	# ── httpx request (low-risk ops) ─────────────────────────────────

	def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
		"""httpx 请求，循环重试（最多 _MAX_RETRIES 次），替代递归调用。"""
		for attempt in range(_MAX_RETRIES + 1):
			client = self._get_client()
			token = self._auth.get_token()
			stoken = token.get("stoken", "")

			add_stoken_to_get_params(method, kwargs, stoken)

			self._throttle.wait()

			extra_headers = self._headers_for(url)
			if is_http_trace_enabled():
				log_outgoing_request(
					channel="httpx",
					method=method,
					url=f"{client.base_url.rstrip('/')}{url}",
					params=kwargs.get("params"),
					data=kwargs.get("data") or kwargs.get("json"),
					headers={**dict(client.headers), **extra_headers},
					cookies=dict(client.cookies),
					extra={"stoken_in_query": bool(stoken and method.upper() == "GET")},
				)
			resp = client.request(method, url, headers=extra_headers, **kwargs)
			self._throttle.mark()
			self._merge_cookies(resp)

			# 403 或安全验证 → 刷新 token 重试
			if resp.status_code == 403 or "安全验证" in resp.text:
				if attempt >= _MAX_RETRIES:
					raise AuthError("Token 刷新后仍被拒绝，请重新登录")
				backoff = (2 ** attempt) + random.uniform(0.5, 1.5)
				time.sleep(backoff)
				self._auth.force_refresh(cdp_url=self._cdp_url)
				self._client = None
				continue

			resp.raise_for_status()
			data = resp.json()
			code = data.get("code")

			# stoken 过期 → 刷新重试
			if code == endpoints.CODE_STOKEN_EXPIRED and attempt < _MAX_RETRIES:
				backoff = (2 ** attempt) + random.uniform(0.5, 1.5)
				time.sleep(backoff)
				self._auth.force_refresh(cdp_url=self._cdp_url)
				self._client = None
				continue

			# 频率限制 → 冷却重试
			if code == endpoints.CODE_RATE_LIMITED and attempt < _MAX_RETRIES:
				cooldown = min(60, 10 * (2 ** attempt))
				time.sleep(cooldown)
				continue

			if is_http_trace_enabled():
				log_incoming_response(
					channel="httpx",
					label=f"HTTP {resp.status_code}",
					body=data,
				)
			return cast("dict[str, Any]", data)

		raise AuthError("请求失败，已达最大重试次数")

	# ── Browser request (high-risk ops) ──────────────────────────────

	def _browser_request(self, method: str, url: str, *, params: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
		if is_http_trace_enabled():
			token = self._auth.get_token()
			referer = endpoints.REFERER_MAP.get(url, f"{endpoints.BASE_URL}/")
			browser_headers_map = {
				"Accept": "application/json, text/plain, */*",
				"Referer": referer,
				"X-Requested-With": "XMLHttpRequest",
			}
			if method.upper() == "POST" and data:
				browser_headers_map["Content-Type"] = "application/x-www-form-urlencoded"
			log_outgoing_request(
				channel="browser-fetch",
				method=method,
				url=url,
				params=params,
				data=data,
				headers=browser_headers_map,
				cookies=dict(token.get("cookies") or {}),
				extra={"stoken": token.get("stoken") or ""},
			)
		result = self._run_browser_op(
			self._do_browser_request, method, url, params=params, data=data,
		)
		if is_http_trace_enabled():
			log_incoming_response(
				channel="browser-fetch",
				label=f"code={result.get('code', '?')}",
				body=result,
			)
		code = result.get("code")
		if code == endpoints.CODE_ACCOUNT_RISK:
			msg = result.get("message", "账户存在异常行为")
			browser = self._browser_session
			is_cdp = getattr(browser, "_is_cdp", False) if browser is not None else False
			mode = "CDP" if is_cdp else "headless patchright"
			raise AccountRiskError(
				f"BOSS 直聘风控拦截 (code {code}): {msg}。"
				f"当前浏览器模式: {mode}。"
				f"建议：停止自动化访问并回到 BOSS 直聘官方页面手动处理。",
				is_cdp=is_cdp,
			)
		return result

	def _do_browser_request(
		self,
		method: str,
		url: str,
		*,
		params: dict[str, Any] | None = None,
		data: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		browser = self._get_browser()
		return browser.request(method, url, params=params, data=data)

	def refresh_browser_home(self) -> None:
		"""每轮侦察前：浏览器回到首页刷新，断开连续采集会话感。"""
		self._run_browser_op(self._get_browser().refresh_home_for_new_round)

	def focus_automation_browser(self, *, url: str | None = None) -> bool:
		"""聚焦 patchright/CDP 自动化窗口（Web 搜岗登录态所在）。"""
		return bool(self._run_browser_op(lambda: self._get_browser().focus_window(url=url)))

	def restart_browser(self) -> dict[str, Any]:
		"""关闭并重建浏览器会话（页面导航卡死时由监控 AI 调用）。"""
		logger = getattr(self._auth, "_logger", None)
		outcome: dict[str, Any] = {
			"ok": False,
			"stoken_ok": False,
			"sequence": "stall_then_close",
		}
		if logger:
			logger.info("[boss-browser] 监控触发浏览器重启（先卡后关）…")
		try:
			session_outcome = self._run_browser_op(self._get_browser().restart_session)
			outcome.update(session_outcome)
		except Exception as exc:
			outcome["phase"] = "failed"
			outcome["error"] = str(exc) or exc.__class__.__name__
			if logger:
				logger.info(f"[boss-browser] 重启失败（关闭/拉起阶段）：{outcome['error']}")
			return outcome

		if not outcome.get("launch_ok"):
			if logger:
				logger.info(
					f"[boss-browser] 新窗口未就绪（phase={outcome.get('phase')}）："
					f"{outcome.get('error') or '未知原因'}"
				)
			return outcome

		try:
			if logger:
				logger.info("[boss-browser] 新窗口已就绪，正在刷新 stoken…")
			self._apply_stoken_refresh_from_browser()
			outcome["stoken_ok"] = True
			outcome["ok"] = True
			if logger:
				logger.info("[boss-browser] 浏览器重启完成，stoken 已同步")
		except Exception as exc:
			self._browser_search_since_refresh = _STOKEN_SEARCH_BATCH
			outcome["stoken_ok"] = False
			outcome["stoken_error"] = str(exc) or exc.__class__.__name__
			outcome["ok"] = True
			outcome["warn"] = "stoken_refresh_failed"
			if logger:
				logger.info(
					f"[boss-browser] 新窗口已拉起但 stoken 刷新失败：{outcome['stoken_error']}；"
					"下次搜岗将优先刷新"
				)
		return outcome

	def close_browser_session(self) -> None:
		"""关闭 BOSS 自动化浏览器页面/窗口，保留 httpx 通道。"""
		session = self._browser_session
		if session is None:
			return
		self._browser_session = None

		def _close() -> None:
			try:
				session.close()
			except Exception:
				pass

		if self._dispatch_browser:
			self._run_browser_op(_close)
		else:
			_close()

	# ── Public API ───────────────────────────────────────────────────
	# High-risk: search, recommend, greet, job_card → browser channel
	# Low-risk: status, me, cities, schema, detail → httpx channel

	def search_jobs(self, query: str, **filters: Any) -> dict[str, Any]:
		params: dict[str, Any] = {"query": query, "page": filters.get("page", 1)}
		if raw_params := filters.get("raw_params"):
			params.update(raw_params)
		city_code = filters.get("city_code")
		if city_code:
			params["city"] = str(city_code)
		elif city := filters.get("city"):
			from pet_boss.api.regions import city_code_map

			code = city_code_map().get(city) or endpoints.CITY_CODES.get(city)
			if code is None:
				raise ValueError(f"未知城市: {city}")
			params["city"] = code
		if district_code := filters.get("district_code"):
			params["multiBusinessDistrict"] = str(district_code)
		if salary := filters.get("salary"):
			code = filters.get("salary_code") or endpoints.SALARY_CODES.get(salary)
			if code:
				params["salary"] = code
		if exp := filters.get("experience"):
			code = filters.get("experience_code") or endpoints.EXPERIENCE_CODES.get(exp)
			if code:
				params["experience"] = code
		if edu := filters.get("education"):
			code = filters.get("education_code") or endpoints.EDUCATION_CODES.get(edu)
			if code:
				params["degree"] = code
		if scale := filters.get("scale"):
			code = filters.get("scale_code") or endpoints.SCALE_CODES.get(scale)
			if code:
				params["scale"] = code
		if industry := filters.get("industry"):
			code = filters.get("industry_code") or endpoints.INDUSTRY_CODES.get(industry)
			if code:
				params["industry"] = code
		if stage := filters.get("stage"):
			code = filters.get("stage_code") or endpoints.STAGE_CODES.get(stage)
			if code:
				params["stage"] = code
		if job_type := filters.get("job_type"):
			code = filters.get("job_type_code") or endpoints.JOB_TYPE_CODES.get(job_type)
			if code:
				params["jobType"] = code
		self._maybe_refresh_stoken_before_search()
		result = self._browser_request("GET", endpoints.SEARCH_URL, params=params)
		if result.get("code") == 0:
			self._browser_search_since_refresh += 1
			return result
		if self._should_retry_search_after_stoken_refresh(result):
			logger = getattr(self._auth, "_logger", None)
			if logger:
				logger.info(
					f"搜岗返回 code={result.get('code')}（{result.get('message', '')}），"
					"尝试刷新 stoken 后重试一次…"
				)
			try:
				self._apply_stoken_refresh_from_browser()
				result = self._browser_request("GET", endpoints.SEARCH_URL, params=params)
				if result.get("code") == 0:
					self._browser_search_since_refresh += 1
					return result
			except Exception as exc:
				if logger:
					logger.info(f"stoken 刷新失败，尝试重开浏览器后同页重试：{exc}")
				try:
					restart_outcome = self.restart_browser()
					if restart_outcome.get("launch_ok"):
						result = self._browser_request("GET", endpoints.SEARCH_URL, params=params)
						if result.get("code") == 0:
							self._browser_search_since_refresh += 1
							if logger:
								logger.info("重开浏览器后同页重试成功")
				except Exception as restart_exc:
					if logger:
						logger.info(f"重开浏览器同页重试失败：{restart_exc}")
		return result

	def recommend_jobs(self, page: int = 1) -> dict[str, Any]:
		params = {"page": page}
		return self._browser_request("GET", endpoints.RECOMMEND_URL, params=params)

	def greet(self, security_id: str, job_id: str, message: str = "") -> dict[str, Any]:
		data = {
			"securityId": security_id,
			"jobId": job_id,
			"greeting": message or "您好，我对该岗位很感兴趣，希望能和您聊一聊。",
		}
		return self._browser_request("POST", endpoints.GREET_URL, data=data)

	def apply(self, security_id: str, job_id: str, lid: str = "") -> dict[str, Any]:
		"""Current minimal apply path - reuses the immediate-chat browser endpoint."""
		data = {
			"securityId": security_id,
			"jobId": job_id,
		}
		if lid:
			data["lid"] = lid
		return self._browser_request("POST", endpoints.GREET_URL, data=data)

	def job_card(self, security_id: str, lid: str = "") -> dict[str, Any]:
		"""httpx 优先 + 浏览器降级获取职位卡片信息。"""
		try:
			return self.job_card_httpx(security_id, lid)
		except Exception:
			pass
		params = {"securityId": security_id, "lid": lid}
		return self._browser_request("GET", endpoints.JOB_CARD_URL, params=params)

	def job_card_httpx(self, security_id: str, lid: str = "") -> dict[str, Any]:
		"""通过 httpx 通道获取职位卡片信息（低延迟）。"""
		params = {"securityId": security_id, "lid": lid}
		return self._request("GET", endpoints.JOB_CARD_URL, params=params)

	# ── Low-risk: httpx channel ──────────────────────────────────────

	def job_detail(self, job_id: str) -> dict[str, Any]:
		params = {"encryptJobId": job_id}
		return self._request("GET", endpoints.DETAIL_URL, params=params)

	def user_info(self) -> dict[str, Any]:
		return self._request("GET", endpoints.USER_INFO_URL)

	def resume_baseinfo(self) -> dict[str, Any]:
		return self._request("GET", endpoints.RESUME_BASEINFO_URL)

	def resume_expect(self) -> dict[str, Any]:
		return self._request("GET", endpoints.RESUME_EXPECT_URL)

	def deliver_list(self, page: int = 1) -> dict[str, Any]:
		params = {"page": page}
		return self._request("GET", endpoints.DELIVER_LIST_URL, params=params)

	def friend_list(self, page: int = 1) -> dict[str, Any]:
		params = {"page": page}
		return self._request("GET", endpoints.FRIEND_LIST_URL, params=params)

	def interview_data(self) -> dict[str, Any]:
		return self._request("GET", endpoints.INTERVIEW_DATA_URL)

	def job_history(self, page: int = 1) -> dict[str, Any]:
		params = {"page": page}
		return self._request("GET", endpoints.JOB_HISTORY_URL, params=params)

	def chat_history(self, gid: str, security_id: str, *, page: int = 1, count: int = 20) -> dict[str, Any]:
		"""获取与指定好友的聊天消息历史。"""
		params = {"gid": gid, "securityId": security_id, "page": page, "c": count, "src": 0}
		return self._request("GET", endpoints.CHAT_HISTORY_URL, params=params)

	def friend_label(self, friend_id: str, label_id: int, friend_source: int = 0, *, remove: bool = False) -> dict[str, Any]:
		"""添加或移除好友标签。"""
		url = endpoints.FRIEND_LABEL_DELETE_URL if remove else endpoints.FRIEND_LABEL_ADD_URL
		params = {"friendId": friend_id, "friendSource": friend_source, "labelId": label_id}
		return self._request("GET", url, params=params)

	def exchange_contact(self, security_id: str, uid: str, name: str, exchange_type: int = 1) -> dict[str, Any]:
		"""请求交换联系方式（1=手机, 2=微信）。"""
		data = {"type": exchange_type, "securityId": security_id, "uniqueId": uid, "name": name}
		return self._browser_request("POST", endpoints.EXCHANGE_REQUEST_URL, data=data)

	def resume_status(self) -> dict[str, Any]:
		"""查询简历完整度和在线状态。"""
		return self._request("GET", endpoints.RESUME_STATUS_URL)

	def geek_get_job(self, security_id: str) -> dict[str, Any]:
		"""查询与某招聘者的互动关系（是否已打招呼等）。"""
		params = {"securityId": security_id}
		return self._request("GET", endpoints.GEEK_GET_JOB_URL, params=params)

	# ── Lifecycle ────────────────────────────────────────────────────

	def close(self) -> None:
		"""Release httpx client and browser session. Idempotent."""
		if self._closed:
			return
		self._closed = True
		self.close_browser_session()
		if self._client:
			self._client.close()
			self._client = None
		_OPEN_CLIENTS.discard(self)

	def __enter__(self) -> "BossClient":
		return self

	def __exit__(
		self,
		exc_type: type[BaseException] | None,
		exc_val: BaseException | None,
		exc_tb: TracebackType | None,
	) -> None:
		self.close()
