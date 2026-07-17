from typing import Any

import click

from pet_boss.compliance import compliance_mode_data
from pet_boss.output import emit_success
from pet_boss.platforms import list_platforms

_JSON_SCHEMA_TYPE_MAP = {
	"string": "string",
	"int": "integer",
	"integer": "integer",
	"bool": "boolean",
	"boolean": "boolean",
	"float": "number",
	"number": "number",
}


def _option_to_json_schema_property(opt_spec: dict[str, Any]) -> dict[str, Any]:
	native_type = opt_spec.get("type", "string")
	prop: dict[str, Any] = {"type": _JSON_SCHEMA_TYPE_MAP.get(native_type, "string")}
	desc = opt_spec.get("description")
	if desc:
		prop["description"] = desc
	default = opt_spec.get("default")
	if default is not None:
		prop["default"] = default
	return prop


def _command_to_json_schema(cmd_name: str, cmd_spec: dict[str, Any]) -> dict[str, Any]:
	properties: dict[str, Any] = {}
	required: list[str] = []

	for arg in cmd_spec.get("args", []):
		arg_name = arg["name"]
		properties[arg_name] = {
			"type": "string",
			"description": arg.get("description", ""),
		}
		if arg.get("required"):
			required.append(arg_name)

	for opt_key, opt_spec in cmd_spec.get("options", {}).items():
		primary_name = opt_key.split(",")[-1].strip().lstrip("-").replace("-", "_")
		properties[primary_name] = _option_to_json_schema_property(opt_spec)

	schema: dict[str, Any] = {
		"type": "object",
		"properties": properties,
	}
	if required:
		schema["required"] = required
	return schema


def _availability_note(availability: dict[str, Any]) -> str:
	roles = ", ".join(availability.get("roles", [])) or "none"
	candidate_platforms = ", ".join(availability.get("candidate_platforms", [])) or "-"
	return f"可用性: roles={roles}; candidate_platforms={candidate_platforms}"


def _command_availability(*, candidate_platforms: list[str]) -> dict[str, Any]:
	return {
		"roles": ["candidate"],
		"candidate_platforms": candidate_platforms,
	}


def _inject_availability(data: dict[str, Any]) -> dict[str, Any]:
	candidate_platforms = data.get("supported_platforms", [])
	commands: dict[str, Any] = {}
	for cmd_name, cmd_spec in data["commands"].items():
		cmd_copy = dict(cmd_spec)
		cmd_copy["availability"] = _command_availability(candidate_platforms=candidate_platforms)
		commands[cmd_name] = cmd_copy
	data["commands"] = commands
	return data


def _format_openai_tools(data: dict[str, Any]) -> list[dict[str, Any]]:
	tools = []
	for cmd_name, cmd_spec in data["commands"].items():
		description = cmd_spec.get("description", "")
		if availability := cmd_spec.get("availability"):
			description = f"{description} [{_availability_note(availability)}]"
		tools.append({
			"type": "function",
			"function": {
				"name": f"boss_{cmd_name.replace('-', '_')}",
				"description": description,
				"parameters": _command_to_json_schema(cmd_name, cmd_spec),
			},
		})
	return tools


def _format_anthropic_tools(data: dict[str, Any]) -> list[dict[str, Any]]:
	tools = []
	for cmd_name, cmd_spec in data["commands"].items():
		description = cmd_spec.get("description", "")
		if availability := cmd_spec.get("availability"):
			description = f"{description} [{_availability_note(availability)}]"
		tools.append({
			"name": f"boss_{cmd_name.replace('-', '_')}",
			"description": description,
			"input_schema": _command_to_json_schema(cmd_name, cmd_spec),
		})
	return tools


SCHEMA_DATA = {
	"name": "boss-agent-cli",
	"description": "BOSS 直聘宠物页 Web 产品 — 最小 CLI（登录、诊断、启动 Web）",
	"commands": {
		"login": {
			"description": "按当前平台登录（zhipin）。用于用户主动触发的本地辅助与只读验证。",
			"args": [],
			"options": {
				"--timeout": {
					"type": "int",
					"default": 120,
					"description": "登录超时时间（秒）",
				},
				"--cdp": {
					"type": "bool",
					"default": False,
					"description": "强制 CDP 模式（跳过 Cookie 提取，CDP 不可用直接报错）",
				},
			},
		},
		"status": {
			"description": "轻量检查当前登录态分层健康状态；默认不请求平台，--live 才执行一次只读在线验证",
			"args": [],
			"options": {
				"--live": {
					"type": "bool",
					"default": False,
					"description": "执行一次只读 user_info 在线验证；默认仅检查本地凭据完整性",
				},
			},
		},
		"doctor": {
			"description": "诊断本地运行环境、依赖、分层认证健康、CDP 可达性和网络连通性；默认不做真实业务探测，CDP 仅用于用户主动的本地诊断与登录兼容，不得用于规避平台风控",
			"args": [],
			"options": {
				"--live-probe": {
					"type": "bool",
					"default": False,
					"description": "显式执行低频只读平台探测，用于区分本地凭据完整但接口不可用的状态",
				},
			},
		},
		"schema": {
			"description": "返回工具完整能力描述的 JSON",
			"args": [],
			"options": {
				"--format": {
					"type": "string",
					"default": "native",
					"description": "输出格式",
					"choices": ["native", "openai-tools", "anthropic-tools"],
				},
			},
		},
		"logout": {
			"description": "退出登录，清除本地保存的登录态",
			"args": [],
			"options": {},
		},
		"cities": {
			"description": "列出所有支持的城市",
			"args": [],
			"options": {},
		},
		"profile": {
			"description": "用户画像 Web 入口",
			"args": [],
			"options": {},
			"subcommands": {
				"web": "启动宠物页 Web 界面（默认 http://127.0.0.1:8787/pet）",
			},
		},
		"web": {
			"description": "启动宠物页 Web 界面（/pet）",
			"args": [],
			"options": {
				"--host": {"type": "string", "default": "127.0.0.1", "description": "监听地址"},
				"--port": {"type": "int", "default": 8787, "description": "监听端口"},
			},
		},
	},
	"global_options": {
		"--data-dir": {
			"type": "string",
			"default": "~/.boss-agent",
			"description": "数据存储目录",
		},
		"--delay": {
			"type": "string",
			"default": "1.5-3.0",
			"description": "请求间隔范围（秒），如 1.5-3.0",
		},
		"--log-level": {
			"type": "string",
			"default": "error",
			"choices": ["error", "warning", "info", "debug"],
			"description": "日志级别",
		},
		"--cdp-url": {
			"type": "string",
			"default": None,
			"description": "Chrome CDP 调试地址。不得用于规避平台风控或重试被平台拦截的操作。",
		},
		"--platform": {
			"type": "string",
			"default": "zhipin",
			"description": "招聘平台适配器",
			"choices": ["zhipin"],
		},
		"--json": {
			"type": "bool",
			"default": False,
			"description": "强制 JSON 输出（即使在终端中，默认管道模式自动 JSON）",
		},
	},
	"error_codes": {
		"AUTH_EXPIRED": {
			"message": "登录态过期",
			"recoverable": True,
			"recovery_action": "boss login",
		},
		"AUTH_REQUIRED": {
			"message": "未登录",
			"recoverable": True,
			"recovery_action": "boss login",
		},
		"RATE_LIMITED": {
			"message": "请求频率过高",
			"recoverable": True,
			"recovery_action": "等待后重试",
		},
		"TOKEN_REFRESH_FAILED": {
			"message": "Token 刷新失败",
			"recoverable": True,
			"recovery_action": "boss login",
		},
		"ACCOUNT_RISK": {
			"message": "风控拦截",
			"recoverable": False,
			"recovery_action": "停止自动化访问，回到平台官网手动处理，必要时联系客服",
		},
		"NETWORK_ERROR": {
			"message": "网络请求失败",
			"recoverable": True,
			"recovery_action": "重试",
		},
		"INVALID_PARAM": {
			"message": "参数校验失败",
			"recoverable": False,
			"recovery_action": "修正参数",
		},
		"NOT_SUPPORTED": {
			"message": "当前平台暂不支持该能力",
			"recoverable": True,
			"recovery_action": "切换平台或调整命令参数后重试",
		},
		"PLATFORM_NOT_SUPPORTED": {
			"message": "当前平台不支持该能力",
			"recoverable": True,
			"recovery_action": "切换到支持的平台后重试",
		},
		"COMPLIANCE_BLOCKED": {
			"message": "默认低风险模式已阻断该敏感操作",
			"recoverable": False,
			"recovery_action": "保持默认低风险模式；如需处理，请回到平台官网手动完成",
		},
		"DEPENDENCY_MISSING": {
			"message": "缺少可选依赖",
			"recoverable": True,
			"recovery_action": "pip install 'boss-agent-cli[web]'",
		},
	},
	"conventions": {
		"stdout": "仅 JSON 结构化数据（信封格式）",
		"stderr": "日志和进度信息（通过 --log-level 控制）",
		"exit_code": {
			"0": "命令成功 (ok=true)",
			"1": "命令失败 (ok=false)",
		},
	},
}


@click.command("schema")
@click.option(
	"--format",
	"output_format",
	type=click.Choice(["native", "openai-tools", "anthropic-tools"]),
	default="native",
	help="输出格式：native / openai-tools / anthropic-tools",
)
@click.pass_context
def schema_cmd(ctx: click.Context, output_format: str) -> None:
	"""返回工具完整能力描述的 JSON"""
	data = dict(SCHEMA_DATA)
	current = (ctx.obj or {}).get("platform") or "zhipin"
	data["current_platform"] = current
	data["supported_platforms"] = list_platforms()
	data["compliance"] = compliance_mode_data(ctx)
	data = _inject_availability(data)

	if output_format == "openai-tools":
		emit_success("schema", {"format": "openai-tools", "tools": _format_openai_tools(data)})
		return
	if output_format == "anthropic-tools":
		emit_success("schema", {"format": "anthropic-tools", "tools": _format_anthropic_tools(data)})
		return
	emit_success("schema", data)
