from pathlib import Path

from pet_boss.agents.analysis_ai import AnalysisResult
from pet_boss.agents.analysis_store import persist_analysis_result
from pet_boss.agents.scout_ai import ScoutAI
from pet_boss.agents.scout_memory import (
	is_already_scouted,
	record_scout_outcome,
	should_skip_scouted_job,
)
from pet_boss.cache.store import CacheStore
from pet_boss.profile.scout_learning import (
	ai_memory_summary_for_prompt,
	learn_from_analysis_outcome,
)
from pet_boss.profile.store import ProfileStore


def _job(**kwargs):
	base = {
		"job_id": "j1",
		"security_id": "s1",
		"title": "Golang 后端",
		"company": "测试科技",
		"salary": "20-35K",
		"city": "广州",
	}
	base.update(kwargs)
	return base


def test_scout_history_skip_already_scouted(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	job = _job()
	record_scout_outcome(cache, job, "seen")
	assert is_already_scouted(cache, job)
	assert cache.count_scout_history() == 1


def test_scout_ai_skips_history_jobs(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	channel = ScoutAI.make_channel(query="Golang", city="广州")
	scout = ScoutAI(cache, channel=channel)
	jobs = [_job(), _job(job_id="j2", security_id="s2")]
	record_scout_outcome(cache, jobs[0], "passed", analysis_score=80)

	result = scout.scout(jobs, None)
	assert result.jobs_history_skipped == 1
	assert len(result.new_jobs) == 1
	assert result.new_jobs[0]["job_id"] == "j2"


def test_bootstrap_from_scout_transmitted(tmp_path: Path):
	db = tmp_path / "boss_agent.db"
	cache = CacheStore(db)
	channel = ScoutAI.make_channel(query="Golang", city="广州")
	job = _job()
	cache.record_scout_transmitted(channel, [job])
	cache._conn.execute("DELETE FROM scout_history")
	cache._conn.commit()
	cache._bootstrap_scout_history()
	assert cache.is_job_scouted("s1:j1")


def test_clear_all_scout_history(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	channel = ScoutAI.make_channel(query="Golang", city="广州")
	job = _job()
	record_scout_outcome(cache, job, "passed", analysis_score=80)
	cache.record_scout_transmitted(channel, [job])
	cache.record_analysis_job(job, "passed", channel=channel)
	cache.add_shortlist({
		"security_id": "s1",
		"job_id": "j1",
		"title": job["title"],
		"company": job["company"],
		"city": job["city"],
		"salary": job["salary"],
		"source": "test",
	})
	assert cache.count_scout_history() == 1
	removed = cache.clear_all_scout_history()
	assert removed["history_removed"] == 1
	assert removed["transmitted_removed"] == 1
	assert removed["analysis_removed"] == 1
	assert removed["shortlist_removed"] == 1
	assert cache.count_scout_history() == 0
	assert not is_already_scouted(cache, job)
	assert not cache.has_analysis_record("s1", "j1")
	assert not cache.is_shortlisted("s1", "j1")


def test_persist_analysis_updates_history_and_memory(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	with ProfileStore(tmp_path) as store:
		result = AnalysisResult(
			jobs_received=1,
			jobs_passed=1,
			passed_jobs=[{
				**_job(),
				"analysis_score": 88,
				"analysis_reason": ["技能栈高度匹配"],
				"analysis_risk": [],
			}],
		)
		count, _ablation = persist_analysis_result(cache, result, channel="scout:golang:", store=store)
		assert count == 1
		assert cache.get_scout_history("s1:j1")["outcome"] == "passed"
		mem = store.list_ai_memory(agent="analysis")
		assert mem
		summary = ai_memory_summary_for_prompt(store)
		assert "技能栈高度匹配" in summary


def test_learn_from_filtered_job(tmp_path: Path):
	with ProfileStore(tmp_path) as store:
		job = {
			**_job(),
			"analysis_score": 35,
			"analysis_risk": ["公司业务方向与用户目标不符"],
		}
		learn_from_analysis_outcome(store, job, passed=False)
		items = store.list_ai_memory(category="reject_pattern")
		assert items


def test_should_skip_shortlisted_job(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	job = _job()
	cache.add_shortlist({
		"security_id": "s1",
		"job_id": "j1",
		"title": job["title"],
		"company": job["company"],
		"city": job["city"],
		"salary": job["salary"],
		"source": "test",
	})
	skip, reason = should_skip_scouted_job(cache, job)
	assert skip is True
	assert reason == "shortlisted"


def test_should_skip_rejected_job(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	job = _job()
	with ProfileStore(tmp_path) as store:
		store.record_feedback(
			security_id="s1",
			job_id="j1",
			action="rejected",
			title=job["title"],
			company=job["company"],
		)
		skip, reason = should_skip_scouted_job(cache, job, profile_store=store)
	assert skip is True
	assert reason == "rejected"


def test_should_skip_by_job_id_when_security_id_changes(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	job_old = _job(security_id="s-old", job_id="j1")
	record_scout_outcome(cache, job_old, "passed", analysis_score=80)
	job_new = _job(security_id="s-new", job_id="j1")
	skip, reason = should_skip_scouted_job(cache, job_new)
	assert skip is True
	assert reason == "passed"
	assert cache.count_scout_history() == 1


def test_record_scout_merges_same_job_id(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	record_scout_outcome(cache, _job(security_id="s1", job_id="j1"), "seen")
	record_scout_outcome(cache, _job(security_id="s2", job_id="j1"), "passed", analysis_score=70)
	assert cache.count_scout_history() == 1
	record = cache.get_scout_history_by_job_id("j1")
	assert record is not None
	assert record["outcome"] == "passed"
	assert record["security_id"] == "s2"
	assert record["job_key"] == "s2:j1"


def test_filter_untransmitted_skips_shortlisted(tmp_path: Path):
	cache = CacheStore(tmp_path / "boss_agent.db")
	job = _job()
	cache.add_shortlist({
		"security_id": "s1",
		"job_id": "j1",
		"title": "",
		"company": "",
		"city": "",
		"salary": "",
		"source": "test",
	})
	new_items, already = cache.filter_untransmitted("scout:test:", [job])
	assert new_items == []
	assert already == 1
