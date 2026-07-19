"""列表 hasMore 推断与末页重复检测。"""

from pet_boss.search_filters import infer_search_has_more, pages_substantially_overlap


def test_has_more_true_passthrough():
	assert infer_search_has_more({"hasMore": True, "jobList": [{"a": 1}]}) is True


def test_has_more_false_means_end_even_if_full_page():
	"""末页也常满 15 条；显式 hasMore=false 必须结束，否则会重复拉末页。"""
	assert infer_search_has_more({"hasMore": False, "jobList": [{"a": 1}] * 3}) is False
	assert infer_search_has_more({"hasMore": False, "jobList": [{"a": 1}] * 15}) is False
	assert infer_search_has_more({"hasMore": False, "jobList": [{"a": 1}] * 30}) is False


def test_has_more_missing_with_full_page_continues():
	assert infer_search_has_more({"jobList": [{"a": 1}] * 15}) is True


def test_has_more_missing_with_empty_means_end():
	assert infer_search_has_more({"jobList": []}) is False
	assert infer_search_has_more({}) is False


def test_pages_substantially_overlap_detects_repeat():
	prev = [{"job_id": f"j{i}"} for i in range(10)]
	curr = [{"job_id": f"j{i}"} for i in range(8)] + [{"job_id": "x1"}, {"job_id": "x2"}]
	assert pages_substantially_overlap(prev, curr) is True
	assert pages_substantially_overlap(prev, [{"job_id": f"n{i}"} for i in range(10)]) is False
