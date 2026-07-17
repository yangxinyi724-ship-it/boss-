"""侦察岗位历史 — 全局去重，已侦察岗位不再重复处理。"""

from __future__ import annotations

from typing import Any

from pet_boss.cache.store import CacheStore

_OUTCOME_RANK = {
	"seen": 1,
	"browse_skip": 1,
	"prefiltered": 1,
	"hard_fail": 2,
	"transmitted": 3,
	"passed": 4,
	"filtered": 4,
	"shortlisted": 5,
	"rejected": 5,
}


def job_key(job: dict[str, Any]) -> str:
	return CacheStore._make_watch_job_key(job)


def _job_id(job: dict[str, Any]) -> str:
	return str(job.get("job_id") or job.get("encryptJobId") or "")


def resolve_scout_record(cache: CacheStore, job: dict[str, Any]) -> dict[str, Any] | None:
	"""按 job_key 或 job_id 查找已有侦察记录。"""
	prior = cache.get_scout_history(job_key(job))
	if prior:
		return prior
	jid = _job_id(job)
	if jid:
		return cache.get_scout_history_by_job_id(jid)
	return None


def is_already_scouted(cache: CacheStore, job: dict[str, Any]) -> bool:
	return resolve_scout_record(cache, job) is not None


def should_skip_scouted_job(
	cache: CacheStore,
	job: dict[str, Any],
	*,
	profile_store: Any | None = None,
) -> tuple[bool, str]:
	"""已侦察 / 候选池 / 不感兴趣 / 已分析过的岗位不再重复处理。"""
	prior = resolve_scout_record(cache, job)
	if prior:
		return True, str(prior.get("outcome") or "seen")

	key = job_key(job)
	jid = _job_id(job)
	sid = str(job.get("security_id") or job.get("securityId") or "")

	if cache.is_scout_transmitted_globally(job_key=key, job_id=jid):
		return True, "transmitted"

	if sid and jid and cache.is_shortlisted(sid, jid):
		return True, "shortlisted"
	if jid and cache.is_shortlisted_by_job_id(jid):
		return True, "shortlisted"

	if profile_store is not None and sid and jid:
		if profile_store.has_feedback_action(sid, jid, "rejected"):
			return True, "rejected"

	if sid and jid and cache.has_analysis_record(sid, jid):
		return True, "analyzed"
	if jid and cache.has_analysis_record_by_job_id(jid):
		return True, "analyzed"

	return False, ""


def get_scout_record(cache: CacheStore, job: dict[str, Any]) -> dict[str, Any] | None:
	return resolve_scout_record(cache, job)


def record_scout_outcome(
	cache: CacheStore,
	job: dict[str, Any],
	outcome: str,
	*,
	channel: str = "",
	analysis_score: int = 0,
) -> None:
	"""写入侦察历史；高优先级 outcome 可覆盖低优先级记录。"""
	existing = resolve_scout_record(cache, job)
	if existing:
		old = str(existing.get("outcome") or "seen")
		if _OUTCOME_RANK.get(outcome, 0) < _OUTCOME_RANK.get(old, 0):
			return
	cache.record_scout_history(
		job,
		outcome,
		channel=channel,
		analysis_score=analysis_score,
	)
