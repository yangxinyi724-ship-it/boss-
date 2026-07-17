"""分析前补全岗位 JD 详情（列表页通常不含 985/211 等完整任职要求）。"""

from __future__ import annotations

from typing import Any


def enrich_job_post_description(job: dict[str, Any], platform: Any | None) -> dict[str, Any]:
	"""拉取 job_card 详情，写入 description / postDescription。"""
	if platform is None:
		return job
	security_id = str(job.get("security_id") or job.get("securityId") or "").strip()
	if not security_id:
		return job
	lid = str(job.get("lid") or "").strip()
	try:
		raw = platform.job_card(security_id, lid)
	except Exception:
		return job
	if not isinstance(raw, dict):
		return job
	zp = raw.get("zpData") or {}
	card = zp.get("jobCard") or {}
	desc = str(card.get("postDescription") or card.get("jobDetail") or "").strip()
	if not desc:
		return job
	return {**job, "postDescription": desc, "description": desc}
