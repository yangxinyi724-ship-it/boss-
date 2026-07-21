"""boss metrics — 可观测汇总。"""

from __future__ import annotations

from typing import Any

import click

from pet_boss.agents.decision_log import read_recent_decisions
from pet_boss.display import handle_output
from pet_boss.observability import summarize_observability


@click.command("metrics")
@click.option("--limit", default=3000, show_default=True, help="读取最近多少条观测事件")
@click.option("--decisions", default=10, show_default=True, help="附带最近决策条数")
@click.pass_context
def metrics_cmd(ctx: click.Context, limit: int, decisions: int) -> None:
	"""汇总本地搜岗观测日志与 Agent 决策。"""
	data_dir = ctx.obj["data_dir"]
	summary = summarize_observability(data_dir, limit=limit)
	recent = read_recent_decisions(data_dir, limit=decisions)
	payload: dict[str, Any] = {
		**summary,
		"recent_decisions": recent,
	}
	handle_output(ctx, "metrics", payload)
