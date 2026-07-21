"""分析 AI 深度评分 — 匹配度、发展前景、隐形雷点（不含侦察 AI 硬性条件）。"""

from __future__ import annotations

import json
import re
from typing import Any

from pet_boss.agents.planners.analysis_review import maybe_review_borderline_score
from pet_boss.ai.service import AIService
from pet_boss.profile.adaptive_scoring import feedback_summary_for_prompt
from pet_boss.profile.models import AdaptiveScore, UserProfile
from pet_boss.profile.prompts import ANALYSIS_SCORE_PROMPT, REFINE_REASON_RISK_PROMPT
from pet_boss.profile.scout_learning import ai_memory_summary_for_prompt
from pet_boss.profile.store import ProfileStore
from pet_boss.rag.retriever import retrieve_analysis_rag_result
from pet_boss.rag.service import format_rag_context_from_references
from pet_boss.secretary.feedback import load_preference_instructions_text

DEFAULT_PASS_SCORE = 60

_SHELL_HINTS = ("人力资源", "外包", "劳务派遣", "人才服务", "企业管理咨询")
_OVERPROMISE = ("不限经验", "轻松月入", "急招", "当天入职", "包教包会", "无责底薪")

_SCOUT_SCOPE_RISK_RE = re.compile(
	r"现居|通勤|搬迁|"
	r"城市.{0,6}(不符|不匹配|冲突|差异)|"
	r"地区.{0,4}(不符|不匹配)|"
	r"岗位地点|意向城市.{0,6}(不符|不匹配)|"
	r"薪资.{0,8}(不符|偏低|不足|不满足|不在)|"
	r"薪资.{0,30}(中等|偏高|水平|可满足|满足)|"
	r"满足.{0,12}期望|"
	r"属于.{0,12}中等|"
	r"可满足基本需求|"
	r"招聘者在线|沟通效率|"
	r"学历.{0,8}(不符|不足|不满足|不在)|"
	r"经验.{0,8}(不符|不足|不满足|不在)|"
	r"(加班|双休|单休|大小周|五险一金|社保).{0,6}(不符|不足|缺失|不满足)",
)

# 候选人画像复述 / 非岗位风险，不应出现在分析展示区
_PROFILE_ECHO_RISK_RE = re.compile(
	r"候选人.{0,20}(偏好|风险)|"
	r"用户.{0,20}(偏好|风险)|"
	r"risk_preference|risk_tolerance|"
	r"偏好为.{0,8}(低|中等|高|medium|low|high)|"
	r"能接受一定风险",
	re.I,
)

_LEVEL_ZH = {
	"low": "低",
	"medium": "中等",
	"high": "高",
}

# 侦察 AI 职责范围内的「已通过」说明，分析侧无需重复展示
_SCOUT_SCOPE_PASS_RE = re.compile(
	r"硬性条件.{0,20}通过|硬条件.{0,12}通过|"
	r"岗位.{0,8}硬性条件|条件.{0,8}全部通过|"
	r"初筛.{0,8}通过|侦察.{0,20}已?.{0,12}通过|"
	r"学历、经验、薪资.{0,8}等.{0,6}通过|"
	r"薪资、学历、经验.{0,8}等.{0,6}通过",
	re.I,
)


def _job_summary_for_refine(job: dict[str, Any] | None) -> str:
	if not job:
		return "（无）"
	parts = [
		str(job.get("title") or job.get("jobName") or ""),
		str(job.get("company") or job.get("brandName") or ""),
		str(job.get("salary") or job.get("salaryDesc") or ""),
		str(job.get("city") or job.get("cityName") or ""),
	]
	text = " · ".join(p for p in parts if p)
	return text[:400] if text else "（无）"


def _parse_ai_json_object(raw: str) -> dict[str, Any]:
	text = raw.strip()
	if text.startswith("```"):
		text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```")).strip()
	return json.loads(text)


def refine_reason_risk_with_ai(
	svc: AIService,
	*,
	reason: list[str],
	risk: list[str],
	job: dict[str, Any] | None = None,
	stage_label: str = "",
) -> tuple[list[str], list[str]]:
	"""由 AI 将候选片段归类为推荐理由（绿）与风险提示（红）。"""
	candidates = [str(x).strip() for x in reason + risk if str(x).strip()]
	if not candidates:
		return [], []
	prompt = REFINE_REASON_RISK_PROMPT.format(
		stage_label=stage_label or "未指定",
		job_summary=_job_summary_for_refine(job),
		reason_json=json.dumps(reason, ensure_ascii=False),
		risk_json=json.dumps(risk, ensure_ascii=False),
	)
	raw = svc.chat([
		{
			"role": "system",
			"content": (
				"你是分析 AI（FX）的展示归类助手。只输出 JSON。"
				"reason 为绿色推荐理由，risk 为红色风险提示，按语义划分，禁止照抄错误分区。"
			),
		},
		{"role": "user", "content": prompt},
	], agent="FX", temperature=0.2, max_tokens=800)
	data = _parse_ai_json_object(raw)
	out_reason = [str(x).strip() for x in (data.get("reason") or []) if str(x).strip()]
	out_risk = [str(x).strip() for x in (data.get("risk") or []) if str(x).strip()]
	return out_reason, out_risk


def localize_analysis_text(text: str) -> str:
	"""将分析文案中的英文等级词替换为中文。"""
	s = str(text or "").strip()
	if not s:
		return s
	for en, zh in _LEVEL_ZH.items():
		s = re.sub(rf"(?<![A-Za-z]){en}(?![A-Za-z])", zh, s, flags=re.I)
	s = s.replace("risk_preference", "风险偏好").replace("risk_tolerance", "风险承受度")
	return s


def localize_analysis_items(items: list[str]) -> list[str]:
	return [localize_analysis_text(x) for x in items if str(x).strip()]


def localize_profile_for_analysis(data: dict[str, Any]) -> dict[str, Any]:
	"""供 AI 使用的画像副本：枚举值中文化，减少英文复述。"""
	out = dict(data)
	prefs = out.get("preferences")
	if isinstance(prefs, dict):
		prefs = dict(prefs)
		for key in ("risk_tolerance", "stability_priority"):
			val = str(prefs.get(key) or "").lower()
			if val in _LEVEL_ZH:
				prefs[key] = _LEVEL_ZH[val]
		out["preferences"] = prefs
	career = out.get("career")
	if isinstance(career, dict):
		career = dict(career)
		for key in ("risk_tolerance",):
			val = str(career.get(key) or "").lower()
			if val in _LEVEL_ZH:
				career[key] = _LEVEL_ZH[val]
		out["career"] = career
	return out


def build_analysis_profile_payload(
	profile: UserProfile,
	*,
	target_city: str | None = None,
	store: ProfileStore | None = None,
) -> dict[str, Any]:
	"""供分析 AI 使用的画像：剔除现居城市，明确意向城市仅来自搜索选择。"""
	data = profile.to_dict()
	parsed = data.get("parsed_resume")
	if isinstance(parsed, dict):
		parsed = dict(parsed)
		parsed.pop("city", None)
		data["parsed_resume"] = parsed
	data = localize_profile_for_analysis(data)
	if store:
		portrait = store.load_secretary_portrait()
		if portrait:
			data["secretary_portrait"] = portrait.get("for_analysis") or portrait
		instr_text = load_preference_instructions_text(store)
		if instr_text and "暂无" not in instr_text:
			data["user_preference_instructions"] = instr_text
		memory_text = ai_memory_summary_for_prompt(store)
		if memory_text:
			data["ai_learned_memory"] = memory_text
	data["job_search_context"] = {
		"target_city": target_city or "不限",
		"scout_already_filtered": [
			"薪资", "学历", "工作经验", "加班", "休息制度", "社保福利", "意向城市",
		],
		"analysis_scope_note": (
			"侦察 AI 已按用户勾选的硬性条件初筛通过。"
			"分析 AI 禁止重复评估上述维度，禁止引用简历现居城市或通勤/搬迁成本。"
		),
	}
	return data


def filter_scout_scope_risks(risks: list[str]) -> list[str]:
	"""移除属于侦察 AI 职责或基于现居城市的风险提示，以及冗余的「硬条件已通过」说明。"""
	filtered: list[str] = []
	for item in risks:
		text = str(item).strip()
		if not text:
			continue
		if _SCOUT_SCOPE_RISK_RE.search(text):
			continue
		if _SCOUT_SCOPE_PASS_RE.search(text):
			continue
		if _PROFILE_ECHO_RISK_RE.search(text):
			continue
		filtered.append(text)
	return filtered


def normalize_analysis_labels(
	reason: list[str],
	risk: list[str],
) -> tuple[list[str], list[str]]:
	"""去重整理 reason / risk 列表（不做语义红绿划分）。"""
	kept_reasons = list(dict.fromkeys(str(x).strip() for x in reason if str(x).strip()))
	merged_risks = list(dict.fromkeys(str(x).strip() for x in risk if str(x).strip()))
	return kept_reasons, merged_risks


def sanitize_risk_lists(
	reason: list[str],
	risk: list[str],
	*,
	ai_service: AIService | None = None,
	job: dict[str, Any] | None = None,
	stage_label: str = "",
) -> tuple[list[str], list[str]]:
	"""规范化展示文案：去重、中文化、剔除侦察职责项；红绿分区交由 AI 判断。"""
	reason, risk = normalize_analysis_labels(reason, risk)
	if ai_service is not None and (reason or risk):
		try:
			reason, risk = refine_reason_risk_with_ai(
				ai_service,
				reason=reason,
				risk=risk,
				job=job,
				stage_label=stage_label,
			)
		except Exception:
			pass
	reason = localize_analysis_items(filter_scout_scope_risks(list(dict.fromkeys(reason))))
	risk = localize_analysis_items(filter_scout_scope_risks(list(dict.fromkeys(risk))))
	return reason, risk


def _text_blob(job: dict[str, Any]) -> str:
	parts = [
		job.get("title", ""),
		job.get("company", ""),
		job.get("description", "") or job.get("postDescription", ""),
		job.get("industry", ""),
		job.get("stage", ""),
		job.get("scale", ""),
		" ".join(job.get("skills") or []),
	]
	return " ".join(str(p) for p in parts).lower()


def score_job_analysis_heuristic(
	job: dict[str, Any],
	profile: UserProfile,
	*,
	store: ProfileStore | None = None,
	target_city: str | None = None,
) -> AdaptiveScore:
	"""启发式深度分析：匹配度 + 发展前景 + 雷点（不含城市/硬性条件）。"""
	blob = _text_blob(job)
	parsed = profile.parsed_resume
	career = profile.career
	prefs = profile.preferences
	reason: list[str] = []
	risk: list[str] = []
	dims: dict[str, int] = {}

	skills = (parsed.skills if parsed else []) + (parsed.tools if parsed else [])
	hits = sum(1 for s in skills if s.lower() in blob)
	dims["skill_match"] = min(100, 35 + hits * 15) if skills else 55
	if dims["skill_match"] >= 70:
		reason.append("技能与岗位描述较匹配")

	primary = career.primary_direction if career else ""
	if primary and any(k in blob for k in primary.lower().split() if len(k) > 1):
		dims["career_fit"] = 88
		reason.append(f"与职业方向「{primary}」一致")
	else:
		dims["career_fit"] = 52

	if career and career.avoid_direction:
		for avoid in career.avoid_direction:
			if avoid and avoid[:2].lower() in blob:
				risk.append(f"接近需避开的方向：{avoid}")
				dims["career_fit"] = max(0, dims["career_fit"] - 20)

	growth_score = 55
	if any(w in blob for w in ("ai", "agent", "增长", "0-1", "核心", "技术负责人")):
		growth_score += 20
		reason.append("岗位描述含成长/技术深度信号")
	stage = job.get("stage", "") or ""
	if "已上市" in stage or "不需要融资" in stage:
		growth_score += 5 if prefs and prefs.stability_priority == "high" else 0
	elif any(s in stage for s in ("B轮", "C轮", "A轮")):
		growth_score += 10
		reason.append("公司处于成长阶段")
	dims["growth_prospect"] = min(100, growth_score)

	company = (job.get("company") or "").strip()
	if not company or len(company) <= 2:
		risk.append("公司信息缺失或过简")
		dims["company_trust"] = 25
	elif any(h in company for h in _SHELL_HINTS):
		risk.append("公司名含外包/人力派遣特征，需核实实际用工")
		dims["company_trust"] = 35
	else:
		dims["company_trust"] = 75

	if not job.get("scale") and not job.get("stage"):
		risk.append("公司规模/融资阶段信息缺失")
		dims["company_trust"] = min(dims.get("company_trust", 60), 50)

	desc = job.get("description") or job.get("postDescription") or ""
	if len(desc) < 80:
		risk.append("JD 描述过短，可能避重就轻")
		dims["jd_quality"] = 40
	else:
		dims["jd_quality"] = 72

	if any(p in blob for p in _OVERPROMISE):
		risk.append("描述含画大饼/过度承诺用语")
		dims["jd_quality"] = min(dims.get("jd_quality", 50), 45)

	if prefs and prefs.sales_role_ok is False and any(w in blob for w in ("销售", "商务", "bd")):
		risk.append("岗位偏销售/商务属性")
		dims["preference_fit"] = 35
	else:
		dims["preference_fit"] = 70

	risk = filter_scout_scope_risks(risk)

	base = (
		dims.get("skill_match", 50) * 0.25
		+ dims.get("career_fit", 50) * 0.25
		+ dims.get("growth_prospect", 50) * 0.2
		+ dims.get("company_trust", 50) * 0.15
		+ dims.get("jd_quality", 50) * 0.1
		+ dims.get("preference_fit", 50) * 0.05
	)
	penalty = min(35, len(risk) * 8)
	score = int(max(0, min(100, base - penalty)))

	if not reason:
		reason.append("整体匹配度尚可，建议结合 JD 详情判断")
	if not risk:
		reason.append("未发现明显雷点")
	if target_city:
		reason.append(f"意向城市（侦察已筛）：{target_city}")

	reason, risk = sanitize_risk_lists(reason, risk)

	return AdaptiveScore(
		score=score,
		reason=reason,
		risk=risk,
		priority="high" if score >= 80 else ("medium" if score >= 60 else "low"),
		dimensions=dims,
	)


def score_job_analysis_with_ai(
	svc: AIService,
	job: dict[str, Any],
	profile: UserProfile,
	*,
	store: ProfileStore | None = None,
	target_city: str | None = None,
	enable_rag: bool = True,
) -> AdaptiveScore:
	learning_hints = feedback_summary_for_prompt(store) if store else ""
	profile_payload = build_analysis_profile_payload(
		profile, target_city=target_city, store=store,
	)
	pref = profile_payload.get("user_preference_instructions")
	if pref:
		learning_hints = f"{learning_hints}\n\n用户偏好指令（秘书 AI 整理）：\n{pref}"
	ai_mem = profile_payload.get("ai_learned_memory")
	if ai_mem:
		learning_hints = f"{learning_hints}\n\n{ai_mem}"
	rag_refs: list[Any] = []
	rag_meta: dict[str, Any] = {"enabled": False, "code": "rag_disabled_for_ablation"}
	if enable_rag:
		rag_bundle = retrieve_analysis_rag_result(store, svc, job, search_city=target_city or "")
		rag_refs = rag_bundle.get("references") or []
		rag_meta = rag_bundle.get("meta") or {}
		rag_ctx = format_rag_context_from_references(rag_refs)
		if rag_ctx:
			learning_hints = f"{learning_hints}\n\n{rag_ctx}"
	else:
		rag_meta = {
			"enabled": False,
			"code": "ablation_no_rag",
			"message": "消融对照：本次未注入向量 RAG 参考。",
			"hit_count": 0,
		}
	prompt = ANALYSIS_SCORE_PROMPT.format(
		profile_json=json.dumps(profile_payload, ensure_ascii=False),
		learning_hints=learning_hints,
		job_json=json.dumps(job, ensure_ascii=False),
		target_city=target_city or "不限",
	)
	raw = svc.chat([
		{
			"role": "system",
			"content": (
				"你是资深职业顾问与尽职调查专家。只输出 JSON。"
				"禁止评估侦察AI已负责的硬性条件，禁止引用用户现居城市或通勤搬迁。"
				"reason 与 risk 字段必须使用简体中文，禁止出现 medium/low/high 等英文等级词。"
				"reason 为绿色推荐理由，risk 为红色风险提示，你必须按语义正确划分。"
			),
		},
		{"role": "user", "content": prompt},
	], agent="FX")
	text = raw.strip()
	if text.startswith("```"):
		text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```")).strip()
	data = json.loads(text)
	reason, risk = sanitize_risk_lists(
		list(data.get("reason") or []),
		list(data.get("risk") or []),
		ai_service=svc,
		job=job,
	)
	return AdaptiveScore(
		score=int(data.get("score", 0)),
		reason=reason,
		risk=risk,
		priority=data.get("priority") or "medium",
		dimensions=dict(data.get("dimensions") or {}),
		rag_references=rag_refs,
		rag_meta=rag_meta,
	)


def score_job_analysis(
	job: dict[str, Any],
	profile: UserProfile,
	*,
	store: ProfileStore | None = None,
	ai_service: AIService | None = None,
	target_city: str | None = None,
	pass_score: int = DEFAULT_PASS_SCORE,
	enable_rag: bool = True,
	borderline_review: bool = True,
) -> AdaptiveScore:
	heuristic = score_job_analysis_heuristic(
		job, profile, store=store, target_city=target_city,
	)
	if ai_service is not None:
		try:
			ai_result = score_job_analysis_with_ai(
				ai_service, job, profile,
				store=store,
				target_city=target_city,
				enable_rag=enable_rag,
			)
			merged_risk = list(dict.fromkeys(ai_result.risk + heuristic.risk))
			reason, merged_risk = sanitize_risk_lists(
				ai_result.reason, merged_risk,
				ai_service=ai_service,
				job=job,
			)
			ai_result.reason = reason
			ai_result.risk = merged_risk
			if ai_result.score <= 0:
				ai_result.score = heuristic.score
			if borderline_review and enable_rag:
				ai_result = maybe_review_borderline_score(
					ai_service,
					ai_result,
					job,
					profile,
					store=store,
					pass_score=pass_score,
				)
			return ai_result
		except Exception:
			pass
	return heuristic


def enrich_job_with_analysis_score(
	job: dict[str, Any],
	profile: UserProfile,
	*,
	store: ProfileStore | None = None,
	ai_service: AIService | None = None,
	target_city: str | None = None,
	pass_score: int = DEFAULT_PASS_SCORE,
) -> dict[str, Any]:
	adaptive = score_job_analysis(
		job, profile, store=store, ai_service=ai_service,
		target_city=target_city, pass_score=pass_score,
	)
	enriched = {
		**job,
		"analysis_score": adaptive.score,
		"analysis_reason": adaptive.reason,
		"analysis_risk": adaptive.risk,
		"analysis_priority": adaptive.priority,
		"analysis_dimensions": adaptive.dimensions,
		"rag_references": adaptive.rag_references,
		"rag_meta": adaptive.rag_meta,
		"analysis_review_plan": adaptive.review_plan,
		"profile_score": adaptive.score,
		"profile_reason": adaptive.reason,
		"profile_risk": adaptive.risk,
		"profile_priority": adaptive.priority,
		"profile_dimensions": adaptive.dimensions,
		"match_score": adaptive.score,
		"match_reasons": adaptive.reason,
	}
	from pet_boss.agents.school_company_fit import apply_school_company_fit_to_enriched

	return apply_school_company_fit_to_enriched(
		job, profile, enriched, ai_service=ai_service,
	)
