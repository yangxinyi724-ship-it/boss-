"""Tests for boss schema --format 扩展（openai-tools / anthropic-tools）。"""

import json

from click.testing import CliRunner

from pet_boss.commands.schema import (
	_command_to_json_schema,
	_format_anthropic_tools,
	_format_openai_tools,
	SCHEMA_DATA,
)
from pet_boss.main import cli


def test_native_format_is_default():
	runner = CliRunner()
	result = runner.invoke(cli, ["schema"])
	assert result.exit_code == 0
	data = json.loads(result.output)["data"]
	assert "commands" in data
	assert "error_codes" in data
	assert "format" not in data


def test_openai_tools_format():
	runner = CliRunner()
	result = runner.invoke(cli, ["schema", "--format", "openai-tools"])
	assert result.exit_code == 0
	data = json.loads(result.output)["data"]
	assert data["format"] == "openai-tools"
	tools = data["tools"]
	assert len(tools) == len(SCHEMA_DATA["commands"])
	for tool in tools:
		assert tool["type"] == "function"
		assert "function" in tool
		fn = tool["function"]
		assert fn["name"].startswith("boss_")
		assert fn["description"]
		assert fn["parameters"]["type"] == "object"
		assert "properties" in fn["parameters"]


def test_anthropic_tools_format():
	runner = CliRunner()
	result = runner.invoke(cli, ["schema", "--format", "anthropic-tools"])
	assert result.exit_code == 0
	data = json.loads(result.output)["data"]
	assert data["format"] == "anthropic-tools"
	tools = data["tools"]
	assert len(tools) == len(SCHEMA_DATA["commands"])
	for tool in tools:
		assert tool["name"].startswith("boss_")
		assert tool["description"]
		assert tool["input_schema"]["type"] == "object"


def test_openai_and_anthropic_share_parameters_schema():
	oai = _format_openai_tools(SCHEMA_DATA)
	anth = _format_anthropic_tools(SCHEMA_DATA)

	oai_web = next(t["function"]["parameters"] for t in oai if t["function"]["name"] == "boss_web")
	anth_web = next(t["input_schema"] for t in anth if t["name"] == "boss_web")
	assert oai_web == anth_web


def test_command_to_json_schema_required_args():
	cmd_spec = {
		"args": [
			{"name": "query", "required": True, "description": "关键词"},
			{"name": "opt", "required": False, "description": "可选"},
		],
		"options": {},
	}
	schema = _command_to_json_schema("test", cmd_spec)
	assert "query" in schema["properties"]
	assert "opt" in schema["properties"]
	assert schema["required"] == ["query"]


def test_command_to_json_schema_type_mapping():
	cmd_spec = {
		"args": [],
		"options": {
			"--days": {"type": "int", "default": 30, "description": "天数"},
			"--dry-run": {"type": "bool", "default": False, "description": "预览"},
			"--name": {"type": "string", "default": None, "description": "名称"},
		},
	}
	schema = _command_to_json_schema("test", cmd_spec)
	assert schema["properties"]["days"]["type"] == "integer"
	assert schema["properties"]["days"]["default"] == 30
	assert schema["properties"]["dry_run"]["type"] == "boolean"
	assert schema["properties"]["name"]["type"] == "string"


def test_invalid_format_raises():
	runner = CliRunner()
	result = runner.invoke(cli, ["schema", "--format", "xml"])
	assert result.exit_code == 1
	payload = json.loads(result.output)
	assert payload["ok"] is False
	assert payload["command"] == "schema"
	assert payload["error"]["code"] == "INVALID_PARAM"
	assert payload["error"]["recoverable"] is False
	assert payload["error"]["recovery_action"] == "修正参数"
	assert result.stderr == ""
