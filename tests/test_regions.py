"""三级地区树解析测试。"""

from pet_boss.api.regions import city_code_map, load_region_tree, resolve_location


def test_load_region_tree_has_provinces():
	tree = load_region_tree()
	assert len(tree) >= 30
	assert any(p.get("name") in ("广东", "北京") for p in tree)


def test_shenzhen_has_nanshan():
	loc = resolve_location(city="深圳", district_code="440305")
	assert loc.city_name == "深圳"
	assert loc.city_code == "101280600"
	assert loc.district_name == "南山区"
	assert loc.district_code == "440305"


def test_resolve_city_by_name():
	loc = resolve_location(city="杭州")
	assert loc.city_name == "杭州"
	assert loc.city_code
	assert loc.city_code == city_code_map()["杭州"]


def test_resolve_empty():
	loc = resolve_location()
	assert loc.city_code == ""
	assert loc.district_code == ""
