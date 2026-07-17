"""HTTP 追踪开关与日志格式。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pet_boss.api import endpoints
from pet_boss.api.client import BossClient
from pet_boss.api.http_trace import is_http_trace_enabled, log_incoming_response, log_outgoing_request


def test_http_trace_disabled_by_default(monkeypatch):
	monkeypatch.delenv("BOSS_HTTP_TRACE", raising=False)
	assert is_http_trace_enabled() is False


def test_http_trace_enabled_with_env(monkeypatch):
	monkeypatch.setenv("BOSS_HTTP_TRACE", "1")
	assert is_http_trace_enabled() is True


def test_log_outgoing_request_prints_to_stderr(monkeypatch, capsys):
	monkeypatch.setenv("BOSS_HTTP_TRACE", "1")
	log_outgoing_request(
		channel="browser-fetch",
		method="GET",
		url=endpoints.SEARCH_URL,
		params={"query": "Java", "page": 6},
		headers={"Referer": "https://www.zhipin.com/"},
		cookies={"wt2": "abc123"},
	)
	out = capsys.readouterr().err
	assert "[BOSS HTTP TRACE] REQUEST" in out
	assert "Java" in out
	assert "page" in out
	assert "wt2" in out


def test_log_incoming_response_truncates_large_body(monkeypatch, capsys):
	monkeypatch.setenv("BOSS_HTTP_TRACE", "1")
	monkeypatch.setenv("BOSS_HTTP_TRACE_MAX", "200")
	log_incoming_response(
		channel="browser-fetch",
		label="code=36",
		body={"code": 36, "message": "环境异常", "zpData": {"jobList": ["x"] * 50}},
	)
	out = capsys.readouterr().err
	assert "[BOSS HTTP TRACE] RESPONSE" in out
	assert "truncated" in out


class _StubAuth:
	def __init__(self):
		self.token = {
			"cookies": {"wt2": "cookie-value", "__zp_stoken__": "stoken-value"},
			"stoken": "stoken-value",
			"user_agent": "UA",
		}

	def get_token(self):
		return self.token

	def force_refresh(self, cdp_url=None):
		return None


def test_browser_request_emits_trace_when_enabled(monkeypatch, capsys):
	monkeypatch.setenv("BOSS_HTTP_TRACE", "1")
	client = BossClient(_StubAuth())
	mock_browser = MagicMock()
	mock_browser.request.return_value = {"code": 0, "message": "Success", "zpData": {"jobList": []}}
	mock_browser._is_cdp = False
	mock_browser._is_bridge = False
	client._browser_session = mock_browser

	client.search_jobs("AI应用开发", page=6)

	err = capsys.readouterr().err
	assert "REQUEST" in err
	assert "page=6" in err or '"page": 6' in err
	assert "RESPONSE" in err
	assert "Success" in err or '"code": 0' in err
	mock_browser.request.assert_called_once()
