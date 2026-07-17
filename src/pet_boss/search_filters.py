"""Reusable search pipeline — list-page prefiltering + welfare detail fallback.

Centralizes filtering logic shared by search, batch-greet, and export commands.
"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from pet_boss.api import endpoints
from pet_boss.api.models import JobItem

# ── Ordinal lookups for threshold comparisons ───────────────────────

_EXPERIENCE_ORDER: dict[str, int] = {
	"应届": 0, "1年以内": 1, "1-3年": 2, "3-5年": 3, "5-10年": 4, "10年以上": 5,
}

_EDUCATION_ORDER: dict[str, int] = {
	"初中及以下": 0, "中专/中技": 1, "高中": 2, "大专": 3, "本科": 4, "硕士": 5, "博士": 6,
}

# ── Welfare keywords ────────────────────────────────────────────────

WELFARE_KEYWORDS: dict[str, list[str]] = {
	"双休": ["双休", "周末双休", "五天工作制", "5天工作制"],
	"五险一金": ["五险一金"],
	"五险": ["五险一金", "五险"],
	"年终奖": ["年终奖"],
	"带薪年假": ["带薪年假"],
	"餐补": ["餐补", "包吃", "免费午餐"],
	"住房补贴": ["住房补贴", "住房补助"],
	"定期体检": ["定期体检"],
	"股票期权": ["股票期权"],
	"加班补助": ["加班补助"],
}

_MAX_FILTER_PAGES = 5
_WELFARE_WORKERS = 3

_BOSS_SEARCH_HOSTS = {"www.zhipin.com", "zhipin.com"}
_BOSS_SEARCH_PATHS = {"/web/geek/job", "/web/geek/jobs"}
_URL_PARAM_ALIASES = {
	"query": "query",
	"city": "city",
	"salary": "salary",
	"experience": "experience",
	"degree": "degree",
	"education": "degree",
	"industry": "industry",
	"scale": "scale",
	"stage": "stage",
	"jobType": "jobType",
	"job_type": "jobType",
}
_URL_SEARCH_PARAM_KEYS = {
	"city",
	"salary",
	"experience",
	"degree",
	"industry",
	"scale",
	"stage",
	"jobType",
}


class SearchUrlParseError(ValueError):
	"""Raised when a user-supplied BOSS search URL cannot be safely used."""


@dataclass(frozen=True)
class ParsedSearchUrl:
	query: str
	params: dict[str, str]
	page: int | None = None


def _first_query_value(parsed: dict[str, list[str]], key: str) -> str:
	values = parsed.get(key, [])
	for value in values:
		candidate = value.strip()
		if candidate:
			return candidate
	return ""


def parse_boss_search_url(search_url: str) -> ParsedSearchUrl:
	"""Parse a user-copied BOSS search URL into whitelisted API search params."""
	parts = urlparse(search_url)
	if parts.scheme not in {"http", "https"} or parts.netloc not in _BOSS_SEARCH_HOSTS:
		raise SearchUrlParseError("仅支持 zhipin.com 的职位搜索 URL")
	if parts.path.rstrip("/") not in _BOSS_SEARCH_PATHS:
		raise SearchUrlParseError("仅支持 BOSS 直聘求职者职位搜索页 URL")

	query_values = parse_qs(parts.query, keep_blank_values=False)
	params: dict[str, str] = {}
	for source_key, target_key in _URL_PARAM_ALIASES.items():
		value = _first_query_value(query_values, source_key)
		if value:
			params[target_key] = value

	query = params.pop("query", "")
	page = None
	if raw_page := _first_query_value(query_values, "page"):
		try:
			page = max(1, int(raw_page))
		except ValueError as exc:
			raise SearchUrlParseError("URL 中的 page 参数不是有效数字") from exc

	if not query and not any(key in params for key in _URL_SEARCH_PARAM_KEYS):
		raise SearchUrlParseError("URL 中没有可用的搜索参数")
	return ParsedSearchUrl(query=query, params=params, page=page)


def _split_multi_value(value: str) -> list[str]:
	return [part.strip() for part in value.split(",") if part.strip()]


def resolve_lookup_codes(value: str | None, lookup: dict[str, str], label: str) -> str | None:
	"""Resolve comma-separated display labels or raw numeric codes into API codes."""
	if not value:
		return None
	codes: list[str] = []
	for part in _split_multi_value(value):
		if part.isdigit():
			codes.append(part)
			continue
		code = lookup.get(part)
		if code is None:
			raise ValueError(f"未知{label}: {part}")
		codes.append(code)
	return ",".join(codes) if codes else None


def resolve_search_code_params(
	*,
	salary: str | None = None,
	experience: str | None = None,
	education: str | None = None,
	industry: str | None = None,
	scale: str | None = None,
	stage: str | None = None,
	job_type: str | None = None,
) -> dict[str, str]:
	"""Resolve user-facing search filters into BOSS API parameter codes."""
	params: dict[str, str] = {}
	if code := resolve_lookup_codes(salary, endpoints.SALARY_CODES, "薪资范围"):
		params["salary"] = code
	if code := resolve_lookup_codes(experience, endpoints.EXPERIENCE_CODES, "经验要求"):
		params["experience"] = code
	if code := resolve_lookup_codes(education, endpoints.EDUCATION_CODES, "学历要求"):
		params["degree"] = code
	if code := resolve_lookup_codes(industry, endpoints.INDUSTRY_CODES, "行业类型"):
		params["industry"] = code
	if code := resolve_lookup_codes(scale, endpoints.SCALE_CODES, "公司规模"):
		params["scale"] = code
	if code := resolve_lookup_codes(stage, endpoints.STAGE_CODES, "融资阶段"):
		params["stage"] = code
	if code := resolve_lookup_codes(job_type, endpoints.JOB_TYPE_CODES, "职位类型"):
		params["jobType"] = code
	return params

# ── Salary parsing ──────────────────────────────────────────────────

_SALARY_RE = re.compile(r"(\d+)(?:\s*[-~]\s*(\d+))?\s*K", re.IGNORECASE)
_SALARY_BELOW_RE = re.compile(r"(\d+)\s*K以下", re.IGNORECASE)


def parse_salary_range(value: str) -> tuple[int, int] | None:
	"""Parse salary string like '20-50K' into (low, high) in K. Returns None if unparseable."""
	if not value or value == "面议":
		return None
	m = _SALARY_BELOW_RE.search(value)
	if m:
		return (0, int(m.group(1)))
	m = _SALARY_RE.search(value)
	if m:
		low = int(m.group(1))
		high = int(m.group(2)) if m.group(2) else low
		return (low, high)
	return None


# ── Threshold comparisons ───────────────────────────────────────────

def meets_experience_threshold(candidate: str, required: str | None) -> bool:
	"""Check if candidate experience meets or exceeds required threshold."""
	if required is None:
		return True
	c = _EXPERIENCE_ORDER.get(candidate)
	r = _EXPERIENCE_ORDER.get(required)
	if c is None:
		return True  # unknown experience passes
	if r is None:
		return True
	return c >= r


def meets_education_threshold(candidate: str, required: str | None) -> bool:
	"""Check if candidate education meets or exceeds required threshold."""
	if required is None:
		return True
	c = _EDUCATION_ORDER.get(candidate)
	r = _EDUCATION_ORDER.get(required)
	if c is None:
		return True  # unknown education passes
	if r is None:
		return True
	return c >= r


def education_in_range(value: str, min_label: str, max_label: str) -> bool:
	"""岗位学历要求是否落在用户设定的 [min, max] 区间。"""
	v = _EDUCATION_ORDER.get(value)
	lo = _EDUCATION_ORDER.get(min_label)
	hi = _EDUCATION_ORDER.get(max_label)
	if v is None:
		return True
	if lo is None or hi is None:
		return False
	return lo <= v <= hi


def experience_in_range(value: str, min_label: str, max_label: str) -> bool:
	"""岗位经验要求是否落在用户设定的 [min, max] 区间。"""
	v = _EXPERIENCE_ORDER.get(value)
	lo = _EXPERIENCE_ORDER.get(min_label)
	hi = _EXPERIENCE_ORDER.get(max_label)
	if v is None:
		return True
	if lo is None or hi is None:
		return False
	return lo <= v <= hi


def salary_overlaps_user_range(job_salary: str, min_k: str | int, max_k: str | int) -> bool:
	"""岗位薪资是否满足用户期望：高于期望上限仍算符合，仅最高薪低于用户最低期望时否决。"""
	item = parse_salary_range(job_salary)
	if not item:
		return True
	try:
		user_min = int(min_k)
	except (TypeError, ValueError):
		return False
	# 岗位最高薪 >= 用户最低期望即通过（薪资更高不否决）
	return item[1] >= user_min


# ── Data structures ─────────────────────────────────────────────────

@dataclass(frozen=True)
class SearchFilterCriteria:
	query: str
	city: str | None = None
	city_code: str | None = None
	district_code: str | None = None
	salary: str | None = None
	experience: str | None = None
	education: str | None = None
	industry: str | None = None
	scale: str | None = None
	stage: str | None = None
	job_type: str | None = None
	raw_params: dict[str, str] = field(default_factory=dict)


@dataclass
class SearchPipelineStats:
	pages_scanned: int = 0
	jobs_seen: int = 0
	jobs_prefiltered: int = 0
	detail_checks: int = 0
	jobs_matched: int = 0


@dataclass
class SearchPipelineResult:
	items: list[dict[str, Any]] = field(default_factory=list)
	has_more: bool = False
	total: int | None = None
	last_page: int = 0
	stats: SearchPipelineStats = field(default_factory=SearchPipelineStats)


class SearchPipelinePlatformError(Exception):
	def __init__(self, code: str | int, message: str, *, browser_lost: bool = False):
		self.code = code
		self.message = message
		self.browser_lost = browser_lost
		super().__init__(message)


# ── List-page prefilter ─────────────────────────────────────────────

def prefilter_job(raw_item: dict[str, Any], criteria: SearchFilterCriteria) -> tuple[bool, list[str]]:
	"""Fast prefilter using list-page fields only. Returns (pass, rejection_reasons)."""
	reasons: list[str] = []

	# City filter
	if criteria.city:
		item_city = raw_item.get("cityName", "")
		if item_city and criteria.city not in item_city:
			reasons.append(f"城市不匹配: {item_city} != {criteria.city}")

	# Salary filter — reject only if candidate max is below required min
	if criteria.salary:
		req_range = parse_salary_range(criteria.salary)
		item_range = parse_salary_range(raw_item.get("salaryDesc", ""))
		if req_range and item_range:
			if item_range[1] < req_range[0]:
				reasons.append(f"薪资不足: {raw_item.get('salaryDesc', '')} < {criteria.salary}")

	# Education filter — user education must meet job requirement
	if criteria.education:
		item_edu = raw_item.get("jobDegree", "")
		if not meets_education_threshold(criteria.education, item_edu):
			reasons.append(f"学历不符: 岗位要求 {item_edu}，用户 {criteria.education}")

	# Experience filter — user experience tier must meet job requirement
	if criteria.experience:
		item_exp = raw_item.get("jobExperience", "")
		if not meets_experience_threshold(criteria.experience, item_exp):
			reasons.append(f"经验不符: 岗位要求 {item_exp}，用户 {criteria.experience}")

	return (len(reasons) == 0, reasons)


# ── Welfare matching ────────────────────────────────────────────────

def resolve_welfare_keywords(label: str) -> list[str]:
	"""Resolve a welfare label to matching keywords."""
	return WELFARE_KEYWORDS.get(label, [label])


def _check_welfare_in_text(keywords: list[str], text: str) -> bool:
	return any(kw in text for kw in keywords)


def match_all_welfare(
	conditions: list[tuple[str, list[str]]],
	welfare_list: list[str],
	description: str,
) -> list[str]:
	"""Check all welfare conditions (AND). Returns match descriptions or empty list."""
	text = " ".join(welfare_list)
	full_text = text + " " + description
	results = []
	for label, keywords in conditions:
		if _check_welfare_in_text(keywords, text):
			results.append(f"{label}(标签)")
		elif description and _check_welfare_in_text(keywords, full_text):
			results.append(f"{label}(描述)")
		else:
			return []
	return results


def _fetch_and_check(client: Any, welfare_conditions: list[tuple[str, list[str]]], raw_item: dict[str, Any]) -> dict[str, Any] | None:
	"""Single job: fetch detail + welfare match. 不访问 cache（线程安全）。"""
	welfare_list = raw_item.get("welfareList", [])
	try:
		card_raw = client.job_card(
			raw_item.get("securityId", ""),
			raw_item.get("lid", ""),
		)
		if not client.is_success(card_raw):
			code, message = client.parse_error(card_raw)
			raise SearchPipelinePlatformError(code, message or "职位详情获取失败")
		desc = card_raw.get("zpData", {}).get("jobCard", {}).get("postDescription", "")
	except NotImplementedError:
		raise SearchPipelinePlatformError(
			"NOT_SUPPORTED",
			"当前平台暂不支持福利详情筛选，请去掉 --welfare 后重试",
		)
	except (OSError, KeyError, TypeError):
		desc = ""

	match_results = match_all_welfare(welfare_conditions, welfare_list, desc)
	if match_results:
		item = JobItem.from_api(raw_item)
		d = item.to_dict()
		d["welfare_match"] = "✅ " + ", ".join(match_results)
		return d
	return None


def _check_details_parallel(
	client: Any,
	cache: Any,
	logger: Any,
	welfare_conditions: list[tuple[str, list[str]]],
	items: list[dict[str, Any]],
	matched: list[dict[str, Any]],
) -> None:
	"""Parallel detail check, append matched to list. cache 操作在主线程完成。"""
	with ThreadPoolExecutor(max_workers=_WELFARE_WORKERS) as pool:
		futures = {
			pool.submit(_fetch_and_check, client, welfare_conditions, raw_item): raw_item
			for raw_item in items
		}
		for future in as_completed(futures):
			raw_item = futures[future]
			company = raw_item.get("brandName", "")
			title = raw_item.get("jobName", "")
			try:
				result = future.result()
				if result:
					# is_greeted 在主线程中安全访问 cache
					sid = result.get("security_id", "")
					if sid:
						result["greeted"] = cache.is_greeted(sid)
					matched.append(result)
					logger.info(f"  ✅ {company} - {title}（详情匹配）")
				else:
					logger.info(f"  ❌ {company} - {title}")
			except SearchPipelinePlatformError:
				logger.info(f"  ❌ {company} - {title}（详情接口失败）")
				raise
			except Exception:
				logger.info(f"  ❌ {company} - {title}（查询失败）")


# ── Main pipeline ───────────────────────────────────────────────────

def build_search_request_filters(criteria: SearchFilterCriteria, page: int) -> dict[str, Any]:
	search_filters: dict[str, Any] = {
		"city": criteria.city,
		"city_code": criteria.city_code,
		"district_code": criteria.district_code,
		"salary": criteria.salary,
		"experience": criteria.experience,
		"education": criteria.education,
		"industry": criteria.industry,
		"scale": criteria.scale,
		"stage": criteria.stage,
		"job_type": criteria.job_type,
		"page": page,
	}
	if criteria.raw_params:
		search_filters["raw_params"] = criteria.raw_params
	return search_filters


def fetch_search_page_raw(
	platform: Any,
	criteria: SearchFilterCriteria,
	page: int,
	logger: Any | None = None,
) -> dict[str, Any]:
	"""仅向 BOSS 拉取列表页（无 cache 访问，可在浏览器线程执行）。"""
	if logger is not None:
		logger.info(f"正在搜索第 {page} 页...")
	raw = platform.search_jobs(
		criteria.query,
		**build_search_request_filters(criteria, page),
	)
	if raw.get("browser_lost"):
		raise SearchPipelinePlatformError(
			raw.get("code", -2),
			str(raw.get("message") or "自动化 Chromium 已断开"),
			browser_lost=True,
		)
	if not platform.is_success(raw):
		code, message = platform.parse_error(raw)
		raise SearchPipelinePlatformError(code, message or "搜索结果获取失败")
	return raw


def process_search_page_result(
	client: Any,
	cache: Any,
	logger: Any,
	criteria: SearchFilterCriteria,
	raw: dict[str, Any],
	page: int,
	*,
	welfare_conditions: list[tuple[str, list[str]]] | None = None,
	skip_greeted: bool = False,
) -> SearchPipelineResult:
	"""处理单页列表结果（含 cache，须在打开 cache 的同一线程执行）。"""
	stats = SearchPipelineStats()
	matched: list[dict[str, Any]] = []
	zp_data = raw.get("zpData", {})
	job_list = zp_data.get("jobList", [])
	stats.pages_scanned = 1
	stats.jobs_seen = len(job_list)
	has_more = bool(zp_data.get("hasMore", False))

	if not job_list:
		return SearchPipelineResult(
			items=matched,
			has_more=has_more,
			total=0,
			last_page=page,
			stats=stats,
		)

	survivors = []
	for raw_item in job_list:
		ok, reasons = prefilter_job(raw_item, criteria)
		if not ok:
			stats.jobs_prefiltered += 1
			logger.info(f"  预筛排除: {raw_item.get('jobName', '')} ({', '.join(reasons)})")
			continue
		survivors.append(raw_item)

	if welfare_conditions:
		need_detail = []
		for raw_item in survivors:
			welfare_list = raw_item.get("welfareList", [])
			match_results = match_all_welfare(welfare_conditions, welfare_list, "")
			if match_results:
				item = JobItem.from_api(raw_item)
				item.greeted = cache.is_greeted(item.security_id)
				if skip_greeted and item.greeted:
					continue
				d = item.to_dict()
				d["welfare_match"] = "✅ " + ", ".join(match_results)
				matched.append(d)
				stats.jobs_matched += 1
				logger.info(f"  ✅ {item.company} - {item.title}（标签匹配）")
			else:
				need_detail.append(raw_item)

		if need_detail:
			logger.info(f"  标签未命中 {len(need_detail)} 个，并行查详情...")
			before = len(matched)
			_check_details_parallel(client, cache, logger, welfare_conditions, need_detail, matched)
			stats.detail_checks += len(need_detail)
			stats.jobs_matched += len(matched) - before

		if skip_greeted:
			matched = [m for m in matched if not m.get("greeted", False)]
	else:
		for raw_item in survivors:
			item = JobItem.from_api(raw_item)
			item.greeted = cache.is_greeted(item.security_id)
			if skip_greeted and item.greeted:
				continue
			matched.append(item.to_dict())
			stats.jobs_matched += 1

	return SearchPipelineResult(
		items=matched,
		has_more=has_more,
		total=len(matched),
		last_page=page,
		stats=stats,
	)


def run_search_pipeline(
	client: Any,
	cache: Any,
	logger: Any,
	*,
	criteria: SearchFilterCriteria,
	start_page: int = 1,
	max_pages: int = 1,
	limit: int | None = None,
	welfare_conditions: list[tuple[str, list[str]]] | None = None,
	skip_greeted: bool = False,
) -> SearchPipelineResult:
	"""Run the full search pipeline: API search → list prefilter → welfare detail fallback."""
	stats = SearchPipelineStats()
	matched: list[dict[str, Any]] = []
	current_page = start_page
	last_page_scanned = 0
	has_more = False

	for _ in range(max_pages):
		if limit and len(matched) >= limit:
			break

		logger.info(f"正在搜索第 {current_page} 页...")
		raw = fetch_search_page_raw(client, criteria, current_page)
		page_result = process_search_page_result(
			client, cache, logger, criteria, raw, current_page,
			welfare_conditions=welfare_conditions,
			skip_greeted=skip_greeted,
		)
		stats.pages_scanned += page_result.stats.pages_scanned
		stats.jobs_seen += page_result.stats.jobs_seen
		stats.jobs_prefiltered += page_result.stats.jobs_prefiltered
		stats.jobs_matched += page_result.stats.jobs_matched
		stats.detail_checks += page_result.stats.detail_checks
		matched.extend(page_result.items)
		last_page_scanned = current_page
		has_more = page_result.has_more

		if not raw.get("zpData", {}).get("jobList"):
			break

		if not has_more:
			break
		if limit and len(matched) >= limit:
			break
		current_page += 1

	if limit:
		matched = matched[:limit]

	return SearchPipelineResult(
		items=matched,
		has_more=has_more,
		total=len(matched),
		last_page=last_page_scanned,
		stats=stats,
	)
