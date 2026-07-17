"""秘书 AI 日报 Markdown 渲染。"""

from __future__ import annotations

import json
import time
from typing import Any

from pet_boss.agents.analysis_store import day_record_summary
from pet_boss.secretary.six_dim_score import SIX_DIM_KEYS, SIX_DIM_LABELS


def _escape_md_cell(text: object) -> str:
	s = "" if text is None else str(text)
	return s.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _fmt_reasons(job: dict[str, Any]) -> str:
	reasons = job.get("analysis_reason") or job.get("profile_reason") or []
	if isinstance(reasons, list):
		return "；".join(str(r) for r in reasons[:2])
	return str(reasons)


def _fmt_risks(job: dict[str, Any]) -> str:
	risks = job.get("analysis_risk") or job.get("profile_risk") or []
	if isinstance(risks, list):
		return "；".join(str(r) for r in risks[:2])
	return str(risks)


def _fmt_scores_row(scores: dict[str, int] | None) -> str:
	if not scores:
		return "-"
	parts = [f"{SIX_DIM_LABELS[k]}{scores.get(k, 0)}" for k in SIX_DIM_KEYS]
	return " · ".join(parts)


def render_analysis_daily_markdown(
	data: dict[str, Any],
	*,
	generated_at: str | None = None,
) -> str:
	"""将秘书 AI 聚合的昨日分析数据渲染为 Markdown 日报（含六维评分）。"""
	if generated_at is None:
		generated_at = time.strftime("%Y-%m-%d %H:%M:%S")

	report_date = data.get("date") or time.strftime("%Y-%m-%d")
	passed = data.get("compiled_passed") or data.get("passed") or []
	filtered = data.get("filtered") or []
	summary = day_record_summary([*passed, *filtered])
	json_jobs = data.get("jobs_json") or []

	lines: list[str] = []
	lines.append(f"# AI 办公室岗位筛选日报 · {report_date}")
	lines.append("")
	lines.append(f"_秘书 AI 整编 · 生成时间 {generated_at}_")
	lines.append("")
	lines.append("## 概览")
	lines.append("")
	lines.append(f"- 分析 AI 共评估 **{summary['total']}** 个岗位")
	lines.append(f"- 精选 **{summary['passed_count']}** 个 · 过滤 **{summary['filtered_count']}** 个")
	if summary["passed_count"]:
		lines.append(
			f"- 精选岗平均分 **{summary['avg_pass_score']}** · 最高 **{summary['top_score']}** 分"
		)
	lines.append("")

	daily_picks = data.get("daily_picks") or []
	if daily_picks:
		lines.append("## 每日精选")
		lines.append("")
		lines.append("今日最值得优先查看的岗位（综合分析分与六维评分）：")
		lines.append("")
		for idx, pick in enumerate(daily_picks, start=1):
			title = _escape_md_cell(pick.get("title") or "-")
			company = _escape_md_cell(pick.get("company") or "-")
			score = pick.get("analysis_score") or 0
			arch = _escape_md_cell(pick.get("archetype") or "-")
			comment = _escape_md_cell(pick.get("commentary") or "")
			salary = _escape_md_cell(pick.get("salary") or "")
			city = _escape_md_cell(pick.get("city") or "")
			lines.append(
				f"{idx}. **{title}** @ {company} · {score} 分 · {arch}"
				f"{f' · {salary}' if salary and salary != '-' else ''}"
				f"{f' · {city}' if city and city != '-' else ''}"
			)
			if comment:
				lines.append(f"   - {comment}")
		lines.append("")

	if passed:
		lines.append("## 精选岗位 · 六维评分")
		lines.append("")
		lines.append(
			"| 类型 | 岗位 | 公司 | 技能 | 薪资 | 福利 | 经验 | 发展 | 通勤 | 点评 |"
		)
		lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
		for row in passed:
			job = row.get("job") or row
			scores = row.get("scores") or {}
			lines.append(
				"| {arch} | {title} | {company} | {skill} | {salary} | {benefits} | "
				"{exp} | {dev} | {commute} | {comment} |".format(
					arch=_escape_md_cell(row.get("archetype") or "-"),
					title=_escape_md_cell(row.get("title") or job.get("title") or "-"),
					company=_escape_md_cell(row.get("company") or job.get("company") or "-"),
					skill=scores.get("skill", "-"),
					salary=scores.get("salary", "-"),
					benefits=scores.get("benefits", "-"),
					exp=scores.get("experience", "-"),
					dev=scores.get("development", "-"),
					commute=scores.get("commute", "-"),
					comment=_escape_md_cell(row.get("commentary") or ""),
				)
			)
		lines.append("")
		lines.append("### 六维 JSON 摘要")
		lines.append("")
		lines.append("```json")
		lines.append(json.dumps(json_jobs, ensure_ascii=False, indent=2))
		lines.append("```")
		lines.append("")

	if filtered:
		lines.append("## 已过滤岗位摘要")
		lines.append("")
		show = filtered[:15]
		for row in show:
			job = row.get("job") or row
			score = row.get("analysis_score") or job.get("analysis_score") or 0
			title = _escape_md_cell(row.get("title") or job.get("title") or "-")
			company = _escape_md_cell(row.get("company") or job.get("company") or "-")
			reason = _escape_md_cell(_fmt_reasons(job) or _fmt_risks(job) or "未达通过线")
			lines.append(f"- **{score} 分** · {title} @ {company} — {reason}")
		if len(filtered) > len(show):
			lines.append(f"- _… 另有 {len(filtered) - len(show)} 个过滤岗未列出_")
		lines.append("")

	lines.append("---")
	lines.append("_本报告由秘书 AI 整编分析 AI 精选岗位，含六维评分与差异化点评。_")
	return "\n".join(lines)
