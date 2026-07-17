"""秘书院校层级与求职画像测试。"""

import json

from pet_boss.profile.models import ParsedResume
from pet_boss.secretary.portrait import (
	apply_secretary_school_tier,
	build_secretary_portrait,
	infer_school_tier_with_secretary_ai,
)


class _FakeSecretaryAI:
	def __init__(self, school_payload: dict):
		self._school_payload = school_payload

	def chat(self, messages, **kwargs):
		return json.dumps(self._school_payload, ensure_ascii=False)


def test_secretary_school_tier_inference():
	payload = {
		"school_name": "广州商学院",
		"education": "本科",
		"school_tier": "三本/民办本科",
		"school_tier_code": 2,
		"school_tier_reason": "民办本科院校，非公办一本",
	}
	parsed = ParsedResume(education="本科")
	data = infer_school_tier_with_secretary_ai(
		_FakeSecretaryAI(payload),
		"广州商学院 本科 计算机",
		parsed,
	)
	apply_secretary_school_tier(parsed, data)
	assert parsed.school_tier_code == 2
	assert "民办" in parsed.school_tier_reason


def test_portrait_includes_basics_and_syncs_agents():
	parsed = ParsedResume(
		skills=["Python"],
		years_of_experience=2,
		education="本科",
		school_name="广州商学院",
		school_tier="三本/民办本科",
		school_tier_code=2,
		school_tier_reason="民办本科",
		gender="男",
		age=24,
	)
	portrait = build_secretary_portrait(parsed, expected_role="Python开发")
	assert portrait["basics"]["gender"] == "男"
	assert portrait["basics"]["school_tier_code"] == 2
	assert portrait["for_scout"]["school_tier"] == "三本/民办本科"
	assert portrait["for_scout"]["years_of_experience"] == 2
	assert portrait["for_analysis"]["basics"]["age"] == 24
