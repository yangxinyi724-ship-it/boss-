import json
from unittest.mock import patch

from click.testing import CliRunner

from pet_boss.main import cli


def test_schema_command():
	runner = CliRunner()
	result = runner.invoke(cli, ["schema"])
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["command"] == "schema"
	assert "web" in parsed["data"]["commands"]
	assert "login" in parsed["data"]["commands"]
	assert "AUTH_REQUIRED" in parsed["data"]["error_codes"]
	assert "stdout" in parsed["data"]["conventions"]


@patch("pet_boss.commands.login.AuthManager")
def test_login_cdp_connection_error_returns_json_envelope(mock_auth_cls):
	mock_auth_cls.return_value.login.side_effect = ConnectionError("CDP 不可用")
	runner = CliRunner()
	result = runner.invoke(cli, ["login", "--cdp"])
	assert result.exit_code == 1
	assert result.stderr == ""
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["command"] == "login"
	assert parsed["error"]["code"] == "NETWORK_ERROR"
	assert parsed["error"]["recoverable"] is True
	assert parsed["error"]["recovery_action"] == "boss login"


@patch("pet_boss.commands.status.AuthManager")
def test_status_not_logged_in(mock_auth_cls):
	mock_auth_cls.return_value.check_status.return_value = None
	runner = CliRunner()
	result = runner.invoke(cli, ["status"])
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "AUTH_REQUIRED"
	assert parsed["hints"]["auth_health"]["primary_name"] == "wt2"
	assert parsed["hints"]["auth_health"]["secondary_name"] == "stoken"


@patch("pet_boss.commands.status.AuthManager")
def test_status_logged_in_happy_path(mock_auth_cls):
	mock_auth_cls.return_value.check_status.return_value = {"cookies": {"wt2": "x"}, "stoken": "s"}
	runner = CliRunner()
	result = runner.invoke(cli, ["--json", "status"])
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["data"]["logged_in"] is True
	assert parsed["data"]["live"] is False
	assert parsed["data"]["auth_state"] == "complete"
	assert parsed["data"]["user_name"] is None
	assert "checks" in parsed["data"]


def test_cities_command():
	runner = CliRunner()
	result = runner.invoke(cli, ["cities"])
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["command"] == "cities"
	assert isinstance(parsed["data"]["cities"], list)
	assert "北京" in parsed["data"]["cities"]
