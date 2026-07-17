import json

from click.testing import CliRunner

from pet_boss.main import cli


def _invoke(*args: str):
	runner = CliRunner()
	result = runner.invoke(cli, ["--json", *args])
	return result.exit_code, json.loads(result.output)


def test_schema_exposes_current_compliance_mode():
	code, parsed = _invoke("schema")
	assert code == 0
	compliance = parsed["data"]["compliance"]
	assert compliance["default_boundary"] == "low_risk_assistance"
	assert compliance["sensitive_commands_blocked"] is True
	assert "low_risk_mode" not in compliance
	assert "greet" in compliance["blocked_commands"]
	assert "pipeline" in compliance["blocked_commands"]


def test_internal_policy_fixture_keeps_historical_contract_tests_reachable(restricted_surface_args):
	runner = CliRunner()
	result = runner.invoke(cli, ["--json", *restricted_surface_args, "schema"])
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["data"]["compliance"]["sensitive_commands_blocked"] is False
