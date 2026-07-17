from pathlib import Path

from pet_boss.agents.pipeline import QueryPassDepthTracker
from pet_boss.web.work_schedule import load_scout_query_pass_depth


def test_query_pass_depth_tracker_advances_after_target():
	queries = ["A", "B", "C"]
	depth = QueryPassDepthTracker(3, min_pass=2, max_pass=2, switch_on_pass=True)
	depth.pass_target = 2
	assert depth.current_query(queries) == "A"
	depth.record_pass()
	assert not depth.depth_met()
	depth.record_pass()
	assert depth.depth_met()
	finished = depth.advance_after_depth_met(queries)
	assert finished == "A"
	assert depth.current_query(queries) == "B"
	assert depth.pass_count == 0
	assert depth.pass_target == 2


def test_switch_on_pass_disabled_by_default():
	depth = QueryPassDepthTracker(3, min_pass=1, max_pass=1)
	assert depth.switch_on_pass is False
	depth.pass_target = 1
	depth.record_pass()
	assert not depth.depth_met()


def test_query_pass_depth_disabled_for_single_query():
	depth = QueryPassDepthTracker(1, min_pass=1, max_pass=6, switch_on_pass=True)
	assert not depth.enabled
	depth.record_pass()
	assert not depth.depth_met()


def test_deferred_advance_keeps_query_until_round_boundary():
	queries = ["A", "B"]
	depth = QueryPassDepthTracker(2, min_pass=1, max_pass=1, switch_on_pass=True)
	depth.pass_target = 1
	depth.record_pass()
	assert depth.depth_met()
	assert depth.current_query(queries) == "A"
	finished = depth.advance_after_depth_met(queries)
	assert finished == "A"
	assert depth.current_query(queries) == "B"


def test_list_exhausted_advances_without_depth_met():
	queries = ["A", "B", "C"]
	depth = QueryPassDepthTracker(3, min_pass=3, max_pass=6)
	depth.pass_target = 5
	depth.record_pass()
	assert not depth.depth_met()
	finished = depth.advance_after_list_exhausted(queries)
	assert finished == "A"
	assert depth.current_query(queries) == "B"
	assert depth.pass_count == 0
	assert 3 <= depth.pass_target <= 6


def test_list_exhausted_no_op_for_single_query():
	depth = QueryPassDepthTracker(1, min_pass=1, max_pass=6)
	assert depth.advance_after_list_exhausted(["only"]) is None


def test_load_scout_query_pass_depth_from_desks_json():
	lo, hi = load_scout_query_pass_depth()
	assert lo == 1
	assert hi == 6


def test_load_scout_query_pass_depth_custom(tmp_path: Path):
	path = tmp_path / "desks.json"
	path.write_text(
		'{"scout": {"queryPassDepth": {"min": 2, "max": 5}}}',
		encoding="utf-8",
	)
	assert load_scout_query_pass_depth(desks_path=path) == (2, 5)
