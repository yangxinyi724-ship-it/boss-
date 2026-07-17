"""侦察 AI — 按用户自选硬性条件筛选，去重后传输给分析 AI。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pet_boss.agents.scout_hard_filter import (
	ScoutFilterConfig,
	ScoutHardResult,
	evaluate_hard_criteria,
)
from pet_boss.agents.scout_memory import record_scout_outcome, should_skip_scouted_job
from pet_boss.cache.store import CacheStore
from pet_boss.profile.models import UserProfile
from pet_boss.search_filters import SearchFilterCriteria, prefilter_job


@dataclass
class ScoutResult:
	channel: str
	jobs_seen: int = 0
	jobs_prefiltered: int = 0
	jobs_scout_passed: int = 0
	jobs_already_transmitted: int = 0
	jobs_history_skipped: int = 0
	new_jobs: list[dict[str, Any]] = field(default_factory=list)
	scout_passed_keys: set[str] = field(default_factory=set)


class ScoutAI:
	"""侦察 AI：按用户启用的硬性条件筛岗、记录已传输岗位。"""

	def __init__(
		self,
		cache: CacheStore,
		*,
		channel: str,
		scout_filters: ScoutFilterConfig | None = None,
	) -> None:
		self._cache = cache
		self._channel = channel
		self._scout_filters = scout_filters or ScoutFilterConfig()

	@staticmethod
	def make_channel(*, query: str, city: str | None = None) -> str:
		return f"scout:{query.strip()}:{city or ''}"

	def evaluate_hard(
		self,
		job: dict[str, Any],
		profile: UserProfile | None,
		*,
		criteria: SearchFilterCriteria | None = None,
	) -> ScoutHardResult:
		return evaluate_hard_criteria(
			job, profile, criteria=criteria, scout_filters=self._scout_filters,
		)

	def scout(
		self,
		jobs: list[dict[str, Any]],
		profile: UserProfile | None,
		*,
		criteria: SearchFilterCriteria | None = None,
	) -> ScoutResult:
		result = ScoutResult(channel=self._channel, jobs_seen=len(jobs))
		candidate_jobs: list[dict[str, Any]] = []
		for job in jobs:
			skip, _reason = should_skip_scouted_job(self._cache, job)
			if skip:
				result.jobs_history_skipped += 1
				continue
			if criteria:
				passed, _ = prefilter_job(job, criteria)
				if not passed:
					result.jobs_prefiltered += 1
					record_scout_outcome(self._cache, job, "prefiltered", channel=self._channel)
					continue
			hard = self.evaluate_hard(job, profile, criteria=criteria)
			job_key = CacheStore._make_watch_job_key(job)
			if hard.passed:
				result.scout_passed_keys.add(job_key)
			if not hard.passed:
				record_scout_outcome(self._cache, job, "hard_fail", channel=self._channel)
				continue
			candidate_jobs.append({
				**job,
				"scout_passed": True,
				"scout_hard_reasons": hard.reasons,
				"scout_hard_failures": hard.failures,
				"scout_hard_checks": hard.checks,
			})
		result.jobs_scout_passed = len(candidate_jobs)
		new_jobs, already = self._cache.filter_untransmitted(self._channel, candidate_jobs)
		result.jobs_already_transmitted = already
		result.new_jobs = new_jobs
		return result

	def mark_transmitted(self, jobs: list[dict[str, Any]]) -> int:
		for job in jobs:
			record_scout_outcome(self._cache, job, "transmitted", channel=self._channel)
		return self._cache.record_scout_transmitted(self._channel, jobs)
