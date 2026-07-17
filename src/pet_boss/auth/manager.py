from pathlib import Path
from typing import Any

from pet_boss.auth.browser import login_via_browser, login_via_cdp, probe_cdp, refresh_stoken, refresh_stoken_via_cdp
from pet_boss.auth.cookie_extract import extract_cookies
from pet_boss.auth.qr_login import qr_login_httpx
from pet_boss.auth.token_store import TokenStore
from pet_boss.output import Logger


class AuthRequired(Exception):
	pass


class TokenRefreshFailed(Exception):
	pass


class AuthManager:
	def __init__(self, data_dir: Path, *, logger: Logger | None = None, platform: str = "zhipin") -> None:
		self._platform = platform or "zhipin"
		auth_dir = data_dir / "auth"
		self._store = TokenStore(auth_dir)
		self._token: dict[str, Any] | None = None
		self._logger = logger or Logger()

	def _login_action(self) -> str:
		return "boss login"

	def get_token(self) -> dict[str, Any]:
		if self._token is not None:
			return self._token
		self._token = self._store.load()
		if self._token is None:
			raise AuthRequired(f"未登录，请先执行 {self._login_action()}")
		return self._token

	def ensure_session(
		self,
		*,
		cdp_url: str | None = None,
		cookie_source: str | None = None,
		try_browser: bool = True,
	) -> dict[str, Any]:
		"""确保有可用的登录态（记住登录）。

		1. 读取本地加密保存的 session（~/.boss-agent/auth/session.enc）
		2. 在线验证 Cookie 是否仍有效
		3. 失效时尝试从本地浏览器同步 Cookie（无需重新扫码）
		4. 缺少 stoken 时尝试静默刷新
		"""
		token = self._store.load()
		if token and self._has_primary_cookie(token):
			if not token.get("stoken"):
				refreshed = self._try_refresh_and_verify(token, cdp_url=cdp_url)
				if refreshed is not None:
					return refreshed

			if self._verify_cookie(token):
				self._token = token
				return token

			refreshed = self._try_refresh_and_verify(token, cdp_url=cdp_url)
			if refreshed is not None:
				return refreshed

			self._logger.info("本地登录态已失效，尝试从浏览器同步 Cookie...")

		if try_browser:
			extracted = extract_cookies(cookie_source, platform=self._platform)
			if extracted and self._has_primary_cookie(extracted) and self._verify_cookie(extracted):
				self._store.save(extracted)
				self._token = extracted
				self._logger.info("已从本地浏览器同步登录态并保存")
				return extracted

		if token is None:
			raise AuthRequired(f"未登录，请先执行 {self._login_action()}")
		raise AuthRequired(f"登录已过期，请重新执行 {self._login_action()}")

	def login(
		self,
		*,
		timeout: int = 120,
		cookie_source: str | None = None,
		cdp_url: str | None = None,
		force_cdp: bool = False,
	) -> dict[str, Any]:
		"""三级降级登录：Cookie 提取 → CDP 自动探测 → patchright 扫码。

		Args:
			force_cdp: 为 True 时跳过 Cookie 提取，CDP 不可用直接报错。
		"""
		method = "未知"
		token: dict[str, Any] | None = None

		if force_cdp:
			# --cdp 强制模式：跳过 Cookie，CDP 不可用直接抛异常
			self._logger.info("强制 CDP 模式，跳过 Cookie 提取")
			token = login_via_cdp(cdp_url=cdp_url, timeout=timeout, platform=self._platform)
			method = "CDP 扫码"
			self._store.save(token)
			self._token = token
			return {**token, "_method": method}

		# 第一步：尝试从本地浏览器提取 Cookie
		self._logger.info("尝试从本地浏览器提取 Cookie...")
		token = extract_cookies(cookie_source, platform=self._platform)
		if token and self._has_primary_cookie(token):
			if self._verify_cookie(token):
				self._store.save(token)
				self._token = token
				self._logger.info("Cookie 提取成功，已保存")
				return {**token, "_method": "Cookie 提取"}
			self._logger.info("提取的 Cookie 已失效，降级到 CDP")
		else:
			self._logger.info("未能从浏览器提取 Cookie，降级到 CDP")

		# 第二步：CDP 自动探测
		if probe_cdp(cdp_url):
			self._logger.info("检测到 CDP 可用，尝试 CDP 登录...")
			try:
				token = login_via_cdp(cdp_url=cdp_url, timeout=timeout, platform=self._platform)
				method = "CDP 扫码"
				self._store.save(token)
				self._token = token
				return {**token, "_method": method}
			except Exception as e:
				self._logger.info(f"CDP 登录失败（{e}），降级到 patchright")
		else:
			self._logger.info("CDP 不可用，尝试 QR 纯 httpx 登录")

		# 第三步：QR 纯 httpx 登录（仅 zhipin）
		if self._platform == "zhipin":
			try:
				self._logger.info("尝试 QR 纯 httpx 登录...")
				token = qr_login_httpx(timeout=timeout)
				method = "QR httpx 登录"
				self._store.save(token)
				self._token = token
				return {**token, "_method": method}
			except Exception as e:
				self._logger.info(f"QR httpx 登录失败（{e}），降级到 patchright")

		# 第四步：patchright 扫码（兜底）
		token = login_via_browser(timeout=timeout, platform=self._platform)
		method = "扫码登录"
		self._store.save(token)
		self._token = token
		return {**token, "_method": method}

	def _has_primary_cookie(self, token: dict[str, Any]) -> bool:
		cookies = token.get("cookies", {})
		return bool(cookies.get("wt2"))

	def _verify_cookie(self, token: dict[str, Any]) -> bool:
		"""验证 Cookie 是否有效（与 BossClient 一致：含 stoken 与浏览器头）。"""
		try:
			import httpx
			from pet_boss.api import endpoints
			from pet_boss.api.httpx_helpers import (
				add_stoken_to_get_params,
				browser_headers,
				referer_header,
			)

			headers = browser_headers(endpoints.DEFAULT_HEADERS, token)
			headers.update(
				referer_header(
					endpoints.USER_INFO_URL,
					endpoints.REFERER_MAP,
					f"{endpoints.BASE_URL}/",
				)
			)
			request_kwargs: dict[str, Any] = {}
			add_stoken_to_get_params("GET", request_kwargs, str(token.get("stoken") or ""))

			resp = httpx.get(
				endpoints.USER_INFO_URL,
				cookies=token.get("cookies", {}),
				headers=headers,
				params=request_kwargs.get("params"),
				timeout=10,
			)
			data = resp.json()
			return bool(data.get("code") == 0)
		except (httpx.HTTPError, ValueError, KeyError):
			return False

	def _try_refresh_and_verify(
		self,
		token: dict[str, Any],
		*,
		cdp_url: str | None = None,
	) -> dict[str, Any] | None:
		"""静默刷新 stoken 后再次校验；失败返回 None。"""
		try:
			self._token = token
			self.force_refresh(cdp_url=cdp_url)
			refreshed = self._token
			if refreshed and self._verify_cookie(refreshed):
				return refreshed
		except TokenRefreshFailed:
			return None
		return None

	def force_refresh(self, cdp_url: str | None = None) -> None:
		with self._store.refresh_lock():
			current = self._store.load()
			if current is None:
				raise TokenRefreshFailed("无法刷新 Token，请重新登录")
			self._logger.info("Token 过期，正在静默刷新...")
			try:
				# CDP 优先：指纹一致，不会被 BOSS 直聘拒绝
				if probe_cdp(cdp_url):
					self._logger.info("检测到 CDP，使用 CDP 刷新 stoken")
					new_stoken = refresh_stoken_via_cdp(cdp_url)
				else:
					self._logger.info("CDP 不可用，降级到 headless 刷新 stoken")
					new_stoken = refresh_stoken(
						current["cookies"],
						current.get("user_agent", ""),
					)
				refreshed = {**current, "stoken": new_stoken}
				self._store.save(refreshed)
				self._token = refreshed
			except Exception as e:
				raise TokenRefreshFailed(f"Token 刷新失败: {e}") from e

	def update_stoken(self, stoken: str) -> None:
		"""写入新 stoken（搜岗批次刷新等场景，不另开浏览器）。"""
		stoken = str(stoken or "").strip()
		if not stoken:
			raise TokenRefreshFailed("stoken 为空，无法更新")
		current = self._store.load() or self.get_token()
		cookies = dict(current.get("cookies") or {})
		cookies["__zp_stoken__"] = stoken
		refreshed = {**current, "stoken": stoken, "cookies": cookies}
		self._store.save(refreshed)
		self._token = refreshed

	def check_status(self) -> dict[str, Any] | None:
		return self._store.load()

	def resolve_session(self, *, try_browser: bool = True) -> tuple[dict[str, Any] | None, bool]:
		"""返回 (token, verified)。verified=True 表示已通过在线校验，可用于搜岗/侦察。"""
		try:
			token = self.ensure_session(try_browser=try_browser)
			return token, True
		except AuthRequired:
			return self.check_status(), False

	def logout(self) -> None:
		"""清除本地登录态"""
		self._store.clear()
		self._token = None
