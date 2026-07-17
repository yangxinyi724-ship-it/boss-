"""搜岗 stoken 批次刷新测试。"""

from unittest.mock import MagicMock

from pet_boss.api.client import BossClient, _STOKEN_SEARCH_BATCH


class _StubAuth:
	def __init__(self):
		self.token = {
			"cookies": {"wt2": "x", "__zp_stoken__": "old"},
			"stoken": "old",
			"user_agent": "UA",
		}
		self._logger = MagicMock()
		self.refresh_count = 0

	def get_token(self):
		return self.token

	def force_refresh(self, cdp_url=None):
		self.refresh_count += 1
		self.token = {**self.token, "stoken": f"new-{self.refresh_count}"}

	def update_stoken(self, stoken: str) -> None:
		cookies = dict(self.token.get("cookies") or {})
		cookies["__zp_stoken__"] = stoken
		self.token = {**self.token, "stoken": stoken, "cookies": cookies}


def test_search_refreshes_stoken_before_sixth_request():
	auth = _StubAuth()
	client = BossClient(auth)
	mock_browser = MagicMock()
	mock_browser.request.return_value = {"code": 0, "message": "Success", "zpData": {}}
	mock_browser.refresh_stoken_in_page.return_value = "new-1"
	client._browser_session = mock_browser

	for i in range(_STOKEN_SEARCH_BATCH):
		client.search_jobs("Java", page=i + 1)
	assert auth.refresh_count == 0
	assert client._browser_search_since_refresh == _STOKEN_SEARCH_BATCH

	client.search_jobs("Java", page=6)
	mock_browser.refresh_stoken_in_page.assert_called_once()
	assert auth.token["stoken"] == "new-1"
	assert client._browser_search_since_refresh == 1
	assert mock_browser.request.call_count == _STOKEN_SEARCH_BATCH + 1


def test_search_skips_refresh_when_batch_not_reached():
	auth = _StubAuth()
	client = BossClient(auth)
	mock_browser = MagicMock()
	mock_browser.request.return_value = {"code": 0, "zpData": {}}
	client._browser_session = mock_browser

	client.search_jobs("Java", page=1)
	assert auth.refresh_count == 0
	mock_browser.refresh_stoken_in_page.assert_not_called()


def test_search_retries_after_env_error_with_stoken_refresh():
	auth = _StubAuth()
	client = BossClient(auth)
	mock_browser = MagicMock()
	mock_browser.request.side_effect = [
		{"code": 37, "message": "您的环境存在异常.", "zpData": {}},
		{"code": 0, "message": "Success", "zpData": {}},
	]
	mock_browser.refresh_stoken_in_page.return_value = "new-retry"
	client._browser_session = mock_browser

	result = client.search_jobs("Java", page=6)
	assert result["code"] == 0
	mock_browser.refresh_stoken_in_page.assert_called_once()
	assert auth.token["stoken"] == "new-retry"


def test_restart_browser_refreshes_stoken_instead_of_resetting_counter():
	auth = _StubAuth()
	client = BossClient(auth)
	client._browser_search_since_refresh = 3
	mock_browser = MagicMock()
	mock_browser.restart_session.return_value = {"launch_ok": True, "ok": True}
	mock_browser.refresh_stoken_in_page.return_value = "after-restart"
	client._browser_session = mock_browser

	client.restart_browser()
	mock_browser.restart_session.assert_called_once()
	mock_browser.refresh_stoken_in_page.assert_called_once()
	assert client._browser_search_since_refresh == 0
	assert auth.token["stoken"] == "after-restart"


def test_restart_browser_forces_refresh_on_next_search_when_stoken_refresh_fails():
	auth = _StubAuth()
	client = BossClient(auth)
	client._browser_search_since_refresh = 2
	mock_browser = MagicMock()
	mock_browser.restart_session.return_value = {"launch_ok": True, "ok": True}
	mock_browser.refresh_stoken_in_page.side_effect = RuntimeError("no page")
	client._browser_session = mock_browser

	client.restart_browser()
	assert client._browser_search_since_refresh == _STOKEN_SEARCH_BATCH


def test_search_restarts_browser_when_stoken_refresh_raises():
	auth = _StubAuth()
	client = BossClient(auth)
	mock_browser = MagicMock()
	mock_browser.request.side_effect = [
		{"code": 37, "message": "您的环境存在异常.", "zpData": {}},
		{"code": 0, "message": "Success", "zpData": {}},
	]
	mock_browser.refresh_stoken_in_page.side_effect = RuntimeError("浏览器页面未生成 stoken")
	mock_browser.restart_session.return_value = {"launch_ok": True, "ok": True}
	client._browser_session = mock_browser

	# 第二次 refresh 在 restart 内成功
	def _refresh_side_effect():
		if mock_browser.refresh_stoken_in_page.call_count == 1:
			raise RuntimeError("浏览器页面未生成 stoken")
		return "recovered"

	mock_browser.refresh_stoken_in_page.side_effect = _refresh_side_effect

	result = client.search_jobs("Java", page=6)
	assert result["code"] == 0
	mock_browser.restart_session.assert_called_once()
	assert auth.token["stoken"] == "recovered"