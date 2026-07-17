"""User Profile Intelligence System — Prompt 模板。"""

RESUME_PARSE_PROMPT = """你是资深 HR 与技术招聘专家。请深度解析以下简历，不仅提取关键词，还要推断候选人的真实能力与职业倾向。

## 简历
{resume_text}

## 输出 JSON（只返回 JSON）
{{
  "skills": ["技能1", "技能2"],
  "projects": [{{"name": "项目名", "role": "角色", "highlights": ["亮点"]}}],
  "years_of_experience": 3.5,
  "industries": ["互联网", "游戏"],
  "tools": ["Go", "Python", "K8s"],
  "education": "本科",
  "school_name": "XX大学",
  "school_tier": "二本",
  "school_tier_code": 3,
  "school_tier_reason": "普通公办二本院校",
  "gender": "男",
  "age": 26,
  "city": "广州",
  "languages": ["中文", "英语"],
  "summary": "一句话能力总结",
  "real_capabilities": ["真实能力1", "真实能力2"]
}}"""

INTERVIEW_NEXT_QUESTION_PROMPT = """你是资深职业顾问，正在与用户进行一对一聊天式画像访谈（已问 {questions_asked}/{max_questions} 题）。

你的任务不是念固定问卷，而是**先思考、再提问**：根据简历与对话，判断此刻最值得澄清的一件事。

## 已解析简历（结构化）
{parsed_resume_json}

## 对话记录
{transcript}

## 思考框架（必须在 reasoning 字段体现，2-5 句中文）
1. **已知**：从简历和对话中已能确定的关键信息
2. **盲区**：仍不清楚、但对判断「什么工作真正适合用户」至关重要的点
3. **策略**：为什么现在问这个问题（可追问上轮模糊/矛盾的回答，或深挖简历暗示但未确认的方向）
4. **结束判断**：仅当核心维度已覆盖且继续追问收益很低时设 done=true（至少已问 5 题后再考虑结束）

## 可参考的画像维度（按需选用，禁止机械逐条遍历）
- 真实职业倾向（技术/产品/运营/业务）
- 薪资 vs 成长 vs 平衡
- 工作强度与加班接受度
- 公司阶段偏好（大厂/成熟/初创）
- 销售或强商务属性岗位
- 远程 / hybrid
- AI 应用层 vs 底层
- 产品定义 vs 工程实现
- 转行或跨领域意愿
- 稳定性与风险偏好
- 求职阶段与紧迫度

## 输出 JSON
{{
  "reasoning": "你的内部分析",
  "topic": "英文话题标签，如 salary_vs_growth",
  "question": "你对用户说的下一句话（口语化、自然、一次只问一件事，不要编号或选项列表）",
  "done": false
}}

规则：
- 禁止重复已问过或用户已明确回答的内容
- 若用户上轮回答含糊，优先追问澄清
- 结合简历具体经历提问（如项目、技能、年限），不要泛泛而谈
- done=true 时 question 留空字符串
- 只返回 JSON，不要 markdown"""

INTERVIEW_EXTRACT_PREFERENCES_PROMPT = """根据以下画像访谈记录，提取用户偏好结构化 JSON。

## 简历摘要
{resume_summary}

## 访谈记录
{transcript}

## 输出 JSON
{{
  "role_preference": "技术/运营/产品/...",
  "salary_vs_growth": "salary/growth/balanced",
  "overtime_tolerance": "yes/no/occasional",
  "startup_fit": true,
  "sales_role_ok": false,
  "remote_ok": true,
  "ai_app_vs_core": "application/infrastructure/both",
  "product_vs_engineering": "product/engineering/balanced",
  "career_change_ok": false,
  "stability_priority": "high/medium/low",
  "job_seeking_stage": "exploring/active/urgent/passive",
  "risk_tolerance": "low/medium/high"
}}

只返回 JSON。"""

CAREER_INFERENCE_PROMPT = """你是职业规划师。结合简历解析与用户偏好，推理最适合的职业方向。

## 简历解析
{parsed_resume_json}

## 用户偏好
{preferences_json}

## 输出 JSON
{{
  "primary_direction": "主方向",
  "secondary_direction": "次方向",
  "avoid_direction": ["应避开的方向"],
  "risk_tolerance": "low/medium/high",
  "startup_fit": true,
  "remote_fit": true,
  "strengths": ["优势"],
  "gaps": ["短板"],
  "growth_paths": ["可成长方向"],
  "realistic_path": "当前阶段最现实的路径",
  "long_term_path": "3-5年长期路径"
}}

只返回 JSON。"""

ADAPTIVE_SCORE_PROMPT = """你是求职匹配专家。基于用户完整画像，对以下岗位做自适应评分（0-100）。

## 用户画像
{profile_json}

## 学习权重提示
{learning_hints}

## 岗位信息
{job_json}

## 输出 JSON
{{
  "score": 87,
  "reason": ["匹配原因1", "匹配原因2"],
  "risk": ["风险提示1"],
  "priority": "high/medium/low",
  "dimensions": {{
    "skill_match": 90,
    "industry_match": 80,
    "growth": 85,
    "salary": 70,
    "preference_fit": 88,
    "work_intensity": 60,
    "company_stage": 75,
    "city_match": 95,
    "career_goal": 90
  }}
}}

只返回 JSON。"""

ANALYSIS_SCORE_PROMPT = """你是资深职业顾问与尽职调查专家。侦察 AI 已按用户勾选的硬性条件初筛通过，请你做**深度分析**（0-100 分）。

## 用户意向城市（唯一城市参考）
{target_city}

## 禁止重复评估（侦察 AI 职责，勿写入 risk/reason）
- 薪资、学历、工作经验、加班、休息制度（单休/双休/大小周）、社保福利
- 城市/地区匹配、用户现居城市、通勤或搬迁成本
- 简历 parsed_resume 中已移除 city 字段，请勿推断现居地
- 禁止写「硬性条件已通过」「侦察已筛过」等侦察侧结论；低风险、财务稳健等正面表述写入 reason，不得写入 risk

## 仅评估以下维度
1. **与用户匹配度**：技能、职业方向、行业、偏好（销售/远程/AI 方向等）
2. **发展前景**：业务阶段、技术深度、成长空间、与用户长期目标契合
3. **隐形雷点**：皮包公司/外包派遣、公司信息缺失或隐瞒、JD 避重就轻、画大饼、过度承诺等

## 用户画像（含 job_search_context）
{profile_json}

## 学习权重提示
{learning_hints}

## 岗位信息
{job_json}

## 输出 JSON
{{
  "score": 72,
  "reason": ["仅写匹配亮点与优势，每条一句正面表述"],
  "risk": ["劣势、技能/经验缺口、不确定性、需核实项，每条一句"],
  "priority": "high/medium/low",
  "dimensions": {{
    "skill_match": 85,
    "career_fit": 80,
    "growth_prospect": 70,
    "company_trust": 55,
    "jd_quality": 60,
    "preference_fit": 75
  }}
}}

禁止把劣势、缺口、不确定性写入 reason；例如「无相关经验」「缺乏XX技能」「存在技能差距」必须写入 risk。

reason 与 risk 的每条文案必须使用**简体中文**，禁止出现 medium/low/high 等英文等级词；不要复述候选人画像字段（如风险偏好）。

**reason 与 risk 的划分由你负责**：reason 仅放匹配亮点与优势（绿色展示）；risk 仅放劣势、缺口、不确定性（红色警告）。正面表述（如薪资有吸引力、财务风险较低、招聘者在线）必须写入 reason，不得写入 risk。

只返回 JSON。"""

REFINE_REASON_RISK_PROMPT = """你是岗位分析展示助手。请将下列评估片段**按语义**正确分为两类，供前端红绿分区展示：

- **reason（绿色·推荐理由）**：匹配亮点、优势、正面说明、机会点
- **risk（红色·风险提示）**：劣势、技能/经验缺口、不确定性、需警惕或需核实项

## 规则
1. 输入片段可能已误标在 reason 或 risk 中，请重新归类，不要照抄错误分区
2. 混合句请拆成独立条目分别归类（如「经营风险较高，但五险一金齐全」→ risk 写风险部分，reason 写福利部分）
3. 禁止把正面表述放入 risk：薪资有吸引力/满足期望、财务风险较低、招聘者在线、福利保障等
4. 禁止把警示表述放入 reason：技能差距、经验不足、JD 堆叠、公司信息缺失等
5. 不要复述候选人画像字段；不要写侦察 AI 已负责的硬性条件（薪资学历经验城市等是否达标）
6. 每条一句简体中文，去重后各最多 6 条

## 职业阶段
{stage_label}

## 岗位摘要
{job_summary}

## 待归类片段
reason 候选：{reason_json}
risk 候选：{risk_json}

## 输出 JSON
{{
  "reason": ["..."],
  "risk": ["..."]
}}

只返回 JSON。"""

SECRETARY_PROFILE_ENRICH_PROMPT = """你是秘书 AI（MS），请从简历中提取求职画像基础字段，只输出 JSON：
{{
  "skills": ["技能栈"],
  "years_of_experience": 3.5,
  "expected_role": "期望岗位",
  "education": "最高学历，如本科/专科/硕士",
  "school_name": "毕业院校全称",
  "gender": "男/女/未知",
  "age": 26,
  "core_strengths": ["核心优势1", "核心优势2"],
  "summary": "一句话总结"
}}

规则：
- age 为整数或 null（简历无出生年份则 null）
- gender 无法判断时填「未知」
- school_name 填最高学历对应院校

简历：
{resume_text}"""

SECRETARY_SCHOOL_TIER_PROMPT = """你是秘书 AI（MS），请根据简历判断候选人**最高学历对应毕业院校**的真实层次，并写入求职画像。

## 简历摘录
{resume_text}

## 已知信息（可参考，以简历为准）
- 院校：{school_name}
- 学历：{education}

## 要求
1. 根据院校名称、办学性质、招生批次等**自行判断**层次，不要使用任何预设院校名单
2. school_tier 用中文标签，如：985 / 211/双一流 / 一本 / 二本 / 三本/民办本科 / 专科
3. school_tier_code：6=985，5=211/双一流，4=一本，3=二本，2=三本/民办，1=专科，0=无法判断
4. school_tier_reason 用 1-2 句说明判断依据（办学性质、批次、是否独立学院等）
5. 若简历未提及院校，school_tier_code 填 0

## 输出 JSON
{{
  "school_name": "广州商学院",
  "education": "本科",
  "school_tier": "三本/民办本科",
  "school_tier_code": 2,
  "school_tier_reason": "民办本科院校，原二本批次招生，非公办一本"
}}

只返回 JSON。"""

COMPANY_SCHOOL_FRIENDLINESS_PROMPT = """评估目标公司/岗位对候选人**已知院校层级**的友好程度。

## 候选人（院校层级已由秘书 AI 判定，请信任勿重新推断院校层次）
- 毕业院校：{school_name}
- 学历：{education}
- 院校层级：{school_tier}（tier={school_tier_code}，6=985，5=211，4=一本，3=二本，2=三本/民办，1=专科）
- 秘书判断依据：{school_tier_reason}

## 岗位
- 公司：{company}
- 职位：{job_title}
- 规模：{job_scale}
- 融资阶段：{job_stage}
- 岗位标注学历：{job_education}
- JD 摘要：{job_description}

## 要求
1. **仅判断**该公司/岗位对此院校层级是否友好、是否设隐性院校门槛
2. JD 仅写「本科」不代表无院校筛选；大厂/名企常有隐性要求
3. fit_level：high（对该层级友好/有先例）/ medium（可尝试）/ low（明显不友好）/ unknown（信息不足）
4. exclude：当该公司/岗位**几乎不考虑**该层级院校时为 true（如三本投华为核心研发岗），此时 fit_level=low，score_adjustment=-30～-35
5. score_adjustment：0 到 -35 的整数
6. reasons 写绿色亮点（若有），risks 写红色警示
7. 全部简体中文

## 输出 JSON
{{
  "fit_level": "low",
  "exclude": true,
  "score_adjustment": -32,
  "reasons": [],
  "risks": ["华为社招/校招通常不考虑三本/民办本科背景，简历关极难过"]
}}

只返回 JSON。"""

SCHOOL_COMPANY_FIT_PROMPT = COMPANY_SCHOOL_FRIENDLINESS_PROMPT

MEMORY_CONSOLIDATE_PROMPT = """将以下用户画像与近期反馈压缩为一段长期记忆摘要（200字内，中文），供后续评分参考。

## 当前画像
{profile_json}

## 近期反馈
{feedback_summary}

只返回纯文本摘要，不要 JSON。"""
