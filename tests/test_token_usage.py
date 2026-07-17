"""Token 用量统计测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from pet_boss.agents.monitor_ai import MonitorAI
from pet_boss.ai.service import AIService
from pet_boss.ai.token_usage import (
	TokenUsageStore,
	estimate_token_cost,
	get_token_usage_store,
	get_token_usage_summary,
	save_token_pricing,
)
from pet_boss.web.server import create_app


def test_token_usage_store_record_and_summary(tmp_path: Path):
	store = TokenUsageStore(data_dir=tmp_path)
	store.record(agent="FX", prompt_tokens=100, completion_tokens=50, total_tokens=150)
	store.record(agent="ZC", prompt_tokens=20, completion_tokens=10, total_tokens=30)
	summary = store.summary()
	assert summary["session_total"]["total_tokens"] == 180
	assert summary["session_total"]["calls"] == 2
	assert "by_agent" not in summary


def test_estimate_token_cost():
	cost = estimate_token_cost(
		{"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
		input_per_m=1.0,
		output_per_m=2.0,
	)
	assert cost["amount"] == 2.0
	assert cost["formatted"] == "¥2.00"


def test_estimate_token_cost_deepseek_cache_hit():
	cost = estimate_token_cost(
		{
			"prompt_tokens": 1_000_000,
			"prompt_cache_hit_tokens": 800_000,
			"prompt_cache_miss_tokens": 200_000,
			"completion_tokens": 500_000,
		},
		input_per_m=1.0,
		output_per_m=2.0,
		input_cache_hit_per_m=0.02,
	)
	# 800k*0.02/1M + 200k*1/1M + 500k*2/1M = 0.016 + 0.2 + 1.0 = 1.216
	assert cost["amount"] == pytest.approx(1.216)


def test_get_token_usage_summary_includes_cost(tmp_path: Path):
	store = get_token_usage_store(tmp_path)
	store.record(prompt_tokens=100_000, completion_tokens=50_000, total_tokens=150_000)
	summary = get_token_usage_summary(tmp_path)
	assert summary["session_total"]["total_tokens"] == 150_000
	assert summary["cost"]["amount"] == pytest.approx(0.2)
	assert summary["pricing"]["input_per_m"] == 1.0
	assert summary["pricing"]["output_per_m"] == 2.0
	assert summary["pricing"]["input_cache_hit_per_m"] == 0.02


def test_save_token_pricing(tmp_path: Path):
	pricing = save_token_pricing(tmp_path, input_per_m=3.5, output_per_m=7.0)
	assert pricing["input_per_m"] == 3.5
	assert pricing["output_per_m"] == 7.0
	store = get_token_usage_store(tmp_path)
	store.record(prompt_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000)
	summary = get_token_usage_summary(tmp_path)
	assert summary["cost"]["amount"] == pytest.approx(3.5)


def test_ai_service_records_usage(tmp_path: Path):
	store = get_token_usage_store(tmp_path)
	service = AIService(
		base_url="https://api.example.com/v1",
		api_key="sk-test",
		model="gpt-4",
		usage_store=store,
	)
	mock_resp = httpx.Response(
		status_code=200,
		json={
			"choices": [{"message": {"content": "ok"}}],
			"usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
		},
		request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
	)
	with patch("pet_boss.ai.service.httpx.post", return_value=mock_resp):
		assert service.chat([{"role": "user", "content": "hi"}], agent="FX") == "ok"
	summary = store.summary()
	assert summary["session_total"]["total_tokens"] == 20
	assert "by_agent" not in summary


def test_ai_service_records_deepseek_cache_usage(tmp_path: Path):
	store = get_token_usage_store(tmp_path)
	service = AIService(
		base_url="https://api.deepseek.com/v1",
		api_key="sk-test",
		model="deepseek-chat",
		usage_store=store,
	)
	mock_resp = httpx.Response(
		status_code=200,
		json={
			"choices": [{"message": {"content": "ok"}}],
			"usage": {
				"prompt_tokens": 1000,
				"completion_tokens": 200,
				"total_tokens": 1200,
				"prompt_cache_hit_tokens": 800,
				"prompt_cache_miss_tokens": 200,
			},
		},
		request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
	)
	with patch("pet_boss.ai.service.httpx.post", return_value=mock_resp):
		assert service.chat([{"role": "user", "content": "hi"}], agent="FX") == "ok"
	summary = store.summary()
	total = summary["session_total"]
	assert total["prompt_cache_hit_tokens"] == 800
	assert total["prompt_cache_miss_tokens"] == 200


def test_monitor_emits_token_event(tmp_path: Path):
	store = TokenUsageStore(data_dir=tmp_path)
	monitor = MonitorAI(tmp_path, usage_store=store)
	store.record(agent="MS", prompt_tokens=5, completion_tokens=5, total_tokens=10)
	events = list(monitor.drain_token_events())
	assert len(events) == 1
	assert events[0]["type"] == "monitor_token"
	assert events[0]["usage"]["session_total"]["total_tokens"] == 10
	assert events[0]["usage"]["cost"]["formatted"]
	assert "约" in events[0]["message"]
	assert list(monitor.drain_token_events()) == []


def test_monitor_token_api(tmp_path: Path):
	from starlette.testclient import TestClient

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.get("/api/monitor/token-usage")
	assert resp.status_code == 200
	body = resp.json()
	assert body["ok"] is True
	assert body["data"]["session_total"]["total_tokens"] == 0
	assert "cost" in body["data"]
	assert "pricing" in body["data"]

	store = get_token_usage_store(tmp_path)
	store.record(agent="FX", prompt_tokens=1, completion_tokens=2, total_tokens=3)
	resp = client.get("/api/monitor/token-usage")
	data = resp.json()["data"]
	assert data["session_total"]["total_tokens"] == 3
	assert data["cost"]["formatted"]

	resp = client.post("/api/monitor/token-pricing", json={"input_per_m": 10, "output_per_m": 20})
	assert resp.status_code == 200
	assert resp.json()["data"]["pricing"]["input_per_m"] == 10
