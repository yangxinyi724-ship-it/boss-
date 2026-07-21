"""boss eval — 标注集评测 / RAG 消融 / 抓取今日集。"""

from __future__ import annotations

from pathlib import Path

import click

from pet_boss.display import handle_output
from pet_boss.eval import (
	capture_eval_today,
	eval_today_path,
	run_eval_report,
	run_rag_ablation_report,
)


@click.command("eval")
@click.option(
	"--labels",
	"labels_path",
	type=click.Path(path_type=Path, exists=True, dir_okay=False),
	default=None,
	help="标注 JSON 路径（默认 data/eval/eval_today.json）",
)
@click.option(
	"--rag-ablation/--no-rag-ablation",
	default=False,
	help="对最近分析岗做有/无 RAG 对照打分（会调用模型）",
)
@click.option(
	"--capture/--no-capture",
	default=False,
	help="从分析库抓取最近岗位写入 data/eval/eval_today.json",
)
@click.option("--limit", default=20, show_default=True, help="抓取/RAG 消融取样岗位数")
@click.pass_context
def eval_cmd(
	ctx: click.Context,
	labels_path: Path | None,
	rag_ablation: bool,
	capture: bool,
	limit: int,
) -> None:
	"""标注集准确率；可选抓取真实岗位或 RAG 消融。"""
	data_dir = ctx.obj["data_dir"]
	if capture:
		report = capture_eval_today(data_dir, limit=limit)
		handle_output(ctx, "eval-capture", report)
		return
	if rag_ablation:
		report = run_rag_ablation_report(data_dir, limit=min(limit, 12))
		handle_output(ctx, "eval-rag-ablation", report)
		return
	path = labels_path or eval_today_path(data_dir)
	report = run_eval_report(path)
	handle_output(ctx, "eval", report)
