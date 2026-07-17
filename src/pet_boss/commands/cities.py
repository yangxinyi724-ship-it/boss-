import click

from pet_boss.api.endpoints import CITY_CODES
from pet_boss.display import handle_output, render_string_grid


@click.command("cities")
@click.pass_context
def cities_cmd(ctx: click.Context) -> None:
	"""列出所有支持的城市"""
	cities = sorted(CITY_CODES.keys())
	handle_output(
		ctx, "cities", {
			"count": len(cities),
			"cities": cities,
		},
		render=lambda d: render_string_grid(d["cities"], "cities"),
		hints={
			"next_actions": [
				"boss search <query> --city <城市名> — 搜索指定城市的职位",
			],
		},
	)
