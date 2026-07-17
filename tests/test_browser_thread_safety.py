"""patchright 须在专用浏览器线程创建/关闭，不可在 asyncio 循环线程直接调用。"""

from unittest.mock import MagicMock, patch

from pet_boss.api.browser_client import _on_running_asyncio_loop, _run_browser_thread_safe


def test_on_running_asyncio_loop_false_outside_async():
	assert _on_running_asyncio_loop() is False


def test_run_browser_thread_safe_runs_inline_without_loop():
	calls: list[str] = []

	def _fn() -> str:
		calls.append("ok")
		return "done"

	assert _run_browser_thread_safe(_fn) == "done"
	assert calls == ["ok"]


def test_run_browser_thread_safe_delegates_on_asyncio_loop():
	import asyncio

	result: list[str] = []

	async def _runner() -> None:
		def _fn() -> str:
			result.append("browser")
			return "ok"

		with patch(
			"pet_boss.web.browser_executor.run_browser_blocking",
			side_effect=lambda f: f(),
		) as mock_run:
			assert _run_browser_thread_safe(_fn) == "ok"
			mock_run.assert_called_once()

	asyncio.run(_runner())
	assert result == ["browser"]


def test_close_browser_session_uses_run_browser_op_when_dispatch():
	from pet_boss.api.client import BossClient

	auth = MagicMock()
	auth.get_token.return_value = {"cookies": {}, "user_agent": ""}
	client = BossClient(auth, delay=(0.0, 0.0))
	client._dispatch_browser = True
	session = MagicMock()
	client._browser_session = session

	with patch.object(client, "_run_browser_op", side_effect=lambda fn: fn()) as run_op:
		client.close_browser_session()

	assert client._browser_session is None
	run_op.assert_called_once()
	session.close.assert_called_once()


def test_get_browser_creates_via_run_browser_op_when_dispatch():
	from pet_boss.api.client import BossClient

	auth = MagicMock()
	auth.get_token.return_value = {"cookies": {}, "user_agent": ""}
	client = BossClient(auth, delay=(0.0, 0.0))
	client._dispatch_browser = True
	fake_session = MagicMock()

	with patch.object(client, "_run_browser_op", return_value=fake_session) as run_op:
		assert client._get_browser() is fake_session

	run_op.assert_called_once()
	assert client._browser_session is fake_session
