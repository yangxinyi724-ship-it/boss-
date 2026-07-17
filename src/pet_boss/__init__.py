"""boss-agent-cli — BOSS 直聘求职 CLI 工具，专为 AI Agent 设计。

Public API 使用示例:

	from pet_boss import AuthManager, BossClient, CacheStore
	from pet_boss import AuthRequired, TokenRefreshFailed

	auth = AuthManager(data_dir)
	with BossClient(auth) as client:
		result = client.search_jobs("Golang", city="广州")
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from pet_boss.ai.service import AIService, AIServiceError
	from pet_boss.api.client import AccountRiskError, AuthError, BossClient
	from pet_boss.api.models import JobDetail, JobItem
	from pet_boss.auth.manager import AuthManager, AuthRequired, TokenRefreshFailed
	from pet_boss.cache.store import CacheStore
	from pet_boss.platforms import BossPlatform, Platform, get_platform, list_platforms
	from pet_boss.resume.models import ResumeData, ResumeFile

__version__ = "1.11.0"

_LAZY_EXPORT_MODULES = {
	"AuthManager": "pet_boss.auth.manager",
	"AuthRequired": "pet_boss.auth.manager",
	"TokenRefreshFailed": "pet_boss.auth.manager",
	"BossClient": "pet_boss.api.client",
	"AuthError": "pet_boss.api.client",
	"AccountRiskError": "pet_boss.api.client",
	"JobItem": "pet_boss.api.models",
	"JobDetail": "pet_boss.api.models",
	"CacheStore": "pet_boss.cache.store",
	"AIService": "pet_boss.ai.service",
	"AIServiceError": "pet_boss.ai.service",
	"ResumeData": "pet_boss.resume.models",
	"ResumeFile": "pet_boss.resume.models",
	"Platform": "pet_boss.platforms",
	"BossPlatform": "pet_boss.platforms",
	"get_platform": "pet_boss.platforms",
	"list_platforms": "pet_boss.platforms",
}

__all__ = [
	"__version__",
	"AuthManager",
	"AuthRequired",
	"TokenRefreshFailed",
	"BossClient",
	"AuthError",
	"AccountRiskError",
	"JobItem",
	"JobDetail",
	"CacheStore",
	"AIService",
	"AIServiceError",
	"ResumeData",
	"ResumeFile",
	"Platform",
	"BossPlatform",
	"get_platform",
	"list_platforms",
]


def __getattr__(name: str) -> object:
	"""Resolve package-level public API exports on first access."""
	try:
		module_name = _LAZY_EXPORT_MODULES[name]
	except KeyError:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

	value = getattr(import_module(module_name), name)
	globals()[name] = value
	return value
