"""Schema 合约测试 + 错误码一致性测试。"""

import json

from click.testing import CliRunner

from pet_boss.main import cli
from pet_boss.commands.schema import SCHEMA_DATA


def test_schema_output_is_json_envelope():
	runner = CliRunner()
	result = runner.invoke(cli, ["schema"])
	assert result.exit_code == 0

	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["schema_version"] == "1.0"
	assert parsed["command"] == "schema"
	assert parsed["error"] is None

	data = parsed["data"]
	assert "commands" in data
	assert "error_codes" in data
	assert "conventions" in data
	assert "global_options" in data
	assert isinstance(data["commands"], dict)
	assert isinstance(data["error_codes"], dict)


def test_schema_commands_match_registered():
	registered = set(cli.commands.keys())
	schema_commands = set(SCHEMA_DATA["commands"].keys())

	missing_in_schema = registered - schema_commands
	extra_in_schema = schema_commands - registered

	assert not missing_in_schema, f"以下命令已注册但未在 schema 中声明: {missing_in_schema}"
	assert not extra_in_schema, f"以下命令在 schema 中声明但未注册: {extra_in_schema}"


def test_schema_commands_have_descriptions():
	commands = SCHEMA_DATA["commands"]
	missing = []
	for name, spec in commands.items():
		desc = spec.get("description", "")
		if not desc or not desc.strip():
			missing.append(name)

	assert not missing, f"以下命令缺少 description: {missing}"


def test_doctor_schema_documents_cdp_risk_boundary():
	description = SCHEMA_DATA["commands"]["doctor"]["description"]
	assert "CDP" in description
	assert "不得用于规避平台风控" in description


def test_schema_error_codes_cover_all_used_codes():
	schema_codes = set(SCHEMA_DATA["error_codes"].keys())
	used_codes = {
		"AUTH_EXPIRED",
		"AUTH_REQUIRED",
		"RATE_LIMITED",
		"TOKEN_REFRESH_FAILED",
		"ACCOUNT_RISK",
		"NETWORK_ERROR",
		"INVALID_PARAM",
		"NOT_SUPPORTED",
		"COMPLIANCE_BLOCKED",
		"HOOK_BLOCKED",
		"DEPENDENCY_MISSING",
	}
	allowed_internal = {"HOOK_BLOCKED"}
	must_be_in_schema = used_codes - allowed_internal
	missing = must_be_in_schema - schema_codes
	assert not missing, f"以下错误码在代码中使用但未在 schema 中声明: {missing}"


def test_schema_error_codes_all_have_message():
	error_codes = SCHEMA_DATA["error_codes"]
	missing = []
	for code, spec in error_codes.items():
		msg = spec.get("message", "")
		if not msg or not msg.strip():
			missing.append(code)

	assert not missing, f"以下错误码缺少 message: {missing}"


def test_schema_error_codes_have_recoverable_field():
	error_codes = SCHEMA_DATA["error_codes"]
	missing = [code for code, spec in error_codes.items() if "recoverable" not in spec]
	assert not missing, f"以下错误码缺少 recoverable 字段: {missing}"


def test_schema_error_codes_have_recovery_action_field():
	error_codes = SCHEMA_DATA["error_codes"]
	missing = [code for code, spec in error_codes.items() if "recovery_action" not in spec]
	assert not missing, f"以下错误码缺少 recovery_action 字段: {missing}"


def test_web_schema_documents_pet_entry():
	web = SCHEMA_DATA["commands"]["web"]
	assert "/pet" in web["description"]
