from pet_boss.profile.learning import apply_feedback_learning
from pet_boss.profile.reject_learning import process_reject_with_learning
from pet_boss.profile.store import ProfileStore


def test_reject_learning_records_weight_changes(tmp_path):
	with ProfileStore(tmp_path) as store:
		before = store.get_dimension_weights()["preference_fit"]
		result = process_reject_with_learning(
			store,
			{
				"title": "后端开发",
				"company": "测试公司",
				"analysis_score": 80,
				"analysis_reason": ["Go 经验匹配"],
				"analysis_risk": ["大小周"],
			},
			tags=["工作强度"],
			reason="不接受大小周",
		)
		after = store.get_dimension_weights()["preference_fit"]
		assert after < before
		assert result["weight_changes"]
		assert result["ai_memory_added"]
		assert "不接受大小周" in result["feedback_text"]


def test_clear_reject_learning_memory_reverts_changes(tmp_path):
	from pet_boss.profile.reject_learning import clear_reject_learning_memory

	with ProfileStore(tmp_path) as store:
		before = store.get_dimension_weights()["preference_fit"]
		result = process_reject_with_learning(
			store,
			{
				"security_id": "s1",
				"job_id": "j1",
				"title": "后端开发",
				"company": "测试公司",
				"analysis_score": 40,
				"analysis_reason": [],
				"analysis_risk": ["大小周"],
			},
			tags=["工作强度"],
			reason="不接受大小周",
		)
		store.add_preference_learning_log({
			"security_id": "s1",
			"job_id": "j1",
			"title": "后端开发",
			"company": "测试公司",
			"user_tags": ["工作强度"],
			"user_reason": "不接受大小周",
			"analysis_score": 40,
			"analysis_reason": [],
			"analysis_risk": ["大小周"],
			"weight_changes": result["weight_changes"],
			"preference_instructions": result["preference_instructions_added"],
			"ai_memory_added": result["ai_memory_added"],
			"created_at": __import__("time").time(),
		})
		assert store.list_preference_learning_logs()
		assert store.list_ai_memory(agent="analysis")

		clear_result = clear_reject_learning_memory(store)
		assert clear_result["logs_removed"] == 1
		assert clear_result["memory_removed"] >= 1
		assert store.get_dimension_weights()["preference_fit"] == before
		assert not store.list_preference_learning_logs()
