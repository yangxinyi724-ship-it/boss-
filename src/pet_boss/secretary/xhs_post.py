"""秘书 AI — 小红书工作 vlog 帖子生成与导出。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pet_boss.agents.analysis_store import day_record_summary


def build_xhs_vlog_post(data: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
	"""生成小红书风格的工作 vlog 文案（标题 + 正文 + 话题）。"""
	cfg = config or {}
	xhs = cfg.get("xiaohongshu") or {}
	report_date = data.get("date") or time.strftime("%Y-%m-%d")
	passed = data.get("passed") or []
	filtered = data.get("filtered") or []
	summary = day_record_summary([*passed, *filtered])
	hashtags = list(xhs.get("hashtags") or ["求职日记", "AI办公", "打工人日常"])
	nickname = xhs.get("nickname") or ""

	title = f"AI办公室vlog｜{report_date} 筛了{summary['total']}个岗✨"
	if summary["passed_count"]:
		title = f"AI办公室vlog｜昨天挖到{summary['passed_count']}个宝藏岗🔥"

	body_lines = [
		f"📅 {report_date} 工作记录",
		"",
		"今天（其实是昨天啦）我们办公室的 AI 小队又开工了：",
		f"🔍 分析 AI 一共看了 **{summary['total']}** 个岗位",
		f"✅ 通过 **{summary['passed_count']}** 个 · ❌ 过滤 **{summary['filtered_count']}** 个",
		"",
	]
	if passed:
		body_lines.append("🏆 **今日 TOP 推荐**：")
		rows = data.get("compiled_passed") or passed
		for idx, row in enumerate(rows[:3], start=1):
			job = row.get("job") or row
			score = row.get("analysis_score") or job.get("analysis_score") or 0
			title_j = row.get("title") or job.get("title") or "-"
			company = row.get("company") or job.get("company") or "-"
			salary = row.get("salary") or job.get("salary") or ""
			line = f"{idx}. {title_j} @ {company}（{score}分）"
			if salary:
				line += f" · {salary}"
			body_lines.append(line)
		body_lines.append("")
	else:
		body_lines.append("今天没有新通过的岗位，但筛选记录都已整理进日报啦～")
		body_lines.append("")

	body_lines.extend([
		"📝 完整岗位清单已整理成日报发到邮箱，需要的姐妹/兄弟自取～",
		"",
		"💼 秘书 AI 每日固定流程：整理 → 日报 → vlog，打工人求职也要仪式感！",
	])
	if nickname:
		body_lines.append(f"\n— {nickname}")

	tag_line = " ".join(f"#{tag.lstrip('#')}" for tag in hashtags)
	body = "\n".join(body_lines)
	full_text = f"{title}\n\n{body}\n\n{tag_line}"

	return {
		"title": title,
		"body": body,
		"hashtags": hashtags,
		"tag_line": tag_line,
		"full_text": full_text,
		"report_date": report_date,
	}


def export_xhs_vlog_post(
	post: dict[str, Any],
	*,
	output_dir: Path,
) -> dict[str, Any]:
	output_dir.mkdir(parents=True, exist_ok=True)
	stem = f"xhs-vlog-{post.get('report_date') or time.strftime('%Y-%m-%d')}"
	md_path = output_dir / f"{stem}.md"
	txt_path = output_dir / f"{stem}.txt"
	content_md = (
		f"# {post.get('title') or '工作 vlog'}\n\n"
		f"{post.get('body') or ''}\n\n"
		f"{post.get('tag_line') or ''}\n"
	)
	md_path.write_text(content_md, encoding="utf-8")
	txt_path.write_text(post.get("full_text") or "", encoding="utf-8")
	return {
		"exported": True,
		"markdown_path": str(md_path),
		"text_path": str(txt_path),
		"mode": "file",
	}
