"""用户画像 Web 入口 — 宠物页主界面。"""

from __future__ import annotations

import click

from pet_boss.display import handle_error_output


@click.group("profile")
def profile_group() -> None:
	"""用户画像与 BOSS 搜岗 Web 界面。"""


def _run_web_server(ctx: click.Context, host: str, port: int) -> None:
	try:
		from pet_boss.web.server import run_server
	except ImportError:
		handle_error_output(
			ctx, "profile-web",
			code="DEPENDENCY_MISSING",
			message="Web 界面需要安装可选依赖",
			recoverable=True,
			recovery_action="pip install 'boss-agent-cli[web]'",
		)
		raise SystemExit(1)
	import webbrowser

	url = f"http://{host}:{port}/pet"
	click.echo(f"AI 办公室: {url}", err=True)
	click.echo("按 Ctrl+C 停止服务", err=True)
	try:
		webbrowser.open(url)
	except Exception:
		pass
	run_server(data_dir=ctx.obj["data_dir"], host=host, port=port)


@click.command("web")
@click.option("--host", default="127.0.0.1", show_default=True, help="监听地址")
@click.option("--port", default=8787, type=int, show_default=True, help="监听端口")
@click.pass_context
def web_cmd(ctx: click.Context, host: str, port: int) -> None:
	"""启动宠物页 Web 界面（/pet）。"""
	_run_web_server(ctx, host, port)


profile_group.add_command(web_cmd)
