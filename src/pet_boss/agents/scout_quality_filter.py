"""侦察 AI 质量过滤 — 始终排除猎头/人力资源代招；筛半个月以上不活跃 HR。"""

from __future__ import annotations

import re
from typing import Any, Literal

# 常见人力资源 / 猎头公司名特征
_AGENCY_COMPANY_HINTS: tuple[str, ...] = (
	"人力资源", "人力服务", "人力咨询", "人才服务", "人才咨询", "人才派遣",
	"猎头", "科锐", "前程无忧", "万宝盛", "FESCO", "仕邦", "诺信",
	"埃摩森", "劳务派遣", "劳务外包", "劳务服务", "外包招聘", "RPO",
	"企业管理咨询", "招聘外包", "人才猎聘",
)

# 猎头 / 代招 HR 职位头衔
_AGENCY_BOSS_TITLE_HINTS: tuple[str, ...] = (
	"猎头", "人才顾问", "招聘顾问", "猎头顾问", "人力顾问", "HR顾问",
	"RPO", "交付顾问", "招聘专员", "资深顾问", "职业顾问", "寻访顾问",
)

# 明确近期活跃（半个月内）
_BOSS_RECENTLY_ACTIVE_RE = re.compile(
	r"刚刚|今日|在线|小时|分钟|"
	r"本日|当天|"
	r"\d{1,2}日内|"
	r"本周|这周|上周|"
	r"近一?周|"
	r"近两周|2周内|"
	r"半月内|半个月内|"
	r"本月|"
	r"[12]月内",
)

# 明确长期不活跃（半个月以上；「离线」不在此列）
_BOSS_LONG_INACTIVE_RE = re.compile(
	r"3周前|"
	r"[4-9]周前|"
	r"十周前|"
	r"一?个?月前|"
	r"\d+个?月前|"
	r"(?:[2-9]|10|11|12)月前|"
	r"半年(?!(?:内|活跃))|"
	r"1年|"
	r"年前|"
	r"久未|"
	r"长期未",
)

_BossActivityStatus = Literal["recent", "long_inactive", "unknown"]

# 离线/未知：不参与活跃筛选
_NEUTRAL_BOSS_STATUS = frozenset({
	"", "离线", "offline", "不在线", "离开",
})


def _is_neutral_boss_status(active: str) -> bool:
	text = str(active or "").strip()
	if not text:
		return True
	lower = text.lower()
	if lower in {"离线", "offline", "不在线", "离开"}:
		return True
	return False


def _company_name(job: dict[str, Any]) -> str:
	return str(job.get("company") or job.get("brandName") or "").strip()


def _boss_title(job: dict[str, Any]) -> str:
	return str(job.get("boss_title") or job.get("bossTitle") or "").strip()


def _active_desc(job: dict[str, Any]) -> str:
	if job.get("bossOnline"):
		return "在线"
	return str(job.get("boss_active") or job.get("activeTimeDesc") or "").strip()


def _is_proxy_job(job: dict[str, Any]) -> bool:
	for key in ("proxyJob", "goldHunter", "hunterJob", "isProxy"):
		val = job.get(key)
		if val in (True, 1, "1", "true"):
			return True
	return False


def _boss_activity_status(active: str) -> _BossActivityStatus:
	text = str(active or "").strip()
	if _is_neutral_boss_status(text):
		return "unknown"
	if _BOSS_RECENTLY_ACTIVE_RE.search(text):
		return "recent"
	if _BOSS_LONG_INACTIVE_RE.search(text):
		return "long_inactive"

	day_match = re.search(r"(\d{1,3})天前", text)
	if day_match:
		days = int(day_match.group(1))
		if days <= 14:
			return "recent"
		if days >= 15:
			return "long_inactive"

	week_match = re.search(r"(\d+)周前", text)
	if week_match:
		weeks = int(week_match.group(1))
		if weeks <= 2:
			return "recent"
		return "long_inactive"

	return "unknown"


def is_agency_hr_job(job: dict[str, Any]) -> tuple[bool, str]:
	"""判断是否为人力资源/猎头代招岗位。"""
	if _is_proxy_job(job):
		company = _company_name(job)
		title = _boss_title(job)
		label = f"{company} · {title}".strip(" ·") or "代招岗位"
		return True, f"猎头/代招岗位：{label}"

	company = _company_name(job)
	title = _boss_title(job)
	if not company and not title:
		return False, ""

	for hint in _AGENCY_BOSS_TITLE_HINTS:
		if hint in title:
			label = f"{company} · {title}".strip(" ·")
			return True, f"人力资源/猎头发布：{label}"

	for hint in _AGENCY_COMPANY_HINTS:
		if hint in company:
			if any(k in title for k in ("顾问", "专员", "经理", "主管", "总监", "HR", "hr")):
				return True, f"疑似人力资源公司：{company} · {title or '招聘方'}"
			if "猎头" in company or "人才" in company:
				return True, f"疑似人力资源公司：{company} · {title or '招聘方'}"
	return False, ""


def is_long_inactive_boss(job: dict[str, Any]) -> tuple[bool, str]:
	"""判断招聘者是否半个月以上未活跃（离线/未知不筛）。"""
	if job.get("bossOnline"):
		return False, ""
	active = _active_desc(job)
	if _is_neutral_boss_status(active):
		return False, ""
	status = _boss_activity_status(active)
	if status == "long_inactive":
		return True, f"招聘者半个月以上未活跃：{active}"
	return False, ""


def is_inactive_boss(job: dict[str, Any]) -> tuple[bool, str]:
	"""兼容旧名：同 is_long_inactive_boss。"""
	return is_long_inactive_boss(job)


def evaluate_agency_filter(
	job: dict[str, Any],
) -> tuple[bool, list[str], list[str], dict[str, bool]]:
	"""始终执行的猎头/代招排除。"""
	checks: dict[str, bool] = {}
	reasons: list[str] = []
	failures: list[str] = []

	agency, agency_msg = is_agency_hr_job(job)
	checks["agency_hr"] = not agency
	if agency:
		failures.append(agency_msg)
	else:
		reasons.append("非猎头/人力资源代招")

	passed = not failures
	return passed, reasons, failures, checks


def evaluate_scout_quality_filters(
	job: dict[str, Any],
) -> tuple[bool, list[str], list[str], dict[str, bool]]:
	"""侦察质量门槛（猎头/代招排除；HR 活跃由 scout_hard_filter 统一处理）。"""
	return evaluate_agency_filter(job)
