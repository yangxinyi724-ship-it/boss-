"""AI Token 用量统计 — 供监控 AI 实时展示。"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_MILLION = 1_000_000.0

# DeepSeek 官方定价（元/百万 tokens）：输入缓存命中 0.02，未命中 1，输出 2
DEEPSEEK_INPUT_CACHE_HIT_PER_M = 0.02
DEEPSEEK_INPUT_CACHE_MISS_PER_M = 1.0
DEEPSEEK_OUTPUT_PER_M = 2.0


@dataclass
class TokenUsageTotals:
	prompt_tokens: int = 0
	completion_tokens: int = 0
	total_tokens: int = 0
	prompt_cache_hit_tokens: int = 0
	prompt_cache_miss_tokens: int = 0
	calls: int = 0

	def add(
		self,
		*,
		prompt: int,
		completion: int,
		total: int,
		prompt_cache_hit: int = 0,
		prompt_cache_miss: int = 0,
	) -> None:
		self.prompt_tokens += max(0, prompt)
		self.completion_tokens += max(0, completion)
		self.total_tokens += max(0, total)
		self.prompt_cache_hit_tokens += max(0, prompt_cache_hit)
		self.prompt_cache_miss_tokens += max(0, prompt_cache_miss)
		self.calls += 1

	def to_dict(self) -> dict[str, int]:
		return {
			"prompt_tokens": self.prompt_tokens,
			"completion_tokens": self.completion_tokens,
			"total_tokens": self.total_tokens,
			"prompt_cache_hit_tokens": self.prompt_cache_hit_tokens,
			"prompt_cache_miss_tokens": self.prompt_cache_miss_tokens,
			"calls": self.calls,
		}


def get_token_pricing(data_dir: Path) -> dict[str, Any]:
	from pet_boss.ai.config import AIConfigStore

	config = AIConfigStore(data_dir).load_config()
	return {
		"provider": "deepseek",
		"input_cache_hit_per_m": float(
			config.get("token_price_input_cache_hit_per_m") or DEEPSEEK_INPUT_CACHE_HIT_PER_M
		),
		"input_per_m": float(
			config.get("token_price_input_per_m") or DEEPSEEK_INPUT_CACHE_MISS_PER_M
		),
		"output_per_m": float(
			config.get("token_price_output_per_m") or DEEPSEEK_OUTPUT_PER_M
		),
		"currency": "CNY",
		"symbol": "¥",
	}


def save_token_pricing(
	data_dir: Path,
	*,
	input_per_m: float,
	output_per_m: float,
) -> dict[str, Any]:
	from pet_boss.ai.config import AIConfigStore

	store = AIConfigStore(data_dir)
	store.save_config(
		token_price_input_per_m=max(0.0, float(input_per_m)),
		token_price_output_per_m=max(0.0, float(output_per_m)),
	)
	return get_token_pricing(data_dir)


def format_token_cost(amount: float, *, symbol: str = "¥") -> str:
	if amount <= 0:
		return f"{symbol}0.00"
	if amount >= 1:
		return f"{symbol}{amount:.2f}"
	if amount >= 0.01:
		return f"{symbol}{amount:.4f}"
	return f"{symbol}{amount:.6f}"


def estimate_token_cost(
	totals: dict[str, Any],
	*,
	input_per_m: float,
	output_per_m: float,
	input_cache_hit_per_m: float = DEEPSEEK_INPUT_CACHE_HIT_PER_M,
	symbol: str = "¥",
) -> dict[str, Any]:
	prompt = int(totals.get("prompt_tokens") or 0)
	completion = int(totals.get("completion_tokens") or 0)
	hit = int(totals.get("prompt_cache_hit_tokens") or 0)
	miss = int(totals.get("prompt_cache_miss_tokens") or 0)
	if hit + miss <= 0:
		miss = prompt
	elif hit + miss < prompt:
		miss += prompt - hit - miss

	input_cost = (
		(hit / _MILLION) * max(0.0, input_cache_hit_per_m)
		+ (miss / _MILLION) * max(0.0, input_per_m)
	)
	output_cost = (completion / _MILLION) * max(0.0, output_per_m)
	amount = input_cost + output_cost
	return {
		"amount": round(amount, 8),
		"input_cost": round(input_cost, 8),
		"output_cost": round(output_cost, 8),
		"prompt_cache_hit_tokens": hit,
		"prompt_cache_miss_tokens": miss,
		"currency": "CNY",
		"symbol": symbol,
		"formatted": format_token_cost(amount, symbol=symbol),
	}


def enrich_summary_with_cost(
	summary: dict[str, Any],
	pricing: dict[str, Any],
) -> dict[str, Any]:
	totals = summary.get("session_total") or {}
	cost = estimate_token_cost(
		totals,
		input_per_m=float(pricing.get("input_per_m") or 0),
		output_per_m=float(pricing.get("output_per_m") or 0),
		input_cache_hit_per_m=float(
			pricing.get("input_cache_hit_per_m") or DEEPSEEK_INPUT_CACHE_HIT_PER_M
		),
		symbol=str(pricing.get("symbol") or "¥"),
	)
	return {
		**summary,
		"pricing": pricing,
		"cost": cost,
	}


def get_token_usage_summary(data_dir: Path) -> dict[str, Any]:
	store = get_token_usage_store(data_dir)
	pricing = get_token_pricing(data_dir)
	return enrich_summary_with_cost(store.summary(), pricing)


@dataclass
class TokenUsageStore:
	"""线程安全的会话级 Token 统计（仅累计总量）。"""

	data_dir: Path | None = None
	_session_started_at: float = field(default_factory=time.time)
	_global: TokenUsageTotals = field(default_factory=TokenUsageTotals)
	_lock: threading.Lock = field(default_factory=threading.Lock)
	_version: int = 0

	def record(
		self,
		*,
		agent: str = "other",
		prompt_tokens: int = 0,
		completion_tokens: int = 0,
		total_tokens: int = 0,
		prompt_cache_hit_tokens: int = 0,
		prompt_cache_miss_tokens: int = 0,
		model: str = "",
	) -> None:
		del agent, model
		total = total_tokens or (prompt_tokens + completion_tokens)
		with self._lock:
			self._global.add(
				prompt=prompt_tokens,
				completion=completion_tokens,
				total=total,
				prompt_cache_hit=prompt_cache_hit_tokens,
				prompt_cache_miss=prompt_cache_miss_tokens,
			)
			self._version += 1
		self._persist()

	def summary(self) -> dict[str, Any]:
		with self._lock:
			return {
				"session_started_at": self._session_started_at,
				"updated_at": time.time(),
				"version": self._version,
				"session_total": self._global.to_dict(),
			}

	def reset_session(self) -> None:
		with self._lock:
			self._global = TokenUsageTotals()
			self._session_started_at = time.time()
			self._version += 1
		self._persist()

	def _persist(self) -> None:
		if not self.data_dir:
			return
		path = self.data_dir / "token_usage_session.json"
		try:
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(
				json.dumps(self.summary(), ensure_ascii=False, indent=2) + "\n",
				encoding="utf-8",
			)
		except OSError:
			pass

	@classmethod
	def load_or_create(cls, data_dir: Path) -> TokenUsageStore:
		store = cls(data_dir=data_dir)
		path = data_dir / "token_usage_session.json"
		if not path.is_file():
			return store
		try:
			raw = json.loads(path.read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError):
			return store
		if not isinstance(raw, dict):
			return store
		with store._lock:
			store._session_started_at = float(raw.get("session_started_at") or time.time())
			store._version = int(raw.get("version") or 0)
			total = raw.get("session_total") or {}
			store._global = TokenUsageTotals(
				prompt_tokens=int(total.get("prompt_tokens") or 0),
				completion_tokens=int(total.get("completion_tokens") or 0),
				total_tokens=int(total.get("total_tokens") or 0),
				prompt_cache_hit_tokens=int(total.get("prompt_cache_hit_tokens") or 0),
				prompt_cache_miss_tokens=int(total.get("prompt_cache_miss_tokens") or 0),
				calls=int(total.get("calls") or 0),
			)
		return store


_STORES: dict[str, TokenUsageStore] = {}
_STORES_LOCK = threading.Lock()


def get_token_usage_store(data_dir: Path) -> TokenUsageStore:
	key = str(data_dir.resolve())
	with _STORES_LOCK:
		if key not in _STORES:
			_STORES[key] = TokenUsageStore.load_or_create(data_dir)
		return _STORES[key]
