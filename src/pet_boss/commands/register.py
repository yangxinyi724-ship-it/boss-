"""Click command registration — 宠物页 Web 产品最小 CLI。"""

import click

from pet_boss.commands import cities, doctor, login, logout, schema, status
from pet_boss.commands import profile_cmd


def register_candidate_commands(cli: click.Group) -> None:
	"""注册 Web 启动与运维所需的最小命令集。"""
	cli.add_command(schema.schema_cmd, "schema")
	cli.add_command(login.login_cmd, "login")
	cli.add_command(logout.logout_cmd, "logout")
	cli.add_command(status.status_cmd, "status")
	cli.add_command(doctor.doctor_cmd, "doctor")
	cli.add_command(cities.cities_cmd, "cities")
	cli.add_command(profile_cmd.profile_group, "profile")
	cli.add_command(profile_cmd.web_cmd, "web")
