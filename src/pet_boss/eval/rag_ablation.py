"""RAG 消融：同一岗位「有 RAG / 无 RAG」各打一次分，看决策是否翻转。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from pet_boss.agents.analysis_scoring import DEFAULT_PASS_SCORE, score_job_analysis
from pet_boss.cache.store import CacheStore
from pet_boss.profile.store import ProfileStore

_LIVE_WINDOW = 5
_DB_SCAN_LIMIT = 2000


def _ablation_path(data_dir: Path) -> Path:
	d = data_dir / "observability"
	d.mkdir(parents=True, exist_ok=True)
	return d / "rag_ablation_latest.json"


def _lifetime_path(data_dir: Path) -> Path:
	d = data_dir / "observability"
	d.mkdir(parents=True, exist_ok=True)
	return d / "rag_ablation_lifetime.json"


def load_latest_rag_ablation(data_dir: Path) -> dict[str, Any] | None:
	path = _ablation_path(data_dir)
	if not path.exists():
		# 无报告也启动补算，并返回仅含累计的占位
		ensure_flip_backfill_running(data_dir)
		life = refresh_lifetime_totals(data_dir)
		if int(life.get("rag_hit_jobs") or 0) <= 0 and int(life.get("analyzed") or 0) <= 0:
			return None
		return {
			"ok": True,
			"ts": time.time(),
			"pass_score": DEFAULT_PASS_SCORE,
			"total": 0,
			"rag_hit_jobs": life.get("rag_hit_jobs", 0),
			"hit_and_flip": life.get("hit_and_flip", 0),
			"flip_rate": 0.0,
			"avg_score_delta": 0,
			"lifetime": life,
			"cases": [],
			"live": True,
			"note": "正在补算历史翻转…",
		}
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return None
	if not isinstance(data, dict):
		return None
	ensure_flip_backfill_running(data_dir)
	life = refresh_lifetime_totals(data_dir, seed_cases=data.get("cases") or [])
	data = dict(data)
	data["lifetime"] = life
	data["rag_hit_jobs"] = life.get("rag_hit_jobs", 0)
	data["hit_and_flip"] = life.get("hit_and_flip", 0)
	compared = len(life.get("seen_ids") or [])
	flips = int(life.get("decision_flips") or 0)
	if compared > 0:
		data["flip_rate"] = round(flips / compared, 4)
	if not life.get("flip_backfill_done"):
		data["note"] = (
			f"历史翻转补算中… 已对照 {life.get('flip_backfill_processed') or compared} 条；"
			"命中岗为库累计，翻转需有/无 RAG 各打一次。"
		)
	return data


def save_latest_rag_ablation(data_dir: Path, report: dict[str, Any]) -> None:
	path = _ablation_path(data_dir)
	path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def load_lifetime_totals(data_dir: Path) -> dict[str, Any]:
	path = _lifetime_path(data_dir)
	empty = {
		"analyzed": 0,
		"rag_hit_jobs": 0,
		"hit_and_flip": 0,
		"decision_flips": 0,
		"seen_ids": [],
		"flip_backfill_done": False,
		"flip_backfill_processed": 0,
	}
	if not path.exists():
		return dict(empty)
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return dict(empty)
	if not isinstance(raw, dict):
		return dict(empty)
	return {
		"analyzed": int(raw.get("analyzed") or 0),
		"rag_hit_jobs": int(raw.get("rag_hit_jobs") or 0),
		"hit_and_flip": int(raw.get("hit_and_flip") or 0),
		"decision_flips": int(raw.get("decision_flips") or 0),
		"seen_ids": list(raw.get("seen_ids") or []),
		"flip_backfill_done": bool(raw.get("flip_backfill_done")),
		"flip_backfill_processed": int(raw.get("flip_backfill_processed") or 0),
	}


def save_lifetime_totals(data_dir: Path, life: dict[str, Any]) -> None:
	path = _lifetime_path(data_dir)
	payload = {
		"analyzed": int(life.get("analyzed") or 0),
		"rag_hit_jobs": int(life.get("rag_hit_jobs") or 0),
		"hit_and_flip": int(life.get("hit_and_flip") or 0),
		"decision_flips": int(life.get("decision_flips") or 0),
		"seen_ids": list(life.get("seen_ids") or [])[-2000:],
		"flip_backfill_done": bool(life.get("flip_backfill_done")),
		"flip_backfill_processed": int(life.get("flip_backfill_processed") or 0),
		"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
	}
	path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _job_has_rag_hit(job: dict[str, Any]) -> bool:
	meta = job.get("rag_meta") if isinstance(job.get("rag_meta"), dict) else {}
	refs = job.get("rag_references") if isinstance(job.get("rag_references"), list) else []
	return int(meta.get("hit_count") or 0) > 0 or len(refs) > 0


def _scan_analysis_db_totals(data_dir: Path) -> dict[str, int]:
	"""从分析库统计历史：分析次数、RAG 命中岗（去重）。"""
	cache_path = data_dir / "cache" / "boss_agent.db"
	if not cache_path.exists():
		return {"analyzed": 0, "rag_hit_jobs": 0}
	seen: set[str] = set()
	hit_ids: set[str] = set()
	with CacheStore(cache_path) as cache:
		rows = cache.list_recent_analysis_records(limit=_DB_SCAN_LIMIT)
	for row in rows:
		job = row.get("job") if isinstance(row.get("job"), dict) else {}
		sid = str(row.get("security_id") or job.get("security_id") or "").strip()
		jid = str(row.get("job_id") or job.get("job_id") or "").strip()
		key = f"{sid}:{jid}" if (sid or jid) else f"{row.get('title')}::{row.get('company')}"
		if not key or key in seen:
			continue
		seen.add(key)
		payload = dict(job)
		payload.setdefault("security_id", sid)
		payload.setdefault("job_id", jid)
		if _job_has_rag_hit(payload):
			hit_ids.add(key)
	return {"analyzed": len(seen), "rag_hit_jobs": len(hit_ids)}


def refresh_lifetime_totals(
	data_dir: Path,
	*,
	seed_cases: list[Any] | None = None,
) -> dict[str, Any]:
	"""合并：独立累计文件 + 分析库回填 + 窗口种子。只增不减。"""
	life = load_lifetime_totals(data_dir)
	db = _scan_analysis_db_totals(data_dir)
	life["analyzed"] = max(int(life.get("analyzed") or 0), int(db.get("analyzed") or 0))
	life["rag_hit_jobs"] = max(int(life.get("rag_hit_jobs") or 0), int(db.get("rag_hit_jobs") or 0))

	# 窗口内已有消融结果：补种子（尤其 hit_and_flip 无法从库反推）
	cases = [c for c in (seed_cases or []) if isinstance(c, dict)]
	if cases:
		seed_hits = sum(1 for c in cases if c.get("rag_hit"))
		seed_flip = sum(1 for c in cases if c.get("flipped") and c.get("rag_hit"))
		seed_flips = sum(1 for c in cases if c.get("flipped"))
		life["rag_hit_jobs"] = max(int(life.get("rag_hit_jobs") or 0), seed_hits)
		life["hit_and_flip"] = max(int(life.get("hit_and_flip") or 0), seed_flip)
		life["decision_flips"] = max(int(life.get("decision_flips") or 0), seed_flips)
		life["analyzed"] = max(int(life.get("analyzed") or 0), len(cases))
		seen = {str(x) for x in (life.get("seen_ids") or []) if x}
		for c in cases:
			cid = str(c.get("id") or "")
			if cid:
				seen.add(cid)
		life["seen_ids"] = sorted(seen)[-2000:]

	save_lifetime_totals(data_dir, life)
	return life


def _decision(score: int, pass_score: int) -> str:
	return "pass" if score >= pass_score else "filter"


def _job_from_record(row: dict[str, Any]) -> dict[str, Any]:
	job = row.get("job") if isinstance(row.get("job"), dict) else {}
	out = dict(job)
	out.setdefault("title", row.get("title") or job.get("title") or "")
	out.setdefault("company", row.get("company") or job.get("company") or job.get("brand_name") or "")
	out.setdefault("city", row.get("city") or job.get("city") or "")
	out.setdefault("salary", row.get("salary") or job.get("salary") or "")
	return out


def _case_identity(job: dict[str, Any], title: str = "") -> str:
	sid = str(job.get("security_id") or "").strip()
	jid = str(job.get("job_id") or job.get("encrypt_job_id") or "").strip()
	if sid or jid:
		return f"{sid}:{jid}"
	company = str(job.get("company") or job.get("brand_name") or "").strip()
	return f"{title or job.get('title') or ''}::{company}"


def _build_case(
	*,
	job: dict[str, Any],
	title: str,
	score_with_rag: int,
	score_without_rag: int,
	pass_score: int,
	rag_hit_count: int,
	historical_status: str | None = None,
	historical_score: Any = None,
	rag_meta_code: Any = None,
	best_score: Any = None,
	rag_expanded: bool | None = None,
) -> dict[str, Any]:
	has_hit = rag_hit_count > 0
	dec_rag = _decision(score_with_rag, pass_score)
	dec_base = _decision(score_without_rag, pass_score)
	flipped = dec_rag != dec_base
	delta = score_with_rag - score_without_rag
	out: dict[str, Any] = {
		"id": _case_identity(job, title),
		"title": title,
		"company": job.get("company") or job.get("brand_name") or "",
		"historical_status": historical_status,
		"historical_score": historical_score,
		"rag_hit": has_hit,
		"rag_hit_count": rag_hit_count,
		"score_with_rag": score_with_rag,
		"score_without_rag": score_without_rag,
		"score_delta": delta,
		"decision_with_rag": dec_rag,
		"decision_without_rag": dec_base,
		"flipped": flipped,
		"rag_meta_code": rag_meta_code,
	}
	if best_score is not None:
		try:
			out["best_score"] = round(float(best_score), 4)
		except (TypeError, ValueError):
			pass
	if rag_expanded is not None:
		out["rag_expanded"] = bool(rag_expanded)
	return out


def _aggregate_report(
	cases: list[dict[str, Any]],
	*,
	pass_score: int,
	errors: list[str] | None = None,
	live: bool = False,
	lifetime: dict[str, Any] | None = None,
) -> dict[str, Any]:
	flips = sum(1 for c in cases if c.get("flipped"))
	rag_hits = sum(1 for c in cases if c.get("rag_hit"))
	hit_and_flip = sum(1 for c in cases if c.get("flipped") and c.get("rag_hit"))
	deltas = [int(c.get("score_delta") or 0) for c in cases]
	n = len(cases)
	avg_delta = round(sum(deltas) / n, 2) if n else 0.0
	life = {
		"analyzed": int((lifetime or {}).get("analyzed") or 0),
		"rag_hit_jobs": int((lifetime or {}).get("rag_hit_jobs") or 0),
		"hit_and_flip": int((lifetime or {}).get("hit_and_flip") or 0),
		"decision_flips": int((lifetime or {}).get("decision_flips") or 0),
	}
	use_life = bool(lifetime) and (
		life["analyzed"] > 0 or life["rag_hit_jobs"] > 0 or life["hit_and_flip"] > 0
	)
	display_rag_hits = life["rag_hit_jobs"] if use_life else rag_hits
	display_hit_flip = life["hit_and_flip"] if use_life else hit_and_flip
	note = (
		"随搜岗分析自动更新：有 RAG 用当次分析分，无 RAG 额外打一次。"
		"命中岗按分析库历史累计；命中且翻转按消融累计（库内无法反推无 RAG 分）。"
		if live
		else "同一岗位各打两次分：注入 RAG 参考 vs 不注入。flipped=通过线两侧决策不同。"
	)
	return {
		"ok": True,
		"ts": time.time(),
		"pass_score": pass_score,
		"total": n,
		"rag_hit_jobs": display_rag_hits,
		"decision_flips": flips,
		"flip_rate": round(flips / n, 4) if n else 0.0,
		"hit_and_flip": display_hit_flip,
		"hit_flip_rate": round(hit_and_flip / rag_hits, 4) if rag_hits else 0.0,
		"avg_score_delta": avg_delta,
		"lifetime": life,
		"cases": cases,
		"errors": list(errors or []),
		"live": live,
		"note": note,
	}


def _bump_lifetime_file(
	data_dir: Path,
	case: dict[str, Any],
	*,
	replacing: bool,
) -> dict[str, Any]:
	"""更新累计：命中岗以分析库为准；命中且翻转仅在消融首次计入时 +1。"""
	life = refresh_lifetime_totals(data_dir, seed_cases=None)
	seen = {str(x) for x in (life.get("seen_ids") or []) if x}
	case_id = str(case.get("id") or "")
	already = replacing or (bool(case_id) and case_id in seen)

	if not already:
		if case.get("flipped"):
			life["decision_flips"] = int(life.get("decision_flips") or 0) + 1
		if case.get("rag_hit") and case.get("flipped"):
			life["hit_and_flip"] = int(life.get("hit_and_flip") or 0) + 1

	if case_id:
		seen.add(case_id)
	life["seen_ids"] = sorted(seen)[-2000:]
	db = _scan_analysis_db_totals(data_dir)
	life["analyzed"] = max(int(life.get("analyzed") or 0), int(db.get("analyzed") or 0))
	life["rag_hit_jobs"] = max(int(life.get("rag_hit_jobs") or 0), int(db.get("rag_hit_jobs") or 0))
	save_lifetime_totals(data_dir, life)
	return life


def record_live_rag_ablation_for_job(
	data_dir: Path,
	job: dict[str, Any],
	*,
	store: ProfileStore,
	ai_service: Any,
	profile: Any | None = None,
	pass_score: int | None = None,
	historical_status: str | None = None,
	search_city: str | None = None,
	window: int = _LIVE_WINDOW,
) -> dict[str, Any] | None:
	"""搜岗分析完成后增量更新消融报告（复用有 RAG 分，只补打无 RAG）。"""
	if ai_service is None or not job:
		return None
	threshold = int(pass_score if pass_score is not None else DEFAULT_PASS_SCORE)
	title = str(job.get("title") or "未命名")
	if (
		job.get("analysis_score") is None
		and not job.get("rag_meta")
		and not job.get("analysis_reason")
		and not job.get("profile_reason")
	):
		return None

	score_with = int(job.get("analysis_score") or job.get("profile_score") or 0)
	rag_meta = job.get("rag_meta") if isinstance(job.get("rag_meta"), dict) else {}
	refs = job.get("rag_references") if isinstance(job.get("rag_references"), list) else []
	hit_count = int(rag_meta.get("hit_count") or len(refs) or 0)
	city = str(search_city or job.get("city") or "") or None

	try:
		prof = profile if profile is not None else store.load_profile()
		no_rag = score_job_analysis(
			job,
			prof,
			store=store,
			ai_service=ai_service,
			target_city=city,
			pass_score=threshold,
			enable_rag=False,
			borderline_review=False,
		)
		score_without = int(no_rag.score)
	except Exception:
		return None

	case = _build_case(
		job=job,
		title=title,
		score_with_rag=score_with,
		score_without_rag=score_without,
		pass_score=threshold,
		rag_hit_count=hit_count,
		historical_status=historical_status or job.get("analysis_status"),
		historical_score=score_with,
		rag_meta_code=rag_meta.get("code"),
		best_score=rag_meta.get("best_score"),
		rag_expanded=rag_meta.get("expanded"),
	)
	case_id = str(case.get("id") or "")

	prev = {}
	path = _ablation_path(data_dir)
	if path.exists():
		try:
			raw = json.loads(path.read_text(encoding="utf-8"))
			if isinstance(raw, dict):
				prev = raw
		except (OSError, json.JSONDecodeError):
			prev = {}
	old_cases = [c for c in (prev.get("cases") or []) if isinstance(c, dict)]
	life0 = load_lifetime_totals(data_dir)
	seen = {str(x) for x in (life0.get("seen_ids") or []) if x}
	for c in old_cases:
		cid = str(c.get("id") or "")
		if cid:
			seen.add(cid)
	replacing = bool(case_id) and case_id in seen
	lifetime = _bump_lifetime_file(data_dir, case, replacing=replacing)

	merged = [case] + [c for c in old_cases if str(c.get("id") or "") != case_id]
	merged = merged[: max(1, min(int(window), 20))]
	report = _aggregate_report(
		merged,
		pass_score=threshold,
		live=True,
		lifetime=lifetime,
	)
	report["seen_ids"] = list(lifetime.get("seen_ids") or [])[-500:]
	try:
		save_latest_rag_ablation(data_dir, report)
	except OSError:
		pass
	return report


def run_rag_ablation_report(
	data_dir: Path,
	*,
	limit: int = 5,
	pass_score: int | None = None,
	ai_service: Any | None = None,
) -> dict[str, Any]:
	"""对最近分析岗做有/无 RAG 对照打分（会调用模型，注意费用）。"""
	limit = max(1, min(int(limit), 12))
	threshold = int(pass_score if pass_score is not None else DEFAULT_PASS_SCORE)

	if ai_service is None:
		from pet_boss.rag.service import build_ai_service_with_embeddings

		ai_service = build_ai_service_with_embeddings(data_dir)
	if ai_service is None:
		return {
			"ok": False,
			"error": "未配置可用的 AI / Embedding，无法做 RAG 消融对比。请先在秘书/设置里配好模型。",
			"total": 0,
			"cases": [],
		}

	cache_path = data_dir / "cache" / "boss_agent.db"
	rows: list[dict[str, Any]] = []
	with CacheStore(cache_path) as cache:
		rows = cache.list_recent_analysis_records(limit=limit)

	if not rows:
		return {
			"ok": False,
			"error": "尚无分析记录。请先搜岗并产生「分析通过/筛掉」后再跑 RAG 对比。",
			"total": 0,
			"cases": [],
		}

	cases: list[dict[str, Any]] = []
	errors: list[str] = []

	with ProfileStore(data_dir) as store:
		profile = store.load_profile()
		for row in rows:
			job = _job_from_record(row)
			title = str(job.get("title") or row.get("title") or "未命名")
			city = str(row.get("search_city") or job.get("city") or "")
			try:
				with_rag = score_job_analysis(
					job,
					profile,
					store=store,
					ai_service=ai_service,
					target_city=city or None,
					pass_score=threshold,
					enable_rag=True,
					borderline_review=False,
				)
				no_rag = score_job_analysis(
					job,
					profile,
					store=store,
					ai_service=ai_service,
					target_city=city or None,
					pass_score=threshold,
					enable_rag=False,
					borderline_review=False,
				)
			except Exception as exc:
				errors.append(f"{title}: {exc}")
				continue

			hit_count = int((with_rag.rag_meta or {}).get("hit_count") or len(with_rag.rag_references or []))
			meta = with_rag.rag_meta or {}
			cases.append(_build_case(
				job=job,
				title=title,
				score_with_rag=int(with_rag.score),
				score_without_rag=int(no_rag.score),
				pass_score=threshold,
				rag_hit_count=hit_count,
				historical_status=row.get("status"),
				historical_score=row.get("analysis_score"),
				rag_meta_code=meta.get("code"),
				best_score=meta.get("best_score"),
				rag_expanded=meta.get("expanded"),
			))

	# 批量重跑不抹掉累计：与库/旧累计取 max，并对本次 cases 中首次出现的翻转累加
	life = refresh_lifetime_totals(data_dir, seed_cases=cases)
	seen = {str(x) for x in (life.get("seen_ids") or []) if x}
	for case in cases:
		cid = str(case.get("id") or "")
		if cid and cid not in seen:
			if case.get("rag_hit") and case.get("flipped"):
				life["hit_and_flip"] = int(life.get("hit_and_flip") or 0) + 1
			if case.get("flipped"):
				life["decision_flips"] = int(life.get("decision_flips") or 0) + 1
			seen.add(cid)
	life["seen_ids"] = sorted(seen)[-2000:]
	db = _scan_analysis_db_totals(data_dir)
	life["analyzed"] = max(int(life.get("analyzed") or 0), int(db.get("analyzed") or 0))
	life["rag_hit_jobs"] = max(int(life.get("rag_hit_jobs") or 0), int(db.get("rag_hit_jobs") or 0))
	save_lifetime_totals(data_dir, life)

	report = _aggregate_report(cases, pass_score=threshold, errors=errors, live=False, lifetime=life)
	try:
		save_latest_rag_ablation(data_dir, report)
	except OSError:
		pass
	return report


_backfill_lock = threading.Lock()
_backfill_threads: dict[str, threading.Thread] = {}


def _iter_rag_hit_rows(data_dir: Path) -> list[dict[str, Any]]:
	cache_path = data_dir / "cache" / "boss_agent.db"
	if not cache_path.exists():
		return []
	with CacheStore(cache_path) as cache:
		rows = cache.list_recent_analysis_records(limit=_DB_SCAN_LIMIT)
	out: list[dict[str, Any]] = []
	seen: set[str] = set()
	for row in rows:
		job = _job_from_record(row)
		if not _job_has_rag_hit(job):
			continue
		cid = _case_identity(job, str(job.get("title") or row.get("title") or ""))
		if not cid or cid in seen:
			continue
		seen.add(cid)
		out.append(row)
	return out


def backfill_rag_flip_history(
	data_dir: Path,
	*,
	pass_score: int | None = None,
	ai_service: Any | None = None,
	limit: int | None = None,
) -> dict[str, Any]:
	"""对历史 RAG 命中岗补打「无 RAG」分，累计命中且翻转。可断点续跑。"""
	threshold = int(pass_score if pass_score is not None else DEFAULT_PASS_SCORE)
	if ai_service is None:
		from pet_boss.rag.service import build_ai_service_with_embeddings

		ai_service = build_ai_service_with_embeddings(data_dir)
	if ai_service is None:
		return {
			"ok": False,
			"error": "未配置 AI，无法补算翻转",
			"processed": 0,
			"hit_and_flip": 0,
		}

	rows = _iter_rag_hit_rows(data_dir)
	if limit is not None:
		rows = rows[: max(0, int(limit))]

	life = refresh_lifetime_totals(data_dir)
	seen = {str(x) for x in (life.get("seen_ids") or []) if x}
	pending = []
	for row in rows:
		job = _job_from_record(row)
		cid = _case_identity(job, str(job.get("title") or row.get("title") or ""))
		if cid and cid not in seen:
			pending.append(row)

	processed = 0
	new_flips = 0
	errors: list[str] = []
	window_cases: list[dict[str, Any]] = []

	with ProfileStore(data_dir) as store:
		profile = store.load_profile()
		for row in pending:
			job = _job_from_record(row)
			title = str(job.get("title") or row.get("title") or "未命名")
			cid = _case_identity(job, title)
			city = str(row.get("search_city") or job.get("city") or "") or None
			score_with = int(
				row.get("analysis_score")
				if row.get("analysis_score") is not None
				else (job.get("analysis_score") or job.get("profile_score") or 0)
			)
			rag_meta = job.get("rag_meta") if isinstance(job.get("rag_meta"), dict) else {}
			refs = job.get("rag_references") if isinstance(job.get("rag_references"), list) else []
			hit_count = int(rag_meta.get("hit_count") or len(refs) or 0)
			try:
				no_rag = score_job_analysis(
					job,
					profile,
					store=store,
					ai_service=ai_service,
					target_city=city,
					pass_score=threshold,
					enable_rag=False,
					borderline_review=False,
				)
				score_without = int(no_rag.score)
			except Exception as exc:
				errors.append(f"{title}: {exc}")
				# 失败也记入 seen，避免反复卡死同一条
				if cid:
					seen.add(cid)
				continue

			case = _build_case(
				job=job,
				title=title,
				score_with_rag=score_with,
				score_without_rag=score_without,
				pass_score=threshold,
				rag_hit_count=hit_count,
				historical_status=row.get("status"),
				historical_score=score_with,
				rag_meta_code=rag_meta.get("code"),
				best_score=rag_meta.get("best_score"),
				rag_expanded=rag_meta.get("expanded"),
			)
			if case.get("flipped"):
				life["decision_flips"] = int(life.get("decision_flips") or 0) + 1
				new_flips += 1
			if case.get("rag_hit") and case.get("flipped"):
				life["hit_and_flip"] = int(life.get("hit_and_flip") or 0) + 1
			if cid:
				seen.add(cid)
			processed += 1
			window_cases.append(case)
			life["seen_ids"] = sorted(seen)[-2000:]
			life["flip_backfill_processed"] = int(life.get("flip_backfill_processed") or 0) + 1
			if processed % 3 == 0:
				db = _scan_analysis_db_totals(data_dir)
				life["analyzed"] = max(int(life.get("analyzed") or 0), int(db.get("analyzed") or 0))
				life["rag_hit_jobs"] = max(int(life.get("rag_hit_jobs") or 0), int(db.get("rag_hit_jobs") or 0))
				save_lifetime_totals(data_dir, life)

	db = _scan_analysis_db_totals(data_dir)
	life["analyzed"] = max(int(life.get("analyzed") or 0), int(db.get("analyzed") or 0))
	life["rag_hit_jobs"] = max(int(life.get("rag_hit_jobs") or 0), int(db.get("rag_hit_jobs") or 0))
	life["seen_ids"] = sorted(seen)[-2000:]
	# 若库内命中岗都已进入 seen，则标记完成
	hit_keys = {
		_case_identity(_job_from_record(r), str((_job_from_record(r).get("title") or r.get("title") or "")))
		for r in _iter_rag_hit_rows(data_dir)
	}
	life["flip_backfill_done"] = bool(hit_keys) and hit_keys.issubset(seen)
	save_lifetime_totals(data_dir, life)

	# 刷新 latest 报告展示字段（保留原窗口 cases，若无则用补算末尾）
	prev = {}
	path = _ablation_path(data_dir)
	if path.exists():
		try:
			raw = json.loads(path.read_text(encoding="utf-8"))
			if isinstance(raw, dict):
				prev = raw
		except (OSError, json.JSONDecodeError):
			prev = {}
	old_cases = [c for c in (prev.get("cases") or []) if isinstance(c, dict)]
	merged = (window_cases[-_LIVE_WINDOW:] + old_cases)[:_LIVE_WINDOW] if window_cases else old_cases
	# 去重
	seen_case: set[str] = set()
	uniq: list[dict[str, Any]] = []
	for c in merged:
		cid = str(c.get("id") or "")
		if cid and cid in seen_case:
			continue
		if cid:
			seen_case.add(cid)
		uniq.append(c)
	report = _aggregate_report(uniq[:_LIVE_WINDOW], pass_score=threshold, live=True, lifetime=life)
	report["seen_ids"] = list(life.get("seen_ids") or [])[-500:]
	report["errors"] = errors[-20:]
	try:
		save_latest_rag_ablation(data_dir, report)
	except OSError:
		pass

	return {
		"ok": True,
		"processed": processed,
		"pending_before": len(pending),
		"new_decision_flips": new_flips,
		"hit_and_flip": int(life.get("hit_and_flip") or 0),
		"decision_flips": int(life.get("decision_flips") or 0),
		"compared": len(seen),
		"flip_backfill_done": bool(life.get("flip_backfill_done")),
		"errors": errors[-10:],
	}


def ensure_flip_backfill_running(data_dir: Path) -> None:
	"""若尚未补算完，后台线程自动补算历史翻转（不阻塞页面）。"""
	life = load_lifetime_totals(data_dir)
	if life.get("flip_backfill_done"):
		return
	# 其他进程正在写累计文件则跳过，避免双跑
	life_path = _lifetime_path(data_dir)
	if life_path.exists():
		age = time.time() - life_path.stat().st_mtime
		if age < 120 and int(life.get("flip_backfill_processed") or 0) > 0:
			return
	key = str(data_dir.resolve())
	with _backfill_lock:
		t = _backfill_threads.get(key)
		if t is not None and t.is_alive():
			return

		def _run() -> None:
			try:
				backfill_rag_flip_history(data_dir)
			except Exception:
				pass
			finally:
				with _backfill_lock:
					cur = _backfill_threads.get(key)
					if cur is threading.current_thread():
						_backfill_threads.pop(key, None)

		thread = threading.Thread(target=_run, name="rag-flip-backfill", daemon=True)
		_backfill_threads[key] = thread
		thread.start()
