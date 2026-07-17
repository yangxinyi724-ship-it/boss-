"""验证 hr 子命令在不支持平台下抛 PLATFORM_NOT_SUPPORTED 错误码。"""
import json
from pathlib import Path

from click.testing import CliRunner

from pet_boss.main import cli


def test_schema_includes_platform_not_supported_error_code(tmp_path: Path) -> None:
	"""boss schema 输出的错误码枚举应包含 PLATFORM_NOT_SUPPORTED。"""
	runner = CliRunner()
	result = runner.invoke(cli, ["--data-dir", str(tmp_path), "schema"])
	assert result.exit_code == 0
	envelope = json.loads(result.output)
	error_codes = envelope["data"].get("error_codes", {})
	assert "PLATFORM_NOT_SUPPORTED" in error_codes
	entry = error_codes["PLATFORM_NOT_SUPPORTED"]
	assert entry["recoverable"] is True
	assert entry["recovery_action"]
