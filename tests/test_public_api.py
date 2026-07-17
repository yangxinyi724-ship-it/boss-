"""Public API 契约测试 — 守护 `pet_boss` 包级导出面不被意外破坏。

这份测试保证下游项目可以通过 `from pet_boss import X` 访问核心类型和异常，
任何改名 / 删除都会在这里被立即捕获。
"""
import importlib
import json
import subprocess
import sys

import pytest


# ── __all__ 契约 ─────────────────────────────────────────


EXPECTED_EXPORTS = {
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
}


@pytest.fixture
def pet_boss():
	return importlib.import_module("pet_boss")


def test_package_import_does_not_eagerly_import_browser_runtime():
	probe = (
		"import json, sys; "
		"sys.modules.pop('patchright.sync_api', None); "
		"import pet_boss; "
		"print(json.dumps({"
		"'version': pet_boss.__version__, "
		"'patchright_loaded': 'patchright.sync_api' in sys.modules"
		"}))"
	)
	result = subprocess.run(
		[sys.executable, "-c", probe],
		check=True,
		capture_output=True,
		text=True,
	)
	payload = json.loads(result.stdout)
	assert payload["version"]
	assert payload["patchright_loaded"] is False


def test_all_is_defined(pet_boss):
	assert hasattr(pet_boss, "__all__")
	assert isinstance(pet_boss.__all__, list)


def test_all_matches_expected_exports(pet_boss):
	assert set(pet_boss.__all__) == EXPECTED_EXPORTS


def test_every_export_is_actually_importable(pet_boss):
	"""__all__ 里声明的每个名字都能真的从包里 import 到。"""
	for name in pet_boss.__all__:
		assert hasattr(pet_boss, name), f"{name} declared in __all__ but not exported"


def test_lazy_export_is_cached_after_first_access(pet_boss):
	assert pet_boss.AuthManager is pet_boss.AuthManager


def test_unknown_package_attribute_raises_attribute_error(pet_boss):
	with pytest.raises(AttributeError, match="no attribute 'MissingExport'"):
		getattr(pet_boss, "MissingExport")


# ── 关键类型的身份一致性 ──────────────────────────────────


def test_auth_manager_identity(pet_boss):
	from pet_boss.auth.manager import AuthManager as OriginalAuthManager
	assert pet_boss.AuthManager is OriginalAuthManager


def test_boss_client_identity(pet_boss):
	from pet_boss.api.client import BossClient as OriginalBossClient
	assert pet_boss.BossClient is OriginalBossClient


def test_cache_store_identity(pet_boss):
	from pet_boss.cache.store import CacheStore as OriginalCacheStore
	assert pet_boss.CacheStore is OriginalCacheStore


def test_job_item_identity(pet_boss):
	from pet_boss.api.models import JobItem as OriginalJobItem
	assert pet_boss.JobItem is OriginalJobItem


def test_ai_service_identity(pet_boss):
	from pet_boss.ai.service import AIService as OriginalAIService
	assert pet_boss.AIService is OriginalAIService


# ── 异常继承关系 ──────────────────────────────────────────


def test_auth_required_is_exception(pet_boss):
	assert issubclass(pet_boss.AuthRequired, Exception)


def test_token_refresh_failed_is_exception(pet_boss):
	assert issubclass(pet_boss.TokenRefreshFailed, Exception)


def test_auth_error_is_exception(pet_boss):
	assert issubclass(pet_boss.AuthError, Exception)


def test_account_risk_error_is_exception(pet_boss):
	assert issubclass(pet_boss.AccountRiskError, Exception)


def test_ai_service_error_is_exception(pet_boss):
	assert issubclass(pet_boss.AIServiceError, Exception)


# ── 平台抽象 ──────────────────────────────────────────────


def test_platform_is_abstract(pet_boss):
	assert inspect_abstract(pet_boss.Platform)


def inspect_abstract(cls: type) -> bool:
	return bool(getattr(cls, "__abstractmethods__", set()))


def test_boss_platform_subclasses_platform(pet_boss):
	assert issubclass(pet_boss.BossPlatform, pet_boss.Platform)


def test_get_platform_returns_boss_by_default(pet_boss):
	assert pet_boss.get_platform("zhipin") is pet_boss.BossPlatform


def test_list_platforms_contains_zhipin(pet_boss):
	assert "zhipin" in pet_boss.list_platforms()


# ── 版本格式 ──────────────────────────────────────────────


def test_version_is_semver_string(pet_boss):
	version = pet_boss.__version__
	assert isinstance(version, str)
	parts = version.split(".")
	assert len(parts) == 3, f"版本应为 X.Y.Z 格式，实际为 {version}"
	for part in parts:
		assert part.isdigit(), f"版本各段应为数字，实际为 {part}"


# ── py.typed marker ──────────────────────────────────────


def test_py_typed_marker_exists():
	"""PEP 561 标记文件必须存在，下游才能启用类型检查。"""
	pkg_spec = importlib.util.find_spec("pet_boss")
	assert pkg_spec is not None
	assert pkg_spec.origin is not None
	import pathlib
	pkg_dir = pathlib.Path(pkg_spec.origin).parent
	assert (pkg_dir / "py.typed").exists(), "py.typed 标记文件丢失"


# ── 包级 docstring ────────────────────────────────────────


def test_package_has_docstring(pet_boss):
	"""提供给 help(pet_boss) 的入口说明。"""
	assert pet_boss.__doc__ is not None
	assert len(pet_boss.__doc__.strip()) > 0
