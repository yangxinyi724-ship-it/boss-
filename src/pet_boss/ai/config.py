"""AI service configuration management.

Handles API key encryption (Fernet), provider settings, and model configuration.
Reuses the auth salt file for key derivation.
"""

import hashlib
import json
import os
import platform
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PROVIDER_BASE_URLS: dict[str, str | None] = {
	"openai": "https://api.openai.com/v1",
	"deepseek": "https://api.deepseek.com/v1",
	"moonshot": "https://api.moonshot.cn/v1",
	"openrouter": "https://openrouter.ai/api/v1",
	"qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
	"zhipu": "https://open.bigmodel.cn/api/paas/v4",
	"siliconflow": "https://api.siliconflow.cn/v1",
	"custom": None,
}

_DEFAULT_CONFIG: dict[str, Any] = {
	"ai_provider": None,
	"ai_model": None,
	"ai_base_url": None,
	"ai_embedding_provider": None,
	"ai_embedding_model": None,
	"ai_embedding_base_url": None,
	"ai_embedding_api_key": None,
	"ai_rag_enabled": True,
	"ai_temperature": 0.7,
	"ai_max_tokens": 4096,
	"token_price_input_cache_hit_per_m": 0.02,
	"token_price_input_per_m": 1.0,
	"token_price_output_per_m": 2.0,
}

# DeepSeek / Moonshot 等对话接口通常不提供 /embeddings
_PROVIDERS_WITH_NATIVE_EMBEDDING = frozenset({
	"openai", "qwen", "zhipu", "siliconflow", "openrouter",
})

_EMBEDDING_MODEL_BY_PROVIDER: dict[str, str] = {
	"openai": "text-embedding-3-small",
	"qwen": "text-embedding-v3",
	"zhipu": "embedding-2",
	"siliconflow": "BAAI/bge-large-zh-v1.5",
	"openrouter": "text-embedding-3-small",
	"moonshot": "text-embedding-3-small",
}


def resolve_embedding_provider(config: dict[str, Any]) -> str | None:
	"""独立 Embedding 平台；未设时回退到对话 provider。"""
	explicit = config.get("ai_embedding_provider")
	if explicit:
		return str(explicit)
	chat = config.get("ai_provider")
	return str(chat) if chat else None


def resolve_embedding_model(config: dict[str, Any]) -> str:
	explicit = config.get("ai_embedding_model")
	if explicit:
		return str(explicit)
	provider = resolve_embedding_provider(config) or ""
	return _EMBEDDING_MODEL_BY_PROVIDER.get(provider, "text-embedding-3-small")


def resolve_embedding_base_url(config: dict[str, Any]) -> str | None:
	"""独立 Embedding 网关（可与对话 provider 不同，例如 DeepSeek 聊天 + 硅基流动 Embedding）。"""
	explicit = config.get("ai_embedding_base_url")
	if explicit:
		return str(explicit).rstrip("/")
	provider = config.get("ai_embedding_provider")
	if provider and provider in PROVIDER_BASE_URLS:
		url = PROVIDER_BASE_URLS[provider]
		return str(url).rstrip("/") if url else None
	return None


def resolve_embedding_api_key(config: dict[str, Any]) -> str | None:
	"""仅读 config 明文；加密的 Embedding Key 请用 AIConfigStore.get_embedding_api_key()。"""
	explicit = config.get("ai_embedding_api_key")
	if explicit:
		return str(explicit)
	return None


def has_embedding_endpoint(config: dict[str, Any] | None = None) -> bool:
	"""是否具备可用的 Embedding 端点（原生平台或独立网关/provider）。"""
	if config is None:
		return True
	if resolve_embedding_base_url(config):
		return True
	provider = str(config.get("ai_provider") or "")
	return bool(provider and provider in _PROVIDERS_WITH_NATIVE_EMBEDDING)


def rag_enabled(config: dict[str, Any] | None = None) -> bool:
	if config is None:
		return True
	value = config.get("ai_rag_enabled")
	if value is False:
		return False
	if value is None:
		value = True
	if not value:
		return False
	return has_embedding_endpoint(config)


class AIConfigStore:
	"""Manages AI service configuration with encrypted API key storage."""

	def __init__(self, data_dir: Path):
		self._data_dir = data_dir
		self._ai_dir = data_dir / "ai"
		self._ai_dir.mkdir(parents=True, exist_ok=True)
		self._key_path = self._ai_dir / "api_key.enc"
		self._embedding_key_path = self._ai_dir / "embedding_api_key.enc"
		self._config_path = self._ai_dir / "config.json"
		self._auth_dir = data_dir / "auth"

	def _get_machine_id(self) -> str:
		"""Get a stable machine identifier for key derivation."""
		if override := os.getenv("BOSS_AGENT_MACHINE_ID"):
			return override
		fingerprint = "|".join([
			platform.node() or "unknown-node",
			platform.system() or "unknown-system",
			platform.machine() or "unknown-machine",
		])
		return hashlib.sha256(fingerprint.encode()).hexdigest()

	def _get_salt(self) -> bytes:
		"""Reuse auth salt file, or create one if it doesn't exist."""
		self._auth_dir.mkdir(parents=True, exist_ok=True)
		salt_path = self._auth_dir / "salt"
		if salt_path.exists():
			return salt_path.read_bytes()
		salt = os.urandom(16)
		salt_path.write_bytes(salt)
		return salt

	def _derive_key(self) -> bytes:
		"""Derive a Fernet key from machine ID and salt."""
		salt = self._get_salt()
		machine_id = self._get_machine_id()
		kdf = PBKDF2HMAC(
			algorithm=hashes.SHA256(),
			length=32,
			salt=salt,
			iterations=480000,
		)
		key = kdf.derive(machine_id.encode())
		return urlsafe_b64encode(key)

	def save_api_key(self, key: str) -> None:
		"""Encrypt and persist the API key."""
		fernet = Fernet(self._derive_key())
		encrypted = fernet.encrypt(key.encode("utf-8"))
		self._key_path.write_bytes(encrypted)

	def get_api_key(self) -> str | None:
		"""Load and decrypt the API key. Returns None if not set or decryption fails."""
		if not self._key_path.exists():
			return None
		fernet = Fernet(self._derive_key())
		try:
			plaintext = fernet.decrypt(self._key_path.read_bytes())
		except (InvalidToken, ValueError):
			return None
		return plaintext.decode("utf-8")

	def save_embedding_api_key(self, key: str) -> None:
		"""Encrypt and persist the Embedding API key (可与对话 Key 不同)。"""
		fernet = Fernet(self._derive_key())
		encrypted = fernet.encrypt(key.encode("utf-8"))
		self._embedding_key_path.write_bytes(encrypted)

	def get_embedding_api_key(self) -> str | None:
		"""独立 Embedding Key：优先加密文件，其次 config 明文，最后回退对话 Key。"""
		if self._embedding_key_path.exists():
			fernet = Fernet(self._derive_key())
			try:
				plaintext = fernet.decrypt(self._embedding_key_path.read_bytes())
				return plaintext.decode("utf-8")
			except (InvalidToken, ValueError):
				pass
		config = self.load_config()
		explicit = resolve_embedding_api_key(config)
		if explicit:
			return explicit
		# 仅当 Embedding 与对话走同一平台时，复用对话 Key
		emb_provider = config.get("ai_embedding_provider")
		chat_provider = config.get("ai_provider")
		if emb_provider and emb_provider != chat_provider:
			return None
		return self.get_api_key()

	def save_config(self, **kwargs: Any) -> None:
		"""Save configuration, merging with existing values."""
		current = self.load_config()
		current.update(kwargs)
		self._config_path.write_text(
			json.dumps(current, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)

	def load_config(self) -> dict[str, Any]:
		"""Load configuration with defaults for missing keys."""
		config = dict(_DEFAULT_CONFIG)
		if self._config_path.exists():
			try:
				saved = json.loads(self._config_path.read_text(encoding="utf-8"))
				config.update(saved)
			except (json.JSONDecodeError, OSError):
				pass
		return config

	def get_base_url(self) -> str | None:
		"""Get the API base URL: user config takes priority, then provider lookup."""
		config = self.load_config()
		base_url = config.get("ai_base_url")
		if base_url:
			return str(base_url)
		provider = config.get("ai_provider")
		if provider and provider in PROVIDER_BASE_URLS:
			return PROVIDER_BASE_URLS[provider]
		return None

	def is_configured(self) -> bool:
		"""Check if all required settings are present (provider + model + api_key)."""
		config = self.load_config()
		provider = config.get("ai_provider")
		model = config.get("ai_model")
		api_key = self.get_api_key()
		return all([provider, model, api_key])
