import click

from pet_boss.display import login_action_for_ctx
from pet_boss.auth.manager import AuthManager
from pet_boss.output import emit_error, emit_success


@click.command("logout")
@click.pass_context
def logout_cmd(ctx: click.Context) -> None:
	"""退出登录，清除本地保存的登录态"""
	data_dir = ctx.obj["data_dir"]
	logger = ctx.obj["logger"]
	auth = AuthManager(data_dir, logger=logger, platform=ctx.obj.get("platform", "zhipin"))
	try:
		auth.logout()
		emit_success("logout", {"message": "已退出登录"}, hints={
			"next_actions": [
				f"{login_action_for_ctx(ctx)} — 重新登录",
			],
		})
	except Exception as e:
		emit_error(
			"logout",
			code="NETWORK_ERROR",
			message=f"退出登录失败: {e}",
			recoverable=False,
			recovery_action=None,
		)
