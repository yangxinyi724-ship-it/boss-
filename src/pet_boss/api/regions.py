"""三级地区树：省/直辖市 → 城市 → 行政区。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_TREE_PATH = Path(__file__).with_name("region_tree.json")


@dataclass(frozen=True)
class ResolvedLocation:
	"""搜岗用的已解析地区。"""

	province_code: str = ""
	province_name: str = ""
	city_code: str = ""
	city_name: str = ""
	district_code: str = ""
	district_name: str = ""

	@property
	def display(self) -> str:
		if self.city_name and self.district_name:
			return f"{self.city_name} · {self.district_name}"
		return self.city_name or ""


@lru_cache(maxsize=1)
def load_region_tree() -> list[dict[str, Any]]:
	raw = json.loads(_TREE_PATH.read_text(encoding="utf-8"))
	if not isinstance(raw, list):
		raise ValueError("region_tree.json 格式错误")
	return raw


@lru_cache(maxsize=1)
def city_code_map() -> dict[str, str]:
	"""城市名 → 城市码。"""
	mapping: dict[str, str] = {}
	for prov in load_region_tree():
		for city in prov.get("cities") or []:
			name = str(city.get("name") or "").strip()
			code = str(city.get("code") or "").strip()
			if name and code:
				mapping[name] = code
	return mapping


@lru_cache(maxsize=1)
def city_name_by_code() -> dict[str, str]:
	"""城市码 → 城市名。"""
	return {code: name for name, code in city_code_map().items()}


def resolve_location(
	*,
	city: str | None = None,
	city_code: str | None = None,
	district_code: str | None = None,
	province_code: str | None = None,
) -> ResolvedLocation:
	"""根据名称或码解析省/市/区；省份 alone 不足以搜岗。"""
	city = (city or "").strip() or None
	city_code = (city_code or "").strip() or None
	district_code = (district_code or "").strip() or None
	province_code = (province_code or "").strip() or None

	if not city and not city_code and not district_code:
		return ResolvedLocation()

	code_map = city_code_map()
	name_map = city_name_by_code()

	if city and not city_code:
		city_code = code_map.get(city)
	if city_code and not city:
		city = name_map.get(city_code)

	prov_code = ""
	prov_name = ""
	dist_name = ""
	resolved_city_code = city_code or ""
	resolved_city_name = city or ""

	for prov in load_region_tree():
		pcode = str(prov.get("code") or "")
		pname = str(prov.get("name") or "")
		if province_code and pcode != province_code:
			continue
		for c in prov.get("cities") or []:
			ccode = str(c.get("code") or "")
			cname = str(c.get("name") or "")
			match_city = (resolved_city_code and ccode == resolved_city_code) or (
				resolved_city_name and cname == resolved_city_name
			)
			if not match_city and not district_code:
				continue
			for d in c.get("districts") or []:
				dcode = str(d.get("code") or "")
				dname = str(d.get("name") or "")
				if district_code and dcode == district_code:
					return ResolvedLocation(
						province_code=pcode,
						province_name=pname,
						city_code=ccode,
						city_name=cname,
						district_code=dcode,
						district_name=dname,
					)
			if match_city:
				prov_code, prov_name = pcode, pname
				resolved_city_code, resolved_city_name = ccode, cname
				break
		if resolved_city_code and prov_code:
			break

	# 仅有区码时再扫一遍
	if district_code and not resolved_city_code:
		for prov in load_region_tree():
			for c in prov.get("cities") or []:
				for d in c.get("districts") or []:
					if str(d.get("code") or "") == district_code:
						return ResolvedLocation(
							province_code=str(prov.get("code") or ""),
							province_name=str(prov.get("name") or ""),
							city_code=str(c.get("code") or ""),
							city_name=str(c.get("name") or ""),
							district_code=district_code,
							district_name=str(d.get("name") or ""),
						)

	return ResolvedLocation(
		province_code=prov_code,
		province_name=prov_name,
		city_code=resolved_city_code,
		city_name=resolved_city_name,
		district_code=district_code or "",
		district_name=dist_name,
	)
