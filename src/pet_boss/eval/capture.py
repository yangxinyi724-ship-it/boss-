"""从宠物页 / 分析库抓取真实岗位，写成 eval_today.json。"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from pet_boss.agents.analysis_scoring import DEFAULT_PASS_SCORE
from pet_boss.cache.store import CacheStore

EVAL_TODAY_NAME = "eval_today.json"
_DEFAULT_LIMIT = 20


def eval_today_path(data_dir: Path) -> Path:
	return data_dir / "eval" / EVAL_TODAY_NAME


def _job_key(job: dict[str, Any]) -> str:
	sid = str(job.get("security_id") or "").strip()
	jid = str(
		job.get("job_id")
		or job.get("encrypt_job_id")
		or job.get("encryptJobId")
		or ""
	).strip()
	if sid or jid:
		return f"{sid}:{jid}"
	title = str(job.get("title") or "").strip()
	company = str(
		job.get("company") or job.get("brand_name") or job.get("brandName") or ""
	).strip()
	return f"{title}::{company}"


def _case_id(job: dict[str, Any], index: int, *, used: set[str] | None = None) -> str:
	"""用例展示名：优先岗位标题，重名时加公司或序号。"""
	title = str(job.get("title") or "").strip() or f"岗位{index}"
	company = str(
		job.get("company") or job.get("brand_name") or job.get("brandName") or ""
	).strip()
	base = title[:40]
	candidate = base
	if used is not None and candidate in used and company:
		candidate = f"{base} · {company[:20]}"
	if used is not None and candidate in used:
		candidate = f"{base} #{index}"
	if used is not None:
		used.add(candidate)
	return candidate


def _decision_from_row(
	row: dict[str, Any] | None,
	job: dict[str, Any],
	*,
	pass_score: int,
) -> tuple[str, str]:
	"""返回 (expected, note_suffix)。"""
	if row and row.get("status") in {"passed", "filtered"}:
		expected = "pass" if row["status"] == "passed" else "filter"
		score = int(row.get("analysis_score") or job.get("analysis_score") or 0)
		return expected, f"库内 status={row['status']} · 分={score}"
	score_raw = job.get("analysis_score")
	if score_raw is None:
		score_raw = job.get("profile_score")
	if score_raw is not None:
		score = int(score_raw)
		expected = "pass" if score >= pass_score else "filter"
		return expected, f"按分数判定 · 分={score} · 线={pass_score}"
	# 侧边栏「通过岗位」无分数时按 pass 标注，并标明需人工复核
	return "pass", "侧边栏抓取 · 默认 expected=pass（可手工改标）"


def _prefer_full_job(client_job: dict[str, Any], db_job: dict[str, Any] | None) -> dict[str, Any]:
	"""优先用库里的完整 BOSS payload，再合并客户端字段。"""
	if isinstance(db_job, dict) and db_job:
		merged = dict(db_job)
		for key, value in client_job.items():
			if value in (None, "", [], {}):
				continue
			if key not in merged or merged.get(key) in (None, "", [], {}):
				merged[key] = value
		return merged
	return dict(client_job)


def _index_analysis_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
	index: dict[str, dict[str, Any]] = {}
	for row in rows:
		job = row.get("job") if isinstance(row.get("job"), dict) else {}
		payload = {
			**job,
			"security_id": row.get("security_id") or job.get("security_id") or "",
			"job_id": row.get("job_id") or job.get("job_id") or "",
			"title": row.get("title") or job.get("title") or "",
			"company": row.get("company") or job.get("company") or "",
			"city": row.get("city") or job.get("city") or "",
			"salary": row.get("salary") or job.get("salary") or "",
			"analysis_score": row.get("analysis_score")
			if row.get("analysis_score") is not None
			else job.get("analysis_score"),
		}
		keys = {
			_job_key(payload),
			_job_key({"security_id": row.get("security_id"), "job_id": row.get("job_id")}),
		}
		for key in keys:
			if key and key not in index:
				index[key] = {**row, "job": payload}
	return index


def build_eval_today_bundle(
	jobs: list[dict[str, Any]],
	*,
	pass_score: int = DEFAULT_PASS_SCORE,
	source: str = "pet_capture",
	limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
	limit = max(1, min(int(limit), 50))
	cases: list[dict[str, Any]] = []
	seen: set[str] = set()
	used_ids: set[str] = set()
	for raw in jobs:
		if not isinstance(raw, dict):
			continue
		job = dict(raw)
		key = _job_key(job)
		if not key or key in seen:
			continue
		seen.add(key)
		row = job.pop("_capture_row", None) if "_capture_row" in job else None
		expected, note = _decision_from_row(row if isinstance(row, dict) else None, job, pass_score=pass_score)
		score = job.get("analysis_score")
		if score is None:
			score = job.get("profile_score")
		case: dict[str, Any] = {
			"id": _case_id(job, len(cases) + 1, used=used_ids),
			"expected": expected,
			"stage": "analysis_score",
			"note": f"真实抓取 · {note}",
			"job": job,
		}
		if score is not None:
			case["mock_score"] = int(score)
			case["baseline_score"] = int(score)
		if isinstance(row, dict) and row.get("status"):
			case["capture_status"] = row["status"]
		cases.append(case)
		if len(cases) >= limit:
			break

	today = date.today().isoformat()
	return {
		"version": 1,
		"pass_score": int(pass_score),
		"description": f"宠物页一键抓取真实岗位 · {today} · 共 {len(cases)} 条",
		"source": source,
		"captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
		"cases": cases,
	}


def capture_eval_today(
	data_dir: Path,
	*,
	client_jobs: list[dict[str, Any]] | None = None,
	limit: int = _DEFAULT_LIMIT,
	pass_score: int | None = None,
) -> dict[str, Any]:
	"""抓取岗位写入 data/eval/eval_today.json。

	优先用页面提交的岗位（按 id 回填库内完整 payload）；
	不足 limit 时用最近分析记录补齐（含通过与筛掉，更「脏」）。
	"""
	threshold = int(pass_score if pass_score is not None else DEFAULT_PASS_SCORE)
	limit = max(1, min(int(limit), 50))
	client_jobs = [j for j in (client_jobs or []) if isinstance(j, dict)]

	cache_path = data_dir / "cache" / "boss_agent.db"
	db_rows: list[dict[str, Any]] = []
	if cache_path.exists():
		with CacheStore(cache_path) as cache:
			db_rows = cache.list_recent_analysis_records(limit=max(limit * 3, 60))
	db_index = _index_analysis_rows(db_rows)

	merged: list[dict[str, Any]] = []
	seen: set[str] = set()

	for client in client_jobs:
		key = _job_key(client)
		row = db_index.get(key)
		db_job = row.get("job") if isinstance(row, dict) else None
		full = _prefer_full_job(client, db_job if isinstance(db_job, dict) else None)
		full["_capture_row"] = row
		k = _job_key(full)
		if not k or k in seen:
			continue
		seen.add(k)
		merged.append(full)
		if len(merged) >= limit:
			break

	# 侧边栏不足 20：用最近分析记录补齐（先 filtered 与 passed 交错，避免全是通过岗）
	if len(merged) < limit:
		passed = [r for r in db_rows if r.get("status") == "passed"]
		filtered = [r for r in db_rows if r.get("status") == "filtered"]
		others = [r for r in db_rows if r.get("status") not in {"passed", "filtered"}]
		interleaved: list[dict[str, Any]] = []
		for i in range(max(len(passed), len(filtered), len(others))):
			if i < len(filtered):
				interleaved.append(filtered[i])
			if i < len(passed):
				interleaved.append(passed[i])
			if i < len(others):
				interleaved.append(others[i])
		for row in interleaved:
			job = row.get("job") if isinstance(row.get("job"), dict) else {}
			full = _prefer_full_job(
				{
					"security_id": row.get("security_id") or "",
					"job_id": row.get("job_id") or "",
					"title": row.get("title") or "",
					"company": row.get("company") or "",
					"city": row.get("city") or "",
					"salary": row.get("salary") or "",
					"analysis_score": row.get("analysis_score"),
				},
				job,
			)
			full["_capture_row"] = row
			k = _job_key(full)
			if not k or k in seen:
				continue
			seen.add(k)
			merged.append(full)
			if len(merged) >= limit:
				break

	bundle = build_eval_today_bundle(
		merged,
		pass_score=threshold,
		source="pet_capture",
		limit=limit,
	)
	path = eval_today_path(data_dir)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8",
	)
	return {
		"ok": True,
		"path": str(path),
		"count": len(bundle.get("cases") or []),
		"from_page": min(len(client_jobs), limit),
		"pass_score": threshold,
		"description": bundle.get("description") or "",
	}
