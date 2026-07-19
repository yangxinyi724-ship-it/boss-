"""分析前补全岗位 JD 详情（列表页通常不含 985/211 等完整任职要求）。"""

from __future__ import annotations

from typing import Any


def enrich_job_post_description(job: dict[str, Any], platform: Any | None) -> dict[str, Any]:
	"""拉取 job_card 详情，写入 description / postDescription，并尽量补全活跃度。"""
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
	out = dict(job)
	desc = str(card.get("postDescription") or card.get("jobDetail") or "").strip()
	if desc:
		out["postDescription"] = desc
		out["description"] = desc
	# 详情里的活跃文案往往比列表准（列表可能只有 bossOnline）
	boss = card.get("bossInfo") if isinstance(card.get("bossInfo"), dict) else {}
	active = str(
		card.get("activeTimeDesc")
		or boss.get("activeTimeDesc")
		or card.get("activeDesc")
		or boss.get("activeDesc")
		or ""
	).strip()
	if active:
		out["boss_active"] = active
		out["activeTimeDesc"] = active
	return out
