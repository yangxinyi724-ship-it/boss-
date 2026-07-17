/** 办公室桌面宠物 — 主界面：搜岗、各 AI 工位、资料柜 */

const PET_BASE = "/static/pet";
/** 素材版本号，来自 desks.json，用于避免浏览器缓存旧 PNG/GIF */
let petAssetVersion = 1;
/** 服务端扫描的素材修改时间(ms)，key 为相对 pet/ 的路径 */
let petAssetMtimes = {};

function petAssetVersionFor(file) {
  const rel = String(file).replace(/^\/+/, "");
  if (petAssetMtimes[rel] != null) return petAssetMtimes[rel];
  return petAssetVersion;
}

function petAssetUrl(file, extra = {}) {
  const params = new URLSearchParams({ v: String(petAssetVersionFor(file)) });
  for (const [key, value] of Object.entries(extra)) {
    if (value != null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `${PET_BASE}/${file}${qs ? `?${qs}` : ""}`;
}

/** 将 desks.json layout 字段应用到 DOM（数字默认 px，字符串原样如 50%） */
function applyPetBoxLayout(el, cfg) {
  if (!el || !cfg || typeof cfg !== "object") return;
  const set = (prop, val) => {
    if (val == null || val === "") return;
    el.style[prop] = typeof val === "number" ? `${val}px` : String(val);
  };
  set("left", cfg.x ?? cfg.left);
  set("top", cfg.y ?? cfg.top);
  set("width", cfg.width);
  set("height", cfg.height);
  set("marginTop", cfg.marginTop);
  set("marginBottom", cfg.marginBottom);
  set("marginLeft", cfg.marginLeft);
  set("marginRight", cfg.marginRight);
  set("fontSize", cfg.fontSize);
  set("color", cfg.color);
  set("alignSelf", cfg.alignSelf);
  set("letterSpacing", cfg.letterSpacing);
  if (cfg.transform) el.style.transform = cfg.transform;
  if (cfg.flex != null) el.style.flex = String(cfg.flex);
  if (cfg.gap != null) {
    el.style.gap = typeof cfg.gap === "number" ? `${cfg.gap}px` : String(cfg.gap);
  }
  if (cfg.alignItems) el.style.alignItems = cfg.alignItems;
  if (cfg.hidden === true) el.hidden = true;
}

function bindPetImageScale(img, scale) {
  if (!img || scale == null || scale === 1) return;
  const apply = () => {
    if (!img.naturalWidth) return;
    img.style.width = `${Math.round(img.naturalWidth * scale)}px`;
    img.style.height = `${Math.round(img.naturalHeight * scale)}px`;
  };
  if (img.complete && img.naturalWidth) apply();
  else img.addEventListener("load", apply, { once: true });
}

const CLIP_LABELS = {
  sit: "坐",
  work: "工作",
  walk: "走路",
  run: "跑步",
  stroll: "溜达",
  eat: "吃东西",
  drink: "喝水",
  sleepShort: "短休息",
  sleepLong: "长休息",
  report: "整理日报",
};

let petConfig = null;
/** @type {Record<string, PetAgent>} */
const agents = {};
/** @type {PetBowls | null} */
let petBowls = null;
/** @type {PetResumeDesk | null} */
let petResumeDesk = null;
/** @type {PetDeskPlates | null} */
let petDeskPlates = null;
/** @type {PetDocumentCabinet | null} */
let petDocumentCabinet = null;
/** @type {PetArchiveManager | null} */
let petArchiveManager = null;
/** @type {PetMonitorSidebar | null} */
let petMonitorSidebar = null;
const PET_PASS_SCORE_KEY = "boss-pet-pass-score";
const SCORE_STORAGE_KEY = "boss_agent_score_prefs";

const REJECT_REASON_TAGS = [
  "薪资不符",
  "通勤太远",
  "公司口碑",
  "技术栈不匹配",
  "工作强度",
  "外包/派遣",
  "行业不符",
  "成长空间",
  "其他",
];

const RAG_STATUS_LABELS = {
  passed: "通过",
  filtered: "筛掉",
  user_rejected: "用户拒绝",
  analysis: "历史分析",
  reject: "用户拒绝",
};

const LEARNING_DIMENSION_LABELS = {
  skill_match: "技能匹配",
  industry_match: "行业匹配",
  growth: "成长空间",
  salary: "薪资",
  preference_fit: "偏好契合",
  work_intensity: "工作强度",
  company_stage: "公司阶段",
  city_match: "城市匹配",
  career_goal: "职业目标",
};
const PET_SCOUT_QUERY_KEY = "pet_scout_query_prefs";
const FALLBACK_CITIES = [
  "北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "苏州",
  "长沙", "郑州", "重庆", "天津", "合肥", "厦门", "济南", "青岛", "大连", "宁波",
  "福州", "东莞", "中山", "珠海", "佛山", "昆明", "贵阳", "太原", "南昌", "南宁", "石家庄",
  "哈尔滨", "长春", "沈阳", "海口", "兰州", "乌鲁木齐", "无锡", "常州", "温州", "惠州",
];
const SCOUT_FILTER_KEYS = ["salary", "education", "experience", "overtime", "weekend", "insurance"];
const SCOUT_FILTER_LABELS = {
  salary: "薪资",
  education: "学历",
  experience: "经验",
  overtime: "加班",
  weekend: "休息",
  insurance: "社保",
};
const EDUCATION_OPTIONS = ["初中及以下", "中专/中技", "高中", "大专", "本科", "硕士", "博士"];
const EXPERIENCE_OPTIONS = ["应届", "1年以内", "1-3年", "3-5年", "5-10年", "10年以上"];
const WEEKEND_OPTIONS = ["单休", "双休", "大小周"];
const INSURANCE_OPTIONS = ["五险一金", "有社保"];
const CAREER_STAGE_OPTIONS = [
  { id: "junior", label: "初级", hint: "培养新人" },
  { id: "intermediate", label: "进阶", hint: "深度成长" },
  { id: "expert", label: "专家", hint: "影响力" },
];
/** @type {Map<string, string>} slotKey -> agentId */
const restSlotOccupancy = new Map();
/** @type {Map<string, string>} interactableId -> agentId */
const interactableOccupancy = new Map();
let officeResting = false;
/** @type {ReturnType<typeof setTimeout> | null} */
let officeRestClearTimer = null;
let jkAlert = false;
let scheduleOffHours = false;
/** 当前已进入的工作时段键（用于每个时段自动开搜岗） */
let lastWorkPeriodKey = null;
let scheduleCheckTimer = null;
/** 防止下班/上班切换回调重叠执行 */
let workScheduleTransitionToken = 0;
/** @type {AbortController | null} */
let petScoutAbortController = null;
let petScoutAckTimer = null;
let petScoutAckWorker = null;
let petScoutAckWorkerUrl = null;
let petScoutAckPending = false;
let petScoutVisibilityWired = false;
let petLocalScouting = false;
/** 用户点击停止后禁止自动重连 SSE */
let petScoutStopRequested = false;
let petScoutOffHoursPaused = false;
let petScoutJobCount = 0;
/** 标题小字用的最新搜岗统计（扫描/通过等） */
let petScoutHeaderStats = null;
/** @type {string[] | null} */
let petCitiesCache = null;
let petRegionsCache = null;
/** @type {object[]} */
const petScoutEventQueue = [];
let petScoutEventDrainScheduled = false;
const PET_SCOUT_UI_CATCHUP_THRESHOLD = 48;
const PET_SCOUT_UI_DRAIN_BATCH = 16;
const PET_SCOUT_UI_CATCHUP_BATCH = 64;
/** catch-up 时仍须走 handleEvent 的状态/监控事件（否则页码、监控状态会卡住） */
const PET_SCOUT_ALWAYS_HANDLE_EVENTS = new Set([
  "start",
  "stopped",
  "done",
  "page_start",
  "search_fetch",
  "search_progress",
  "page_done",
  "page_turn",
  "page_empty",
  "round_start",
  "scout_strategy_plan",
  "round_resume",
  "round_done",
  "round_pause",
  "round_fatigue_pause",
  "page_hidden_pause",
  "page_hidden_continue",
  "page_visible_resume",
  "scout_ack_warn",
  "scout_query_switch",
  "scout_list_exhausted",
  "scout_query_cooldown",
  "scout_heartbeat",
  "browser_restart_begin",
  "browser_restart_failed",
  "browser_session_lost",
  "browser_stuck",
  "browser_restarted",
  "monitor_start",
  "monitor_ok",
  "monitor_alert",
  "monitor_stall",
  "monitor_recovered",
  "monitor_browser_restart",
  "monitor_browser_open",
  "monitor_probe",
  "monitor_stopped",
  "job_passed",
  "job_filtered",
]);
const PET_SCOUT_HIGH_FREQ_EVENTS = new Set([
  "scout_seen",
  "scout_glance",
  "scout_browse_skip",
  "scout_history_skip",
  "scout_filter",
  "scout_skip",
  "scout_duplicate",
  "search_progress",
  "monitor_ok",
  "monitor_token",
  "scout_heartbeat",
]);
/** 不写入「最新进展」的技术/碎事件（页码与岗位仍走其它字段） */
const PET_SCOUT_PROGRESS_SKIP_TYPES = new Set([
  "scout_ack_warn",
  "scout_heartbeat",
  "monitor_ok",
  "monitor_token",
  "page_hidden_continue",
  "page_visible_resume",
  "search_progress",
]);

function parseScheduleMinutes(value) {
  if (typeof value !== "string") return null;
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
  return hour * 60 + minute;
}

function getScheduleClock(now = new Date()) {
  return now.getHours() * 60 + now.getMinutes();
}

function getCurrentWorkPeriodKey(now = new Date()) {
  const periods = petConfig?.workSchedule?.periods;
  if (!Array.isArray(periods) || !periods.length) return "always";
  const mins = getScheduleClock(now);
  for (let i = 0; i < periods.length; i++) {
    const period = periods[i];
    const start = parseScheduleMinutes(period?.start);
    const end = parseScheduleMinutes(period?.end);
    if (start == null || end == null || start === end) continue;
    let inPeriod = false;
    if (start < end) inPeriod = mins >= start && mins < end;
    else inPeriod = mins >= start || mins < end;
    if (inPeriod) return `${i}:${period.start}-${period.end}`;
  }
  return null;
}

function onWorkPeriodStarted(periodKey) {
  if (!periodKey || petConfig?.workSchedule?.autoStartScout === false) return;
  setScoutUserStopped(false);
  setScoutAutoRun(true);
  if (scheduleOffHours) {
    endOffHoursMode();
    return;
  }
  tryAutoStartScout();
}

function isWithinWorkSchedule(now = new Date()) {
  const periods = petConfig?.workSchedule?.periods;
  if (!Array.isArray(periods) || !periods.length) return true;
  const mins = getScheduleClock(now);
  for (const period of periods) {
    const start = parseScheduleMinutes(period?.start);
    const end = parseScheduleMinutes(period?.end);
    if (start == null || end == null || start === end) continue;
    if (start < end) {
      if (mins >= start && mins < end) return true;
    } else if (mins >= start || mins < end) {
      return true;
    }
  }
  return false;
}

function shouldApplyWorkClips() {
  return !scheduleOffHours && !officeResting;
}

function isScoutWorkPaused() {
  return scheduleOffHours || petScoutOffHoursPaused;
}

const SCOUT_WORK_EVENT_TYPES = new Set([
  "start",
  "page_start",
  "search_fetch",
  "scout_seen",
  "scout_glance",
  "scout_browse_skip",
  "scout_history_skip",
  "scout_filter",
  "scout_skip",
  "scout_duplicate",
  "scout_transmit",
  "analysis_start",
  "job_passed",
  "job_filtered",
  "round_start",
  "round_resume",
  "round_home_refresh",
  "round_early_stop",
  "page_done",
  "page_empty",
  "scout_list_exhausted",
  "scout_query_cooldown",
  "scout_query_skip_cooldown",
  "scout_query_switch",
  "scout_query_strategy",
]);

/** 状态关键事件：休息/下班期间也必须处理（如恢复搜岗、写入通过岗位） */
const SCOUT_STATE_EVENT_TYPES = new Set([
  "start",
  "stopped",
  "done",
  "job_passed",
  "job_filtered",
  "round_start",
  "round_resume",
  "round_home_refresh",
  "round_pause",
  "round_fatigue_pause",
  "round_done",
  "page_start",
  "search_fetch",
  "search_progress",
  "page_done",
  "page_turn",
  "off_hours_pause",
  "work_hours_resume",
  "scout_heartbeat",
  "scout_query_switch",
  "scout_query_depth",
  "scout_query_depth_progress",
  "scout_query_depth_met",
  "scout_query_cooldown",
  "scout_query_skip_cooldown",
  "browser_restart_begin",
  "browser_restart_failed",
  "browser_session_lost",
]);

function shouldSkipScoutWorkUi(type) {
  if (SCOUT_STATE_EVENT_TYPES.has(type)) return false;
  if (officeResting) return true;
  if (isScoutWorkPaused() && SCOUT_WORK_EVENT_TYPES.has(type)) return true;
  return false;
}

function formatWorkScheduleHint() {
  const periods = petConfig?.workSchedule?.periods;
  if (!Array.isArray(periods) || !periods.length) return "";
  return periods.map((p) => `${p.start}–${p.end}`).join("、");
}

function formatOffHoursStatus() {
  const hint = formatWorkScheduleHint();
  return hint
    ? `非工作时间 · AI 自由活动（${hint} 为工作时间）`
    : "非工作时间 · AI 自由活动";
}

function formatOffHoursScoutStatus() {
  const hint = formatWorkScheduleHint();
  const base = hint
    ? `非工作时间 · 搜岗已暂停（${hint} 上班后自动继续）`
    : "非工作时间 · 搜岗已暂停 · 上班后自动继续";
  return `${base} · 累计通过 ${petScoutJobCount} 个岗位`;
}

function shouldAutoRunScout() {
  try {
    return localStorage.getItem(PET_SCOUT_AUTO_RUN_KEY) === "1";
  } catch {
    return false;
  }
}

function setScoutAutoRun(enabled) {
  try {
    if (enabled) localStorage.setItem(PET_SCOUT_AUTO_RUN_KEY, "1");
    else localStorage.removeItem(PET_SCOUT_AUTO_RUN_KEY);
  } catch {
    /* ignore */
  }
}

function tryAutoResumeScout() {
  tryAutoStartScout();
}

function tryAutoStartScout() {
  if (petLocalScouting) return;
  if (!canAutoStartScoutNow()) return;
  void startPetScoutStream();
}

/** 页面加载时若后端任务仍在跑，只订阅不重新启动 */
async function tryResumeScoutSubscription() {
  if (petLocalScouting) return;
  try {
    const data = await syncScoutLiveFromServer();
    if (!data?.active) return;
    petLocalScouting = true;
    petScoutStopRequested = false;
    petScoutOffHoursPaused = false;
    startPetScoutAckPulse();
    petMonitorSidebar?.setStreamState("connecting");
    if (data.server_query || data.server_page) {
      petMonitorSidebar?.setSearchContext(
        data.server_query || "",
        data.server_page > 0 ? data.server_page : null,
      );
    }
    updatePetScoutControls(true);
    setAgentTask("ZC", "搜岗中");
    refreshPetHeaderScoutStats();
    void subscribePetScoutEvents({ resume: true });
  } catch {
    /* ignore */
  }
}

function getLastWorkPeriodEndMinutes() {
  const periods = petConfig?.workSchedule?.periods;
  if (!Array.isArray(periods) || !periods.length) return null;
  let maxEnd = 0;
  for (const period of periods) {
    const end = parseScheduleMinutes(period?.end);
    if (end != null && end > maxEnd) maxEnd = end;
  }
  return maxEnd || null;
}

function isPastWorkDayEnd(now = new Date()) {
  const lastEnd = getLastWorkPeriodEndMinutes();
  if (lastEnd == null) return false;
  return getScheduleClock(now) >= lastEnd;
}

const PET_DAILY_PICKS_SHOWN_KEY = "pet_daily_picks_shown_date";
const PET_DAILY_EMAIL_SENT_KEY = "pet_daily_email_sent_date";
const PET_SCOUT_AUTO_RUN_KEY = "pet_scout_auto_run";
const PET_SCOUT_USER_STOPPED_KEY = "pet_scout_user_stopped";

function shouldAutoStartScoutOnSchedule() {
  if (petConfig?.workSchedule?.autoStartScout === false) return false;
  const periods = petConfig?.workSchedule?.periods;
  return Array.isArray(periods) && periods.length > 0;
}

function isScoutUserStopped() {
  try {
    return localStorage.getItem(PET_SCOUT_USER_STOPPED_KEY) === "1";
  } catch {
    return false;
  }
}

function setScoutUserStopped(stopped) {
  try {
    if (stopped) localStorage.setItem(PET_SCOUT_USER_STOPPED_KEY, "1");
    else localStorage.removeItem(PET_SCOUT_USER_STOPPED_KEY);
  } catch {
    /* ignore */
  }
}

function canAutoStartScoutNow() {
  if (!isWithinWorkSchedule()) return false;
  if (isScoutUserStopped()) return false;
  if (shouldAutoRunScout()) return true;
  return shouldAutoStartScoutOnSchedule();
}

function maybeShowDailyPicksAtEndOfDay() {
  if (!isPastWorkDayEnd()) return;
  const today = new Date().toISOString().slice(0, 10);
  try {
    if (localStorage.getItem(PET_DAILY_PICKS_SHOWN_KEY) === today) return;
  } catch {
    /* ignore */
  }
  void (async () => {
    try {
      const data = await fetchDailyReport("today");
      if (!(data?.daily_picks?.length || data?.summary?.passed_count)) {
        try {
          localStorage.setItem(PET_DAILY_PICKS_SHOWN_KEY, today);
        } catch {
          /* ignore */
        }
        return;
      }
      await showDailyPicksModal("today", { auto: true });
    } catch {
      /* 自动弹层失败时静默，可手动从资料柜打开 */
    }
  })();
}

async function sendDailyReportEmail(date = "today") {
  const resp = await fetch("/api/secretary/send-daily-email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date }),
  });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "日报邮件发送失败");
  return body.data;
}

function maybeSendDailyReportEmailAtEndOfDay() {
  if (!isPastWorkDayEnd()) return;
  const today = new Date().toISOString().slice(0, 10);
  try {
    if (localStorage.getItem(PET_DAILY_EMAIL_SENT_KEY) === today) return;
  } catch {
    /* ignore */
  }
  void (async () => {
    try {
      const settings = await loadSecretarySettings();
      if (!settings.email_configured) return;

      const report = await fetchDailyReport("today");
      if (!(report?.daily_picks?.length || report?.summary?.passed_count)) {
        try {
          localStorage.setItem(PET_DAILY_EMAIL_SENT_KEY, today);
        } catch {
          /* ignore */
        }
        return;
      }

      if (shouldApplyWorkClips()) agents.MS?.setClip("work");
      setStatus("秘书 AI 正在发送今日日报邮件…");

      const result = await sendDailyReportEmail("today");
      try {
        localStorage.setItem(PET_DAILY_EMAIL_SENT_KEY, today);
      } catch {
        /* ignore */
      }

      if (shouldApplyWorkClips()) agents.MS?.setClip("sit");
      if (result?.sent) {
        const to = result.to || settings.recipient_email || "邮箱";
        setStatus(`今日日报已发送至 ${to} · 下班愉快`);
        agents.MS?.showHeadBubble("日报已发送", { durationMs: 4500 });
      }
      refreshIdleAgentTasks();
    } catch (err) {
      if (shouldApplyWorkClips()) agents.MS?.setClip("sit");
      setStatus(err?.message || "日报邮件发送失败");
      agents.MS?.showHeadBubble("发信失败", { durationMs: 4000 });
      refreshIdleAgentTasks();
    }
  })();
}

async function fetchDailyReport(date = "today") {
  const resp = await fetch(
    `/api/secretary/daily-report?date=${encodeURIComponent(date)}`,
    { cache: "no-store" },
  );
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "无法读取日报");
  return body.data;
}

async function fetchDailyPickDates() {
  const resp = await fetch("/api/secretary/daily-picks/dates?limit=120", { cache: "no-store" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "无法读取精选日期");
  return body.data;
}

async function parsePetApiResponse(resp, fallbackMsg) {
  const raw = await resp.text();
  let body;
  try {
    body = raw ? JSON.parse(raw) : {};
  } catch {
    if (resp.status === 405 || resp.status === 404) {
      throw new Error("候选池接口未就绪，请重启 boss web 服务后重试");
    }
    throw new Error(raw || `${fallbackMsg} (${resp.status})`);
  }
  if (!body?.ok) throw new Error(body?.error?.message || fallbackMsg);
  return body.data;
}

async function fetchShortlist() {
  const resp = await fetch("/api/boss/shortlist", { cache: "no-store" });
  return parsePetApiResponse(resp, "无法读取候选池");
}

async function fetchFilteredAnalysis() {
  const resp = await fetch("/api/boss/analysis/filtered?limit=200", { cache: "no-store" });
  return parsePetApiResponse(resp, "无法读取分析筛掉记录");
}

async function fetchDailyActionPlan(refresh = false) {
  const qs = refresh ? "?refresh=1" : "";
  const resp = await fetch(`/api/secretary/daily-action-plan${qs}`, { cache: "no-store" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "无法读取今日行动计划");
  return body.data;
}

async function fetchScoutStrategyPlan() {
  const resp = await fetch("/api/secretary/scout-strategy-plan", { cache: "no-store" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "无法读取侦察策略");
  return body.data;
}

async function removeShortlistItem(payload) {
  const resp = await fetch("/api/boss/shortlist/remove", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parsePetApiResponse(resp, "移出候选池失败");
}

function formatShortlistTime(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return "";
  try {
    return new Date(n * 1000).toLocaleString("zh-CN", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function formatShortlistContent(data) {
  const items = data?.items || [];
  if (!items.length) {
    return `
      <p class="pet-archive-hint">候选池暂无岗位。</p>
      <p class="pet-archive-hint">在「通过岗位」侧边栏点击「加入候选池」即可收藏。</p>
    `;
  }
  const rows = items.map((item, i) => {
    const added = formatShortlistTime(item.created_at);
    const sid = escHtml(item.security_id || "");
    const jid = escHtml(item.job_id || "");
    return `
      <article class="pet-daily-pick-card pet-shortlist-card" data-sid="${sid}" data-jid="${jid}">
        <div class="pet-daily-pick-rank">#${i + 1}</div>
        <div class="pet-daily-pick-body">
          <h3 class="pet-daily-pick-title">${escHtml(item.title || "岗位")}</h3>
          <p class="pet-daily-pick-meta">${escHtml(item.company || "")} · ${escHtml(item.salary || "-")} · ${escHtml(item.city || "-")}</p>
          ${added ? `<p class="pet-shortlist-added">加入于 ${escHtml(added)}</p>` : ""}
          <div class="pet-shortlist-actions">
            <button type="button" class="pet-archive-btn pet-shortlist-open" data-sid="${sid}" data-jid="${jid}">BOSS 查看</button>
            <button type="button" class="pet-archive-btn pet-shortlist-remove" data-sid="${sid}" data-jid="${jid}">移出候选池</button>
          </div>
        </div>
      </article>
    `;
  }).join("");
  return `
    <p class="pet-daily-picks-summary pet-shortlist-summary">共 ${items.length} 个岗位</p>
    <div class="pet-daily-picks-list pet-shortlist-list">${rows}</div>
  `;
}

function wireShortlistPanel(container) {
  container.querySelectorAll(".pet-shortlist-open").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const jobId = btn.dataset.jid || "";
      if (!jobId) return;
      btn.disabled = true;
      try {
        const data = await petOpenBossJob({
          job_id: jobId,
          security_id: btn.dataset.sid || "",
        });
        setStatus(data?.message || "已在登录态浏览器打开岗位");
      } catch (err) {
        setStatus(err?.message || "打开岗位失败");
      } finally {
        btn.disabled = false;
      }
    });
  });
  container.querySelectorAll(".pet-shortlist-remove").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const sid = btn.dataset.sid || "";
      const jid = btn.dataset.jid || "";
      if (!sid || !jid) return;
      btn.disabled = true;
      try {
        await removeShortlistItem({ security_id: sid, job_id: jid });
        setStatus("已移出候选池");
        await renderShortlistPanel(container);
      } catch (err) {
        setStatus(err?.message || "移出失败");
        btn.disabled = false;
      }
    });
  });
}

async function renderShortlistPanel(container) {
  container.innerHTML = `<p class="pet-archive-hint">加载候选池…</p>`;
  const data = await fetchShortlist();
  container.innerHTML = formatShortlistContent(data);
  wireShortlistPanel(container);
  petDocumentCabinet?.clearNew("shortlist");
}

function resolveAnalysisFilterReason(job, ev) {
  const explicit = String(ev?.filter_reason || job?.analysis_filter_reason || "").trim();
  if (explicit) return explicit;
  const fit = job?.school_company_fit || {};
  if (fit.exclude) {
    const risks = [...(job?.analysis_risk || []), ...(job?.profile_risk || [])].filter(Boolean);
    if (risks.length) return risks[0];
    return "院校层级与公司招聘偏好不匹配";
  }
  const risks = [...(job?.analysis_risk || []), ...(job?.profile_risk || [])].filter(Boolean);
  if (risks.length) return risks[0];
  const passScore = ev?.stats?.analysis?.pass_score;
  const score = ev?.score ?? job?.analysis_score ?? job?.profile_score;
  if (passScore != null && score != null) {
    return `综合得分 ${score} 分，低于通过线 ${passScore} 分`;
  }
  return "综合评分未达通过线";
}

function ragStatusLabel(status) {
  return RAG_STATUS_LABELS[status] || status || "历史";
}

function summarizeRagReferencesBrief(refs) {
  const items = Array.isArray(refs) ? refs : [];
  if (!items.length) return "";
  return `参考 ${items.length} 条`;
}

function formatReviewPlanHtml(review) {
  if (!review || typeof review !== "object") return "";
  const initial = review.initial_score;
  const finalScore = review.final_score;
  const decision = review.decision || "unchanged";
  const reasons = (review.review_reason || []).map((r) => escHtml(r)).join("；");
  const risks = (review.review_risk || []).map((r) => escHtml(r)).join("；");
  const decisionLabel =
    decision === "pass" ? "上调通过" : decision === "filter" ? "下调筛掉" : "维持";
  return `
    <div class="pet-learning-log-section">
      <b>边界复核（Planner）</b>
      <div>决策：${escHtml(decisionLabel)}${initial != null && finalScore != null ? ` · ${initial} → ${finalScore} 分` : ""}</div>
      ${reasons ? `<div>复核理由：${reasons}</div>` : ""}
      ${risks ? `<div>补充风险：${risks}</div>` : ""}
      ${(review.rag_references || []).length ? `<div class="pet-rag-ref-inline">${formatRagReferencesHtml(review.rag_references)}</div>` : ""}
    </div>
  `;
}

function formatDailyActionPlanHtml(plan) {
  if (!plan) {
    return `<p class="pet-archive-hint">暂无今日行动计划。搜岗运行后会由秘书 AI 生成。</p>`;
  }
  const priorities = (plan.priorities || [])
    .map((p) => `<li>${escHtml(p)}</li>`)
    .join("");
  const applyRows = (plan.apply_today || [])
    .map(
      (row) => `
      <article class="pet-daily-pick-card">
        <div class="pet-daily-pick-body">
          <h3 class="pet-daily-pick-title">${escHtml(row.title || "岗位")}</h3>
          <p class="pet-daily-pick-meta">${escHtml(row.company || "")}</p>
          <p class="pet-filtered-reason">${escHtml(row.reason || "")}</p>
        </div>
      </article>`,
    )
    .join("");
  const review = (plan.review_filtered || []).map((x) => `<li>${escHtml(x)}</li>`).join("");
  const profile = (plan.profile_actions || []).map((x) => `<li>${escHtml(x)}</li>`).join("");
  const risks = (plan.risk_notes || []).map((x) => `<li>${escHtml(x)}</li>`).join("");
  return `
    <div class="pet-learning-log-detail">
      <h3 class="pet-learning-log-title">${escHtml(plan.headline || "今日行动建议")}</h3>
      <p class="pet-learning-log-meta">${escHtml(plan.date || "")} · ${plan.planner === "llm" ? "LLM 规划" : "规则建议"}</p>
      ${priorities ? `<div class="pet-learning-log-section"><b>今日优先</b><ul>${priorities}</ul></div>` : ""}
      ${applyRows ? `<div class="pet-learning-log-section"><b>建议优先处理岗位</b><div class="pet-daily-picks-list">${applyRows}</div></div>` : ""}
      ${review ? `<div class="pet-learning-log-section"><b>复盘建议</b><ul>${review}</ul></div>` : ""}
      ${profile ? `<div class="pet-learning-log-section"><b>画像/简历</b><ul>${profile}</ul></div>` : ""}
      ${risks ? `<div class="pet-learning-log-section"><b>节奏提醒</b><ul>${risks}</ul></div>` : ""}
    </div>
  `;
}

function formatScoutStrategyPlanHtml(data) {
  const payload = data?.plan;
  if (!payload?.plan) {
    return `<p class="pet-archive-hint">暂无侦察策略记录。开始搜岗后，每轮开始前会生成策略计划。</p>`;
  }
  const plan = payload.plan;
  const notes = (plan.focus_notes || []).map((n) => `<li>${escHtml(n)}</li>`).join("");
  return `
    <div class="pet-learning-log-detail">
      <h3 class="pet-learning-log-title">第 ${escHtml(String(payload.round || "—"))} 轮 · ${escHtml(payload.query || "搜岗")}</h3>
      <p class="pet-learning-log-meta">${escHtml(payload.city || "不限城市")} · ${plan.planner === "llm" ? "LLM 策略" : "默认策略"}</p>
      <div class="pet-learning-log-section">
        <b>策略摘要</b>
        <div>${escHtml(plan.strategy_summary || plan.stop_reason || "—")}</div>
      </div>
      <div class="pet-learning-log-section">
        <b>翻页计划</b>
        <div>计划 ${escHtml(String(plan.planned_cap ?? "—"))} 页 · 实际浏览上限 ${escHtml(String(plan.effective_cap ?? "—"))} 页${plan.early_stop ? " · 可提前结束" : ""}</div>
      </div>
      ${notes ? `<div class="pet-learning-log-section"><b>执行建议</b><ul>${notes}</ul></div>` : ""}
      <p class="pet-archive-hint">说明：搜索词、城市与轮间休息时长仍由你/系统默认控制；换词仅在列表扫完时进行。Planner 不改这些项。</p>
    </div>
  `;
}

async function renderDailyActionPlanPanel(container, refresh = false) {
  container.innerHTML = `<p class="pet-archive-hint">${refresh ? "重新生成今日行动计划…" : "加载今日行动计划…"}</p>`;
  try {
    const plan = await fetchDailyActionPlan(refresh);
    container.innerHTML = `
      <div class="pet-learning-log-toolbar">
        <p class="pet-learning-log-summary">${escHtml(plan?.headline || "今日行动建议")}</p>
        <button type="button" class="pet-archive-btn pet-learning-log-clear" data-action="refresh-plan">重新生成</button>
      </div>
      ${formatDailyActionPlanHtml(plan)}
    `;
    container.querySelector("[data-action='refresh-plan']")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      const prev = btn.textContent;
      btn.textContent = "生成中…";
      try {
        await renderDailyActionPlanPanel(container, true);
        setStatus("今日行动计划已更新");
      } catch (err) {
        setStatus(err?.message || "生成失败");
        btn.disabled = false;
        btn.textContent = prev;
      }
    });
  } catch (err) {
    container.innerHTML = `<p class="pet-archive-hint pet-archive-hint-err">${escHtml(err?.message || "加载失败")}</p>`;
  }
}

async function renderScoutStrategyPlanPanel(container) {
  container.innerHTML = `<p class="pet-archive-hint">加载侦察策略…</p>`;
  const data = await fetchScoutStrategyPlan();
  container.innerHTML = formatScoutStrategyPlanHtml(data);
}

function formatRagReferencesHtml(refs) {
  const items = Array.isArray(refs) ? refs : [];
  if (!items.length) {
    return `<p class="pet-archive-hint">本次分析未命中向量库中的相似历史案例（可能尚无足够历史，或 Embedding 未启用）。</p>`;
  }
  const rows = items.map((ref, i) => {
    const status = ragStatusLabel(ref.status || ref.source_type);
    const title = escHtml(ref.title || "岗位");
    const company = escHtml(ref.company || "");
    const sim = Number(ref.similarity);
    const simText = Number.isFinite(sim) ? `${(sim * 100).toFixed(0)}%` : "—";
    const histScore = ref.analysis_score != null ? ` · 历史 ${ref.analysis_score} 分` : "";
    const summary = ref.summary ? `<p class="pet-rag-ref-summary">${escHtml(ref.summary)}</p>` : "";
    return `
      <article class="pet-rag-ref-card">
        <div class="pet-rag-ref-head">
          <span class="pet-rag-ref-rank">#${i + 1}</span>
          <span class="pet-rag-ref-badge">${escHtml(status)}</span>
          <span class="pet-rag-ref-sim">相似度 ${simText}${escHtml(histScore)}</span>
        </div>
        <h4 class="pet-rag-ref-title">${title}${company ? ` · ${company}` : ""}</h4>
        ${summary}
      </article>
    `;
  }).join("");
  return `<div class="pet-rag-ref-list">${rows}</div>`;
}

function formatFilteredAnalysisListContent(data) {
  const items = data?.items || [];
  if (!items.length) {
    return `
      <p class="pet-archive-hint">暂无分析筛掉的岗位。</p>
      <p class="pet-archive-hint">分析 AI 判定不通过的岗位会自动记录在此，可查看筛掉原因与 RAG 参考案例。</p>
    `;
  }
  const rows = items.map((item, i) => {
    const reason = item.filter_reason || resolveAnalysisFilterReason(item.job || item, {});
    const brief = escHtml(reason.length > 56 ? `${reason.slice(0, 56)}…` : reason);
    const when = escHtml(formatShortlistTime(item.analyzed_at));
    const score = item.analysis_score != null ? ` · 分析 ${item.analysis_score} 分` : "";
    const ragChip = summarizeRagReferencesBrief(item.rag_references);
    return `
      <button type="button" class="pet-learning-log-row pet-filtered-log-row" data-index="${i}">
        <span class="pet-learning-log-row-main">
          <span class="pet-learning-log-row-title">${escHtml(item.title || "岗位")}</span>
          <span class="pet-learning-log-row-meta">${escHtml(item.company || "")}${score}${when ? ` · ${when}` : ""}</span>
          <span class="pet-learning-log-row-brief">${brief}</span>
        </span>
        <span class="pet-learning-log-row-side">
          ${ragChip ? `<span class="pet-learning-log-row-chips">${escHtml(ragChip)}</span>` : ""}
          <span class="pet-learning-log-row-chevron">›</span>
        </span>
      </button>
    `;
  }).join("");
  return `
    <p class="pet-learning-log-summary">共 ${items.length} 个被筛掉岗位 · 点击查看详情与 RAG 参考</p>
    <div class="pet-learning-log-list">${rows}</div>
  `;
}

function formatFilteredAnalysisDetailHtml(item) {
  const reason = item.filter_reason || resolveAnalysisFilterReason(item.job || item, {});
  const risks = (item.analysis_risk || [])
    .map((r) => escHtml(r))
    .join("；");
  const when = formatShortlistTime(item.analyzed_at);
  const sid = escHtml(item.security_id || "");
  const jid = escHtml(item.job_id || "");
  return `
    <div class="pet-learning-log-detail">
      <button type="button" class="pet-learning-log-back" data-action="back">← 返回列表</button>
      <h3 class="pet-learning-log-title">${escHtml(item.title || "岗位")}</h3>
      <p class="pet-learning-log-meta">${escHtml(item.company || "")} · ${escHtml(item.salary || "-")} · ${escHtml(item.city || "-")}${item.analysis_score != null ? ` · 分析 ${item.analysis_score} 分` : ""}${when ? ` · ${escHtml(when)}` : ""}</p>
      <div class="pet-learning-log-section">
        <b>筛掉原因</b>
        <div>${escHtml(reason)}</div>
      </div>
      ${risks ? `<div class="pet-learning-log-section"><b>分析风险</b><div>${risks}</div></div>` : ""}
      <div class="pet-learning-log-section">
        <b>本次分析参考的历史案例（向量 RAG）</b>
        ${formatRagReferencesHtml(item.rag_references)}
      </div>
      ${formatReviewPlanHtml(item.analysis_review_plan || (item.job || {}).analysis_review_plan)}
      <div class="pet-shortlist-actions">
        <button type="button" class="pet-archive-btn pet-filtered-open" data-sid="${sid}" data-jid="${jid}">BOSS 查看</button>
      </div>
    </div>
  `;
}

function formatFilteredAnalysisContent(data) {
  return formatFilteredAnalysisListContent(data);
}

function wireFilteredAnalysisPanel(container, items) {
  container.querySelectorAll(".pet-filtered-log-row").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.dataset.index);
      const item = items[idx];
      if (!item) return;
      container.innerHTML = formatFilteredAnalysisDetailHtml(item);
      container.querySelector("[data-action='back']")?.addEventListener("click", () => {
        container.innerHTML = formatFilteredAnalysisListContent({ items });
        wireFilteredAnalysisPanel(container, items);
      });
      container.querySelector(".pet-filtered-open")?.addEventListener("click", async (ev) => {
        const openBtn = ev.currentTarget;
        const jobId = openBtn.dataset.jid || "";
        if (!jobId) return;
        openBtn.disabled = true;
        try {
          const data = await petOpenBossJob({
            job_id: jobId,
            security_id: openBtn.dataset.sid || "",
          });
          setStatus(data?.message || "已在登录态浏览器打开岗位");
        } catch (err) {
          setStatus(err?.message || "打开岗位失败");
        } finally {
          openBtn.disabled = false;
        }
      });
    });
  });
}

async function renderFilteredAnalysisPanel(container) {
  container.innerHTML = `<p class="pet-archive-hint">加载分析筛掉记录…</p>`;
  const data = await fetchFilteredAnalysis();
  const items = data?.items || [];
  container.innerHTML = formatFilteredAnalysisListContent(data);
  wireFilteredAnalysisPanel(container, items);
  petDocumentCabinet?.clearNew("filtered_analysis");
}

async function fetchLearningLog(limit = 100) {
  const resp = await fetch(`/api/profile/learning-log?limit=${encodeURIComponent(limit)}`, { cache: "no-store" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "加载学习记录失败");
  return body.data;
}

function formatLearningLogTime(ts) {
  if (!ts) return "";
  try {
    return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return String(ts);
  }
}

function summarizeLearningLogBrief(item) {
  const tags = Array.isArray(item.user_tags) ? item.user_tags : [];
  const reason = (item.user_reason || "").trim();
  if (tags.length) return tags.slice(0, 3).join("、");
  if (reason) return reason.length > 48 ? `${reason.slice(0, 48)}…` : reason;
  return "（未填写理由）";
}

function learningLogChangeSummary(item) {
  const parts = [];
  const weightN = (item.weight_changes || []).length;
  const memN = (item.ai_memory_added || []).length;
  const instrN = (item.preference_instructions || []).length;
  if (weightN) parts.push(`权重×${weightN}`);
  if (memN) parts.push(`记忆×${memN}`);
  if (instrN) parts.push(`指令×${instrN}`);
  return parts.join(" · ") || "已记录";
}

function formatLearningLogDetailHtml(item) {
  const tags = Array.isArray(item.user_tags) ? item.user_tags : [];
  const reason = item.user_reason || "";
  const userLine = [
    tags.length ? tags.map((t) => escHtml(t)).join("、") : "",
    reason ? escHtml(reason) : "",
  ].filter(Boolean).join(" · ") || "（未填写理由）";
  const weightLines = (item.weight_changes || []).map((chg) => {
    const label = LEARNING_DIMENSION_LABELS[chg.dimension] || chg.dimension;
    return `<li>${escHtml(label)}：${chg.before} → ${chg.after}</li>`;
  }).join("");
  const instrLines = (item.preference_instructions || [])
    .map((line) => `<li>${escHtml(line)}</li>`)
    .join("");
  const memoryLines = (item.ai_memory_added || [])
    .map((mem) => `<li>${escHtml(mem.content || "")}</li>`)
    .join("");
  const reasons = (item.analysis_reason || [])
    .map((r) => escHtml(r))
    .join("；");
  const risks = (item.analysis_risk || [])
    .map((r) => escHtml(r))
    .join("；");
  return `
    <div class="pet-learning-log-detail">
      <button type="button" class="pet-learning-log-back" data-action="back">← 返回列表</button>
      <h3 class="pet-learning-log-title">${escHtml(item.title || "岗位")}</h3>
      <p class="pet-learning-log-meta">${escHtml(item.company || "")} · ${formatLearningLogTime(item.created_at)}${item.analysis_score != null ? ` · 分析 ${item.analysis_score} 分` : ""}</p>
      <div class="pet-learning-log-section">
        <b>你的拒绝理由</b>
        <div>${userLine}</div>
      </div>
      ${reasons ? `<div class="pet-learning-log-section"><b>当时分析亮点</b><div>${reasons}</div></div>` : ""}
      ${risks ? `<div class="pet-learning-log-section"><b>当时分析风险</b><div>${risks}</div></div>` : ""}
      ${weightLines ? `<div class="pet-learning-log-section"><b>评分权重调整</b><ul>${weightLines}</ul></div>` : ""}
      ${instrLines ? `<div class="pet-learning-log-section"><b>新增偏好指令</b><ul>${instrLines}</ul></div>` : ""}
      ${memoryLines ? `<div class="pet-learning-log-section"><b>写入 AI 记忆</b><ul>${memoryLines}</ul></div>` : ""}
    </div>
  `;
}

function formatLearningLogListContent(data) {
  const items = data?.items || [];
  if (!items.length) {
    return `
      <p class="pet-archive-hint">暂无拒绝与学习记录。</p>
      <p class="pet-archive-hint">在通过岗位栏点「不感兴趣」并填写理由后，系统会在此记录你的偏好与权重变化。</p>
    `;
  }
  const rows = items.map((item, i) => {
    const brief = escHtml(summarizeLearningLogBrief(item));
    const summary = escHtml(learningLogChangeSummary(item));
    const when = escHtml(formatLearningLogTime(item.created_at));
    const score = item.analysis_score != null ? ` · 分析 ${item.analysis_score} 分` : "";
    return `
      <button type="button" class="pet-learning-log-row" data-index="${i}">
        <span class="pet-learning-log-row-main">
          <span class="pet-learning-log-row-title">${escHtml(item.title || "岗位")}</span>
          <span class="pet-learning-log-row-meta">${escHtml(item.company || "")}${score} · ${when}</span>
          <span class="pet-learning-log-row-brief">${brief}</span>
        </span>
        <span class="pet-learning-log-row-side">
          <span class="pet-learning-log-row-chips">${summary}</span>
          <span class="pet-learning-log-row-chevron">›</span>
        </span>
      </button>
    `;
  }).join("");
  return `
    <div class="pet-learning-log-toolbar">
      <p class="pet-learning-log-summary">共 ${items.length} 条记录 · 点击查看详情</p>
      <button type="button" class="pet-archive-btn pet-learning-log-clear" data-action="clear">清空学习记忆</button>
    </div>
    <div class="pet-learning-log-list">${rows}</div>
  `;
}

async function clearLearningLogMemory() {
  const ok = window.confirm(
    "确定清空拒绝与学习记忆？\n\n将删除全部记录，并回滚由此产生的评分权重调整、偏好指令与分析 AI 记忆。\n此操作不可恢复。",
  );
  if (!ok) return null;
  const resp = await fetch("/api/profile/learning-log", { method: "DELETE" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "清空失败");
  return body.data;
}

function wireLearningLogPanel(container, items) {
  container.querySelectorAll(".pet-learning-log-row").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.dataset.index);
      const item = items[idx];
      if (!item) return;
      container.innerHTML = formatLearningLogDetailHtml(item);
      container.querySelector("[data-action='back']")?.addEventListener("click", () => {
        container.innerHTML = formatLearningLogListContent({ items });
        wireLearningLogPanel(container, items);
      });
    });
  });
  container.querySelector("[data-action='clear']")?.addEventListener("click", async () => {
    const clearBtn = container.querySelector("[data-action='clear']");
    if (clearBtn) clearBtn.disabled = true;
    try {
      const result = await clearLearningLogMemory();
      setStatus(result?.message || "已清空学习记忆");
      container.innerHTML = `
        <p class="pet-archive-hint">暂无拒绝与学习记录。</p>
        <p class="pet-archive-hint">在通过岗位栏点「不感兴趣」并填写理由后，系统会在此记录你的偏好与权重变化。</p>
      `;
    } catch (err) {
      setStatus(err?.message || "清空失败");
      if (clearBtn) clearBtn.disabled = false;
    }
  });
}

async function renderRejectLearningPanel(container) {
  container.innerHTML = `<p class="pet-archive-hint">加载拒绝与学习记录…</p>`;
  const data = await fetchLearningLog();
  const items = data?.items || [];
  container.innerHTML = formatLearningLogListContent(data);
  wireLearningLogPanel(container, items);
  petDocumentCabinet?.clearNew("reject_learning");
}

function petShowRejectDialog(job) {
  const modal = document.getElementById("petRejectModal");
  const tagsEl = document.getElementById("petRejectTags");
  const reasonEl = document.getElementById("petRejectReason");
  const subtitleEl = document.getElementById("petRejectSubtitle");
  const closeBtn = document.getElementById("petRejectClose");
  const cancelBtn = document.getElementById("petRejectCancel");
  const skipBtn = document.getElementById("petRejectSkip");
  const submitBtn = document.getElementById("petRejectSubmit");
  if (!modal || !tagsEl || !reasonEl || !skipBtn || !submitBtn) {
    return Promise.resolve({ tags: [], reason: "", skipped: true });
  }

  const title = job?.title || "该岗位";
  const company = job?.company || "";
  if (subtitleEl) {
    subtitleEl.textContent = company ? `${title} · ${company}` : title;
  }
  reasonEl.value = "";
  tagsEl.innerHTML = "";
  const selected = new Set();

  for (const label of REJECT_REASON_TAGS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pet-reject-tag";
    btn.textContent = label;
    btn.addEventListener("click", () => {
      if (selected.has(label)) {
        selected.delete(label);
        btn.classList.remove("is-active");
      } else {
        selected.add(label);
        btn.classList.add("is-active");
      }
    });
    tagsEl.appendChild(btn);
  }

  modal.hidden = false;

  return new Promise((resolve) => {
    const cleanup = () => {
      modal.hidden = true;
      closeBtn?.removeEventListener("click", onCancel);
      cancelBtn?.removeEventListener("click", onCancel);
      skipBtn.removeEventListener("click", onSkip);
      submitBtn.removeEventListener("click", onSubmit);
      modal.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKeydown);
    };
    const finish = (result) => {
      cleanup();
      resolve(result);
    };
    const onCancel = () => finish({ cancelled: true });
    const onSkip = () => finish({ tags: [], reason: "", skipped: true });
    const onSubmit = () => finish({
      tags: [...selected],
      reason: reasonEl.value.trim(),
      skipped: false,
    });
    const onBackdrop = (ev) => {
      if (ev.target === modal) onCancel();
    };
    const onKeydown = (ev) => {
      if (ev.key === "Escape") onCancel();
    };
    closeBtn?.addEventListener("click", onCancel);
    cancelBtn?.addEventListener("click", onCancel);
    skipBtn.addEventListener("click", onSkip);
    submitBtn.addEventListener("click", onSubmit);
    modal.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKeydown);
  });
}

function resolveDailyPickDateParam(dateParam) {
  if (!dateParam || dateParam === "today") {
    return new Date().toISOString().slice(0, 10);
  }
  return dateParam;
}

function formatDailyPickDateLabel(dateStr, todayStr) {
  if (dateStr === todayStr) return `今天 · ${dateStr}`;
  return dateStr;
}

function formatDailyPicksContent(data) {
  const picks = data?.daily_picks || [];
  const summary = data?.summary || {};
  const date = data?.date || "";
  if (!picks.length) {
    return `
      <p class="pet-archive-hint">${escHtml(date)} 暂无精选岗位。</p>
      <p class="pet-archive-hint">当日有通过的分析岗后，秘书 AI 会在此整理每日精选。</p>
    `;
  }
  const rows = picks.map((pick, i) => {
    const reasons = Array.isArray(pick.analysis_reason) ? pick.analysis_reason.slice(0, 2) : [];
    const scores = pick.scores_labeled || {};
    const sixLine = Object.entries(scores)
      .map(([k, v]) => `${escHtml(k)}${v}`)
      .join(" · ");
    const link = pick.boss_url
      ? `<a class="pet-archive-btn" href="${escHtml(pick.boss_url)}" target="_blank" rel="noopener">在 BOSS 打开</a>`
      : "";
    return `
      <article class="pet-daily-pick-card">
        <div class="pet-daily-pick-rank">#${i + 1}</div>
        <div class="pet-daily-pick-body">
          <h3 class="pet-daily-pick-title">${escHtml(pick.title || "岗位")}</h3>
          <p class="pet-daily-pick-meta">${escHtml(pick.company || "")} · ${escHtml(pick.salary || "-")} · ${escHtml(pick.city || "-")}</p>
          <p class="pet-daily-pick-scores">分析 ${pick.analysis_score ?? "—"} 分 · 综合 ${pick.pick_score ?? "—"} · ${escHtml(pick.archetype || "")}</p>
          ${sixLine ? `<p class="pet-daily-pick-six">${sixLine}</p>` : ""}
          ${pick.commentary ? `<p class="pet-daily-pick-comment">${escHtml(pick.commentary)}</p>` : ""}
          ${reasons.length ? `<p class="pet-daily-pick-reason">${reasons.map((r) => escHtml(r)).join("；")}</p>` : ""}
          ${link}
        </div>
      </article>
    `;
  }).join("");
  return `
    <div class="pet-daily-picks-head">
      <p class="pet-daily-picks-date">${escHtml(date)}</p>
      <p class="pet-daily-picks-summary">评估 ${summary.total ?? 0} 个 · 通过 ${summary.passed_count ?? 0} 个 · 精选 ${picks.length} 个</p>
    </div>
    <div class="pet-daily-picks-list">${rows}</div>
  `;
}

function buildDailyPickDateNavHtml(dates, activeDate, todayStr) {
  if (!dates.length) {
    return `<p class="pet-archive-hint pet-daily-picks-dates-empty">暂无历史记录</p>`;
  }
  return dates
    .map((item) => {
      const active = item.date === activeDate ? " is-active" : "";
      const label = formatDailyPickDateLabel(item.date, todayStr);
      const meta = item.passed_count > 0
        ? `通过 ${item.passed_count}`
        : `评估 ${item.total ?? 0}`;
      return `
        <button type="button" class="pet-daily-picks-date-btn${active}" data-date="${escHtml(item.date)}">
          <span class="pet-daily-picks-date-label">${escHtml(label)}</span>
          <span class="pet-daily-picks-date-meta">${escHtml(meta)}</span>
        </button>
      `;
    })
    .join("");
}

function wireDailyPickDateNav(container, datesMeta, todayStr) {
  const nav = container.querySelector(".pet-daily-picks-dates");
  if (!nav) return;
  nav.querySelectorAll(".pet-daily-picks-date-btn[data-date]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const date = btn.dataset.date;
      if (!date) return;
      void renderDailyPicksPanel(container, date, { datesMeta, todayStr });
    });
  });
}

async function renderDailyPicksPanel(container, dateParam = "today", cached = {}) {
  const todayStr = cached.todayStr || new Date().toISOString().slice(0, 10);
  let datesMeta = cached.datesMeta;
  if (!datesMeta) {
    const meta = await fetchDailyPickDates();
    datesMeta = meta?.dates || [];
    cached.todayStr = meta?.today || todayStr;
    cached.datesMeta = datesMeta;
  }
  const activeDate = resolveDailyPickDateParam(dateParam);
  if (!datesMeta.some((item) => item.date === activeDate)) {
    datesMeta = [{ date: activeDate, total: 0, passed_count: 0 }, ...datesMeta];
  }
  container.innerHTML = `
    <div class="pet-daily-picks-layout">
      <nav class="pet-daily-picks-dates" aria-label="精选日期">
        ${buildDailyPickDateNavHtml(datesMeta, activeDate, cached.todayStr || todayStr)}
      </nav>
      <div class="pet-daily-picks-main">
        <p class="pet-archive-hint">加载中…</p>
      </div>
    </div>
  `;
  wireDailyPickDateNav(container, datesMeta, cached.todayStr || todayStr);
  const main = container.querySelector(".pet-daily-picks-main");
  const nav = container.querySelector(".pet-daily-picks-dates");
  try {
    const data = await fetchDailyReport(activeDate);
    if (main) main.innerHTML = formatDailyPicksContent(data);
    nav?.querySelectorAll(".pet-daily-picks-date-btn").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.date === data.date);
    });
  } catch (err) {
    if (main) {
      main.innerHTML = `<p class="pet-archive-hint pet-archive-hint-err">${escHtml(err?.message || "加载失败")}</p>`;
    }
  }
}

function formatDailyPicksHtml(data) {
  return formatDailyPicksContent(data);
}

async function showDailyPicksModal(date = "today", opts = {}) {
  if (!petArchiveManager) return;
  try {
    await petArchiveManager.openReport("daily_picks", {
      fromDrawer: false,
      reportDate: date,
    });
    if (opts.auto) {
      const today = new Date().toISOString().slice(0, 10);
      try {
        localStorage.setItem(PET_DAILY_PICKS_SHOWN_KEY, today);
      } catch {
        /* ignore */
      }
      petDocumentCabinet?.markNew("daily_picks");
      setStatus("今日工作结束 · 秘书 AI 已整理每日精选");
    }
  } catch (err) {
    if (!opts.auto) setStatus(err?.message || "加载每日精选失败");
  }
}

function applyOffHoursActivityForAgent(agent) {
  if (!agent) return;
  const modes = [];
  if (agent.canStroll()) modes.push("stroll");
  if (agent.canLongRest()) modes.push("longRest");
  if (!modes.length) {
    agent.setClip("sleepShort", true);
    return;
  }
  const mode = modes[Math.floor(Math.random() * modes.length)];
  if (mode === "stroll") {
    if (!agent.strolling) agent.beginStroll();
    return;
  }
  if (!agent.atLongRest && !agent.moving) agent.beginLongRest();
}

function ensureOffHoursFreeActivity() {
  for (const agent of Object.values(agents)) {
    if (!agent) continue;
    if (agent.strolling || agent.atLongRest || agent.moving) continue;
    finishRestActivity(agent, () => applyOffHoursActivityForAgent(agent));
  }
}

function beginOffHoursMode() {
  workScheduleTransitionToken += 1;
  officeResting = false;
  for (const agent of Object.values(agents)) {
    finishRestActivity(agent, () => applyOffHoursActivityForAgent(agent));
  }
  if (petLocalScouting) {
    petScoutOffHoursPaused = true;
    setStatus(formatOffHoursScoutStatus());
  } else {
    setStatus(formatOffHoursStatus());
  }
  refreshIdleAgentTasks();
  maybeShowDailyPicksAtEndOfDay();
  maybeSendDailyReportEmailAtEndOfDay();
}

function applyWorkdayAgentClips() {
  if (petLocalScouting) {
    agents.ZC?.setClip("work", true);
    agents.FX?.setClip("sit", true);
    agents.JK?.setClip(jkAlert ? "work" : "sit", true);
  } else {
    agents.ZC?.setClip("sit", true);
    agents.FX?.setClip("sit", true);
    agents.JK?.setClip(jkAlert ? "work" : "sit", true);
  }
  agents.MS?.setClip("sit", true);
}

function formatRoundRestStatus(remainingSec, message = "") {
  const sec = Math.ceil(Number(remainingSec) || 0);
  const isFatigue = /疲劳/.test(message || "");
  const label = isFatigue ? "疲劳休息中" : "本轮休息中";
  return sec > 0 ? `${label} · 约 ${sec} 秒后继续搜岗` : `${label} · 即将继续搜岗`;
}

function clearOfficeRestTimer() {
  if (officeRestClearTimer != null) {
    clearTimeout(officeRestClearTimer);
    officeRestClearTimer = null;
  }
}

function scheduleOfficeRestAutoResume(pauseSec) {
  clearOfficeRestTimer();
  const sec = Number(pauseSec);
  if (!Number.isFinite(sec) || sec <= 0) return;
  // 仅作 SSE 断线兜底；正常以 scout_heartbeat / round_resume 为准
  officeRestClearTimer = setTimeout(() => {
    officeRestClearTimer = null;
    if (!officeResting || scheduleOffHours) return;
    resumeAfterRest();
    petMonitorSidebar?.exitRestState();
  }, Math.ceil(sec * 1000) + 2500);
}

function endOffHoursMode() {
  petScoutOffHoursPaused = false;
  setScoutUserStopped(false);
  scheduleOffHours = false;
  if (officeResting) {
    refreshIdleAgentTasks();
    return;
  }
  officeResting = false;
  const token = ++workScheduleTransitionToken;
  wakeFromRest(() => {
    if (token !== workScheduleTransitionToken) return;
    applyWorkdayAgentClips();
    if (petLocalScouting) {
      refreshPetHeaderScoutStats();
    } else {
      tryAutoStartScout();
      if (!petLocalScouting) {
        setStatus(
          isScoutUserStopped()
            ? "工作时间 · 已手动停止搜岗 · 点击「开始搜岗」恢复"
            : "工作时间 · 点击「开始搜岗」启动各 AI",
        );
      }
    }
    refreshIdleAgentTasks();
  });
}

function syncWorkSchedule() {
  const periods = petConfig?.workSchedule?.periods;
  if (!Array.isArray(periods) || !periods.length) {
    if (scheduleOffHours) {
      scheduleOffHours = false;
      endOffHoursMode();
    }
    return;
  }
  const inWork = isWithinWorkSchedule();
  const periodKey = inWork ? getCurrentWorkPeriodKey() : null;
  if (inWork && periodKey && periodKey !== lastWorkPeriodKey) {
    lastWorkPeriodKey = periodKey;
    onWorkPeriodStarted(periodKey);
  } else if (!inWork) {
    lastWorkPeriodKey = null;
  }
  if (inWork && scheduleOffHours) {
    endOffHoursMode();
  } else if (!inWork && !scheduleOffHours && !officeResting) {
    scheduleOffHours = true;
    beginOffHoursMode();
  }
}

function startWorkScheduleWatcher() {
  if (scheduleCheckTimer != null) {
    clearInterval(scheduleCheckTimer);
    scheduleCheckTimer = null;
  }
  if (!petConfig?.workSchedule?.periods?.length) return;
  syncWorkSchedule();
  scheduleCheckTimer = setInterval(syncWorkSchedule, 10000);
}

function getExcludeRects(bounds) {
  return bounds?.excludeRects || [];
}

function pointInRect(x, y, rect) {
  if (rect.w == null || rect.h == null) return false;
  return x >= rect.x && x <= rect.x + rect.w && y >= rect.y && y <= rect.y + rect.h;
}

function isPointExcluded(x, y, bounds) {
  return getExcludeRects(bounds).some((rect) => pointInRect(x, y, rect));
}

function findFallbackPointInBounds(bounds) {
  if (!normalizeActivityBounds(bounds)) return null;
  const cols = 14;
  const rows = 14;
  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
      const point = {
        x: bounds.x + ((c + 0.5) * bounds.w) / cols,
        y: bounds.y + ((r + 0.5) * bounds.h) / rows,
      };
      if (!isPointExcluded(point.x, point.y, bounds)) return point;
    }
  }
  return null;
}

/** 溜达移动是否合法：起点/终点/路径均不可进入禁区 */
function isStrollMoveValid(fromX, fromY, toX, toY, bounds) {
  if (!bounds) return true;
  if (isPointExcluded(fromX, fromY, bounds)) return false;
  if (isPointExcluded(toX, toY, bounds)) return false;

  const dist = Math.hypot(toX - fromX, toY - fromY);
  const steps = Math.max(2, Math.ceil(dist / 3));
  for (let i = 1; i < steps; i += 1) {
    const t = i / steps;
    const x = fromX + (toX - fromX) * t;
    const y = fromY + (toY - fromY) * t;
    if (isPointExcluded(x, y, bounds)) return false;
  }
  return true;
}

function findNearestValidPoint(fromX, fromY, bounds) {
  if (!normalizeActivityBounds(bounds)) return null;
  let best = null;
  let bestDist = Infinity;
  const cols = 16;
  const rows = 16;
  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
      const point = {
        x: bounds.x + ((c + 0.5) * bounds.w) / cols,
        y: bounds.y + ((r + 0.5) * bounds.h) / rows,
      };
      if (isPointExcluded(point.x, point.y, bounds)) continue;
      const dist = Math.hypot(point.x - fromX, point.y - fromY);
      if (dist < bestDist) {
        bestDist = dist;
        best = point;
      }
    }
  }
  return best;
}

function normalizeActivityBounds(bounds) {
  if (!bounds || bounds.w == null || bounds.h == null) return null;
  return bounds;
}

function randomPointInBounds(bounds) {
  if (!normalizeActivityBounds(bounds)) return null;
  for (let attempt = 0; attempt < 64; attempt += 1) {
    const point = {
      x: bounds.x + Math.random() * bounds.w,
      y: bounds.y + Math.random() * bounds.h,
    };
    if (!isPointExcluded(point.x, point.y, bounds)) return point;
  }
  return findFallbackPointInBounds(bounds);
}

function sleepMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 从 GIF 二进制解析每帧停留时长（毫秒） */
function parseGifFrameDurations(buffer) {
  const bytes = new Uint8Array(buffer);
  const durations = [];
  for (let i = 0; i < bytes.length - 7; i += 1) {
    if (bytes[i] === 0x21 && bytes[i + 1] === 0xf9 && bytes[i + 2] === 0x04) {
      const units = bytes[i + 4] | (bytes[i + 5] << 8);
      durations.push(Math.max(units * 10, 20));
    }
  }
  return durations.length ? durations : [100];
}

class PetBowls {
  constructor(stage, bowlConfigs) {
    this.stage = stage;
    this.configs = bowlConfigs || [];
    /** @type {Map<string, { usesLeft: number }>} */
    this.state = new Map();
    /** @type {Map<string, { el: HTMLButtonElement, img: HTMLImageElement, cfg: object }>} */
    this.elements = new Map();
    this._mount();
  }

  _mount() {
    for (const cfg of this.configs) {
      const maxUses = cfg.usesWhenFull ?? 2;
      const usesLeft = cfg.defaultFull === false ? 0 : maxUses;
      this.state.set(cfg.id, { usesLeft });

      const el = document.createElement("button");
      el.type = "button";
      el.className = "pet-bowl";
      el.dataset.bowlId = cfg.id;
      el.style.left = `${cfg.x}px`;
      el.style.top = `${cfg.y}px`;
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        this.toggle(cfg.id);
      });

      const img = document.createElement("img");
      img.alt = cfg.label || cfg.id;
      img.draggable = false;
      el.appendChild(img);

      this.elements.set(cfg.id, { el, img, cfg });
      this.stage.appendChild(el);
      this._syncVisual(cfg.id);
    }
  }

  _entry(id) {
    return this.elements.get(id);
  }

  _maxUses(id) {
    return this._entry(id)?.cfg.usesWhenFull ?? 2;
  }

  isAvailable(id) {
    return (this.state.get(id)?.usesLeft ?? 0) > 0;
  }

  refill(id) {
    const entry = this._entry(id);
    if (!entry) return;
    this.state.set(id, { usesLeft: this._maxUses(id) });
    this._syncVisual(id);
    setStatus(`${entry.cfg.label}已加满 · 可供 ${this._maxUses(id)} 次互动`);
  }

  clear(id) {
    const entry = this._entry(id);
    if (!entry) return;
    this.state.set(id, { usesLeft: 0 });
    this._syncVisual(id);
    setStatus(`${entry.cfg.label}已清空`);
  }

  toggle(id) {
    if (this.isAvailable(id)) this.clear(id);
    else this.refill(id);
  }

  consumeUse(id) {
    const st = this.state.get(id);
    if (!st || st.usesLeft <= 0) return;
    st.usesLeft -= 1;
    this._syncVisual(id);
  }

  _syncVisual(id) {
    const entry = this._entry(id);
    if (!entry) return;
    const { el, img, cfg } = entry;
    const usesLeft = this.state.get(id)?.usesLeft ?? 0;
    const full = usesLeft > 0;
    img.src = petAssetUrl(full ? cfg.full : cfg.empty, { s: usesLeft });
    el.classList.toggle("pet-bowl-full", full);
    el.classList.toggle("pet-bowl-empty", !full);
    el.title = full
      ? `${cfg.label} · 剩余 ${usesLeft} 次（点击清空）`
      : `${cfg.label} · 空的（点击加满）`;
  }

  /** @returns {object[]} */
  getActiveInteractables() {
    const items = [];
    for (const [id, { cfg }] of this.elements) {
      if (!this.isAvailable(id) || interactableOccupancy.has(id)) continue;
      items.push({
        id,
        bowl: true,
        x: cfg.agentX ?? cfg.x,
        y: cfg.agentY ?? cfg.y,
        label: cfg.label,
        clip: cfg.clip,
        pauseMs: cfg.pauseMs,
      });
    }
    return items;
  }
}

class PetDeskPlates {
  constructor(stage, plateConfigs) {
    this.stage = stage;
    this.configs = plateConfigs || [];
    /** @type {Map<string, { cfg: object, nameplate: HTMLButtonElement, panel: HTMLElement }>} */
    this.plates = new Map();
    this.openAgentId = null;
    this._mount();
  }

  _mount() {
    for (const cfg of this.configs) {
      const agentId = cfg.agentId || cfg.id;
      if (!agentId) continue;
      const panelCfg = cfg.panel === false ? null : cfg.panel || {};

      const nameplate = document.createElement("button");
      nameplate.type = "button";
      nameplate.className = "pet-desk-nameplate";
      nameplate.dataset.agentId = agentId;
      nameplate.style.left = `${cfg.x ?? 128}px`;
      nameplate.style.top = `${cfg.y ?? 150}px`;
      nameplate.title = cfg.label || "工位设置";

      const inner = document.createElement("span");
      inner.className = "pet-desk-nameplate-inner";

      const plateImg = document.createElement("img");
      plateImg.className = "pet-desk-nameplate-img";
      plateImg.src = petAssetUrl(cfg.nameplate || "分析员.png");
      plateImg.alt = cfg.label || "工位牌";
      plateImg.draggable = false;
      const plateScale = cfg.nameplateScale;
      if (plateScale != null && plateScale !== 1) {
        plateImg.addEventListener("load", () => {
          plateImg.style.width = `${Math.round(plateImg.naturalWidth * plateScale)}px`;
          plateImg.style.height = `${Math.round(plateImg.naturalHeight * plateScale)}px`;
        }, { once: true });
      }
      inner.appendChild(plateImg);

      const textCfg = cfg.plateText;
      if (textCfg) {
        const textEl = document.createElement("span");
        textEl.className = "pet-desk-nameplate-text";
        textEl.textContent = textCfg.text ?? cfg.label ?? agentId;
        textEl.style.left = `${textCfg.x ?? 0}px`;
        textEl.style.top = `${textCfg.y ?? 0}px`;
        if (textCfg.fontSize != null) textEl.style.fontSize = `${textCfg.fontSize}px`;
        if (textCfg.color) textEl.style.color = textCfg.color;
        if (textCfg.fontWeight) textEl.style.fontWeight = String(textCfg.fontWeight);
        if (textCfg.letterSpacing != null) textEl.style.letterSpacing = `${textCfg.letterSpacing}px`;
        inner.appendChild(textEl);
      }

      nameplate.appendChild(inner);
      nameplate.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (panelCfg === null) {
          setStatus(`${cfg.label || agentId} 设置即将开放`);
          return;
        }
        this.openPanel(agentId);
      });

      if (panelCfg === null) {
        this.stage.appendChild(nameplate);
        this.plates.set(agentId, { cfg, nameplate, panel: null });
        continue;
      }

      const panel = document.createElement("div");
      panel.className = "pet-desk-panel";
      panel.dataset.agentId = agentId;
      panel.hidden = true;
      panel.style.left = `${panelCfg.x ?? cfg.x ?? 128}px`;
      panel.style.top = `${panelCfg.y ?? 100}px`;

      const panelBg = document.createElement("img");
      panelBg.className = "pet-desk-panel-bg";
      panelBg.src = petAssetUrl(panelCfg.image || "分析设置.png");
      panelBg.alt = `${cfg.label || agentId}设置`;
      panelBg.draggable = false;
      panel.appendChild(panelBg);

      const body = document.createElement("div");
      body.className = "pet-desk-panel-body";
      this._buildPanelBody(agentId, body, cfg);
      panel.appendChild(body);

      const closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.className = "pet-desk-panel-close";
      closeBtn.title = "关闭";
      const closeOffset = panelCfg.closeOffset || {};
      if (closeOffset.x != null) closeBtn.style.left = `${closeOffset.x}px`;
      if (closeOffset.y != null) closeBtn.style.top = `${closeOffset.y}px`;
      const closeImg = document.createElement("img");
      closeImg.src = petAssetUrl(panelCfg.closeButton || "关闭按钮.png");
      closeImg.alt = "关闭";
      closeImg.draggable = false;
      closeBtn.appendChild(closeImg);
      closeBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        this.closePanel();
      });
      panel.appendChild(closeBtn);

      panel.addEventListener("click", (ev) => ev.stopPropagation());

      this.stage.appendChild(nameplate);
      this.stage.appendChild(panel);
      this.plates.set(agentId, { cfg, nameplate, panel });
    }
  }

  _buildPanelBody(agentId, body, cfg) {
    if (agentId === "FX" || cfg.role === "analysis") {
      this._buildFxPanel(body, cfg);
      return;
    }
    if (agentId === "MS" || cfg.role === "secretary") {
      this._buildSecretaryPanel(body, cfg);
      return;
    }
    if (agentId === "JK" || cfg.role === "monitor") {
      this._buildMonitorPanel(body, cfg);
      return;
    }
    if (agentId === "ZC" || cfg.role === "scout") {
      this._buildScoutPanel(body, cfg);
      return;
    }
    body.innerHTML = `<p class="pet-desk-field-hint">${cfg.label || agentId} 设置即将开放</p>`;
  }

  _buildFxPanel(body, cfg) {
    const panelCfg = cfg.panel || {};
    const layout = panelCfg.layout || {};
    const buttonImg = panelCfg.buttonImage || "小按钮.png";
    const confirmText = panelCfg.confirmButtonText || "确定";
    const passScore = loadPassScore(petConfig?.analysis?.defaultPassScore ?? 60);
    const careerPrefs = loadCareerStagePrefs();
    const stageRadios = CAREER_STAGE_OPTIONS.map(
      (o) => `
        <label class="pet-fx-stage-opt">
          <input type="radio" name="petCareerStage" value="${escHtml(o.id)}"
            ${o.id === careerPrefs.stage ? "checked" : ""}>
          <span>${escHtml(o.label)} · ${escHtml(o.hint)}</span>
        </label>`,
    ).join("");
    body.className = "pet-desk-panel-body pet-desk-panel-body-fx";
    applyPetBoxLayout(body, layout.body);
    body.innerHTML = `
      <div class="pet-fx-panel">
        <div class="pet-fx-pass"${careerPrefs.enabled ? " hidden" : ""}>
          <label class="pet-fx-pass-label">
            通过分 <span class="pet-desk-pass-val">${passScore}</span>
          </label>
          <input type="range" class="pet-fx-pass-range" min="0" max="100" step="5" value="${passScore}"${careerPrefs.enabled ? " disabled" : ""}>
        </div>
        <div class="pet-fx-career">
          <label class="pet-fx-career-toggle">
            <input type="checkbox" class="pet-desk-career-enable" ${careerPrefs.enabled ? "checked" : ""}>
            <span>职业阶段评估</span>
          </label>
          <div class="pet-fx-scroll"${careerPrefs.enabled ? "" : " hidden"}>
            ${stageRadios}
          </div>
        </div>
        <div class="pet-fx-confirm-wrap"></div>
      </div>
    `;
    applyPetBoxLayout(body.querySelector(".pet-fx-pass-label"), layout.passLabel);
    applyPetBoxLayout(body.querySelector(".pet-fx-career-toggle span"), layout.careerToggle);
    body.querySelectorAll(".pet-fx-stage-opt span").forEach((el) => {
      applyPetBoxLayout(el, layout.stageOpt);
    });
    const confirmWrap = body.querySelector(".pet-fx-confirm-wrap");
    const confirmBtn = this._createPixelButton(buttonImg, confirmText, "pet-fx-confirm-btn");
    confirmWrap?.appendChild(confirmBtn);
    applyPetBoxLayout(confirmWrap, layout.confirmWrap);
    applyPetBoxLayout(confirmBtn, layout.confirmButton);
    applyPetBoxLayout(confirmBtn.querySelector(".pet-desk-pixel-btn-text"), layout.confirmButtonText);
    bindPetImageScale(confirmBtn.querySelector("img"), layout.confirmButton?.scale);
    this._wireFxPanel(body, confirmBtn);
  }

  _syncFxPanelMode(body) {
    const enabled = Boolean(body.querySelector(".pet-desk-career-enable")?.checked);
    const passBlock = body.querySelector(".pet-fx-pass");
    const careerScroll = body.querySelector(".pet-fx-scroll");
    const range = body.querySelector(".pet-fx-pass-range");
    if (passBlock) passBlock.hidden = enabled;
    if (careerScroll) careerScroll.hidden = !enabled;
    if (range) range.disabled = enabled;
  }

  _wireFxPanel(body, confirmBtn) {
    if (!body || body._fxWired) return;
    body._fxWired = true;
    const range = body.querySelector(".pet-fx-pass-range");
    const valEl = body.querySelector(".pet-desk-pass-val");
    range?.addEventListener("input", () => {
      const v = Number(range.value);
      if (valEl) valEl.textContent = String(v);
    });
    const careerEnable = body.querySelector(".pet-desk-career-enable");
    careerEnable?.addEventListener("change", () => {
      this._syncFxPanelMode(body);
    });
    this._syncFxPanelMode(body);
    confirmBtn?.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const enabled = Boolean(careerEnable?.checked);
      if (!enabled) {
        const passScore = Number(range?.value ?? loadPassScore(60));
        savePassScore(passScore);
      }
      const stageEl = body.querySelector('input[name="petCareerStage"]:checked');
      const stage = stageEl?.value || "junior";
      saveCareerStagePrefs(enabled, stage);
      this.closePanel();
      const stageLabel = CAREER_STAGE_OPTIONS.find((o) => o.id === stage)?.label || stage;
      if (enabled) {
        setStatus(`分析 AI 设置已保存 · 职业阶段：${stageLabel}`);
      } else {
        const passScore = Number(range?.value ?? loadPassScore(60));
        setStatus(`分析 AI 设置已保存 · 传统六维分析 · 通过分 ${passScore}`);
      }
    });
  }

  _refreshFxPanel(body, cfg) {
    if (!body) return;
    body._fxWired = false;
    this._buildFxPanel(body, cfg);
  }

  _buildScoutPanel(body, cfg) {
    const panelCfg = cfg.panel || {};
    const layout = panelCfg.layout || {};
    const buttonImg = panelCfg.buttonImage || "小按钮.png";
    const confirmText = panelCfg.confirmButtonText || "确认";

    body.className = "pet-desk-panel-body pet-desk-panel-body-zc";
    applyPetBoxLayout(body, layout.body);
    body.innerHTML = `
      <div class="pet-zc-panel">
        <div class="pet-zc-region-fields">
          <div class="pet-zc-city-field">
            <label class="pet-zc-city-label">省/直辖市</label>
            <select class="pet-zc-province-select" aria-label="省/直辖市">
              <option value="">不限</option>
            </select>
          </div>
          <div class="pet-zc-city-field">
            <label class="pet-zc-city-label">城市</label>
            <select class="pet-zc-city-select" aria-label="城市" disabled>
              <option value="">先选省份</option>
            </select>
          </div>
          <div class="pet-zc-city-field">
            <label class="pet-zc-city-label">行政区</label>
            <select class="pet-zc-district-select" aria-label="行政区" disabled>
              <option value="">全市</option>
            </select>
          </div>
        </div>
        <div class="pet-zc-scroll">
          <p class="pet-zc-filter-guide">筛选条件</p>
          <div class="pet-zc-filters">${buildScoutFilterPanelHtml()}</div>
        </div>
        <div class="pet-zc-confirm-wrap"></div>
      </div>
    `;

    const confirmWrap = body.querySelector(".pet-zc-confirm-wrap");
    const confirmBtn = this._createPixelButton(buttonImg, confirmText, "pet-zc-confirm-btn");
    confirmWrap?.appendChild(confirmBtn);
    applyPetBoxLayout(confirmWrap, layout.confirmWrap);
    applyPetBoxLayout(confirmBtn, layout.confirmButton);
    applyPetBoxLayout(confirmBtn.querySelector(".pet-desk-pixel-btn-text"), layout.confirmButtonText);
    bindPetImageScale(confirmBtn.querySelector("img"), layout.confirmButton?.scale);

    wireScoutFilterPanel(body);
    applyScoutFiltersToPetPanel(body, loadScoutFiltersFromPrefs());
    wireZcRegionSelects(body);
    syncZcPanelRegionSelects(body);

    confirmBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const filters = getScoutFiltersFromPetPanel(body);
      const err = validateScoutFilters(filters);
      if (err) {
        setStatus(err);
        return;
      }
      saveScoutFiltersToPrefs(filters);
      const loc = getRegionSelectionFromPanel(body);
      const regionErr = validateScoutRegion(loc);
      if (regionErr) {
        setStatus(regionErr);
        return;
      }
      const queryEl = document.getElementById("petScoutQuery");
      savePetScoutQueryPrefs(queryEl?.value?.trim() || "", loc);
      this.closePanel();
      const label = formatRegionLabel(loc) || "不限城市";
      setStatus(`侦察 AI 筛选条件与地区已保存（${label}）`);
    });

  }

  _buildMonitorPanel(body, cfg) {
    const panelCfg = cfg.panel || {};
    const layout = panelCfg.layout || {};
    const buttonImg = panelCfg.buttonImage || "小按钮.png";
    const loginText = panelCfg.bossLoginText || "登录 BOSS";
    const syncText = panelCfg.bossSyncText || "同步登录态";
    const logoutText = panelCfg.bossLogoutText || "退出登录";

    body.className = "pet-desk-panel-body pet-desk-panel-body-jk";
    applyPetBoxLayout(body, layout.body);
    body.innerHTML = `
      <div class="pet-jk-panel">
        <div class="pet-jk-boss-section">
          <p class="pet-jk-section-title">BOSS 登录态</p>
          <p class="pet-jk-boss-status pet-jk-boss-status--warn">读取中…</p>
          <div class="pet-jk-boss-actions"></div>
        </div>
        <div class="pet-jk-token-section">
          <p class="pet-jk-section-title">Token 累计</p>
          <div class="pet-jk-token-total">
            累计 <span class="pet-jk-token-total-val">0</span> tokens
          </div>
          <div class="pet-jk-token-cost">
            约 <span class="pet-jk-token-cost-val">¥0.00</span>
          </div>
          <div class="pet-jk-token-price-fields">
            <label class="pet-jk-token-price-field">
              <span>输入(未命中)</span>
              <input type="number" class="pet-jk-token-input-price" min="0" step="0.01" value="1">
            </label>
            <label class="pet-jk-token-price-field">
              <span>输出</span>
              <input type="number" class="pet-jk-token-output-price" min="0" step="0.01" value="2">
            </label>
          </div>
          <p class="pet-jk-token-hint">DeepSeek：输入命中缓存 ¥0.02/百万 · 未命中 ¥1 · 输出 ¥2（自动统计缓存）</p>
        </div>
      </div>
    `;

    const actionsEl = body.querySelector(".pet-jk-boss-actions");
    const loginBtn = this._createPixelButton(buttonImg, loginText, "pet-jk-boss-login");
    const syncBtn = this._createPixelButton(buttonImg, syncText, "pet-jk-boss-sync");
    const logoutBtn = this._createPixelButton(buttonImg, logoutText, "pet-jk-boss-logout");
    actionsEl?.appendChild(loginBtn);
    actionsEl?.appendChild(syncBtn);
    actionsEl?.appendChild(logoutBtn);

    applyPetBoxLayout(actionsEl, layout.bossActions);
    applyPetBoxLayout(loginBtn, layout.bossLoginButton);
    applyPetBoxLayout(loginBtn.querySelector(".pet-desk-pixel-btn-text"), layout.bossLoginButtonText);
    applyPetBoxLayout(syncBtn, layout.bossSyncButton);
    applyPetBoxLayout(syncBtn.querySelector(".pet-desk-pixel-btn-text"), layout.bossSyncButtonText);
    applyPetBoxLayout(logoutBtn, layout.bossLogoutButton);
    applyPetBoxLayout(logoutBtn.querySelector(".pet-desk-pixel-btn-text"), layout.bossLogoutButtonText);
    bindPetImageScale(loginBtn.querySelector("img"), layout.bossLoginButton?.scale);
    bindPetImageScale(syncBtn.querySelector("img"), layout.bossSyncButton?.scale);
    bindPetImageScale(logoutBtn.querySelector("img"), layout.bossLogoutButton?.scale);
    if (layout.bossActions?.gap != null) {
      actionsEl.style.gap = typeof layout.bossActions.gap === "number"
        ? `${layout.bossActions.gap}px`
        : String(layout.bossActions.gap);
    }

    const refreshPanel = (opts = {}) => refreshMonitorPanel(body, opts);

    loginBtn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      loginBtn.disabled = true;
      syncBtn.disabled = true;
      setStatus("正在打开浏览器，请扫码或手机号登录（最多 120 秒）…");
      try {
        const data = await petBossLogin();
        setStatus(data?.message || "BOSS 登录成功");
        await refreshPanel({ bossSync: true });
      } catch (err) {
        setStatus(err?.message || "BOSS 登录失败");
      } finally {
        loginBtn.disabled = false;
        syncBtn.disabled = false;
      }
    });

    syncBtn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      loginBtn.disabled = true;
      syncBtn.disabled = true;
      setStatus("正在从本地浏览器同步 Cookie…");
      try {
        const data = await petBossSync();
        setStatus(data?.message || "BOSS 登录态已同步");
        await refreshPanel({ bossSync: true });
      } catch (err) {
        setStatus(err?.message || "同步失败");
      } finally {
        loginBtn.disabled = false;
        syncBtn.disabled = false;
      }
    });

    logoutBtn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (!confirm("确定退出 BOSS 登录？本地保存的登录态将被清除。")) return;
      logoutBtn.disabled = true;
      try {
        const data = await petBossLogout();
        setStatus(data?.message || "已退出 BOSS 登录");
        await refreshPanel({ bossSync: true });
      } catch (err) {
        setStatus(err?.message || "退出失败");
      } finally {
        logoutBtn.disabled = false;
      }
    });

    body._refreshMonitorPanel = () => refreshMonitorPanel(body, { bossSync: !scheduleOffHours });
    body._saveTokenPricing = saveMonitorTokenPricing;

    const inputPriceEl = body.querySelector(".pet-jk-token-input-price");
    const outputPriceEl = body.querySelector(".pet-jk-token-output-price");
    let pricingSaveTimer = null;
    const schedulePricingSave = () => {
      if (pricingSaveTimer) clearTimeout(pricingSaveTimer);
      pricingSaveTimer = setTimeout(async () => {
        pricingSaveTimer = null;
        try {
          await saveMonitorTokenPricing(body);
        } catch (err) {
          setStatus(err?.message || "Token 单价保存失败");
        }
      }, 500);
    };
    inputPriceEl?.addEventListener("change", schedulePricingSave);
    outputPriceEl?.addEventListener("change", schedulePricingSave);

    refreshPanel();
  }

  _createPixelButton(image, text, className = "") {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `pet-desk-pixel-btn ${className}`.trim();
    const img = document.createElement("img");
    img.src = petAssetUrl(image);
    img.alt = text;
    img.draggable = false;
    const span = document.createElement("span");
    span.className = "pet-desk-pixel-btn-text";
    span.textContent = text;
    btn.appendChild(img);
    btn.appendChild(span);
    return btn;
  }

  _createPixelLabel(image, text, className = "") {
    const label = document.createElement("div");
    label.className = `pet-desk-pixel-label ${className}`.trim();
    const img = document.createElement("img");
    img.src = petAssetUrl(image);
    img.alt = text;
    img.draggable = false;
    const span = document.createElement("span");
    span.className = "pet-desk-pixel-label-text";
    span.textContent = text;
    label.appendChild(img);
    label.appendChild(span);
    return label;
  }

  _buildSecretaryPanel(body, cfg) {
    const panelCfg = cfg.panel || {};
    const layout = panelCfg.layout || {};
    const buttonImg = panelCfg.buttonImage || "小按钮.png";
    const inputImg = panelCfg.inputImage || "输入框.png";
    const emailGuide = panelCfg.emailGuideText || "设置邮箱";
    const actions = panelCfg.actions || {};
    const careerText = actions.careerChat?.text || "职业方向对话";
    const portraitText = actions.portraitView?.text || "求职画像查看";
    const confirmText = panelCfg.confirmButtonText || "确认";

    body.className = "pet-desk-panel-body pet-desk-panel-body-ms";
    applyPetBoxLayout(body, layout.body);
    body.innerHTML = `
      <div class="pet-ms-panel">
        <div class="pet-ms-panel-main">
          <div class="pet-ms-email-row">
            <div class="pet-ms-email-guide-wrap"></div>
            <label class="pet-desk-email-input-wrap">
              <img class="pet-desk-email-input-bg" src="${petAssetUrl(inputImg)}" alt="">
              <input type="email" class="pet-desk-email-input" autocomplete="email" spellcheck="false" placeholder="you@example.com">
            </label>
          </div>
          <div class="pet-ms-auth-row">
            <span class="pet-ms-auth-label">授权码</span>
            <label class="pet-desk-email-input-wrap pet-ms-auth-input-wrap">
              <img class="pet-desk-email-input-bg" src="${petAssetUrl(inputImg)}" alt="">
              <input type="password" class="pet-ms-auth-input" autocomplete="off" spellcheck="false" placeholder="SMTP 授权码">
            </label>
          </div>
          <p class="pet-ms-email-hint">收件与发件使用同一邮箱 · 授权码在邮箱设置中开启 SMTP 后获取</p>
          <div class="pet-ms-picks-row">
            <span class="pet-ms-picks-label">每日精选</span>
            <input type="number" class="pet-ms-picks-input" min="1" max="20" step="1" value="5" aria-label="每日精选数量">
            <span class="pet-ms-picks-unit">个</span>
          </div>
          <div class="pet-ms-actions"></div>
        </div>
        <div class="pet-ms-overlay pet-ms-career-overlay" hidden>
          <p class="pet-ms-overlay-title">职业方向对话</p>
          <div class="pet-ms-chat-log"></div>
          <label class="pet-ms-chat-input-wrap">
            <input type="text" class="pet-ms-chat-input" placeholder="输入回答…" maxlength="500">
          </label>
          <button type="button" class="pet-ms-overlay-back">返回</button>
        </div>
        <div class="pet-ms-overlay pet-ms-portrait-overlay" hidden>
          <p class="pet-ms-overlay-title">求职画像</p>
          <div class="pet-ms-portrait-content"></div>
          <button type="button" class="pet-ms-overlay-back">返回</button>
        </div>
        <div class="pet-ms-confirm-wrap"></div>
      </div>
    `;

    const emailRow = body.querySelector(".pet-ms-email-row");
    const guideWrap = body.querySelector(".pet-ms-email-guide-wrap");
    const inputWrap = body.querySelector(".pet-desk-email-input-wrap");
    const inputBg = body.querySelector(".pet-desk-email-input-bg");
    const emailInput = body.querySelector(".pet-desk-email-input");
    const authInput = body.querySelector(".pet-ms-auth-input");
    const picksInput = body.querySelector(".pet-ms-picks-input");
    const actionsEl = body.querySelector(".pet-ms-actions");
    const confirmWrap = body.querySelector(".pet-ms-confirm-wrap");
    const careerOverlay = body.querySelector(".pet-ms-career-overlay");
    const portraitOverlay = body.querySelector(".pet-ms-portrait-overlay");
    const mainEl = body.querySelector(".pet-ms-panel-main");

    applyPetBoxLayout(emailRow, layout.emailRow);
    applyPetBoxLayout(guideWrap, layout.emailGuide);
    applyPetBoxLayout(inputWrap, layout.inputBox);
    applyPetBoxLayout(emailInput, layout.inputText);
    const authRow = body.querySelector(".pet-ms-auth-row");
    applyPetBoxLayout(authRow, layout.authRow);
    applyPetBoxLayout(body.querySelector(".pet-ms-auth-label"), layout.authLabel);
    applyPetBoxLayout(body.querySelector(".pet-ms-auth-input-wrap"), layout.authInputBox);
    applyPetBoxLayout(authInput, layout.authInputText);
    bindPetImageScale(body.querySelector(".pet-ms-auth-input-wrap .pet-desk-email-input-bg"), layout.authInputBox?.scale);
    const picksRow = body.querySelector(".pet-ms-picks-row");
    applyPetBoxLayout(picksRow, layout.picksRow);
    applyPetBoxLayout(body.querySelector(".pet-ms-picks-label"), layout.picksLabel);
    applyPetBoxLayout(picksInput, layout.picksInput);
    applyPetBoxLayout(body.querySelector(".pet-ms-picks-unit"), layout.picksUnit);
    applyPetBoxLayout(actionsEl, layout.actions);
    bindPetImageScale(inputBg, layout.inputBox?.scale);

    const emailGuideLabel = this._createPixelLabel(buttonImg, emailGuide, "pet-ms-email-guide");
    guideWrap?.appendChild(emailGuideLabel);
    applyPetBoxLayout(emailGuideLabel, layout.emailGuideLabel);
    applyPetBoxLayout(
      emailGuideLabel.querySelector(".pet-desk-pixel-label-text"),
      layout.emailGuideText,
    );
    bindPetImageScale(emailGuideLabel.querySelector("img"), layout.emailGuideLabel?.scale);

    const careerBtn = this._createPixelButton(buttonImg, careerText, "pet-ms-career-btn");
    const portraitBtn = this._createPixelButton(buttonImg, portraitText, "pet-ms-portrait-btn");
    const confirmBtn = this._createPixelButton(buttonImg, confirmText, "pet-ms-confirm-btn");
    actionsEl.appendChild(careerBtn);
    actionsEl.appendChild(portraitBtn);
    confirmWrap.appendChild(confirmBtn);

    applyPetBoxLayout(careerBtn, layout.careerButton);
    applyPetBoxLayout(careerBtn.querySelector(".pet-desk-pixel-btn-text"), layout.careerButtonText);
    applyPetBoxLayout(portraitBtn, layout.portraitButton);
    applyPetBoxLayout(portraitBtn.querySelector(".pet-desk-pixel-btn-text"), layout.portraitButtonText);
    applyPetBoxLayout(confirmWrap, layout.confirmWrap);
    applyPetBoxLayout(confirmBtn, layout.confirmButton);
    applyPetBoxLayout(confirmBtn.querySelector(".pet-desk-pixel-btn-text"), layout.confirmButtonText);
    bindPetImageScale(careerBtn.querySelector("img"), layout.careerButton?.scale);
    bindPetImageScale(portraitBtn.querySelector("img"), layout.portraitButton?.scale);
    bindPetImageScale(confirmBtn.querySelector("img"), layout.confirmButton?.scale);

    if (layout.actions?.gap != null) {
      actionsEl.style.gap = typeof layout.actions.gap === "number"
        ? `${layout.actions.gap}px`
        : String(layout.actions.gap);
    }

    const showMain = () => {
      mainEl.hidden = false;
      confirmWrap.hidden = false;
      careerOverlay.hidden = true;
      portraitOverlay.hidden = true;
      body.classList.remove("pet-ms-panel-overlay-open");
    };
    const showOverlay = (overlay) => {
      mainEl.hidden = true;
      confirmWrap.hidden = true;
      careerOverlay.hidden = overlay !== careerOverlay;
      portraitOverlay.hidden = overlay !== portraitOverlay;
      body.classList.add("pet-ms-panel-overlay-open");
    };

    careerBtn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      showOverlay(careerOverlay);
      await this._openSecretaryCareerChat(careerOverlay);
    });
    portraitBtn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      this.closePanel();
      petArchiveManager?.openReport("portrait");
    });
    careerOverlay.querySelector(".pet-ms-overlay-back")?.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      showMain();
    });
    portraitOverlay.querySelector(".pet-ms-overlay-back")?.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      showMain();
    });

    const chatInput = careerOverlay.querySelector(".pet-ms-chat-input");
    chatInput?.addEventListener("keydown", async (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      await this._sendSecretaryCareerAnswer(careerOverlay, chatInput);
    });

    body._loadSecretarySettings = async () => {
      const settings = await loadSecretarySettings();
      if (emailInput) emailInput.value = settings.recipient_email || "";
      if (authInput) {
        authInput.value = "";
        authInput.placeholder = settings.has_smtp_password
          ? "已设置（留空不修改）"
          : "SMTP 授权码";
      }
      if (picksInput) picksInput.value = String(settings.max_daily_picks ?? 5);
    };
    body._loadSecretarySettings();

    confirmBtn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      confirmBtn.disabled = true;
      try {
        const maxDailyPicks = Math.min(20, Math.max(1, Number(picksInput?.value) || 5));
        if (picksInput) picksInput.value = String(maxDailyPicks);
        const msg = await saveSecretaryPanelSettings(
          emailInput?.value?.trim() || "",
          maxDailyPicks,
          authInput?.value?.trim() || "",
        );
        showMain();
        this.closePanel();
        setStatus(msg);
      } catch (err) {
        setStatus(err?.message || "保存失败");
      } finally {
        confirmBtn.disabled = false;
      }
    });

    body._resetMsView = showMain;
  }

  async _openSecretaryCareerChat(overlay) {
    const logEl = overlay.querySelector(".pet-ms-chat-log");
    const chatInput = overlay.querySelector(".pet-ms-chat-input");
    if (!logEl) return;
    logEl.innerHTML = `<p class="pet-ms-chat-hint">正在连接 AI 访谈…</p>`;
    if (chatInput) {
      chatInput.value = "";
      chatInput.disabled = true;
    }
    try {
      let current = await fetchInterviewCurrent();
      if (!current?.active && !current?.question) {
        const started = await startSecretaryInterview();
        current = {
          active: true,
          question: started.question,
          reasoning: started.reasoning,
          transcript: [],
        };
      }
      this._renderSecretaryChatLog(logEl, current);
      if (chatInput) {
        chatInput.disabled = !!current.completed;
      }
    } catch (err) {
      logEl.innerHTML = `<p class="pet-ms-chat-hint pet-ms-chat-err">${escHtml(err?.message || "无法开始对话")}</p>`;
    }
  }

  _renderSecretaryChatLog(logEl, data) {
    const lines = [];
    for (const item of data?.transcript || []) {
      if (item.question) {
        lines.push(`<div class="pet-ms-chat-msg pet-ms-chat-ai">${escHtml(item.question)}</div>`);
      }
      if (item.answer) {
        lines.push(`<div class="pet-ms-chat-msg pet-ms-chat-user">${escHtml(item.answer)}</div>`);
      }
    }
    if (data?.question) {
      lines.push(`<div class="pet-ms-chat-msg pet-ms-chat-ai">${escHtml(data.question)}</div>`);
    }
    if (!lines.length) {
      lines.push(`<p class="pet-ms-chat-hint">请回答 AI 关于职业方向的问题</p>`);
    }
    logEl.innerHTML = lines.join("");
    logEl.scrollTop = logEl.scrollHeight;
  }

  async _sendSecretaryCareerAnswer(overlay, chatInput) {
    const text = chatInput?.value?.trim();
    if (!text) return;
    chatInput.disabled = true;
    const logEl = overlay.querySelector(".pet-ms-chat-log");
    try {
      const data = await answerSecretaryInterview(text);
      chatInput.value = "";
      this._renderSecretaryChatLog(logEl, data);
      if (data.completed) {
        chatInput.disabled = true;
        setStatus("职业方向对话已完成，点击「确认」保存");
      } else {
        chatInput.disabled = false;
        chatInput.focus();
      }
    } catch (err) {
      setStatus(err?.message || "发送失败");
      chatInput.disabled = false;
    }
  }

  async _showSecretaryPortrait(overlay) {
    const content = overlay.querySelector(".pet-ms-portrait-content");
    if (!content) return;
    content.innerHTML = `<p class="pet-ms-chat-hint">加载画像中…</p>`;
    try {
      const data = await loadSecretaryPortrait();
      content.innerHTML = formatSecretaryPortraitHtml(data);
    } catch (err) {
      content.innerHTML = `<p class="pet-ms-chat-hint pet-ms-chat-err">${escHtml(err?.message || "加载失败")}</p>`;
    }
  }

  openPanel(agentId) {
    const entry = this.plates.get(agentId);
    if (!entry?.panel) {
      setStatus(`${entry?.cfg.label || agentId} 设置即将开放`);
      return;
    }
    if (this.openAgentId && this.openAgentId !== agentId) {
      const prev = this.plates.get(this.openAgentId);
      if (prev) prev.panel.hidden = true;
    }
    entry.panel.hidden = false;
    this.openAgentId = agentId;
    entry.nameplate.classList.add("pet-desk-nameplate-active");
    if (agentId === "MS") {
      const body = entry.panel.querySelector(".pet-desk-panel-body-ms");
      body?._loadSecretarySettings?.();
    }
    if (agentId === "JK") {
      startMonitorTokenPoll(entry.panel);
      const body = entry.panel.querySelector(".pet-desk-panel-body-jk");
      body?._refreshMonitorPanel?.();
    }
    if (agentId === "ZC") {
      const body = entry.panel.querySelector(".pet-desk-panel-body-zc");
      if (body) {
        applyScoutFiltersToPetPanel(body, loadScoutFiltersFromPrefs());
        syncZcPanelRegionSelects(body);
      }
    }
    if (agentId === "FX") {
      const body = entry.panel.querySelector(".pet-desk-panel-body-fx");
      this._refreshFxPanel(body, entry.cfg);
    }
    setStatus(`打开 ${entry.cfg.label || agentId} 工位设置`);
  }

  closePanel() {
    if (!this.openAgentId) return;
    const closingId = this.openAgentId;
    const entry = this.plates.get(this.openAgentId);
    if (entry?.panel) {
      entry.panel.hidden = true;
      const body = entry.panel.querySelector(".pet-desk-panel-body-ms");
      if (body?._resetMsView) body._resetMsView();
    }
    if (closingId === "JK") stopMonitorTokenPoll();
    entry?.nameplate.classList.remove("pet-desk-nameplate-active");
    this.openAgentId = null;
    setStatus("工位设置已关闭");
  }

  isOpen(agentId) {
    return this.openAgentId === agentId;
  }
}

class PetResumeDesk {
  constructor(stage, cfg) {
    this.stage = stage;
    this.cfg = cfg || {};
    this.uploading = false;
    this.deleting = false;
    this.hasResume = false;
    this._deleteAnimTimer = null;
    this._hideDeleteTimer = null;
    this._deleteZoneGraceMs = 320;

    const uploadCfg = this.cfg.upload || {};
    const displayCfg = this.cfg.display || {};
    const deleteCfg = this.cfg.delete || {};

    this.fileInput = document.createElement("input");
    this.fileInput.type = "file";
    this.fileInput.accept = ".pdf,application/pdf";
    this.fileInput.className = "pet-resume-file-input";
    document.body.appendChild(this.fileInput);

    this.uploadBtn = document.createElement("button");
    this.uploadBtn.type = "button";
    this.uploadBtn.className = "pet-resume-upload";
    this.uploadBtn.style.left = `${uploadCfg.x ?? 128}px`;
    this.uploadBtn.style.top = `${uploadCfg.y ?? 198}px`;
    this.uploadBtn.title = uploadCfg.label || "点击上传 PDF 简历";
    const uploadImg = document.createElement("img");
    uploadImg.src = petAssetUrl(uploadCfg.image || "jian.png");
    uploadImg.alt = uploadCfg.label || "上传简历";
    uploadImg.draggable = false;
    this.uploadBtn.appendChild(uploadImg);
    this.uploadBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (!this.uploading) this.fileInput.click();
    });

    this.stack = document.createElement("div");
    this.stack.className = "pet-resume-stack";
    this.stack.style.left = `${displayCfg.x ?? uploadCfg.x ?? 128}px`;
    this.stack.style.top = `${displayCfg.y ?? uploadCfg.y ?? 192}px`;
    this.stack.hidden = true;
    this.stack.title = displayCfg.label || "简历";

    this.displayEl = document.createElement("img");
    this.displayEl.className = "pet-resume-display";
    this.displayEl.src = petAssetUrl(displayCfg.image || "jianli.png");
    this.displayEl.alt = displayCfg.label || "简历";
    this.displayEl.draggable = false;
    this.stack.appendChild(this.displayEl);
    this.stack.addEventListener("mouseenter", () => this._onDeleteZoneEnter());
    this.stack.addEventListener("mouseleave", (ev) => this._onDeleteZoneLeave(ev));

    this.deleteBtn = document.createElement("button");
    this.deleteBtn.type = "button";
    this.deleteBtn.className = "pet-resume-delete";
    this.deleteBtn.style.left = `${deleteCfg.x ?? displayCfg.x ?? 128}px`;
    this.deleteBtn.style.top = `${deleteCfg.y ?? displayCfg.y ?? 192}px`;
    this.deleteBtn.title = deleteCfg.label || "点击删除简历";
    this.deleteBtn.hidden = true;
    this.deleteImg = document.createElement("img");
    this.deleteImg.alt = deleteCfg.label || "删除简历";
    this.deleteImg.draggable = false;
    this.deleteBtn.appendChild(this.deleteImg);
    this.deleteBtn.addEventListener("mouseenter", () => this._onDeleteZoneEnter());
    this.deleteBtn.addEventListener("mouseleave", (ev) => this._onDeleteZoneLeave(ev));
    this.deleteBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      this._deleteResume();
    });

    this.fileInput.addEventListener("change", () => this._onFileSelected());

    this.stage.appendChild(this.uploadBtn);
    this.stage.appendChild(this.stack);
    this.stage.appendChild(this.deleteBtn);
    this._deleteAnimMs = deleteCfg.durationMs ?? 550;
    this._deleteAnimDurationMs = this._deleteAnimMs;
    this._deleteLastFrameSrc = null;
    this._deleteFrames = [];
    this._deleteFrameTimer = null;
    this._deleteAnimFrozen = false;
    this._deletePreloadPromise = this._preloadDeleteAssets();
    this.syncFromStatus();
  }

  async _preloadDeleteAssets() {
    const deleteCfg = this.cfg.delete || {};
    const image = deleteCfg.image || "shan.gif";
    const url = petAssetUrl(image);

    if (deleteCfg.lastFrame) {
      this._deleteLastFrameSrc = petAssetUrl(deleteCfg.lastFrame);
      this._deleteFrames = [{ src: this._deleteLastFrameSrc, durationMs: 0 }];
      return;
    }

    if (typeof ImageDecoder === "undefined") {
      await this._preloadDeleteAssetsViaHiddenPlay(url, deleteCfg);
      return;
    }

    try {
      const buffer = await fetch(url).then((r) => r.arrayBuffer());
      const decoder = new ImageDecoder({ data: buffer, type: "image/gif" });
      const frames = [];
      let totalMs = 0;
      let index = 0;

      while (true) {
        try {
          const { image } = await decoder.decode({ frameIndex: index });
          const durationMs = Math.max(Math.round(image.duration / 1000), 20);
          const canvas = document.createElement("canvas");
          canvas.width = image.displayWidth;
          canvas.height = image.displayHeight;
          canvas.getContext("2d").drawImage(image, 0, 0);
          frames.push({ src: canvas.toDataURL("image/png"), durationMs });
          totalMs += durationMs;
          image.close();
          index += 1;
        } catch {
          break;
        }
      }
      decoder.close();

      if (!frames.length) {
        await this._preloadDeleteAssetsViaHiddenPlay(url, deleteCfg, buffer);
        return;
      }

      this._deleteFrames = frames;
      this._deleteLastFrameSrc = frames[frames.length - 1].src;
      this._deleteAnimDurationMs = deleteCfg.durationMs ?? totalMs;
    } catch {
      await this._preloadDeleteAssetsViaHiddenPlay(url, deleteCfg);
    }
  }

  /** 离屏播放 GIF 一轮并截取各帧（避免页面上循环播放） */
  async _preloadDeleteAssetsViaHiddenPlay(url, deleteCfg, buffer = null) {
    try {
      const buf = buffer ?? await fetch(url).then((r) => r.arrayBuffer());
      const durations = parseGifFrameDurations(buf);
      const totalMs = durations.reduce((sum, d) => sum + d, 0);

      const holder = document.createElement("div");
      holder.className = "pet-resume-gif-probe";
      const probe = document.createElement("img");
      probe.decoding = "sync";
      holder.appendChild(probe);
      document.body.appendChild(holder);

      await new Promise((resolve, reject) => {
        probe.onload = () => resolve(undefined);
        probe.onerror = () => reject(new Error("gif load failed"));
        probe.src = petAssetUrl(image, { preload: Date.now() });
      });

      const canvas = document.createElement("canvas");
      canvas.width = probe.naturalWidth;
      canvas.height = probe.naturalHeight;
      const ctx = canvas.getContext("2d");
      const frames = new Array(durations.length);

      const captures = durations.map((durationMs, i) => {
        const delay = durations.slice(0, i + 1).reduce((sum, d) => sum + d, 0) - 1;
        return sleepMs(Math.max(delay, 0)).then(() => {
          ctx.drawImage(probe, 0, 0);
          frames[i] = { src: canvas.toDataURL("image/png"), durationMs };
        });
      });

      await Promise.all(captures);
      holder.remove();

      if (!frames.length || frames.some((f) => !f)) return;

      this._deleteFrames = frames;
      this._deleteLastFrameSrc = frames[frames.length - 1].src;
      this._deleteAnimDurationMs = deleteCfg.durationMs ?? totalMs;
    } catch {
      /* 解析失败则不展示循环 GIF */
    }
  }

  _stopDeleteAnim() {
    if (this._deleteAnimTimer != null) {
      clearTimeout(this._deleteAnimTimer);
      this._deleteAnimTimer = null;
    }
    if (this._deleteFrameTimer != null) {
      clearTimeout(this._deleteFrameTimer);
      this._deleteFrameTimer = null;
    }
  }

  _clearDeleteAnimTimer() {
    this._stopDeleteAnim();
  }

  _cancelHideDeleteHint() {
    if (this._hideDeleteTimer != null) {
      clearTimeout(this._hideDeleteTimer);
      this._hideDeleteTimer = null;
    }
  }

  _isInDeleteZone(el) {
    if (!el || !(el instanceof Node)) return false;
    return this.stack.contains(el) || this.deleteBtn.contains(el);
  }

  _onDeleteZoneEnter() {
    this._cancelHideDeleteHint();
    void this._showDeleteHint();
  }

  _onDeleteZoneLeave(ev) {
    if (this._isInDeleteZone(ev.relatedTarget)) return;
    this._scheduleHideDeleteHint();
  }

  _scheduleHideDeleteHint() {
    this._cancelHideDeleteHint();
    this._hideDeleteTimer = setTimeout(() => {
      this._hideDeleteTimer = null;
      this._hideDeleteHint();
    }, this._deleteZoneGraceMs);
  }

  async _showDeleteHint() {
    if (!this.hasResume || this.deleting || this.uploading) return;

    if (!this.deleteBtn.hidden && this._deleteAnimFrozen) {
      if (this._deleteLastFrameSrc) {
        this.deleteImg.src = this._deleteLastFrameSrc;
      }
      return;
    }
    if (!this.deleteBtn.hidden) return;

    this._stopDeleteAnim();
    this._deleteAnimFrozen = false;
    this.deleteBtn.hidden = false;

    try {
      await this._deletePreloadPromise;
    } catch {
      /* ignore */
    }

    if (this._deleteFrames.length > 0) {
      this._playDeleteFrame(0);
      return;
    }

    this.deleteBtn.hidden = true;
  }

  _playDeleteFrame(index) {
    if (!this.hasResume || this.deleteBtn.hidden) return;
    const frames = this._deleteFrames;
    if (!frames.length || index >= frames.length) {
      this._showDeleteLastFrame();
      return;
    }

    const frame = frames[index];
    this.deleteImg.src = frame.src;

    if (index >= frames.length - 1) {
      this._deleteAnimFrozen = true;
      return;
    }

    this._deleteFrameTimer = setTimeout(() => {
      this._deleteFrameTimer = null;
      this._playDeleteFrame(index + 1);
    }, frame.durationMs);
  }

  _showDeleteLastFrame() {
    this._deleteAnimTimer = null;
    if (!this.hasResume || this.deleteBtn.hidden) return;
    if (this._deleteLastFrameSrc) {
      this.deleteImg.src = this._deleteLastFrameSrc;
    }
    this._deleteAnimFrozen = true;
  }

  _hideDeleteHint() {
    this._cancelHideDeleteHint();
    this._stopDeleteAnim();
    this._deleteAnimFrozen = false;
    this.deleteBtn.hidden = true;
    this.deleteImg.src = "";
  }

  async syncFromStatus() {
    try {
      const res = await fetch("/api/status");
      const json = await res.json();
      if (!json.ok) return;
      const data = json.data || {};
      const has =
        data.has_parsed_resume ||
        (Array.isArray(data.resumes) && data.resumes.length > 0);
      this.setHasResume(has);
    } catch {
      /* ignore */
    }
  }

  setHasResume(show) {
    this.hasResume = show;
    this.stack.hidden = !show;
    if (!show) this._hideDeleteHint();
    else this.deleteBtn.hidden = true;
  }

  async _deleteResume() {
    if (!this.hasResume || this.deleting) return;
    this.deleting = true;
    this._hideDeleteHint();
    setStatus("正在删除简历…");
    const name = this.cfg.name || "default";
    try {
      const res = await fetch(`/api/resume?name=${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error?.message || "删除失败");
      this.setHasResume(false);
      setStatus("简历已删除");
    } catch (err) {
      setStatus(err.message || "简历删除失败");
      if (this.hasResume) this.setHasResume(true);
    } finally {
      this.deleting = false;
    }
  }

  async _onFileSelected() {
    const file = this.fileInput.files?.[0];
    this.fileInput.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setStatus("请选择 PDF 格式的简历");
      return;
    }

    this.uploading = true;
    this.uploadBtn.classList.add("pet-resume-uploading");
    setStatus("正在上传并解析简历…");

    const form = new FormData();
    form.append("file", file);
    form.append("name", this.cfg.name || "default");
    form.append("title", "");
    form.append("auto_parse", "true");

    try {
      const res = await fetch("/api/resume/upload-pdf", { method: "POST", body: form });
      const raw = await res.text();
      let json;
      try {
        json = JSON.parse(raw);
      } catch {
        throw new Error(
          raw.startsWith("Internal")
            ? "服务器错误，请确认已安装 python-multipart、pypdf"
            : raw.slice(0, 120),
        );
      }
      if (!json.ok) throw new Error(json.error?.message || "上传失败");
      const data = json.data || {};
      this.setHasResume(true);
      const title = data.title ? ` · ${data.title}` : "";
      setStatus(`简历已上传${title}`);
      petDocumentCabinet?.markNew("resume");
      triggerSecretaryResumeParse(this.cfg.name || "default");
    } catch (err) {
      setStatus(err.message || "简历上传失败");
    } finally {
      this.uploading = false;
      this.uploadBtn.classList.remove("pet-resume-uploading");
    }
  }
}

const ARCHIVE_NEW_KEY = "pet-archive-new";

function loadArchiveNewSet() {
  try {
    const raw = localStorage.getItem(ARCHIVE_NEW_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

function saveArchiveNewSet(set) {
  try {
    localStorage.setItem(ARCHIVE_NEW_KEY, JSON.stringify([...set]));
  } catch {
    /* ignore */
  }
}

class PetDocumentCabinet {
  constructor(stage, cfg) {
    this.stage = stage;
    this.cfg = cfg || {};

    this.btn = document.createElement("button");
    this.btn.type = "button";
    this.btn.className = "pet-doc-cabinet";
    this.btn.style.left = `${cfg.x ?? 32}px`;
    this.btn.style.top = `${cfg.y ?? 128}px`;
    this.btn.title = cfg.label || "资料柜 · 查看档案";

    const img = document.createElement("img");
    img.src = petAssetUrl(cfg.image || "资料柜.png");
    img.alt = cfg.label || "资料柜";
    img.draggable = false;
    this.btn.appendChild(img);

    this.badge = document.createElement("span");
    this.badge.className = "pet-doc-cabinet-badge";
    this.badge.hidden = true;
    this.badge.textContent = "新";
    this.btn.appendChild(this.badge);

    bindPetImageScale(img, cfg.scale);

    this.btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      petArchiveManager?.openDrawer();
    });

    this.stage.appendChild(this.btn);
    this._syncBadge();
  }

  markNew(type) {
    const set = loadArchiveNewSet();
    set.add(type);
    saveArchiveNewSet(set);
    this._syncBadge();
  }

  clearNew(type) {
    const set = loadArchiveNewSet();
    set.delete(type);
    saveArchiveNewSet(set);
    this._syncBadge();
  }

  _syncBadge() {
    if (!this.badge) return;
    this.badge.hidden = loadArchiveNewSet().size === 0;
  }
}

class PetArchiveManager {
  constructor() {
    this.drawer = document.getElementById("petArchiveDrawer");
    this.drawerClose = document.getElementById("petArchiveDrawerClose");
    this.listEl = document.getElementById("petArchiveList");
    this.reportModal = document.getElementById("petArchiveReport");
    this.reportTitle = document.getElementById("petArchiveReportTitle");
    this.reportBody = document.getElementById("petArchiveReportBody");
    this.reportActions = document.getElementById("petArchiveReportActions");
    this.reportBack = document.getElementById("petArchiveReportBack");
    this.reportClose = document.getElementById("petArchiveReportClose");
    this.reportSheet = this.reportModal?.querySelector(".pet-archive-sheet");
    this.currentReportId = null;

    this.drawerClose?.addEventListener("click", () => this.closeDrawer());
    this.drawer?.addEventListener("click", (ev) => {
      if (ev.target === this.drawer) this.closeDrawer();
    });
    this.reportBack?.addEventListener("click", () => this.backToDrawer());
    this.reportClose?.addEventListener("click", () => this.closeAll());
    this.reportModal?.addEventListener("click", (ev) => {
      if (ev.target === this.reportModal) this.closeAll();
    });
  }

  async openDrawer() {
    if (!this.drawer || !this.listEl) return;
    this.closeReport();
    this.drawer.hidden = false;
    this.listEl.innerHTML = `<p class="pet-archive-hint">加载档案目录…</p>`;
    try {
      const status = await fetchPetAppStatus();
      this._renderDrawerList(status);
      setStatus("资料柜已打开 · 选择档案查看");
    } catch (err) {
      this.listEl.innerHTML = `<p class="pet-archive-hint pet-archive-hint-err">${escHtml(err?.message || "加载失败")}</p>`;
    }
  }

  closeDrawer() {
    if (this.drawer) this.drawer.hidden = true;
  }

  closeReport() {
    revokeResumePdfObjectUrl();
    if (this.reportModal) this.reportModal.hidden = true;
    this.currentReportId = null;
    if (this.reportActions) this.reportActions.innerHTML = "";
  }

  closeAll() {
    this.closeReport();
    this.closeDrawer();
  }

  backToDrawer() {
    this.closeReport();
    this.openDrawer();
  }

  _renderDrawerList(status) {
    const newSet = loadArchiveNewSet();
    const items = [
      {
        id: "resume",
        icon: "📃",
        title: "简历预览",
        sub: "上传的 PDF 原件",
        available: resumePreviewAvailable(status),
        locked: "请先在简历桌上传 PDF",
      },
      {
        id: "portrait",
        icon: "📄",
        title: "求职画像",
        sub: "简历与偏好摘要",
        available: !!(status.has_parsed_resume || status.has_preferences),
        locked: "请先上传并解析简历",
      },
      {
        id: "daily_picks",
        icon: "⭐",
        title: "每日精选",
        sub: "按日期查看精选岗位",
        available: true,
        locked: "",
      },
      {
        id: "shortlist",
        icon: "📌",
        title: "候选池查看",
        sub: "已加入候选池的岗位",
        available: true,
        locked: "",
      },
      {
        id: "daily_action_plan",
        icon: "🗓",
        title: "今日行动计划",
        sub: "秘书 AI 规划的优先事项",
        available: true,
        locked: "",
      },
      {
        id: "scout_strategy_plan",
        icon: "🧭",
        title: "侦察策略",
        sub: "最近一轮 LLM 翻页/深度计划",
        available: true,
        locked: "",
      },
      {
        id: "filtered_analysis",
        icon: "🚫",
        title: "分析筛掉",
        sub: "分析 AI 未通过的岗位与原因",
        available: true,
        locked: "",
      },
      {
        id: "reject_learning",
        icon: "📝",
        title: "拒绝与学习记录",
        sub: "你的拒绝理由与系统偏好调整",
        available: true,
        locked: "",
      },
      {
        id: "career",
        icon: "📋",
        title: "职业推理报告",
        sub: "主方向、路径与优短板",
        available: !!(status.has_career || status.has_preferences),
        locked: "请先完成职业方向对话",
      },
    ];
    this.listEl.innerHTML = "";
    for (const item of items) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pet-archive-item";
      btn.disabled = !item.available;
      const isNew = newSet.has(item.id);
      btn.innerHTML = `
        <span class="pet-archive-item-icon">${item.icon}</span>
        <span class="pet-archive-item-text">
          <div class="pet-archive-item-title">${escHtml(item.title)}</div>
          <div class="pet-archive-item-sub">${escHtml(item.available ? item.sub : item.locked)}</div>
        </span>
        ${isNew ? '<span class="pet-archive-item-badge">新</span>' : ""}
      `;
      if (item.available) {
        btn.addEventListener("click", () => this.openReport(item.id, { fromDrawer: true }));
      }
      this.listEl.appendChild(btn);
    }
  }

  async openReport(reportId, opts = {}) {
    if (!this.reportModal || !this.reportBody) return;
    if (!opts.fromDrawer) this.closeDrawer();
    this.currentReportId = reportId;
    this.reportModal.hidden = false;
    this.reportBody.innerHTML = `<p class="pet-archive-hint">加载中…</p>`;
    if (this.reportActions) this.reportActions.innerHTML = "";
    this.reportSheet?.classList.toggle("pet-archive-sheet--pdf", reportId === "resume");

    const titles = {
      resume: "简历预览",
      portrait: "求职画像",
      career: "职业推理报告",
      daily_picks: "每日精选",
      daily_action_plan: "今日行动计划",
      scout_strategy_plan: "侦察策略",
      shortlist: "候选池",
      filtered_analysis: "分析筛掉",
      reject_learning: "拒绝与学习记录",
    };
    if (this.reportTitle) this.reportTitle.textContent = titles[reportId] || "档案";

    try {
      if (reportId === "resume") {
        const status = await fetchPetAppStatus();
        if (!resumePreviewAvailable(status)) {
          this.reportBody.innerHTML = formatResumePreviewEmptyHtml();
          return;
        }
        this.reportBody.innerHTML = await loadResumePdfPreviewHtml(status);
        petDocumentCabinet?.clearNew("resume");
      } else if (reportId === "portrait") {
        const data = await loadSecretaryPortrait();
        this.reportBody.innerHTML = formatArchivePortraitHtml(data);
        petDocumentCabinet?.clearNew("portrait");
      } else if (reportId === "career") {
        let careerData = opts.careerData;
        if (!careerData) {
          const profileData = await fetchPetProfile();
          const career = profileData?.profile?.career;
          if (!career?.primary_direction) {
            this.reportBody.innerHTML = formatCareerReportEmptyHtml();
            this._renderCareerActions(false);
            return;
          }
          careerData = {
            career,
            memory_summary: profileData?.profile?.memory_summary || "",
          };
        }
        this.reportBody.innerHTML = formatCareerReportHtml(careerData);
        petDocumentCabinet?.clearNew("career");
        this._renderCareerActions(true);
      } else if (reportId === "daily_picks") {
        const reportDate = opts.reportDate || "today";
        await renderDailyPicksPanel(this.reportBody, reportDate);
        petDocumentCabinet?.clearNew("daily_picks");
      } else if (reportId === "daily_action_plan") {
        await renderDailyActionPlanPanel(this.reportBody, false);
        petDocumentCabinet?.clearNew("daily_action_plan");
      } else if (reportId === "scout_strategy_plan") {
        await renderScoutStrategyPlanPanel(this.reportBody);
        petDocumentCabinet?.clearNew("scout_strategy_plan");
      } else if (reportId === "shortlist") {
        await renderShortlistPanel(this.reportBody);
      } else if (reportId === "filtered_analysis") {
        await renderFilteredAnalysisPanel(this.reportBody);
      } else if (reportId === "reject_learning") {
        await renderRejectLearningPanel(this.reportBody);
      }
    } catch (err) {
      this.reportBody.innerHTML = `<p class="pet-archive-hint pet-archive-hint-err">${escHtml(err?.message || "加载失败")}</p>`;
    }
  }

  _renderCareerActions(hasCareer) {
    if (!this.reportActions) return;
    this.reportActions.innerHTML = "";
    const inferBtn = document.createElement("button");
    inferBtn.type = "button";
    inferBtn.className = "pet-archive-btn pet-archive-btn-primary";
    inferBtn.textContent = hasCareer ? "重新推理" : "生成推理报告";
    inferBtn.addEventListener("click", async () => {
      inferBtn.disabled = true;
      const prevText = inferBtn.textContent;
      inferBtn.textContent = "推理中…";
      try {
        const data = await inferCareerDirection();
        if (this.reportBody) this.reportBody.innerHTML = formatCareerReportHtml(data);
        petDocumentCabinet?.clearNew("career");
        inferBtn.textContent = "重新推理";
        setStatus("职业推理报告已更新 · 已存入资料柜");
      } catch (err) {
        setStatus(err?.message || "推理失败");
        inferBtn.textContent = prevText;
      } finally {
        inferBtn.disabled = false;
      }
    });
    this.reportActions.appendChild(inferBtn);
  }
}

class PetAgent {
  constructor(id, cfg, clips, optionalClips, destinations, moveCfg, activityCfg, globalCharScale = 1) {
    this.id = id;
    this.cfg = cfg;
    this.clips = { ...clips, ...(cfg.clips || {}) };
    for (const key of Object.keys(optionalClips || {})) {
      if (!Object.prototype.hasOwnProperty.call(cfg.clips || {}, key)) {
        delete this.clips[key];
      }
    }
    this.destinations = destinations || {};
    this.moveCfg = moveCfg || {};
    this.activityCfg = activityCfg || {};
    this.clipKey = "";
    this.sleepVariants = cfg.sleepVariants ?? 2;
    this.atLongRest = false;
    this.strolling = false;
    this.shortRestMode = null;
    this.moving = false;
    this._moveFrame = null;
    this._midSwitchTimer = null;
    this._strollPauseTimer = null;
    this._moveSegment = null;
    this.claimedRestSlot = null;
    this.restTargetPos = null;
    this.claimedInteractable = null;
    this._longRestMoveGen = 0;

    this.root = document.createElement("div");
    this.root.className = "pet-agent";
    const charScale = cfg.size ?? globalCharScale;
    this.root.style.setProperty("--char-scale", String(charScale));
    this._bubbleCfg = cfg.bubble || {};
    this._syncBubbleLayout();
    this._restoreDefaultFacing();

    this.img = document.createElement("img");
    this.img.alt = cfg.label || id;
    this.img.decoding = "async";
    this.img.addEventListener("load", () => this._syncBubbleLayout());

    this.root.appendChild(this.img);
    this.bubbleEl = null;
    this._bubbleTimer = null;
    this._taskBubbleText = "";
    this._applyPosition("sit");
  }

  _syncBubbleLayout() {
    const charScale = parseFloat(this.root.style.getPropertyValue("--char-scale")) || 1;
    const flipX = this.cfg.flipX ? -1 : 1;
    const headRatio = this._bubbleCfg.headRatio ?? 0.1;
    const gapScreen = this._bubbleCfg.gapScreen ?? 4;
    const offsetX = this._bubbleCfg.offsetX ?? 0;
    const fontSize = this._bubbleCfg.fontSize ?? 5;
    this.root.style.setProperty("--bubble-head-ratio", `${headRatio * 100}%`);
    this.root.style.setProperty("--bubble-gap-local", `${gapScreen / charScale}px`);
    this.root.style.setProperty("--bubble-offset-x-local", `${offsetX / (charScale * flipX)}px`);
    this.root.style.setProperty("--bubble-font-size", `${fontSize}px`);
  }

  _ensureBubbleEl() {
    if (!this.bubbleEl) {
      this.bubbleEl = document.createElement("div");
      this.bubbleEl.className = "pet-agent-bubble";
      this.root.appendChild(this.bubbleEl);
    }
    return this.bubbleEl;
  }

  _showBubbleText(text, { explain = false } = {}) {
    const el = this._ensureBubbleEl();
    el.classList.toggle("pet-agent-bubble--explain", explain);
    el.textContent = text;
    el.hidden = false;
  }

  _restoreTaskBubble() {
    if (this.bubbleEl) {
      this.bubbleEl.classList.remove("pet-agent-bubble--explain");
    }
    if (this._taskBubbleText) {
      this._showBubbleText(this._taskBubbleText);
    } else if (this.bubbleEl) {
      this.bubbleEl.hidden = true;
    }
  }

  setTaskBubble(text) {
    this._taskBubbleText = text || "";
    if (!this._bubbleTimer) this._restoreTaskBubble();
  }

  showHeadBubble(text, { durationMs = 0, explain = false } = {}) {
    if (this._bubbleTimer) {
      clearTimeout(this._bubbleTimer);
      this._bubbleTimer = null;
    }
    this._showBubbleText(text, { explain });
    if (durationMs > 0) {
      this._bubbleTimer = setTimeout(() => {
        this._bubbleTimer = null;
        this._restoreTaskBubble();
      }, durationMs);
    } else {
      this._taskBubbleText = text;
    }
  }

  hideHeadBubble() {
    if (this._bubbleTimer) {
      clearTimeout(this._bubbleTimer);
      this._bubbleTimer = null;
    }
    this._restoreTaskBubble();
  }

  _activityConfig() {
    return { ...this.activityCfg, ...(this.cfg.activity || {}) };
  }

  _currentPos() {
    return {
      x: parseFloat(this.root.style.left) || this.cfg.x,
      y: parseFloat(this.root.style.top) || this.cfg.y,
    };
  }

  _setPos(x, y) {
    this.root.style.left = `${x}px`;
    this.root.style.top = `${y}px`;
  }

  _restoreDefaultFacing() {
    this.root.style.setProperty("--flip-x", this.cfg.flipX ? "-1" : "1");
  }

  _setFacingToward(targetX) {
    const { x } = this._currentPos();
    this.root.style.setProperty("--flip-x", targetX >= x ? "1" : "-1");
  }

  _positionFor(clipKey) {
    const base = { x: this.cfg.x, y: this.cfg.y };
    const clipPos = this.cfg.positions?.[clipKey];
    if (!clipPos) return base;
    return { x: clipPos.x ?? base.x, y: clipPos.y ?? base.y };
  }

  _applyPosition(clipKey) {
    const pos = this._positionFor(clipKey);
    this._setPos(pos.x, pos.y);
  }

  _walkSpeed() {
    return this.cfg.move?.walkSpeed ?? this.moveCfg.walkSpeed ?? 42;
  }

  _runSpeed() {
    return this.cfg.move?.runSpeed ?? this.moveCfg.runSpeed ?? 78;
  }

  _speedForClip(clipKey) {
    return clipKey === "run" ? this._runSpeed() : this._walkSpeed();
  }

  _moveDuration(dist, clipKey) {
    const speed = Math.max(1, this._speedForClip(clipKey));
    const minMs = this.moveCfg.minDurationMs ?? 280;
    const maxMs = this.moveCfg.maxDurationMs ?? 8000;
    const ms = (dist / speed) * 1000;
    return Math.min(maxMs, Math.max(minMs, ms));
  }

  _strollTiming() {
    const local = this.cfg.stroll || {};
    const global = this._activityConfig();
    return {
      pauseMin: local.pauseMinMs ?? global.pauseMinMs ?? 600,
      pauseMax: local.pauseMaxMs ?? global.pauseMaxMs ?? 1800,
      switchMidMove: local.switchMidMove ?? global.switchMidMove ?? true,
      interactChance: local.interactChance ?? global.interactChance ?? 0.4,
    };
  }

  _activityBounds() {
    return normalizeActivityBounds(this._activityConfig().bounds);
  }

  canStroll() {
    return this._activityBounds() != null && this._hasMoveClips();
  }

  _randomPointInBounds() {
    return randomPointInBounds(this._activityBounds());
  }

  _isInExclude() {
    const bounds = this._activityBounds();
    if (!bounds) return false;
    const { x, y } = this._currentPos();
    return isPointExcluded(x, y, bounds);
  }

  _exitExcludeForStroll(onDone) {
    const bounds = this._activityBounds();
    const cur = this._currentPos();
    const exit = findNearestValidPoint(cur.x, cur.y, bounds);
    if (!exit) {
      this._stopStroll();
      return;
    }
    const clip = this._pickStrollMoveKind();
    this.moveTo(exit.x, exit.y, clip, onDone);
  }

  _releaseInteractable() {
    if (
      this.claimedInteractable &&
      interactableOccupancy.get(this.claimedInteractable) === this.id
    ) {
      interactableOccupancy.delete(this.claimedInteractable);
    }
    this.claimedInteractable = null;
  }

  _pickStrollTarget() {
    const activity = this._activityConfig();
    const bounds = this._activityBounds();
    const current = this._currentPos();
    const bowlItems = petBowls?.getActiveInteractables() || [];
    const interactables = [...bowlItems, ...(activity.interactables || [])];
    const available = interactables.filter((item) => !interactableOccupancy.has(item.id));
    const timing = this._strollTiming();

    if (available.length && Math.random() < timing.interactChance) {
      const shuffled = [...available].sort(() => Math.random() - 0.5);
      for (const pick of shuffled) {
        if (isPointExcluded(pick.x, pick.y, bounds)) continue;
        if (!isStrollMoveValid(current.x, current.y, pick.x, pick.y, bounds)) continue;
        const clip = pick.clip || "sit";
        if (!this.canInteractClip(clip)) continue;
        return { type: "interact", object: pick, x: pick.x, y: pick.y };
      }
    }

    for (let attempt = 0; attempt < 48; attempt += 1) {
      const point = this._randomPointInBounds();
      if (!point) break;
      if (!isStrollMoveValid(current.x, current.y, point.x, point.y, bounds)) continue;
      if (attempt < 40 && Math.hypot(point.x - current.x, point.y - current.y) < 12) continue;
      return { type: "roam", x: point.x, y: point.y };
    }
    return null;
  }

  _restSlotOptions() {
    const lr = this.cfg.longRest || {};
    const options = lr.options || ["nest", "sofa"];
    const keys = [];
    if (options.includes("nest") && this.cfg.nest) keys.push(`nest:${this.id}`);
    if (options.includes("sofa")) {
      for (let i = 0; i < (this.destinations.sofas?.length || 0); i += 1) {
        keys.push(`sofa:${i}`);
      }
    }
    return keys;
  }

  _posForRestSlot(slotKey) {
    if (slotKey.startsWith("nest:")) {
      if (!this.cfg.nest) return null;
      return { x: this.cfg.nest.x, y: this.cfg.nest.y };
    }
    if (slotKey.startsWith("sofa:")) {
      const idx = Number.parseInt(slotKey.split(":")[1], 10);
      const sofa = this.destinations.sofas?.[idx];
      if (!sofa) return null;
      return { x: sofa.x, y: sofa.y };
    }
    return null;
  }

  _fixedRestSlotKey() {
    const lr = this.cfg.longRest;
    if (!lr?.destination) return null;
    if (lr.destination === "nest") return `nest:${this.id}`;
    if (lr.destination === "sofa") return `sofa:${lr.sofaIndex ?? 0}`;
    return null;
  }

  _releaseRestSlot() {
    if (this.claimedRestSlot && restSlotOccupancy.get(this.claimedRestSlot) === this.id) {
      restSlotOccupancy.delete(this.claimedRestSlot);
    }
    this.claimedRestSlot = null;
    this.restTargetPos = null;
  }

  _claimRestSlot() {
    this._releaseRestSlot();
    const lr = this.cfg.longRest || {};
    if (lr.random === false) {
      const slot = this._fixedRestSlotKey();
      const pos = slot ? this._posForRestSlot(slot) : null;
      if (!slot || !pos || restSlotOccupancy.has(slot)) return null;
      restSlotOccupancy.set(slot, this.id);
      this.claimedRestSlot = slot;
      this.restTargetPos = pos;
      return pos;
    }
    const pool = this._restSlotOptions();
    const available = pool.filter((key) => !restSlotOccupancy.has(key));
    if (!available.length) return null;
    const pick = available[Math.floor(Math.random() * available.length)];
    const pos = this._posForRestSlot(pick);
    if (!pos) return null;
    restSlotOccupancy.set(pick, this.id);
    this.claimedRestSlot = pick;
    this.restTargetPos = pos;
    return pos;
  }

  _longRestSleepPos() {
    const target = this.restTargetPos || this._positionFor("sit");
    const override = this.cfg.positions?.sleepLong;
    if (!override) return target;
    return { x: override.x ?? target.x, y: override.y ?? target.y };
  }

  canLongRest() {
    return this._restSlotOptions().length > 0 && this._hasMoveClips();
  }

  _clipFiles(clipKey) {
    const val = this.clips[this._resolveClip(clipKey)];
    if (Array.isArray(val)) return val.filter(Boolean);
    if (val) return [val];
    return [];
  }

  _resolvePlayableClip(clipKey) {
    const key = clipKey === "drink" ? "eat" : clipKey;
    if (this._clipFiles(key).length) return key;
    return null;
  }

  canInteractClip(clipKey) {
    return this._resolvePlayableClip(clipKey) != null;
  }

  _hasMoveClips() {
    return this._clipFiles("walk").length > 0 || this._clipFiles("run").length > 0;
  }

  _pickClipFile(clipKey) {
    const files = this._clipFiles(clipKey);
    if (!files.length) return this._clipFiles("sit")[0] || "sit.gif";
    if (files.length === 1) return files[0];
    return files[Math.floor(Math.random() * files.length)];
  }

  _canSwitchMoveClip() {
    return this._clipFiles("walk").length + this._clipFiles("run").length > 1;
  }

  _pickStrollMoveKind(excludeKind = null) {
    const walkFiles = this._clipFiles("walk");
    const runFiles = this._clipFiles("run");
    if (walkFiles.length === 1 && !runFiles.length) return "walk";

    const movePref = this.cfg.stroll?.move ?? this._activityConfig().move ?? "random";
    if (movePref === "walk" && walkFiles.length) return "walk";
    if (movePref === "run" && runFiles.length) return "run";

    let kinds = [];
    if (walkFiles.length) kinds.push("walk");
    if (runFiles.length) kinds.push("run");
    if (excludeKind && kinds.length > 1) kinds = kinds.filter((k) => k !== excludeKind);
    if (!kinds.length) return excludeKind === "walk" ? "run" : "walk";
    return kinds[Math.floor(Math.random() * kinds.length)];
  }

  _pickMoveKind() {
    const lr = this.cfg.longRest || {};
    const walkFiles = this._clipFiles("walk");
    const runFiles = this._clipFiles("run");
    if (lr.move === "random") {
      const kinds = [];
      if (walkFiles.length) kinds.push("walk");
      if (runFiles.length) kinds.push("run");
      return kinds.length ? kinds[Math.floor(Math.random() * kinds.length)] : "walk";
    }
    if (lr.move === "run" && runFiles.length) return "run";
    if (walkFiles.length) return "walk";
    if (runFiles.length) return "run";
    return "walk";
  }

  _resolveClip(clipKey) {
    if ((clipKey === "sleepLong" || clipKey === "sleepShort") && this.sleepVariants < 2) {
      return "sleepShort";
    }
    return clipKey;
  }

  _clipFile(clipKey) {
    const resolved = this._resolveClip(clipKey);
    if (resolved === "walk" || resolved === "run" || resolved === "eat") {
      return this._pickClipFile(resolved);
    }
    const files = this._clipFiles(resolved);
    return files[0] || this._clipFiles("sit")[0] || "sit.gif";
  }

  _clearMoveTimers() {
    if (this._midSwitchTimer != null) {
      clearTimeout(this._midSwitchTimer);
      this._midSwitchTimer = null;
    }
  }

  _clearStrollTimers() {
    if (this._strollPauseTimer != null) {
      clearTimeout(this._strollPauseTimer);
      this._strollPauseTimer = null;
    }
    this._clearMoveTimers();
  }

  _stopStroll() {
    this.strolling = false;
    this.shortRestMode = null;
    this._releaseInteractable();
    this._clearStrollTimers();
    if (isScoutWorkPaused() && !this.atLongRest && !this.moving) {
      window.setTimeout(() => {
        if (isScoutWorkPaused() && !this.strolling && !this.atLongRest && !this.moving) {
          applyOffHoursActivityForAgent(this);
        }
      }, 1500 + Math.random() * 2500);
    }
  }

  _cancelMove() {
    if (this._moveFrame != null) {
      cancelAnimationFrame(this._moveFrame);
      this._moveFrame = null;
    }
    this.moving = false;
    this._moveSegment = null;
    this._clearMoveTimers();
  }

  _runMoveSegment(fromX, fromY, toX, toY, clipKey, onDone, opts = {}) {
    const dx = toX - fromX;
    const dy = toY - fromY;
    const dist = Math.hypot(dx, dy);
    if (dist < 0.5) {
      this._setPos(toX, toY);
      this.moving = false;
      this._moveSegment = null;
      onDone?.();
      return;
    }

    const duration = this._moveDuration(dist, clipKey);
    this.moving = true;
    this._moveSegment = { targetX: toX, targetY: toY, clipKey, onDone, opts };
    this._setFacingToward(toX);
    this._showClip(clipKey, null, true);

    if (opts.allowMidSwitch && this._canSwitchMoveClip() && this._strollTiming().switchMidMove) {
      const switchAt = 0.25 + Math.random() * 0.5;
      this._midSwitchTimer = setTimeout(() => {
        if (!this.moving || !this._moveSegment) return;
        const next = this._pickStrollMoveKind(clipKey);
        if (next === clipKey && this._clipFiles(next).length <= 1) return;
        const cur = this._currentPos();
        const seg = this._moveSegment;
        this._clearMoveTimers();
        if (this._moveFrame != null) cancelAnimationFrame(this._moveFrame);
        this._moveFrame = null;
        this._runMoveSegment(cur.x, cur.y, seg.targetX, seg.targetY, next, seg.onDone, seg.opts);
      }, duration * switchAt);
    }

    const t0 = performance.now();
    const bounds = opts.respectExclude ? this._activityBounds() : null;
    const step = (now) => {
      const t = Math.min(1, (now - t0) / duration);
      let x = fromX + dx * t;
      let y = fromY + dy * t;
      if (bounds && isPointExcluded(x, y, bounds)) {
        const prevT = Math.max(0, t - 1 / Math.max(2, Math.ceil(dist / 3)));
        x = fromX + dx * prevT;
        y = fromY + dy * prevT;
        this._setPos(x, y);
        this._moveFrame = null;
        this.moving = false;
        this._moveSegment = null;
        this._clearMoveTimers();
        onDone?.();
        return;
      }
      this._setPos(x, y);
      if (t < 1) {
        this._moveFrame = requestAnimationFrame(step);
        return;
      }
      this._moveFrame = null;
      this.moving = false;
      this._moveSegment = null;
      this._clearMoveTimers();
      this._setPos(toX, toY);
      onDone?.();
    };
    this._moveFrame = requestAnimationFrame(step);
  }

  moveTo(targetX, targetY, clipKey, onDone, opts = {}) {
    this._cancelMove();
    const start = this._currentPos();
    this._runMoveSegment(start.x, start.y, targetX, targetY, clipKey, onDone, opts);
  }

  _showClip(clipKey, pos = null, force = false) {
    const resolved = this._resolvePlayableClip(clipKey) || this._resolveClip(clipKey);
    if (!force && this.clipKey === resolved && this.img.src && !this.moving) return;
    this.clipKey = resolved;
    if (pos) this._setPos(pos.x, pos.y);
    else if (!this.moving && !this.atLongRest && !this.strolling) this._applyPosition(resolved);

    const playable = this._resolvePlayableClip(resolved);
    const file = playable
      ? this._clipFile(playable)
      : this._clipFiles("sit")[0] || "sit.gif";
    const url = petAssetUrl(`characters/${this.id}/${file}`);
    this.img.onerror = () => {
      const sitFile = this._clipFiles("sit")[0] || "sit.gif";
      const sitUrl = petAssetUrl(`characters/${this.id}/${sitFile}`);
      if (this.img.src !== sitUrl) this.img.src = sitUrl;
    };
    this.img.src = force
      ? petAssetUrl(`characters/${this.id}/${file}`, { t: Date.now() })
      : url;
    this._updateLegend();
  }

  setClip(clipKey, force = false) {
    if (force) {
      this._stopStroll();
      this._cancelMove();
      this.atLongRest = false;
      this._releaseRestSlot();
      this._restoreDefaultFacing();
    }
    if (this.moving && !force) return;
    this._showClip(clipKey, null, force);
  }

  _longRestMoveClip() {
    return this._pickMoveKind();
  }

  _longRestSleepClip() {
    return this.sleepVariants < 2 ? "sleepShort" : "sleepLong";
  }

  beginStroll() {
    if (this.strolling || !this.canStroll()) return;
    this.strolling = true;
    this.shortRestMode = "stroll";
    this.atLongRest = false;
    this._releaseRestSlot();
    this._strollStep();
    this._updateLegend();
  }

  _afterStrollArrive(target) {
    if (!this.strolling) return;
    if (target.type === "interact" && target.object) {
      const obj = target.object;
      this.claimedInteractable = obj.id;
      interactableOccupancy.set(obj.id, this.id);
      if (obj.bowl) petBowls?.consumeUse(obj.id);
      const clip = this._resolvePlayableClip(obj.clip || "sit");
      if (clip) {
        this._showClip(clip, { x: obj.x, y: obj.y }, true);
      } else {
        this._showClip("sit", { x: obj.x, y: obj.y }, true);
      }
      const pause = obj.pauseMs ?? 1800;
      this._strollPauseTimer = setTimeout(() => {
        this._releaseInteractable();
        if (this.strolling) this._strollStep();
      }, pause);
      return;
    }
    const timing = this._strollTiming();
    const pause = timing.pauseMin + Math.random() * Math.max(0, timing.pauseMax - timing.pauseMin);
    this._strollPauseTimer = setTimeout(() => this._strollStep(), pause);
  }

  _strollStep() {
    if (!this.strolling) return;
    if (this._isInExclude()) {
      this._exitExcludeForStroll(() => this._strollStep());
      return;
    }
    const target = this._pickStrollTarget();
    if (!target) {
      this._stopStroll();
      return;
    }
    const clip = this._pickStrollMoveKind();
    this.moveTo(target.x, target.y, clip, () => this._afterStrollArrive(target), {
      allowMidSwitch: true,
      respectExclude: true,
    });
  }

  endStroll(onDone) {
    if (!this.strolling) {
      onDone?.();
      return;
    }
    this._stopStroll();
    this._cancelMove();
    const home = this._positionFor("sit");
    const clip = this._pickStrollMoveKind();
    this.moveTo(home.x, home.y, clip, () => {
      this._restoreDefaultFacing();
      onDone?.();
    });
  }

  beginLongRest() {
    if (this.moving || this.atLongRest) return;
    this._stopStroll();
    this._cancelMove();
    this._longRestMoveGen += 1;
    const moveGen = this._longRestMoveGen;
    const target = this._claimRestSlot();
    if (!target) {
      this.setClip(this._longRestSleepClip(), true);
      return;
    }
    this.moveTo(target.x, target.y, this._longRestMoveClip(), () => {
      if (moveGen !== this._longRestMoveGen) return;
      this.atLongRest = true;
      this._restoreDefaultFacing();
      this._showClip(this._longRestSleepClip(), this._longRestSleepPos(), true);
    });
  }

  endLongRest(onDone) {
    this._longRestMoveGen += 1;
    this._cancelMove();
    if (!this.atLongRest) {
      this._releaseRestSlot();
      onDone?.();
      return;
    }
    const home = this._positionFor("sit");
    const moveClip = this._longRestMoveClip();
    this.atLongRest = false;
    this._releaseRestSlot();
    this.moveTo(home.x, home.y, moveClip, () => {
      this._restoreDefaultFacing();
      onDone?.();
    });
  }

  _updateLegend() {
    const chip = document.querySelector(`[data-agent="${this.id}"]`);
    if (!chip) return;
    chip.className = "pet-chip";
    if (this.strolling || ["work", "walk", "run", "eat", "drink"].includes(this.clipKey)) {
      chip.classList.add("work");
    }
    if (this.clipKey.startsWith("sleep")) chip.classList.add("rest");
    let label = CLIP_LABELS[this.clipKey] || this.clipKey;
    if (this.strolling && (this.clipKey === "walk" || this.clipKey === "run")) {
      label = CLIP_LABELS.stroll;
    }
    chip.innerHTML = `<strong>${this.cfg.label}</strong> ${label}`;
  }
}

function restClipForAgent(agentId, durationSec, isFatigue) {
  const agent = agents[agentId];
  if (!agent) return "sit";
  const threshold = petConfig?.restThresholdSec ?? 120;
  const sec = Number(durationSec) || 0;
  if (agent.sleepVariants < 2 && !agent.canLongRest()) return "sleepShort";
  if (isFatigue || sec >= threshold) return "sleepLong";
  return "sleepShort";
}

function applyShortRest(agent) {
  const sr = agent.cfg.shortRest || { random: true, options: ["idle", "stroll"] };
  let mode = "idle";
  if (sr.random !== false) {
    const opts = (sr.options || ["idle", "stroll"]).filter(
      (o) => o !== "stroll" || agent.canStroll(),
    );
    mode = opts.length ? opts[Math.floor(Math.random() * opts.length)] : "idle";
  } else {
    mode = sr.mode || "idle";
  }
  if (mode === "stroll" && agent.canStroll()) {
    if (!agent.strolling) agent.beginStroll();
    return;
  }
  agent.endStroll(() => {
    agent.shortRestMode = "idle";
    agent.setClip("sleepShort", true);
  });
}

function applyRestClip(agentId, durationSec, isFatigue) {
  const agent = agents[agentId];
  if (!agent) return;
  const clip = restClipForAgent(agentId, durationSec, isFatigue);
  if (clip === "sleepLong" && agent.canLongRest()) {
    if (!agent.atLongRest && !agent.moving) agent.beginLongRest();
    return;
  }
  agent._releaseRestSlot();
  agent.atLongRest = false;
  if (agent.strolling && clip === "sleepShort") return;
  if (
    agent.shortRestMode === "idle" &&
    !agent.strolling &&
    agent.clipKey === "sleepShort" &&
    clip === "sleepShort"
  ) {
    return;
  }
  applyShortRest(agent);
}

function finishRestActivity(agent, onDone) {
  agent.endStroll(() => agent.endLongRest(onDone));
}

function wakeFromRest(onDone) {
  const ids = ["ZC", "FX", "JK", "MS"];
  let left = ids.length;
  const finish = () => {
    left -= 1;
    if (left <= 0) onDone?.();
  };
  for (const id of ids) {
    const agent = agents[id];
    if (!agent) {
      finish();
      continue;
    }
    finishRestActivity(agent, finish);
  }
}

function setOfficeRest(isRest, durationSec, isFatigue) {
  if (scheduleOffHours) return;
  officeResting = isRest;
  if (isRest) {
    scheduleOfficeRestAutoResume(durationSec);
    applyRestClip("ZC", durationSec, isFatigue);
    applyRestClip("FX", durationSec, isFatigue);
    applyRestClip("JK", durationSec, isFatigue);
    refreshIdleAgentTasks();
    return;
  }
  clearOfficeRestTimer();
  wakeFromRest(() => {
    applyWorkdayAgentClips();
    refreshIdleAgentTasks();
  });
}

function resumeAfterRest() {
  if (scheduleOffHours) return;
  clearOfficeRestTimer();
  officeResting = false;
  wakeFromRest(() => {
    applyWorkdayAgentClips();
    setStatus(petLocalScouting ? "搜岗进行中 · 休息结束，继续工作" : "侦察进行中 · 休息结束，继续工作");
    setAgentTask("ZC", "继续搜岗");
    setAgentTask("FX", "待命分析");
    setAgentTask("JK", jkAlert ? "处理异常" : "监控浏览器");
  });
}

function loadPassScore(defaultScore = 60) {
  try {
    const prefs = loadScoutPrefs();
    if (prefs.pass_score != null) {
      const n = Number(prefs.pass_score);
      if (Number.isFinite(n)) return Math.min(100, Math.max(0, n));
    }
    const legacy = localStorage.getItem(PET_PASS_SCORE_KEY);
    if (legacy != null) {
      const n = Number(legacy);
      if (Number.isFinite(n)) {
        const score = Math.min(100, Math.max(0, n));
        savePassScore(score);
        return score;
      }
    }
  } catch {
    /* ignore */
  }
  return defaultScore;
}

function savePassScore(score) {
  try {
    const prefs = loadScoutPrefs();
    prefs.pass_score = score;
    localStorage.setItem(SCORE_STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* ignore */
  }
}

function loadCareerStagePrefs() {
  try {
    const prefs = loadScoutPrefs();
    const stage = String(prefs.career_stage || "junior");
    return {
      enabled: Boolean(prefs.career_stage_mode),
      stage: CAREER_STAGE_OPTIONS.some((o) => o.id === stage) ? stage : "junior",
    };
  } catch {
    return { enabled: false, stage: "junior" };
  }
}

function saveCareerStagePrefs(enabled, stage) {
  try {
    const prefs = loadScoutPrefs();
    prefs.career_stage_mode = Boolean(enabled);
    prefs.career_stage = CAREER_STAGE_OPTIONS.some((o) => o.id === stage) ? stage : "junior";
    localStorage.setItem(SCORE_STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* ignore */
  }
}

async function parseSecretaryResume(resumeName) {
  const resp = await fetch("/api/secretary/parse-resume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resume_name: resumeName || "default" }),
  });
  const body = await resp.json();
  if (!body?.ok) {
    throw new Error(body?.error?.message || "秘书解析简历失败");
  }
  return body.data;
}

async function triggerSecretaryResumeParse(resumeName) {
  const ms = agents.MS;
  if (!ms || ms.cfg?.enabled === false) return;

  ms.setTaskBubble("解析用户简历…");
  ms.setClip("work", true);

  try {
    await parseSecretaryResume(resumeName);
    ms.setClip("sit", true);
    ms.showHeadBubble("简历解析已完成", { durationMs: 5000 });
    setStatus("秘书 AI 已完成简历解析");
    petDocumentCabinet?.markNew("resume");
    refreshIdleAgentTasks();
  } catch (err) {
    ms.setClip("sit", true);
    refreshIdleAgentTasks();
    setStatus(err?.message || "秘书解析简历失败");
  }
}

/** @type {object | null} */
let monitorTokenUsage = null;
let monitorTokenPollTimer = null;

function getMonitorTokenPricingDefaults() {
  const panelCfg = petConfig?.deskPlates?.find((p) => p.agentId === "JK")?.panel;
  const pricing = panelCfg?.tokenPricing || {};
  return {
    input_per_m: pricing.inputPerM ?? 1,
    output_per_m: pricing.outputPerM ?? 2,
    symbol: pricing.currencySymbol || "¥",
  };
}

function applyMonitorTokenPricingFields(panelBody, pricing) {
  if (!panelBody || !pricing) return;
  const inputEl = panelBody.querySelector(".pet-jk-token-input-price");
  const outputEl = panelBody.querySelector(".pet-jk-token-output-price");
  if (inputEl && document.activeElement !== inputEl) {
    inputEl.value = String(pricing.input_per_m ?? getMonitorTokenPricingDefaults().input_per_m);
  }
  if (outputEl && document.activeElement !== outputEl) {
    outputEl.value = String(pricing.output_per_m ?? getMonitorTokenPricingDefaults().output_per_m);
  }
}

function applyMonitorTokenUsage(usage, panelBody = null) {
  if (!usage) return;
  monitorTokenUsage = usage;
  const scope = panelBody || document;
  const totalEl = scope.querySelector(".pet-jk-token-total-val");
  const costEl = scope.querySelector(".pet-jk-token-cost-val");
  const sessionTotal = usage.session_total || {};
  const cost = usage.cost || {};
  if (totalEl) totalEl.textContent = String(sessionTotal.total_tokens ?? 0);
  if (costEl) costEl.textContent = cost.formatted || `${cost.symbol || "¥"}0.00`;
  const pricingPanel = panelBody || document.querySelector(".pet-desk-panel-body-jk");
  if (usage.pricing) applyMonitorTokenPricingFields(pricingPanel, usage.pricing);
}

async function fetchMonitorTokenUsage() {
  const resp = await fetch("/api/monitor/token-usage", { cache: "no-store" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "无法读取 Token 统计");
  return body.data;
}

async function saveMonitorTokenPricing(panelBody) {
  const root = panelBody || document.querySelector(".pet-desk-panel-body-jk");
  const inputEl = root?.querySelector(".pet-jk-token-input-price");
  const outputEl = root?.querySelector(".pet-jk-token-output-price");
  if (!inputEl || !outputEl) return null;
  const input_per_m = Number(inputEl.value);
  const output_per_m = Number(outputEl.value);
  if (!Number.isFinite(input_per_m) || !Number.isFinite(output_per_m) || input_per_m < 0 || output_per_m < 0) {
    throw new Error("单价必须为非负数字");
  }
  const resp = await fetch("/api/monitor/token-pricing", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input_per_m, output_per_m }),
  });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "单价保存失败");
  if (body.data?.usage) applyMonitorTokenUsage(body.data.usage, root);
  return body.data;
}

async function refreshMonitorTokenPanel(panelBody) {
  try {
    const data = await fetchMonitorTokenUsage();
    applyMonitorTokenUsage(data, panelBody);
  } catch {
    const totalEl = panelBody?.querySelector(".pet-jk-token-total-val");
    const costEl = panelBody?.querySelector(".pet-jk-token-cost-val");
    if (totalEl) totalEl.textContent = "—";
    if (costEl) costEl.textContent = "—";
  }
}

function formatBossAuthStatus(boss) {
  if (!boss) {
    return { text: "无法读取 BOSS 状态", level: "err" };
  }
  if (boss.logged_in) {
    const age = boss.session_age_hours != null ? `（约 ${boss.session_age_hours} 小时前保存）` : "";
    const verifyNote = boss.verified ? "" : " · 本地缓存";
    return {
      text: `已登录${verifyNote} · ${boss.login_hint || "登录态有效"}${age}`,
      level: "ok",
    };
  }
  if (boss.session_stale || boss.session_load_failed || boss.persisted) {
    return {
      text: boss.login_hint || "本地登录态已过期，请同步或重新登录",
      level: "warn",
    };
  }
  return {
    text: "未登录 BOSS 直聘，请登录或从浏览器同步",
    level: "warn",
  };
}

function applyBossAuthPanel(panelBody, boss) {
  const statusEl = panelBody?.querySelector(".pet-jk-boss-status");
  const loginBtn = panelBody?.querySelector(".pet-jk-boss-login");
  const syncBtn = panelBody?.querySelector(".pet-jk-boss-sync");
  const logoutBtn = panelBody?.querySelector(".pet-jk-boss-logout");
  if (!statusEl) return;

  const { text, level } = formatBossAuthStatus(boss);
  statusEl.textContent = text;
  statusEl.className = `pet-jk-boss-status pet-jk-boss-status--${level}`;

  const loggedIn = !!boss?.logged_in;
  const hasPersisted = !!(boss?.session_stale || boss?.session_load_failed || boss?.persisted);
  if (loginBtn) loginBtn.hidden = loggedIn;
  if (syncBtn) syncBtn.hidden = loggedIn;
  if (logoutBtn) logoutBtn.hidden = !loggedIn && !hasPersisted;
}

async function fetchPetAppStatus({ bossSync = false } = {}) {
  const qs = bossSync ? "?boss_sync=1" : "";
  const resp = await fetch(`/api/status${qs}`, { cache: "no-store" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "无法读取状态");
  return body.data;
}

async function refreshBossAuthPanel(panelBody, { bossSync = false } = {}) {
  if (scheduleOffHours && !bossSync) return;
  try {
    const data = await fetchPetAppStatus({ bossSync });
    applyBossAuthPanel(panelBody, data.boss);
  } catch (err) {
    const statusEl = panelBody?.querySelector(".pet-jk-boss-status");
    if (statusEl) {
      statusEl.textContent = err?.message || "BOSS 状态加载失败";
      statusEl.className = "pet-jk-boss-status pet-jk-boss-status--err";
    }
  }
}

async function refreshMonitorPanel(panelBody, { bossSync = false } = {}) {
  const tasks = [refreshMonitorTokenPanel(panelBody)];
  if (!scheduleOffHours || bossSync) {
    tasks.push(refreshBossAuthPanel(panelBody, { bossSync }));
  }
  await Promise.all(tasks);
}

async function petBossLogin() {
  const resp = await fetch("/api/boss/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "登录失败");
  return body.data;
}

async function petBossSync() {
  const resp = await fetch("/api/boss/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "同步失败");
  return body.data;
}

async function petBossLogout() {
  const resp = await fetch("/api/boss/logout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "退出失败");
  return body.data;
}

function startMonitorTokenPoll(panel) {
  stopMonitorTokenPoll();
  monitorTokenPollTimer = setInterval(() => {
    const body = panel?.querySelector(".pet-desk-panel-body-jk");
    if (!body || panel.hidden) return;
    if (scheduleOffHours) {
      refreshMonitorTokenPanel(body);
      return;
    }
    refreshMonitorPanel(body);
  }, 2000);
}

function stopMonitorTokenPoll() {
  if (monitorTokenPollTimer) {
    clearInterval(monitorTokenPollTimer);
    monitorTokenPollTimer = null;
  }
}

function loadScoutPrefs() {
  try {
    const raw = localStorage.getItem(SCORE_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function loadScoutFiltersFromPrefs() {
  return loadScoutPrefs().scout_filters || null;
}

function saveScoutFiltersToPrefs(scoutFilters) {
  const prefs = loadScoutPrefs();
  prefs.scout_filters = scoutFilters;
  localStorage.setItem(SCORE_STORAGE_KEY, JSON.stringify(prefs));
}

function buildSelectOptions(options, selected) {
  return options.map((o) => `<option value="${escHtml(o)}"${o === selected ? " selected" : ""}>${escHtml(o)}</option>`).join("");
}

function buildScoutFilterPanelHtml() {
  const eduOpts = buildSelectOptions(EDUCATION_OPTIONS, "大专");
  const expOpts = buildSelectOptions(EXPERIENCE_OPTIONS, "1-3年");
  const weekendChecks = WEEKEND_OPTIONS.map(
    (m) => `<label class="pet-zc-sub-opt"><input type="checkbox" data-weekend="${escHtml(m)}"> ${escHtml(m)}</label>`,
  ).join("");
  const insuranceChecks = INSURANCE_OPTIONS.map(
    (m) => `<label class="pet-zc-sub-opt"><input type="checkbox" data-insurance="${escHtml(m)}"> ${escHtml(m)}</label>`,
  ).join("");
  return `
    <div class="pet-zc-filter-item">
      <label class="pet-zc-filter-main"><input type="checkbox" data-filter="salary"> ${SCOUT_FILTER_LABELS.salary}</label>
      <div class="pet-zc-filter-detail" data-detail="salary" hidden>
        <div class="pet-zc-range-row">
          <input type="number" class="pet-zc-range-input" data-salary-min min="1" max="200" placeholder="最低K">
          <span>-</span>
          <input type="number" class="pet-zc-range-input" data-salary-max min="1" max="200" placeholder="最高K">
        </div>
      </div>
    </div>
    <div class="pet-zc-filter-item">
      <label class="pet-zc-filter-main"><input type="checkbox" data-filter="education"> ${SCOUT_FILTER_LABELS.education}</label>
      <div class="pet-zc-filter-detail" data-detail="education" hidden>
        <div class="pet-zc-range-row">
          <select class="pet-zc-range-select" data-edu-min>${eduOpts}</select>
          <span>-</span>
          <select class="pet-zc-range-select" data-edu-max>${buildSelectOptions(EDUCATION_OPTIONS, "本科")}</select>
        </div>
      </div>
    </div>
    <div class="pet-zc-filter-item">
      <label class="pet-zc-filter-main"><input type="checkbox" data-filter="experience"> ${SCOUT_FILTER_LABELS.experience}</label>
      <div class="pet-zc-filter-detail" data-detail="experience" hidden>
        <div class="pet-zc-range-row">
          <select class="pet-zc-range-select" data-exp-min>${expOpts}</select>
          <span>-</span>
          <select class="pet-zc-range-select" data-exp-max>${buildSelectOptions(EXPERIENCE_OPTIONS, "5-10年")}</select>
        </div>
      </div>
    </div>
    <div class="pet-zc-filter-item">
      <label class="pet-zc-filter-main"><input type="checkbox" data-filter="overtime"> ${SCOUT_FILTER_LABELS.overtime}</label>
      <div class="pet-zc-filter-detail" data-detail="overtime" hidden>
        <p class="pet-zc-filter-note">按画像访谈中的加班接受度筛掉明显加班岗</p>
      </div>
    </div>
    <div class="pet-zc-filter-item">
      <label class="pet-zc-filter-main"><input type="checkbox" data-filter="weekend"> ${SCOUT_FILTER_LABELS.weekend}</label>
      <div class="pet-zc-filter-detail" data-detail="weekend" hidden>
        <div class="pet-zc-sub-options">${weekendChecks}</div>
      </div>
    </div>
    <div class="pet-zc-filter-item">
      <label class="pet-zc-filter-main"><input type="checkbox" data-filter="insurance"> ${SCOUT_FILTER_LABELS.insurance}</label>
      <div class="pet-zc-filter-detail" data-detail="insurance" hidden>
        <div class="pet-zc-sub-options">${insuranceChecks}</div>
      </div>
    </div>
  `;
}

function togglePetScoutFilterDetail(body, key, show) {
  const detail = body.querySelector(`.pet-zc-filter-detail[data-detail="${key}"]`);
  if (detail) detail.hidden = !show;
}

function getScoutFiltersFromPetPanel(body) {
  const payload = {};
  SCOUT_FILTER_KEYS.forEach((key) => {
    const el = body.querySelector(`input[data-filter="${key}"]`);
    payload[key] = !!(el && el.checked);
  });
  payload.salary_range = {
    min: body.querySelector("[data-salary-min]")?.value?.trim() || "",
    max: body.querySelector("[data-salary-max]")?.value?.trim() || "",
  };
  payload.education_range = {
    min: body.querySelector("[data-edu-min]")?.value || "",
    max: body.querySelector("[data-edu-max]")?.value || "",
  };
  payload.experience_range = {
    min: body.querySelector("[data-exp-min]")?.value || "",
    max: body.querySelector("[data-exp-max]")?.value || "",
  };
  payload.weekend_modes = [...body.querySelectorAll("input[data-weekend]:checked")]
    .map((el) => el.dataset.weekend);
  payload.insurance_types = [...body.querySelectorAll("input[data-insurance]:checked")]
    .map((el) => el.dataset.insurance);
  return payload;
}

function applyScoutFiltersToPetPanel(body, filters) {
  if (!filters || typeof filters !== "object") return;
  SCOUT_FILTER_KEYS.forEach((key) => {
    const el = body.querySelector(`input[data-filter="${key}"]`);
    const on = !!filters[key];
    if (el) el.checked = on;
    togglePetScoutFilterDetail(body, key, on);
  });
  const salary = filters.salary_range || {};
  const edu = filters.education_range || {};
  const exp = filters.experience_range || {};
  const salaryMin = body.querySelector("[data-salary-min]");
  const salaryMax = body.querySelector("[data-salary-max]");
  const eduMin = body.querySelector("[data-edu-min]");
  const eduMax = body.querySelector("[data-edu-max]");
  const expMin = body.querySelector("[data-exp-min]");
  const expMax = body.querySelector("[data-exp-max]");
  if (salaryMin && salary.min != null) salaryMin.value = salary.min;
  if (salaryMax && salary.max != null) salaryMax.value = salary.max;
  if (eduMin && edu.min) eduMin.value = edu.min;
  if (eduMax && edu.max) eduMax.value = edu.max;
  if (expMin && exp.min) expMin.value = exp.min;
  if (expMax && exp.max) expMax.value = exp.max;
  body.querySelectorAll("input[data-weekend]").forEach((el) => {
    el.checked = (filters.weekend_modes || []).includes(el.dataset.weekend);
  });
  body.querySelectorAll("input[data-insurance]").forEach((el) => {
    el.checked = (filters.insurance_types || []).includes(el.dataset.insurance);
  });
}

function wireScoutFilterPanel(body) {
  body.querySelectorAll("input[data-filter]").forEach((el) => {
    el.addEventListener("change", () => {
      togglePetScoutFilterDetail(body, el.dataset.filter, el.checked);
    });
  });
}

function validateScoutFilters(filters) {
  const enabled = SCOUT_FILTER_KEYS.filter((k) => filters[k]);
  if (!enabled.length) return "请至少勾选一项侦察硬性条件";
  if (filters.salary) {
    const min = Number(filters.salary_range?.min);
    const max = Number(filters.salary_range?.max);
    if (!min || !max) return "请设置薪资范围（最低与最高 K）";
    if (min > max) return "薪资最低值不能高于最高值";
  }
  if (filters.education && (!filters.education_range?.min || !filters.education_range?.max)) {
    return "请设置学历范围";
  }
  if (filters.experience && (!filters.experience_range?.min || !filters.experience_range?.max)) {
    return "请设置工作经验范围";
  }
  if (filters.weekend && !(filters.weekend_modes || []).length) {
    return "请至少选择一种休息制度";
  }
  if (filters.insurance && !(filters.insurance_types || []).length) {
    return "请至少选择一种社保福利";
  }
  return null;
}

const REGION_PLACEHOLDER_NAMES = new Set([
  "",
  "选择城市",
  "先选省份",
  "不限",
  "全市",
]);

function sanitizeScoutLocation(loc) {
  const out = {
    province_code: String(loc?.province_code || "").trim(),
    city: String(loc?.city || "").trim(),
    city_code: String(loc?.city_code || "").trim(),
    district_code: String(loc?.district_code || "").trim(),
    district_name: String(loc?.district_name || "").trim(),
  };
  if (REGION_PLACEHOLDER_NAMES.has(out.city)) out.city = "";
  if (!out.city_code) {
    out.city = "";
    out.district_code = "";
    out.district_name = "";
  }
  if (!out.province_code && !out.city_code) {
    out.city = "";
    out.district_code = "";
    out.district_name = "";
  }
  return out;
}

function loadPetScoutQueryPrefs() {
  try {
    const raw = localStorage.getItem(PET_SCOUT_QUERY_KEY);
    return sanitizeScoutLocation(raw ? JSON.parse(raw) : {});
  } catch {
    return sanitizeScoutLocation({});
  }
}

function savePetScoutQueryPrefs(query, locOrCity) {
  try {
    const payload = { query: query || "" };
    if (locOrCity && typeof locOrCity === "object") {
      const loc = sanitizeScoutLocation(locOrCity);
      payload.province_code = loc.province_code;
      payload.city = loc.city;
      payload.city_code = loc.city_code;
      payload.district_code = loc.district_code;
    } else {
      payload.city = locOrCity || "";
    }
    localStorage.setItem(PET_SCOUT_QUERY_KEY, JSON.stringify(payload));
  } catch {
    /* ignore */
  }
}

function formatRegionLabel(loc) {
  if (!loc) return "";
  if (loc.city && loc.district_name) return `${loc.city} · ${loc.district_name}`;
  if (loc.city) return loc.city;
  return "";
}

function getRegionSelectionFromPanel(body) {
  const provSel = body?.querySelector(".pet-zc-province-select");
  const citySel = body?.querySelector(".pet-zc-city-select");
  const distSel = body?.querySelector(".pet-zc-district-select");
  const cityOpt = citySel?.selectedOptions?.[0];
  const distOpt = distSel?.selectedOptions?.[0];
  const cityCode = citySel?.value || "";
  const districtCode = distSel?.value || "";
  return sanitizeScoutLocation({
    province_code: provSel?.value || "",
    city: cityCode ? (cityOpt?.dataset?.name || cityOpt?.textContent || "") : "",
    city_code: cityCode,
    district_code: districtCode,
    district_name: districtCode ? (distOpt?.dataset?.name || distOpt?.textContent || "") : "",
  });
}

function validateScoutRegion(loc) {
  const clean = sanitizeScoutLocation(loc);
  if (clean.province_code && !clean.city_code) {
    return "已选省/直辖市但未选城市，请选城市或改回「不限」";
  }
  return null;
}

function persistZcRegionFromPanel(body) {
  const queryEl = document.getElementById("petScoutQuery");
  savePetScoutQueryPrefs(queryEl?.value?.trim() || "", getRegionSelectionFromPanel(body));
}

function fillSelectOptions(sel, items, { emptyLabel, valueKey = "code", labelKey = "name", preferred }) {
  if (!sel) return;
  sel.innerHTML = "";
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = emptyLabel;
  sel.appendChild(empty);
  for (const item of items || []) {
    const opt = document.createElement("option");
    opt.value = String(item[valueKey] || "");
    opt.textContent = String(item[labelKey] || "");
    opt.dataset.name = String(item[labelKey] || "");
    sel.appendChild(opt);
  }
  if (preferred && [...sel.options].some((o) => o.value === preferred)) {
    sel.value = preferred;
  }
}

function findProvinceCities(provinceCode) {
  const tree = petRegionsCache || [];
  const prov = tree.find((p) => String(p.code) === String(provinceCode));
  return prov?.cities || [];
}

function findCityDistricts(provinceCode, cityCode) {
  const cities = findProvinceCities(provinceCode);
  const city = cities.find((c) => String(c.code) === String(cityCode));
  return city?.districts || [];
}

function findProvinceForCityCode(cityCode) {
  if (!cityCode) return null;
  for (const prov of petRegionsCache || []) {
    for (const city of prov.cities || []) {
      if (String(city.code) === String(cityCode)) return prov;
    }
  }
  return null;
}

function findCityByName(cityName) {
  if (!cityName) return null;
  for (const prov of petRegionsCache || []) {
    for (const city of prov.cities || []) {
      if (city.name === cityName) return { province: prov, city };
    }
  }
  return null;
}

function syncZcPanelRegionSelects(body) {
  if (!body) return;
  const prefs = loadPetScoutQueryPrefs();
  const provSel = body.querySelector(".pet-zc-province-select");
  const citySel = body.querySelector(".pet-zc-city-select");
  const distSel = body.querySelector(".pet-zc-district-select");
  if (!provSel || !citySel || !distSel) return;

  const tree = petRegionsCache || [];
  let preferredProv = prefs.province_code || "";
  let preferredCity = prefs.city_code || "";
  let preferredDist = prefs.district_code || "";

  if (!preferredCity && prefs.city) {
    const hit = findCityByName(prefs.city);
    if (hit) {
      preferredProv = hit.province.code;
      preferredCity = hit.city.code;
    }
  }
  if (preferredCity && !preferredProv) {
    const prov = findProvinceForCityCode(preferredCity);
    if (prov) preferredProv = prov.code;
  }

  fillSelectOptions(provSel, tree, {
    emptyLabel: "不限",
    preferred: preferredProv,
  });

  if (!preferredProv) {
    citySel.disabled = true;
    distSel.disabled = true;
    fillSelectOptions(citySel, [], { emptyLabel: "先选省份" });
    fillSelectOptions(distSel, [], { emptyLabel: "全市" });
    return;
  }

  citySel.disabled = false;
  fillSelectOptions(citySel, findProvinceCities(preferredProv), {
    emptyLabel: "选择城市",
    preferred: preferredCity,
  });

  if (!preferredCity) {
    distSel.disabled = true;
    fillSelectOptions(distSel, [], { emptyLabel: "全市" });
    return;
  }

  distSel.disabled = false;
  fillSelectOptions(distSel, findCityDistricts(preferredProv, preferredCity), {
    emptyLabel: "全市",
    preferred: preferredDist,
  });
}

function wireZcRegionSelects(body) {
  if (!body || body._regionWired) return;
  body._regionWired = true;
  const provSel = body.querySelector(".pet-zc-province-select");
  const citySel = body.querySelector(".pet-zc-city-select");
  const distSel = body.querySelector(".pet-zc-district-select");

  provSel?.addEventListener("change", () => {
    const pcode = provSel.value;
    if (!pcode) {
      citySel.disabled = true;
      distSel.disabled = true;
      fillSelectOptions(citySel, [], { emptyLabel: "先选省份" });
      fillSelectOptions(distSel, [], { emptyLabel: "全市" });
      persistZcRegionFromPanel(body);
      return;
    }
    citySel.disabled = false;
    distSel.disabled = true;
    fillSelectOptions(citySel, findProvinceCities(pcode), { emptyLabel: "选择城市" });
    fillSelectOptions(distSel, [], { emptyLabel: "全市" });
    persistZcRegionFromPanel(body);
  });

  citySel?.addEventListener("change", () => {
    const pcode = provSel?.value || "";
    const ccode = citySel.value;
    if (!ccode) {
      distSel.disabled = true;
      fillSelectOptions(distSel, [], { emptyLabel: "全市" });
      persistZcRegionFromPanel(body);
      return;
    }
    distSel.disabled = false;
    fillSelectOptions(distSel, findCityDistricts(pcode, ccode), { emptyLabel: "全市" });
    persistZcRegionFromPanel(body);
  });

  distSel?.addEventListener("change", () => {
    persistZcRegionFromPanel(body);
  });
}

function getPetScoutLocation() {
  const panel = document.querySelector(".pet-desk-panel-body-zc");
  if (panel) {
    const loc = getRegionSelectionFromPanel(panel);
    if (loc.city_code || loc.province_code) return loc;
  }
  return loadPetScoutQueryPrefs();
}

function getPetScoutCity() {
  const loc = getPetScoutLocation();
  return loc.city || null;
}

async function loadPetRegions() {
  try {
    const resp = await fetch("/api/boss/regions", { cache: "no-store" });
    const body = await resp.json();
    if (!body?.ok) throw new Error(body?.error?.message || "加载地区失败");
    petRegionsCache = body.data;
  } catch (err) {
    petRegionsCache = null;
    setStatus(`地区列表加载失败：${err?.message || "网络错误"}`);
  }
  document.querySelectorAll(".pet-desk-panel-body-zc").forEach((body) => {
    syncZcPanelRegionSelects(body);
  });
}

async function loadPetCities() {
  try {
    const resp = await fetch("/api/boss/cities", { cache: "no-store" });
    const body = await resp.json();
    if (!body?.ok) throw new Error(body?.error?.message || "加载城市失败");
    petCitiesCache = body.data;
  } catch (err) {
    petCitiesCache = FALLBACK_CITIES;
  }
  await loadPetRegions();
}

function getPetScorePrefs() {
  const pass_score = loadPassScore(petConfig?.analysis?.defaultPassScore ?? 60);
  const scout_filters = loadScoutFiltersFromPrefs() || {};
  const career = loadCareerStagePrefs();
  const prefs = loadScoutPrefs();
  if (!career.enabled) {
    prefs.pass_score = pass_score;
  }
  prefs.scout_filters = scout_filters;
  prefs.career_stage_mode = career.enabled;
  prefs.career_stage = career.stage;
  localStorage.setItem(SCORE_STORAGE_KEY, JSON.stringify(prefs));
  return {
    pass_score: career.enabled ? undefined : pass_score,
    scout_filters,
    career_stage: { enabled: career.enabled, stage: career.stage },
  };
}

function updatePetScoutControls(running) {
  const startBtn = document.getElementById("petScoutStart");
  const stopBtn = document.getElementById("petScoutStop");
  const queryEl = document.getElementById("petScoutQuery");
  if (startBtn) {
    startBtn.disabled = running;
    startBtn.hidden = running;
  }
  if (stopBtn) {
    stopBtn.disabled = !running;
    stopBtn.hidden = !running;
  }
  if (queryEl) queryEl.disabled = running;
  document.querySelectorAll(".pet-zc-city-select").forEach((sel) => {
    sel.disabled = running;
  });
}

function getPassedJobDisplayCount(stats) {
  const sidebarCount = petJobSidebar?.getJobCount?.();
  if (typeof sidebarCount === "number") return sidebarCount;
  return stats?.analysis?.jobs_passed ?? 0;
}

function formatScoutStatsMessage(stats) {
  const s = stats?.scout;
  const a = stats?.analysis;
  if (!s) return "";
  const parts = [
    `扫描 ${s.jobs_seen ?? 0}`,
    `传输 ${s.jobs_new_transmitted ?? 0}`,
  ];
  if (a) parts.push(`通过 ${getPassedJobDisplayCount(stats)}`);
  return parts.join(" · ");
}

/** 办公室标题小字：只展示搜岗统计，不展示休息/同步等文案 */
function formatPetHeaderScoutStats(stats) {
  const s = stats?.scout || {};
  const a = stats?.analysis || {};
  const seen = Number(s.jobs_seen ?? 0) || 0;
  const scoutPassed = Number(s.jobs_scout_passed ?? 0) || 0;
  const analysisPassed = getPassedJobDisplayCount(stats != null ? stats : { analysis: a });
  return `已侦察 ${seen} · 侦察通过 ${scoutPassed} · 分析通过 ${analysisPassed}`;
}

function rememberPetScoutHeaderStats(stats) {
  if (!stats || typeof stats !== "object") return;
  petScoutHeaderStats = stats;
}

function refreshPetHeaderScoutStats() {
  if (!(petLocalScouting && !scheduleOffHours && !petScoutOffHoursPaused)) return;
  const el = document.getElementById("petStatus");
  if (!el) return;
  el.textContent = formatPetHeaderScoutStats(petScoutHeaderStats);
}

function refreshPetScoutStatusLine(event) {
  if (scheduleOffHours || petScoutOffHoursPaused) return;
  if (!petLocalScouting) return;
  const q = String(
    event?.query
    || event?.next_query
    || event?.stats?.search?.current_query
    || petMonitorSidebar?.searchQuery
    || "",
  ).trim();
  if (q && petMonitorSidebar && petMonitorSidebar.searchQuery !== q) {
    petMonitorSidebar.searchQuery = q;
    petMonitorSidebar._renderLocation?.();
  }
  if (event?.stats) rememberPetScoutHeaderStats(event.stats);
  refreshPetHeaderScoutStats();
}

function updatePetScoutStreamStatus(event) {
  if (!event?.stats && event?.type !== "scout_heartbeat") return;
  if (petScoutOffHoursPaused || scheduleOffHours) return;
  refreshPetScoutStatusLine(event);
}

function applyScoutStreamStateFromEvent(ev) {
  const type = ev?.type || "";
  if (!type || scheduleOffHours) return;
  if (type === "round_fatigue_pause") {
    const sec = ev.pause_sec ?? ev.remaining_sec ?? petConfig?.restThresholdSec ?? 120;
    setOfficeRest(true, sec, true);
  } else if (type === "round_pause") {
    const sec = ev.pause_sec ?? ev.remaining_sec ?? 60;
    setOfficeRest(true, sec, false);
  } else if (
    type === "round_resume" ||
    type === "page_start" ||
    type === "search_fetch" ||
    type === "page_turn"
  ) {
    if (officeResting) resumeAfterRest();
    petMonitorSidebar?.exitRestState?.();
  } else if (type === "scout_heartbeat" && officeResting) {
    const sec = ev.remaining_sec ?? 0;
    if (sec <= 0) {
      resumeAfterRest();
      petMonitorSidebar?.exitRestState?.();
    }
  }
}

function buildPetScoutAckBody() {
  return {
    page: petMonitorSidebar?.searchPage != null ? Number(petMonitorSidebar.searchPage) : null,
    query: String(petMonitorSidebar?.searchQuery || ""),
    type: String(petMonitorSidebar?.lastEventType || ""),
    sse_at: Date.now(),
    // 最小化/切后台时浏览器会节流主线程定时器；后端据此放宽超时
    hidden: typeof document !== "undefined" ? !!document.hidden : false,
  };
}

function pushAckBodyToWorker() {
  if (!petScoutAckWorker) return;
  try {
    const body = buildPetScoutAckBody();
    petScoutAckWorker.postMessage({ type: "update", body });
    petScoutAckWorker.postMessage({ type: "setHidden", hidden: !!body.hidden });
  } catch {
    /* ignore */
  }
}

function sendPetScoutAck() {
  if (!petLocalScouting) return;
  petScoutAckPending = false;
  const body = buildPetScoutAckBody();
  pushAckBodyToWorker();
  fetch("/api/boss/scout/ack", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    keepalive: true,
  }).catch(() => {});
}

function wirePetScoutVisibilityAck() {
  if (petScoutVisibilityWired || typeof document === "undefined") return;
  petScoutVisibilityWired = true;
  document.addEventListener("visibilitychange", () => {
    if (!petLocalScouting) return;
    // 隐藏时也继续跑：只上报 hidden，后端放宽超时，不暂停管道
    sendPetScoutAck();
    if (document.hidden) {
      setStatus("页面已隐藏，搜岗继续在后台运行…");
      return;
    }
    // 回到前台：强制追上服务端最新页码/状态（浏览器后台时 UI 可能没刷新）
    void syncScoutLiveFromServer({ resumeUi: true });
    while (petScoutEventQueue.length) {
      drainPetScoutEventQueue();
    }
    petMonitorSidebar?._render?.();
  });
}

async function syncScoutLiveFromServer(opts = {}) {
  try {
    const resp = await fetch("/api/boss/scout/live", { cache: "no-store" });
    const body = await resp.json();
    if (!body?.ok) return null;
    const data = body.data || {};
    applyScoutLiveCatchUp(data, opts);
    return data;
  } catch {
    return null;
  }
}

/** 从 live 快照补拉：页码/统计/已通过岗位（SSE 丢事件后的兜底） */
function applyScoutLiveCatchUp(data, opts = {}) {
  if (!data || typeof data !== "object") return;
  if (data.server_query || data.server_page) {
    petMonitorSidebar?.setSearchContext(
      data.server_query || petMonitorSidebar.searchQuery || "",
      data.server_page > 0 ? data.server_page : petMonitorSidebar.searchPage,
    );
  }
  if (data.stats) {
    rememberPetScoutHeaderStats(data.stats);
    refreshPetHeaderScoutStats();
  }
  if (Array.isArray(data.passed_jobs) && data.passed_jobs.length) {
    let added = 0;
    for (const job of data.passed_jobs) {
      const before = petJobSidebar?.getJobCount?.() ?? 0;
      petJobSidebar?.addJob(job);
      const after = petJobSidebar?.getJobCount?.() ?? 0;
      if (after > before) {
        added += 1;
        petScoutJobCount = Math.max(petScoutJobCount, after);
      }
    }
    if (added > 0) refreshPetHeaderScoutStats();
  }
  if (data.last_error) {
    petMonitorSidebar?.setStreamState?.("error", data.last_error);
    if (!petLocalScouting) setStatus(data.last_error);
  } else if (data.ui_stale || data.last_warn) {
    petMonitorSidebar?.setStreamState?.(
      petLocalScouting ? "streaming" : (petMonitorSidebar.streamState || "idle"),
      data.last_warn || "已从快照同步岗位进度",
    );
  } else if (data.last_message && opts.resumeUi && petMonitorSidebar) {
    petMonitorSidebar.progress = data.last_message;
  }
  if (opts.resumeUi && data.page_hidden === false && petLocalScouting) {
    petMonitorSidebar?.exitRestState?.();
    petMonitorSidebar?.setStreamState?.("streaming");
    if (
      petMonitorSidebar
      && (petMonitorSidebar.stage === "页面隐藏暂停" || petMonitorSidebar.stage === "本轮休息")
      && data.server_page > 0
    ) {
      petMonitorSidebar.stage = "列表翻页";
    }
    refreshPetHeaderScoutStats();
  }
  petMonitorSidebar?._render?.();
}

let petScoutLivePollTimer = null;

function startPetScoutLivePoll() {
  stopPetScoutLivePoll();
  petScoutLivePollTimer = setInterval(() => {
    if (!petLocalScouting) return;
    void syncScoutLiveFromServer({ resumeUi: false });
  }, 8000);
}

function stopPetScoutLivePoll() {
  if (petScoutLivePollTimer != null) {
    clearInterval(petScoutLivePollTimer);
    petScoutLivePollTimer = null;
  }
}

function syncScoutStreamMeta(event) {
  if (!event) return;
  if (event.stats) rememberPetScoutHeaderStats(event.stats);
  applyScoutStreamStateFromEvent(event);
  petMonitorSidebar?.syncEventMeta(event);
  updatePetScoutStreamStatus(event);
  petScoutAckPending = true;
  sendPetScoutAck();
}

function schedulePetScoutEventDrain() {
  if (petScoutEventDrainScheduled) return;
  petScoutEventDrainScheduled = true;
  queueMicrotask(() => {
    petScoutEventDrainScheduled = false;
    drainPetScoutEventQueue();
  });
}

function drainPetScoutEventQueue() {
  if (!petScoutEventQueue.length) return;
  const catchUp = petScoutEventQueue.length > PET_SCOUT_UI_CATCHUP_THRESHOLD;
  const batchSize = catchUp ? PET_SCOUT_UI_CATCHUP_BATCH : PET_SCOUT_UI_DRAIN_BATCH;
  let processed = 0;
  while (petScoutEventQueue.length && processed < batchSize) {
    const ev = petScoutEventQueue.shift();
    handleScoutEvent(ev, { local: true, catchUp });
    processed += 1;
  }
  if (petScoutEventQueue.length) schedulePetScoutEventDrain();
}

function enqueuePetScoutStreamEvent(event) {
  syncScoutStreamMeta(event);
  const type = event?.type || "";
  // 高频事件 meta 已同步；积压时跳过 UI 队列，避免主线程卡死导致 SSE 读不动
  if (PET_SCOUT_HIGH_FREQ_EVENTS.has(type) && petScoutEventQueue.length >= PET_SCOUT_UI_CATCHUP_THRESHOLD) {
    return;
  }
  petScoutEventQueue.push(event);
  schedulePetScoutEventDrain();
}

function startPetScoutAckPulse() {
  stopPetScoutAckPulse();
  startPetScoutLivePoll();
  wirePetScoutVisibilityAck();
  const body = buildPetScoutAckBody();
  // Worker 心跳：后台标签对主线程 setInterval 节流更狠，Worker 更稳
  try {
    const workerSrc = `
      let timer = null;
      let payload = {};
      let hiddenFlag = false;
      async function tick() {
        try {
          const body = Object.assign({}, payload, { hidden: hiddenFlag });
          await fetch("/api/boss/scout/ack", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
        } catch (e) {}
      }
      self.onmessage = (ev) => {
        const msg = ev.data || {};
        if (msg.type === "update") {
          payload = msg.body || payload;
          if (typeof payload.hidden === "boolean") hiddenFlag = payload.hidden;
        } else if (msg.type === "setHidden") {
          hiddenFlag = !!msg.hidden;
        } else if (msg.type === "start") {
          payload = msg.body || {};
          if (typeof payload.hidden === "boolean") hiddenFlag = payload.hidden;
          if (timer) clearInterval(timer);
          tick();
          timer = setInterval(tick, msg.intervalMs || 5000);
        } else if (msg.type === "stop") {
          if (timer) clearInterval(timer);
          timer = null;
        }
      };
    `;
    const blob = new Blob([workerSrc], { type: "application/javascript" });
    petScoutAckWorkerUrl = URL.createObjectURL(blob);
    petScoutAckWorker = new Worker(petScoutAckWorkerUrl);
    petScoutAckWorker.postMessage({ type: "start", body, intervalMs: 5000 });
  } catch {
    petScoutAckWorker = null;
  }
  const pulse = () => {
    if (!petLocalScouting) return;
    sendPetScoutAck();
  };
  pulse();
  // 主线程兜底（Worker 不可用时仍有心跳）
  petScoutAckTimer = setInterval(pulse, 5000);
}

function stopPetScoutAckPulse() {
  stopPetScoutLivePoll();
  if (petScoutAckTimer != null) {
    clearInterval(petScoutAckTimer);
    petScoutAckTimer = null;
  }
  if (petScoutAckWorker) {
    try {
      petScoutAckWorker.postMessage({ type: "stop" });
      petScoutAckWorker.terminate();
    } catch {
      /* ignore */
    }
    petScoutAckWorker = null;
  }
  if (petScoutAckWorkerUrl) {
    try {
      URL.revokeObjectURL(petScoutAckWorkerUrl);
    } catch {
      /* ignore */
    }
    petScoutAckWorkerUrl = null;
  }
}

function resetPetScoutEventQueue() {
  petScoutEventQueue.length = 0;
  petScoutEventDrainScheduled = false;
}

function stopPetScoutStream() {
  setScoutAutoRun(false);
  setScoutUserStopped(true);
  petScoutStopRequested = true;
  stopPetScoutAckPulse();
  // 先通知后端停任务；再断开本地 SSE（断开本身不再杀任务）
  void fetch("/api/boss/scout/stop", { method: "POST", keepalive: true }).catch(() => {});
  if (petScoutAbortController) {
    petScoutAbortController.abort();
  }
}

async function subscribePetScoutEvents(opts = {}) {
  if (petScoutAbortController) {
    try {
      petScoutAbortController.abort();
    } catch {
      /* ignore */
    }
  }
  petScoutAbortController = new AbortController();
  const resume = !!opts.resume;
  try {
    const resp = await fetch("/api/boss/scout/events", {
      method: "GET",
      signal: petScoutAbortController.signal,
      cache: "no-store",
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error?.message || `订阅失败 (${resp.status})`);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let sseBatch = 0;
    petMonitorSidebar?.setStreamState("streaming");

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const payload = JSON.parse(line.slice(5).trim());
        if (payload.idle) {
          if (resume) {
            petLocalScouting = false;
            return;
          }
          throw new Error("后端暂无搜岗任务");
        }
        if (payload.snapshot) {
          applyScoutLiveCatchUp(payload.snapshot, { resumeUi: resume });
          continue;
        }
        if (payload.done) {
          setStatus(`搜岗已结束 · 累计通过 ${petScoutJobCount} 个岗位`);
          return;
        }
        if (!payload.ok) throw new Error(payload.error?.message || "搜岗失败");
        if (payload.event) {
          enqueuePetScoutStreamEvent(payload.event);
          sseBatch += 1;
          if (sseBatch >= 24) {
            sseBatch = 0;
            await new Promise((r) => setTimeout(r, 0));
          }
        }
      }
    }
  } catch (e) {
    if (e.name === "AbortError") {
      // 用户停止或切换订阅：后端仍 active 则不算失败
      const live = await syncScoutLiveFromServer().catch(() => null);
      if (live?.active) return;
      handleScoutEvent({ type: "stopped", message: "用户手动停止搜岗" }, { local: true });
      setStatus(`搜岗已停止 · 累计通过 ${petScoutJobCount} 个岗位`);
      return;
    }
    handleScoutEvent({ type: "stopped", message: e.message || "搜岗出错" }, { local: true });
    petMonitorSidebar?.setStreamState("error", e.message || "搜岗出错");
    setStatus(e.message || "搜岗出错");
  } finally {
    const live = await syncScoutLiveFromServer().catch(() => null);
    if (live?.active && !petScoutStopRequested) {
      // SSE 断开但任务仍在：保持本地 scouting，并自动重连订阅
      petScoutAbortController = null;
      petMonitorSidebar?.setStreamState("connecting");
      setStatus(
        live.last_message
        || `搜岗继续中（重连订阅）· ${live.server_query || ""} · 第 ${live.server_page || "—"} 页`,
      );
      setTimeout(() => {
        if (petLocalScouting && !petScoutStopRequested && !petScoutAbortController) {
          void subscribePetScoutEvents({ resume: true });
        }
      }, 800);
      return;
    }
    stopPetScoutAckPulse();
    resetPetScoutEventQueue();
    petScoutAbortController = null;
    petLocalScouting = false;
    petMonitorSidebar?.setStreamState("stopped");
    updatePetScoutControls(false);
    refreshIdleAgentTasks();
  }
}

async function fetchScoutHistorySummary() {
  const resp = await fetch("/api/boss/scout/history");
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "读取侦察历史失败");
  return body.data;
}

async function refreshScoutHistorySidebar() {
  const numEl = document.getElementById("petScoutHistoryNum");
  try {
    const data = await fetchScoutHistorySummary();
    const total = String(data?.total ?? 0);
    if (numEl) numEl.textContent = total;
  } catch {
    if (numEl) numEl.textContent = "—";
  }
}

async function clearScoutHistory() {
  if (
    !confirm(
      "确定全部重置搜岗记录？\n\n将清空：侦察历史、分析记录、候选池、不感兴趣标记。\n所有岗位将可重新搜岗与分析。",
    )
  ) {
    return;
  }
  const clearBtn = document.getElementById("petScoutHistoryClear");
  if (clearBtn) clearBtn.disabled = true;
  try {
    const resp = await fetch("/api/boss/scout/history/clear", { method: "POST" });
    const body = await resp.json();
    if (!body?.ok) throw new Error(body?.error?.message || "重置失败");
    await refreshScoutHistorySidebar();
    petJobSidebar?.clear();
    void petJobSidebar?.refreshShortlistKeys();
    setStatus(body.data?.message || "搜岗记录已全部重置");
  } catch (e) {
    setStatus(e.message || "重置搜岗记录失败");
  } finally {
    if (clearBtn) clearBtn.disabled = false;
  }
}

function initScoutHistorySidebar() {
  document.getElementById("petScoutHistoryClear")?.addEventListener("click", () => {
    void clearScoutHistory();
  });
  void refreshScoutHistorySidebar();
}

async function startPetScoutStream() {
  if (petLocalScouting) {
    const live = await syncScoutLiveFromServer().catch(() => null);
    if (live?.active) {
      void subscribePetScoutEvents({ resume: true });
      return;
    }
    petLocalScouting = false;
    updatePetScoutControls(false);
  }

  const queryEl = document.getElementById("petScoutQuery");
  const query = queryEl?.value?.trim() || "";
  const loc = getPetScoutLocation();
  const regionErr = validateScoutRegion(loc);
  if (regionErr) {
    setStatus(`${regionErr} · 请在侦察 AI 工位选择城市`);
    petDeskPlates?.openPanel("ZC");
    return;
  }
  const city = loc.city || null;

  const { scout_filters, pass_score, career_stage } = getPetScorePrefs();
  const scoutErr = validateScoutFilters(scout_filters);
  if (scoutErr) {
    setStatus(`${scoutErr} · 请在侦察 AI 工位保存筛选条件`);
    petDeskPlates?.openPanel("ZC");
    return;
  }

  savePetScoutQueryPrefs(query, loc);
  if (!query) {
    setStatus("未输入关键词，将使用秘书画像自动生成搜索词…");
  }

  resetPetScoutEventQueue();
  petLocalScouting = true;
  petScoutStopRequested = false;
  petScoutOffHoursPaused = false;
  petScoutJobCount = 0;
  petScoutHeaderStats = null;
  startPetScoutAckPulse();
  petMonitorSidebar?.setStreamState("connecting");
  petMonitorSidebar?.setSearchContext(query || "", null);
  setScoutAutoRun(true);
  setScoutUserStopped(false);
  petJobSidebar?.clear();
  void petJobSidebar?.refreshShortlistKeys();
  updatePetScoutControls(true);
  refreshPetHeaderScoutStats();
  setAgentTask("ZC", "搜岗启动中");
  setAgentTask("FX", "待命分析");
  setAgentTask("JK", "监控浏览器");
  setAgentTask("MS", "待命中");

  const startBody = {
    query,
    city,
    city_code: loc.city_code || null,
    district_code: loc.district_code || null,
    profile_score: true,
    scout_filters,
    career_stage,
    auto_keywords: true,
  };
  if (pass_score != null) startBody.pass_score = pass_score;

  try {
    // 若后端任务已在跑，start 会返回 already_running，直接订阅
    const startResp = await fetch("/api/boss/scout/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(startBody),
    });
    const startJson = await startResp.json().catch(() => ({}));
    if (!startResp.ok || !startJson?.ok) {
      throw new Error(startJson?.error?.message || `启动失败 (${startResp.status})`);
    }
    await subscribePetScoutEvents({ resume: !!startJson.data?.already_running });
  } catch (e) {
    stopPetScoutAckPulse();
    resetPetScoutEventQueue();
    petScoutAbortController = null;
    petLocalScouting = false;
    petMonitorSidebar?.setStreamState("error", e.message || "搜岗出错");
    updatePetScoutControls(false);
    refreshIdleAgentTasks();
    setStatus(e.message || "搜岗出错");
  }
}

function initPetScoutControls() {
  const queryEl = document.getElementById("petScoutQuery");
  const startBtn = document.getElementById("petScoutStart");
  const stopBtn = document.getElementById("petScoutStop");

  const prefs = loadPetScoutQueryPrefs();
  if (queryEl && prefs.query) queryEl.value = prefs.query;

  startBtn?.addEventListener("click", () => startPetScoutStream());
  stopBtn?.addEventListener("click", () => stopPetScoutStream());

  queryEl?.addEventListener("change", () => {
    savePetScoutQueryPrefs(queryEl.value.trim(), getPetScoutLocation());
  });

  updatePetScoutControls(false);
}

async function loadSecretarySettings() {
  const fallback = {
    recipient_email: "",
    max_daily_picks: petConfig?.secretary?.dailyPicks?.defaultMax ?? 5,
    email_configured: false,
    has_smtp_password: false,
    smtp_host: "",
  };
  try {
    const resp = await fetch("/api/secretary/email", { cache: "no-store" });
    if (!resp.ok) return fallback;
    const body = await resp.json();
    if (!body?.ok) return fallback;
    return {
      recipient_email: body.data?.recipient_email || "",
      max_daily_picks: Number(body.data?.max_daily_picks) || fallback.max_daily_picks,
      email_configured: !!body.data?.email_configured,
      has_smtp_password: !!body.data?.has_smtp_password,
      smtp_host: body.data?.smtp_host || "",
    };
  } catch {
    return fallback;
  }
}

async function loadSecretaryEmail() {
  const settings = await loadSecretarySettings();
  return settings.recipient_email;
}

async function saveSecretarySettings(settings) {
  const payload = {
    recipient_email: settings.recipient_email || "",
    max_daily_picks: settings.max_daily_picks,
  };
  if (settings.smtp_auth_code) {
    payload.smtp_auth_code = settings.smtp_auth_code;
  }
  const resp = await fetch("/api/secretary/email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await resp.json();
  if (!body?.ok) {
    throw new Error(body?.error?.message || "保存秘书设置失败");
  }
  return body.data;
}

async function saveSecretaryEmail(email) {
  const current = await loadSecretarySettings();
  return saveSecretarySettings({
    recipient_email: email,
    max_daily_picks: current.max_daily_picks,
  });
}

function escHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function fetchInterviewCurrent() {
  const resp = await fetch("/api/interview/current", { cache: "no-store" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "无法读取对话状态");
  return body.data;
}

async function startSecretaryInterview() {
  const resp = await fetch("/api/interview/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resume_name: "default", max_questions: 8 }),
  });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "无法开始职业方向对话");
  return body.data;
}

async function answerSecretaryInterview(answer) {
  const resp = await fetch("/api/interview/answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "发送回答失败");
  return body.data;
}

async function finishSecretaryInterview() {
  const resp = await fetch("/api/interview/finish", { method: "POST" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "保存职业偏好失败");
  return body.data;
}

async function inferCareerDirection() {
  const resp = await fetch("/api/infer", { method: "POST" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "职业方向推理失败");
  return body.data;
}

async function loadSecretaryPortrait() {
  const resp = await fetch("/api/secretary/portrait", { cache: "no-store" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "无法加载求职画像");
  return body.data;
}

async function fetchPetProfile() {
  const resp = await fetch("/api/profile", { cache: "no-store" });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "无法读取画像");
  return body.data;
}

function pickResumeMeta(status) {
  const resumes = Array.isArray(status?.resumes) ? status.resumes : [];
  const preferred = petConfig?.resumeDesk?.name || "default";
  return resumes.find((r) => r.name === preferred) || resumes[0] || { name: preferred, title: "" };
}

function resumePreviewAvailable(status) {
  const meta = pickResumeMeta(status);
  if (meta.has_pdf === true) return true;
  if (meta.has_pdf === false) return false;
  return Array.isArray(status?.resumes) && status.resumes.length > 0;
}

/** @type {string | null} */
let petResumePdfObjectUrl = null;

function revokeResumePdfObjectUrl() {
  if (petResumePdfObjectUrl) {
    URL.revokeObjectURL(petResumePdfObjectUrl);
    petResumePdfObjectUrl = null;
  }
}

function formatResumePreviewEmptyHtml() {
  return `<p class="pet-archive-hint">尚无简历文件。<br>请先在场景中的简历桌上传 PDF。</p>`;
}

function formatResumePreviewMissingPdfHtml(title) {
  return `
    <div class="pet-resume-pdf-head">
      <p class="pet-resume-pdf-name">${escHtml(title || "我的简历")}</p>
    </div>
    <p class="pet-archive-hint">未找到 PDF 原件，请在场景中的简历桌重新上传。</p>
  `;
}

async function loadResumePdfPreviewHtml(status) {
  const meta = pickResumeMeta(status);
  const resumeName = meta.name || petConfig?.resumeDesk?.name || "default";
  const displayTitle = meta.title || `${resumeName}.pdf`;
  if (meta.has_pdf === false) {
    return formatResumePreviewMissingPdfHtml(displayTitle);
  }

  const pdfUrl = `/api/resume/pdf?name=${encodeURIComponent(resumeName)}&t=${Date.now()}`;
  const resp = await fetch(pdfUrl, { cache: "no-store" });
  if (!resp.ok) {
    if (resp.status === 404) {
      const ct = resp.headers.get("content-type") || "";
      if (ct.includes("json")) {
        const body = await resp.json().catch(() => null);
        throw new Error(body?.error?.message || "未找到 PDF 文件，请重新上传");
      }
      throw new Error("PDF 接口不可用（404），请重启 Web 服务后重试");
    }
    throw new Error(`PDF 加载失败（${resp.status}）`);
  }

  const contentType = resp.headers.get("content-type") || "";
  if (!contentType.includes("pdf") && !contentType.includes("octet-stream")) {
    throw new Error("服务器未返回 PDF，请重启 Web 服务后重试");
  }

  revokeResumePdfObjectUrl();
  const blob = await resp.blob();
  petResumePdfObjectUrl = URL.createObjectURL(blob);

  return `
    <div class="pet-resume-pdf-head">
      <p class="pet-resume-pdf-name">${escHtml(displayTitle)}</p>
      ${meta.updated_at ? `<p class="pet-resume-pdf-meta">更新：${escHtml(String(meta.updated_at).slice(0, 10))}</p>` : ""}
    </div>
    <div class="pet-resume-pdf-wrap">
      <embed class="pet-resume-pdf-frame" src="${petResumePdfObjectUrl}#toolbar=1" type="application/pdf" title="简历 PDF" />
    </div>
    <p class="pet-resume-pdf-fallback">
      <a class="pet-archive-btn" href="${petResumePdfObjectUrl}" target="_blank" rel="noopener">在新标签页打开 PDF</a>
    </p>
  `;
}

function formatArchivePortraitHtml(data) {
  return formatSecretaryPortraitHtml(data)
    .replace(/pet-ms-portrait-block/g, "pet-archive-portrait-block")
    .replace(/pet-ms-portrait-label/g, "pet-archive-portrait-label")
    .replace(/pet-ms-portrait-val/g, "pet-archive-portrait-val");
}

function formatCareerReportEmptyHtml() {
  return `<p class="pet-archive-hint">尚无职业推理报告。<br>请先完成秘书「职业方向对话」，再点击「生成推理报告」。</p>`;
}

function formatCareerReportHtml(data) {
  const c = data?.career || {};
  const memory = data?.memory_summary || "";
  const riskLabels = { low: "低", medium: "中", high: "高" };
  const avoids = (c.avoid_direction || []).filter(Boolean);
  const strengths = c.strengths || [];
  const gaps = c.gaps || [];
  const growth = c.growth_paths || [];
  const fitTags = [
    c.startup_fit
      ? '<span class="pet-career-tag pet-career-tag--ok">创业适配</span>'
      : '<span class="pet-career-tag">创业一般</span>',
    c.remote_fit
      ? '<span class="pet-career-tag pet-career-tag--ok">接受远程</span>'
      : '<span class="pet-career-tag">现场优先</span>',
    `<span class="pet-career-tag">风险承受：${escHtml(riskLabels[c.risk_tolerance] || c.risk_tolerance || "中")}</span>`,
  ].join("");
  const avoidHtml = avoids.length
    ? avoids.map((a) => `<span class="pet-career-tag pet-career-tag--avoid">${escHtml(a)}</span>`).join("")
    : '<span class="pet-career-tag">暂无明显避开项</span>';
  const growthHtml = growth.length
    ? growth.map((g, i) => `${i > 0 ? '<span class="pet-career-growth-arrow">→</span>' : ""}<span class="pet-career-growth-step">${escHtml(g)}</span>`).join("")
    : "—";

  return `
    <div class="pet-career-hero">
      <p class="pet-career-hero-primary">${escHtml(c.primary_direction || "待明确")}</p>
      ${c.secondary_direction ? `<p class="pet-career-hero-secondary">次方向：${escHtml(c.secondary_direction)}</p>` : ""}
    </div>
    <div class="pet-career-section">
      <p class="pet-career-section-title">建议避开</p>
      <div class="pet-career-tags">${avoidHtml}</div>
    </div>
    <div class="pet-career-tags">${fitTags}</div>
    <div class="pet-career-section">
      <p class="pet-career-section-title">优势</p>
      <ul class="pet-career-list">${strengths.map((s) => `<li>${escHtml(s)}</li>`).join("") || "<li>—</li>"}</ul>
    </div>
    <div class="pet-career-section">
      <p class="pet-career-section-title">短板</p>
      <ul class="pet-career-list">${gaps.map((g) => `<li>${escHtml(g)}</li>`).join("") || "<li>—</li>"}</ul>
    </div>
    <div class="pet-career-section">
      <p class="pet-career-section-title">路径规划</p>
      <div class="pet-career-path-block">
        <p class="pet-career-path-label">现实路径（1–3 年）</p>
        <p class="pet-career-path-val">${escHtml(c.realistic_path || "—")}</p>
      </div>
      <div class="pet-career-path-block">
        <p class="pet-career-path-label">长期路径（3–5 年+）</p>
        <p class="pet-career-path-val">${escHtml(c.long_term_path || "—")}</p>
      </div>
    </div>
    <div class="pet-career-section">
      <p class="pet-career-section-title">成长路径</p>
      <div class="pet-career-growth">${growthHtml}</div>
    </div>
    ${memory ? `<p class="pet-career-memory">${escHtml(memory)}</p>` : ""}
  `;
}

function formatSecretaryPortraitHtml(data) {
  const portrait = data?.portrait;
  const profile = data?.profile || {};
  const pr = profile.parsed_resume || {};
  const pref = profile.preferences || {};
  const career = profile.career || {};

  if (!portrait && !pr.summary && !pref.role_preference) {
    return "<p class=\"pet-ms-chat-hint\">尚无求职画像，请先上传并解析简历</p>";
  }

  const role = portrait?.expected_role || pref.role_preference || career.primary_direction || "—";
  const skills = (portrait?.skills || pr.skills || []).slice(0, 6);
  const summary = portrait?.summary || pr.summary || "—";
  const stage = pref.job_seeking_stage || "—";
  const basics = portrait?.basics || {};
  const gender = basics.gender || pr.gender || "—";
  const age = basics.age ?? pr.age;
  const ageText = age != null && age !== "" ? `${age} 岁` : "—";
  const education = basics.education || portrait?.education || pr.education || "—";
  const years = basics.years_of_experience ?? portrait?.years_of_experience ?? pr.years_of_experience;
  const yearsText = years != null && years !== "" ? `${years} 年` : "—";
  const schoolName = basics.school_name || pr.school_name || "—";
  const schoolTier = basics.school_tier || pr.school_tier || "—";
  const schoolReason = basics.school_tier_reason || pr.school_tier_reason || "";

  return `
    <div class="pet-ms-portrait-block">
      <p class="pet-ms-portrait-label">性别</p>
      <p class="pet-ms-portrait-val">${escHtml(gender)}</p>
      <p class="pet-ms-portrait-label">年龄</p>
      <p class="pet-ms-portrait-val">${escHtml(ageText)}</p>
      <p class="pet-ms-portrait-label">学历</p>
      <p class="pet-ms-portrait-val">${escHtml(education)}</p>
      <p class="pet-ms-portrait-label">工作经验</p>
      <p class="pet-ms-portrait-val">${escHtml(yearsText)}</p>
      <p class="pet-ms-portrait-label">毕业院校</p>
      <p class="pet-ms-portrait-val">${escHtml(schoolName)}</p>
      <p class="pet-ms-portrait-label">院校层级（秘书判定）</p>
      <p class="pet-ms-portrait-val">${escHtml(schoolTier)}${schoolReason ? `<span class="pet-ms-portrait-sub">${escHtml(schoolReason)}</span>` : ""}</p>
      <p class="pet-ms-portrait-label">意向方向</p>
      <p class="pet-ms-portrait-val">${escHtml(role)}</p>
      <p class="pet-ms-portrait-label">求职阶段</p>
      <p class="pet-ms-portrait-val">${escHtml(stage)}</p>
      <p class="pet-ms-portrait-label">核心技能</p>
      <p class="pet-ms-portrait-val">${escHtml(skills.join(" · ") || "—")}</p>
      <p class="pet-ms-portrait-label">摘要</p>
      <p class="pet-ms-portrait-val">${escHtml(summary)}</p>
    </div>
  `;
}

async function saveSecretaryPanelSettings(email, maxDailyPicks, smtpAuthCode = "") {
  const data = await saveSecretarySettings({
    recipient_email: email,
    max_daily_picks: maxDailyPicks,
    smtp_auth_code: smtpAuthCode || undefined,
  });
  const parts = [];
  if (email) {
    parts.push(`邮箱 ${email}`);
    if (data?.email_configured) parts.push("日报邮件已就绪");
    else parts.push("请填写授权码以启用发信");
  } else {
    parts.push("邮箱已清空");
  }
  parts.push(`每日精选 ${maxDailyPicks} 个`);

  try {
    const cur = await fetchInterviewCurrent();
    const hasTranscript = (cur?.transcript?.length || 0) > 0;
    if (hasTranscript || cur?.active) {
      await finishSecretaryInterview();
      parts.push("职业偏好已保存");
      try {
        const inferData = await inferCareerDirection();
        parts.push("职业方向已更新");
        petDocumentCabinet?.markNew("career");
        agents.MS?.showHeadBubble("职业推理报告已存入资料柜", { durationMs: 3200 });
        setTimeout(() => {
          petArchiveManager?.openReport("career", { careerData: inferData });
        }, 400);
      } catch {
        /* 推理可选，偏好已保存即可 */
      }
    }
  } catch (err) {
    const msg = err?.message || "";
    if (!msg.includes("无进行中的访谈") && !msg.includes("请先解析简历")) {
      throw err;
    }
  }

  return `秘书设置已保存：${parts.join(" · ")}`;
}

function setStatus(text) {
  const el = document.getElementById("petStatus");
  if (!el) return;
  // 搜岗进行中：标题小字只显示统计（已侦察/通过等），忽略休息/同步等其它文案
  if (petLocalScouting && !scheduleOffHours && !petScoutOffHoursPaused) {
    el.textContent = formatPetHeaderScoutStats(petScoutHeaderStats);
    return;
  }
  el.textContent = text;
}

/** @type {PetJobSidebar | null} */
let petJobSidebar = null;

const MONITOR_STATE_LABELS = {
  idle: "待命",
  watching: "监控中",
  paused: "已暂停",
  recovering: "恢复中",
  stalled: "卡住",
  stopped: "已停止",
  alert: "异常",
};

const MONITOR_STREAM_LABELS = {
  idle: "未连接",
  connecting: "连接中",
  streaming: "传输中",
  paused: "搜岗暂停",
  off_hours: "下班暂停",
  resting: "休息中",
  stopped: "已结束",
  error: "出错",
};

const MONITOR_EVENT_LABELS = {
  start: "搜岗启动",
  stopped: "搜岗停止",
  done: "搜岗完成",
  monitor_start: "监控启动",
  monitor_stopped: "监控结束",
  monitor_ok: "运行正常",
  monitor_alert: "异常告警",
  monitor_stall: "无进展卡住",
  monitor_token: "Token 更新",
  monitor_browser_open: "打开浏览器",
  monitor_browser_restart: "重启浏览器",
  monitor_recovered: "已恢复",
  monitor_probe: "健康探测",
  page_start: "翻页浏览",
  page_done: "页完成",
  page_turn: "准备翻页",
  page_empty: "空页",
  scout_list_exhausted: "列表扫完",
  scout_query_cooldown: "搜索词冷却",
  scout_query_skip_cooldown: "跳过冷却词",
  search_fetch: "拉取列表",
  search_progress: "拉取进度",
  scout_seen: "发现岗位",
  scout_glance: "浏览岗位",
  scout_browse_skip: "跳过已浏览",
  scout_history_skip: "跳过历史",
  scout_filter: "硬性筛选",
  scout_skip: "跳过岗位",
  scout_duplicate: "重复岗位",
  scout_transmit: "传送分析",
  analysis_start: "分析岗位",
  job_passed: "岗位通过",
  job_filtered: "岗位筛掉",
  round_start: "新一轮",
  round_resume: "继续搜岗",
  round_home_refresh: "刷新首页",
  round_pause: "轮次休息",
  round_fatigue_pause: "疲劳休息",
  round_early_stop: "提前结束",
  page_hidden_pause: "页面隐藏（后台续跑）",
  page_hidden_continue: "页面隐藏（后台续跑）",
  page_visible_resume: "页面已恢复",
  scout_ack_warn: "同步警告",
  off_hours_pause: "下班暂停",
  work_hours_resume: "上班恢复",
  scout_heartbeat: "心跳",
  scout_query_switch: "切换搜索词",
  scout_query_depth: "关键词深度",
  scout_query_depth_progress: "深度进度",
  scout_query_depth_met: "深度达标",
  scout_query_strategy: "搜索策略",
  boss_browser_closed: "关闭浏览器",
  browser_stuck: "页面卡住",
  browser_restarted: "浏览器重启",
  browser_restart_begin: "准备重启",
  browser_restart_failed: "重启失败",
  browser_session_lost: "窗口已断开",
  account_risk: "账号风险",
};

const MONITOR_STAGE_BY_EVENT = {
  start: "启动搜岗",
  monitor_start: "监控就绪",
  page_start: "列表翻页",
  page_done: "页完成",
  page_turn: "准备翻页",
  scout_list_exhausted: "列表扫完",
  scout_query_cooldown: "搜索词冷却",
  scout_query_skip_cooldown: "跳过冷却词",
  search_fetch: "拉取结果",
  search_progress: "拉取进度",
  scout_seen: "发现岗位",
  scout_glance: "浏览详情",
  scout_filter: "硬性筛选",
  scout_transmit: "传送分析",
  analysis_start: "AI 分析",
  job_passed: "收录通过",
  job_filtered: "分析筛掉",
  round_start: "新一轮搜岗",
  round_resume: "休息结束",
  round_pause: "轮次休息",
  round_fatigue_pause: "疲劳休息",
  page_hidden_pause: "页面隐藏（后台续跑）",
  page_hidden_continue: "页面隐藏（后台续跑）",
  page_visible_resume: "页面已恢复",
  scout_ack_warn: "同步警告",
  off_hours_pause: "非工作时间",
  work_hours_resume: "恢复工作",
  monitor_alert: "异常处理",
  monitor_stall: "卡住检测",
  monitor_recovered: "恢复运行",
  monitor_browser_restart: "重启浏览器",
  browser_restart_begin: "准备重启",
  browser_restart_failed: "重启失败",
  browser_session_lost: "窗口断开",
  stopped: "已停止",
  done: "已完成",
};

function formatMonitorClock(date = new Date()) {
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

/** 心跳事件文案 → 监控器当前阶段（非轮次休息时） */
function heartbeatStageFromMessage(message = "") {
  const msg = String(message);
  if (/疲劳休息/.test(msg)) return "疲劳休息";
  if (/本轮休息|轮次休息/.test(msg)) return "本轮休息";
  if (/细读|JD|点开/.test(msg)) return "细读岗位";
  if (/悬停|扫一眼|略读/.test(msg)) return "浏览列表";
  if (/快速划过|划过/.test(msg)) return "快速划过";
  if (/历史/.test(msg)) return "跳过历史";
  if (/拉取|搜索/.test(msg)) return "拉取结果";
  return "搜岗节奏";
}

class PetMonitorSidebar {
  constructor(root) {
    this.root = root;
    this.statusEl = document.getElementById("petMonitorStatus");
    this.stageEl = document.getElementById("petMonitorStage");
    this.eventEl = document.getElementById("petMonitorEvent");
    this.locationEl = document.getElementById("petMonitorLocation");
    this.progressEl = document.getElementById("petMonitorProgress");
    this.streamEl = document.getElementById("petMonitorStream");
    this.actionsEl = document.getElementById("petMonitorActions");
    this.monitorState = "idle";
    this.streamState = "idle";
    this.stage = "待命";
    this.lastEventType = "—";
    this.searchQuery = "";
    this.searchPage = null;
    this.queryPassCount = 0;
    this.queryPassTarget = null;
    this.progress = "等待开始搜岗…";
    this.streamHint = "";
    this.recentActions = [];
    this._renderPending = false;
    this._render();
  }

  reset() {
    this.monitorState = "idle";
    this.streamState = "idle";
    this.stage = "待命";
    this.lastEventType = "—";
    this.searchQuery = "";
    this.searchPage = null;
    this.queryPassCount = 0;
    this.queryPassTarget = null;
    this.progress = "等待开始搜岗…";
    this.streamHint = "";
    this.recentActions = [];
    this._renderActions();
    this._render();
  }

  setSearchContext(query, page) {
    if (query != null) {
      this.searchQuery = String(query).trim();
    }
    if (page !== undefined) {
      this.searchPage = page != null && Number.isFinite(Number(page)) ? Number(page) : null;
    }
    this._renderLocation();
    refreshPetHeaderScoutStats();
  }

  setStreamState(state, hint = "") {
    this.streamState = state || "idle";
    this.streamHint = hint || "";
    this._renderStream();
  }

  syncFromApp() {
    if (!petLocalScouting) {
      if (this.streamState !== "stopped" && this.streamState !== "error") {
        this.streamState = "idle";
      }
    } else if (petScoutOffHoursPaused || scheduleOffHours) {
      this.streamState = "off_hours";
    } else if (officeResting) {
      this.streamState = "resting";
    } else if (this.streamState === "connecting") {
      this.streamState = "streaming";
    } else if (this.streamState !== "error") {
      this.streamState = "streaming";
      if (this.stage === "疲劳休息" || this.stage === "本轮休息") {
        this.stage = "列表翻页";
      }
    }
    this._renderStream();
  }

  exitRestState() {
    if (officeResting) return;
    this.stage = petLocalScouting ? "列表翻页" : this.stage;
    this.streamState = petLocalScouting ? "streaming" : this.streamState;
    this.streamHint = "";
    this._render();
  }

  syncEventMeta(ev) {
    const type = ev?.type || "";
    if (!type) return;

    if (type.startsWith("monitor_") || type === "browser_restart_begin" || type === "browser_restart_failed" || type === "browser_session_lost") {
      this._applyMonitorEvent(ev);
    }

    if (
      officeResting &&
      !scheduleOffHours &&
      (type === "page_start" ||
        type === "search_fetch" ||
        type === "search_progress" ||
      type === "page_done" ||
      type === "page_turn" ||
      type === "round_resume" ||
        type === "round_start")
    ) {
      resumeAfterRest();
    }

    this.lastEventType = type;
    if (type === "page_start" || type === "search_fetch" || type === "search_progress" || type === "page_done" || type === "page_turn") {
      this.stage = MONITOR_STAGE_BY_EVENT[type] || this.stage;
      if (petLocalScouting && !scheduleOffHours && !petScoutOffHoursPaused) {
        this.streamState = "streaming";
      }
    } else if (type === "round_start" || type === "round_resume") {
      this.stage = MONITOR_STAGE_BY_EVENT[type] || this.stage;
      if (petLocalScouting && !scheduleOffHours) {
        this.streamState = "streaming";
      }
    } else if (type === "scout_heartbeat" && officeResting) {
      const sec = ev.remaining_sec ?? 0;
      if (sec <= 0) {
        this.stage = MONITOR_STAGE_BY_EVENT.round_resume || "继续搜岗";
        this.streamState = petLocalScouting ? "streaming" : this.streamState;
      } else {
        this.stage = /疲劳/.test(ev.message || "") ? "疲劳休息" : "本轮休息";
        this.streamState = "resting";
      }
    }

    this._updateSearchContext(ev, type);
    const metaType = String(ev?.type || "");
    if (ev.message && !PET_SCOUT_PROGRESS_SKIP_TYPES.has(metaType)) {
      this.progress = String(ev.message);
    } else if (ev.stats && !PET_SCOUT_PROGRESS_SKIP_TYPES.has(metaType)) {
      const msg = formatScoutStatsMessage(ev.stats);
      if (msg) this.progress = msg;
    }
    this._scheduleRender();
  }

  _scheduleRender() {
    if (this._renderPending) return;
    this._renderPending = true;
    requestAnimationFrame(() => {
      this._renderPending = false;
      this._render();
    });
  }

  handleEvent(ev, opts = {}) {
    const type = ev?.type || "";
    if (!type) return;

    this.lastEventType = type;
    if (type.startsWith("monitor_")) {
      this._applyMonitorEvent(ev);
    } else if (type === "start") {
      this.monitorState = "watching";
      this.stage = MONITOR_STAGE_BY_EVENT.start;
      this.streamState = "streaming";
    } else if (type === "stopped" || type === "done") {
      this.monitorState = "stopped";
      this.stage = MONITOR_STAGE_BY_EVENT[type] || "已停止";
    } else if (type === "off_hours_pause") {
      this.stage = MONITOR_STAGE_BY_EVENT.off_hours_pause;
      this.streamState = "off_hours";
    } else if (type === "work_hours_resume") {
      this.stage = MONITOR_STAGE_BY_EVENT.work_hours_resume;
      if (petLocalScouting) this.streamState = "streaming";
    } else if (type === "round_start" || type === "round_resume") {
      this.stage = MONITOR_STAGE_BY_EVENT[type] || this.stage;
      if (petLocalScouting && !scheduleOffHours) {
        this.streamState = "streaming";
        this.streamHint = "";
      }
    } else if (type === "round_fatigue_pause" || type === "round_pause") {
      this.stage = MONITOR_STAGE_BY_EVENT[type] || this.stage;
      this.streamState = "resting";
    } else if (type === "page_start" || type === "search_fetch" || type === "search_progress" || type === "page_done" || type === "page_turn") {
      if (petLocalScouting && !scheduleOffHours && !petScoutOffHoursPaused) {
        this.streamState = "streaming";
      }
    } else if (MONITOR_STAGE_BY_EVENT[type]) {
      this.stage = MONITOR_STAGE_BY_EVENT[type];
    } else if (type === "scout_heartbeat") {
      const msg = ev.message || "";
      if (officeResting) {
        this.stage = /疲劳/.test(msg) ? "疲劳休息" : "本轮休息";
        this.streamState = "resting";
        this.streamHint = "";
      } else {
        this.stage = heartbeatStageFromMessage(msg);
        this.streamState = petLocalScouting ? "streaming" : this.streamState;
        const sec = Math.ceil(ev.remaining_sec ?? 0);
        this.streamHint = sec > 0 ? `等待 ${sec}s` : "";
      }
    }

    this._updateSearchContext(ev, type);

    const progress = this._resolveProgress(ev, type, opts);
    if (progress) this.progress = progress;

    const actionLabel = this._actionLabel(ev, type);
    if (actionLabel && type !== "scout_heartbeat" && type !== "monitor_token") {
      this._pushAction(actionLabel, type, ev);
    }

    this._render();
  }

  _applyMonitorEvent(ev) {
    const state = String(ev.state || "").trim();
    if (state === "paused") this.monitorState = "paused";
    else if (state === "recovering") this.monitorState = "recovering";
    else if (state === "stalled") this.monitorState = "stalled";
    else if (state === "stopped") this.monitorState = "stopped";
    else if (ev.type === "monitor_alert" || ev.type === "monitor_stall") this.monitorState = "alert";
    else if (
      ev.type === "browser_restart_failed" || ev.type === "browser_session_lost"
    ) this.monitorState = "alert";
    else if (ev.type === "browser_restart_begin") this.monitorState = "recovering";
    else if (
      ev.type === "monitor_start"
      || ev.type === "monitor_ok"
      || ev.type === "monitor_recovered"
      || ev.type === "monitor_browser_restart"
    ) {
      this.monitorState = "watching";
    }

    if (MONITOR_STAGE_BY_EVENT[ev.type]) {
      this.stage = MONITOR_STAGE_BY_EVENT[ev.type];
    }
  }

  _resolveQueryFromEvent(ev, type) {
    if (ev?.next_query) return String(ev.next_query).trim();
    if (ev?.query) return String(ev.query).trim();
    if (ev?.stats?.search?.current_query) return String(ev.stats.search.current_query).trim();
    if ((type === "start" || type === "scout_query_strategy") && Array.isArray(ev?.queries) && ev.queries[0]) {
      return String(ev.queries[0]).trim();
    }
    return "";
  }

  _updateSearchContext(ev, type) {
    const prevQuery = this.searchQuery;
    const resolvedQuery = this._resolveQueryFromEvent(ev, type);
    const queryChanged = !!(resolvedQuery && prevQuery && resolvedQuery !== prevQuery);
    if (resolvedQuery) this.searchQuery = resolvedQuery;

    const forcePage =
      type === "page_start" ||
      type === "search_fetch" ||
      type === "search_progress" ||
      type === "page_done" ||
      type === "page_turn" ||
      type === "round_start" ||
      type === "round_resume" ||
      type === "round_done" ||
      type === "scout_query_switch" ||
      type === "scout_list_exhausted" ||
      type === "page_empty";

    const heartbeatPage = type === "scout_heartbeat";

    const resetPage =
      type === "page_empty" ||
      type === "scout_list_exhausted" ||
      type === "scout_query_switch" ||
      type === "round_start";

    let page = null;
    if (ev?.page != null && Number.isFinite(Number(ev.page))) {
      page = Number(ev.page);
    } else if (ev?.next_page != null && Number.isFinite(Number(ev.next_page))) {
      page = Number(ev.next_page);
    } else if (ev?.stats?.search?.current_page != null && Number.isFinite(Number(ev.stats.search.current_page))) {
      const pageFromStats = Number(ev.stats.search.current_page);
      if (pageFromStats > 0) page = pageFromStats;
    }

    if (page != null) {
      if (queryChanged || forcePage || resetPage || this.searchPage == null) {
        this.searchPage = page;
      } else if (heartbeatPage) {
        // 休息心跳里的 stats 可能滞后，禁止把页码回退
        this.searchPage = Math.max(this.searchPage, page);
      } else if (this.searchQuery === prevQuery) {
        this.searchPage = Math.max(this.searchPage, page);
      } else {
        this.searchPage = page;
      }
    } else if (queryChanged) {
      this.searchPage = null;
    } else if (type === "round_start" && ev?.page == null) {
      this.searchPage = null;
    }

    if (type === "scout_list_exhausted") {
      if (!ev.switch_query) this.searchPage = 1;
    } else if (type === "page_empty") {
      this.searchPage = 1;
    }

    if (type === "scout_query_depth_met" && (ev.deferred || ev.list_exhausted)) {
      if (ev.pass_count != null && Number.isFinite(Number(ev.pass_count))) {
        this.queryPassCount = Number(ev.pass_count);
      }
      if (ev.pass_target != null && Number.isFinite(Number(ev.pass_target))) {
        this.queryPassTarget = Number(ev.pass_target);
      }
      this._renderLocation();
      refreshPetHeaderScoutStats();
      return;
    }

    if (ev?.pass_target != null && Number.isFinite(Number(ev.pass_target))) {
      this.queryPassTarget = Number(ev.pass_target);
    }
    if (ev?.pass_count != null && Number.isFinite(Number(ev.pass_count))) {
      this.queryPassCount = Number(ev.pass_count);
    } else if (type === "scout_query_depth" || type === "scout_query_switch") {
      this.queryPassCount = 0;
    }

    this._renderLocation();
    refreshPetHeaderScoutStats();
  }

  _formatSearchLocation() {
    const query = this.searchQuery.trim();
    const page = this.searchPage;
    if (!query && page == null && this.queryPassTarget == null) return "—";
    const parts = [];
    if (query) parts.push(query);
    else parts.push("自动生成关键词");
    if (page != null) parts.push(`第 ${page} 页`);
    if (this.queryPassTarget != null && this.queryPassTarget > 0) {
      parts.push(`通过 ${this.queryPassCount}/${this.queryPassTarget}`);
    }
    return parts.join(" · ");
  }

  _renderLocation() {
    if (this.locationEl) {
      this.locationEl.textContent = this._formatSearchLocation();
    }
  }

  _resolveProgress(ev, type, opts) {
    if (PET_SCOUT_PROGRESS_SKIP_TYPES.has(type)) return "";
    if (type === "job_passed" && ev.job?.title) {
      return `通过：${truncateTaskLabel(ev.job.title, 24)}`;
    }
    if (type === "job_filtered" && ev.job?.title) {
      return `未通过：${truncateTaskLabel(ev.job.title, 24)}`;
    }
    if (type === "analysis_start" && ev.job?.title) {
      return `分析中：${truncateTaskLabel(ev.job.title, 24)}`;
    }
    if (ev.message) return String(ev.message);
    if (ev.stats) {
      const msg = formatScoutStatsMessage(ev.stats);
      if (msg) return msg;
    }
    if (type === "monitor_token" && ev.usage?.session_total) {
      const total = ev.usage.session_total.total_tokens ?? 0;
      const cost = ev.usage.cost?.formatted || "";
      return cost ? `Token ${total} · ${cost}` : `Token ${total}`;
    }
    if (type === "start" && opts.local) return "各 AI 已就位，侦察流已连接";
    return "";
  }

  _actionLabel(ev, type) {
    const base = MONITOR_EVENT_LABELS[type] || type;
    if (ev.message) return `${base} · ${truncateTaskLabel(ev.message, 36)}`;
    if (ev.job?.title) return `${base} · ${truncateTaskLabel(ev.job.title, 20)}`;
    if (ev.page != null) return `${base} · 第 ${ev.page} 页`;
    return base;
  }

  _pushAction(label, type) {
    const alertTypes = new Set([
      "monitor_alert",
      "monitor_stall",
      "browser_stuck",
      "browser_restart_failed",
      "browser_session_lost",
      "account_risk",
      "stopped",
    ]);
    const okTypes = new Set([
      "monitor_ok",
      "monitor_recovered",
      "job_passed",
      "work_hours_resume",
    ]);
    this.recentActions.unshift({
      time: formatMonitorClock(),
      label,
      kind: alertTypes.has(type) ? "alert" : okTypes.has(type) ? "ok" : "normal",
    });
    if (this.recentActions.length > 16) this.recentActions.length = 16;
    this._renderActions();
  }

  _monitorBadgeClass() {
    if (this.monitorState === "watching") return "pet-monitor-badge--watching";
    if (this.monitorState === "paused" || this.monitorState === "recovering") {
      return "pet-monitor-badge--paused";
    }
    if (this.monitorState === "stalled" || this.monitorState === "alert") {
      return "pet-monitor-badge--alert";
    }
    if (this.monitorState === "stopped") return "pet-monitor-badge--stopped";
    return "pet-monitor-badge--idle";
  }

  _streamClass() {
    const map = {
      streaming: "pet-monitor-stream--streaming",
      connecting: "pet-monitor-stream--connecting",
      paused: "pet-monitor-stream--paused",
      off_hours: "pet-monitor-stream--off-hours",
      resting: "pet-monitor-stream--resting",
      stopped: "pet-monitor-stream--stopped",
      error: "pet-monitor-stream--error",
    };
    return map[this.streamState] || "pet-monitor-stream--idle";
  }

  _renderStream() {
    if (!this.streamEl) return;
    const label = MONITOR_STREAM_LABELS[this.streamState] || this.streamState;
    this.streamEl.textContent = this.streamHint ? `${label} · ${this.streamHint}` : label;
    this.streamEl.className = `pet-monitor-stream ${this._streamClass()}`;
  }

  _renderActions() {
    if (!this.actionsEl) return;
    if (!this.recentActions.length) {
      this.actionsEl.innerHTML = '<li class="pet-monitor-action pet-monitor-action--empty">暂无动作记录</li>';
      return;
    }
    this.actionsEl.innerHTML = this.recentActions.map((item) => {
      const kindClass = item.kind === "alert"
        ? " pet-monitor-action--alert"
        : item.kind === "ok"
          ? " pet-monitor-action--ok"
          : "";
      return `<li class="pet-monitor-action${kindClass}"><time>${escHtml(item.time)}</time>${escHtml(item.label)}</li>`;
    }).join("");
  }

  _render() {
    if (this.statusEl) {
      this.statusEl.textContent = MONITOR_STATE_LABELS[this.monitorState] || this.monitorState;
      this.statusEl.className = `pet-monitor-badge ${this._monitorBadgeClass()}`;
    }
    if (this.stageEl) this.stageEl.textContent = this.stage || "—";
    if (this.eventEl) this.eventEl.textContent = this.lastEventType || "—";
    this._renderLocation();
    if (this.progressEl) this.progressEl.textContent = this.progress || "—";
    this._renderStream();
  }
}

function petJobDedupeKey(job) {
  const sid = String(job?.security_id || "").trim();
  const jid = String(job?.job_id || job?.encrypt_job_id || "").trim();
  if (sid || jid) return `${sid}:${jid}`;
  return `${String(job?.title || "").trim()}::${String(job?.company || "").trim()}`;
}

class PetJobSidebar {
  constructor(root) {
    this.root = root;
    this.listEl = document.getElementById("petJobList");
    this.emptyEl = document.getElementById("petJobEmpty");
    this.countEl = document.getElementById("petJobCount");
    this.countInlineEl = document.getElementById("petJobCountInline");
    this.toggleBtn = document.getElementById("petJobSidebarToggle");
    this.openBtn = document.getElementById("petJobSidebarOpen");
    this.jobIndex = 0;
    this.seenJobKeys = new Set();
    this.shortlistKeys = new Set();
    this._bindUi();
    this.updateCount();
    void this.refreshShortlistKeys();
  }

  _bindUi() {
    this.toggleBtn?.addEventListener("click", () => this.toggleCollapsed());
    this.openBtn?.addEventListener("click", () => this.setCollapsed(false));
    this._syncCollapsedUi();
  }

  toggleCollapsed() {
    this.setCollapsed(!this.root.classList.contains("collapsed"));
  }

  setCollapsed(collapsed) {
    this.root.classList.toggle("collapsed", collapsed);
    if (this.toggleBtn) {
      this.toggleBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }
    this._syncCollapsedUi();
  }

  _syncCollapsedUi() {
    const collapsed = this.root.classList.contains("collapsed");
    if (this.openBtn) this.openBtn.hidden = !collapsed;
  }

  clear() {
    this.jobIndex = 0;
    this.seenJobKeys.clear();
    if (this.listEl) this.listEl.innerHTML = "";
    if (this.emptyEl) this.emptyEl.hidden = false;
    this.updateCount();
  }

  async refreshShortlistKeys() {
    try {
      const data = await fetchShortlist();
      this.shortlistKeys = new Set(
        (data?.items || []).map((item) => petJobDedupeKey(item)),
      );
    } catch {
      /* ignore */
    }
  }

  markShortlisted(job) {
    const key = petJobDedupeKey(job);
    if (key) this.shortlistKeys.add(key);
    this.seenJobKeys.add(key);
  }

  addJob(job) {
    if (!this.listEl || !job) return;
    const key = petJobDedupeKey(job);
    if (!key || this.seenJobKeys.has(key) || this.shortlistKeys.has(key)) return;
    this.seenJobKeys.add(key);
    this.jobIndex += 1;
    if (this.emptyEl) this.emptyEl.hidden = true;
    const card = document.createElement("article");
    const pri = job.profile_priority || "medium";
    card.className = `pet-job-card pet-job-card--${pri}`;
    card.innerHTML = buildPetJobCardHtml(job, this.jobIndex);
    card._petJob = job;
    this.listEl.prepend(card);
    this.bindCardActions(card);
    this.updateCount();
    this.setCollapsed(false);
  }

  getJobCount() {
    return this.listEl?.querySelectorAll(".pet-job-card").length ?? 0;
  }

  updateCount() {
    const text = String(this.getJobCount());
    if (this.countEl) this.countEl.textContent = text;
    if (this.countInlineEl) this.countInlineEl.textContent = text;
  }

  bindCardActions(card) {
    card.querySelector(".pet-job-shortlist")?.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const btn = ev.currentTarget;
      if (!(btn instanceof HTMLButtonElement) || btn.disabled) return;
      btn.disabled = true;
      try {
        await petShortlistJob({
          security_id: btn.dataset.sid || "",
          job_id: btn.dataset.jid || "",
          title: btn.dataset.title || "",
          company: btn.dataset.company || "",
          city: btn.dataset.city || "",
          salary: btn.dataset.salary || "",
        });
        this.markShortlisted({
          security_id: btn.dataset.sid || "",
          job_id: btn.dataset.jid || "",
        });
        card.classList.add("pet-job-card--shortlisted");
        petDocumentCabinet?.markNew("shortlist");
        setStatus("已加入候选池");
      } catch (err) {
        btn.disabled = false;
        setStatus(err?.message || "加入候选池失败");
      }
    });

    card.querySelector(".pet-job-reject")?.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const btn = ev.currentTarget;
      if (!(btn instanceof HTMLButtonElement) || btn.disabled) return;
      btn.disabled = true;
      try {
        const jobMeta = card._petJob || {};
        const dialog = await petShowRejectDialog({
          title: btn.dataset.title || jobMeta.title || "",
          company: btn.dataset.company || jobMeta.company || "",
        });
        if (dialog.cancelled) {
          btn.disabled = false;
          return;
        }
        await petRejectJob({
          security_id: btn.dataset.sid || "",
          job_id: btn.dataset.jid || "",
          title: btn.dataset.title || "",
          company: btn.dataset.company || "",
          reason: dialog.reason || "",
          tags: dialog.tags || [],
          analysis_score: jobMeta.analysis_score ?? jobMeta.profile_score ?? null,
          analysis_reason: jobMeta.analysis_reason || jobMeta.profile_reason || [],
          analysis_risk: jobMeta.analysis_risk || jobMeta.profile_risk || [],
        });
        card.remove();
        this.updateCount();
        if (!this.listEl?.querySelector(".pet-job-card") && this.emptyEl) {
          this.emptyEl.hidden = false;
        }
        petDocumentCabinet?.markNew("reject_learning");
        setStatus(dialog.skipped && !dialog.reason && !(dialog.tags || []).length
          ? "已记录不感兴趣"
          : "已记录拒绝理由 · 可在资料柜查看学习变更");
      } catch (err) {
        btn.disabled = false;
        setStatus(err?.message || "拒绝失败");
      }
    });

    card.querySelector(".pet-job-boss-view")?.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const btn = ev.currentTarget;
      if (!(btn instanceof HTMLButtonElement) || btn.disabled) return;
      const jobId = btn.dataset.jid || "";
      if (!jobId) {
        setStatus("缺少岗位 ID");
        return;
      }
      btn.disabled = true;
      try {
        const data = await petOpenBossJob({
          job_id: jobId,
          security_id: btn.dataset.sid || "",
        });
        setStatus(data?.message || "已在登录态浏览器打开岗位");
      } catch (err) {
        setStatus(err?.message || "打开岗位失败");
      } finally {
        btn.disabled = false;
      }
    });
  }
}

function buildPetJobCardHtml(j, index) {
  const isCareerStage = j.evaluation_mode === "career_stage" || Boolean(j.career_stage_evaluation);
  const stageLabel = j.career_stage_label || "";
  const reasons = (j.analysis_reason || j.profile_reason || j.match_reasons || [])
    .map((r) => `✓ ${escHtml(r)}`)
    .join("<br>");
  const risks = (j.analysis_risk || j.profile_risk || [])
    .map((r) => `⚠ ${escHtml(r)}`)
    .join("<br>");
  const sid = escHtml(j.security_id || "");
  const jid = escHtml(j.job_id || j.encrypt_job_id || "");
  const title = escHtml(j.title || j.jobName || "-");
  const company = escHtml(j.company || j.brandName || "-");
  const salary = escHtml(j.salary || "-");
  const city = escHtml(j.city || "-");
  const experience = escHtml(j.experience || "-");
  const score = j.profile_score ?? j.analysis_score ?? j.match_score ?? "—";

  let careerMetaHtml = "";
  let dimsHtml = "";
  if (isCareerStage) {
    const labeled = j.analysis_dimensions_labeled || {};
    const dimEntries = Object.entries(labeled);
    if (dimEntries.length) {
      dimsHtml = `
        <div class="pet-job-card-dims">
          ${dimEntries
            .map(([name, val]) => `<span class="pet-job-dim"><b>${escHtml(name)}</b> ${escHtml(String(val))}</span>`)
            .join("")}
        </div>`;
    }
    const suitable = j.evaluation_suitable_for || j.career_stage_evaluation?.suitable_for || "";
    const riskLevel = j.evaluation_risk_level || j.career_stage_evaluation?.risk_level || "";
    const confidence = j.evaluation_confidence ?? j.career_stage_evaluation?.confidence;
    const metaParts = [];
    if (stageLabel) metaParts.push(`阶段：${escHtml(stageLabel)}`);
    if (riskLevel) metaParts.push(`风险：${escHtml(String(riskLevel))}`);
    if (confidence != null && confidence !== "") {
      metaParts.push(`置信度：${escHtml(String(Math.round(Number(confidence) * 100)))}%`);
    }
    if (suitable) metaParts.push(escHtml(suitable));
    if (metaParts.length) {
      careerMetaHtml = `<div class="pet-job-card-career-meta">${metaParts.join(" · ")}</div>`;
    }
  }

  const scoreBadge = isCareerStage && stageLabel
    ? `<div class="pet-job-card-score-wrap"><span class="pet-job-card-stage">${escHtml(stageLabel)}</span><span class="pet-job-card-score">${escHtml(String(score))}</span></div>`
    : `<div class="pet-job-card-score">${escHtml(String(score))}</div>`;

  return `
    <div class="pet-job-card-head">
      <div class="pet-job-card-title">#${index} ${title}</div>
      ${scoreBadge}
    </div>
    <div class="pet-job-card-meta">${company} · ${salary} · ${city} · ${experience}</div>
    ${careerMetaHtml}
    ${dimsHtml}
    ${reasons ? `<div class="pet-job-card-reasons">${reasons}</div>` : ""}
    ${risks ? `<div class="pet-job-card-risks">${risks}</div>` : ""}
    ${(j.rag_references || []).length ? `<div class="pet-job-card-rag"><b>参考历史</b> ${escHtml(summarizeRagReferencesBrief(j.rag_references))}</div>` : ""}
    ${j.analysis_review_plan ? formatReviewPlanHtml(j.analysis_review_plan) : ""}
    <div class="pet-job-card-actions">
      <button type="button" class="pet-job-btn pet-job-btn-primary pet-job-shortlist"
        data-sid="${sid}" data-jid="${jid}" data-title="${title}"
        data-company="${company}" data-city="${city}" data-salary="${salary}">加入候选池</button>
      <button type="button" class="pet-job-btn pet-job-btn-ghost pet-job-reject"
        data-sid="${sid}" data-jid="${jid}" data-title="${title}" data-company="${company}">不感兴趣</button>
      <button type="button" class="pet-job-btn pet-job-btn-ghost pet-job-boss-view"
        data-sid="${sid}" data-jid="${jid}">BOSS 查看</button>
    </div>
  `;
}

async function petShortlistJob(payload) {
  const resp = await fetch("/api/boss/shortlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "加入候选池失败");
  return body.data;
}

async function petRejectJob(payload) {
  const resp = await fetch("/api/boss/reject", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await resp.json();
  if (!body?.ok) throw new Error(body?.error?.message || "拒绝失败");
  return body.data;
}

async function petOpenBossJob(payload) {
  const resp = await fetch("/api/boss/open-job", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const raw = await resp.text();
  let body;
  try {
    body = raw ? JSON.parse(raw) : {};
  } catch {
    if (resp.status === 404) {
      throw new Error("打开岗位接口未就绪，请重启 boss web 服务后重试");
    }
    throw new Error(raw || `打开岗位失败 (${resp.status})`);
  }
  if (!body?.ok) throw new Error(body?.error?.message || "打开岗位失败");
  return body.data;
}

function resetAllAgents() {
  restSlotOccupancy.clear();
  interactableOccupancy.clear();
  for (const agent of Object.values(agents)) {
    agent._stopStroll();
    agent._cancelMove();
    agent.atLongRest = false;
    agent._releaseRestSlot();
    agent._restoreDefaultFacing();
  }
}

function setAgentTask(agentId, text) {
  agents[agentId]?.setTaskBubble(text);
}

function truncateTaskLabel(text, maxLen = 14) {
  const s = String(text || "").trim();
  if (!s) return "";
  return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s;
}

function truncateBubbleReason(text, maxLen = 22) {
  const s = String(text || "").trim().replace(/\s+/g, " ");
  if (!s) return "";
  return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s;
}

function isOfflineInactiveFailure(text) {
  const s = String(text || "").trim();
  if (!s || /^离线$/i.test(s)) return true;
  return /(?:长期|半个月以上)?未活跃[：:]\s*离线\s*$/i.test(s)
    || /(?:长期|半个月以上)?不活跃[：:]\s*离线\s*$/i.test(s);
}

function getScoutHardFailures(ev) {
  return (ev?.scout_hard_failures || []).filter(
    (f) => f && !isOfflineInactiveFailure(f),
  );
}

function shouldShowScoutRejectBubble(ev) {
  if (ev?.scout_hard_passed !== false) return false;
  return getScoutHardFailures(ev).length > 0;
}

function formatScoutHistorySkipBubble(ev) {
  const title = truncateBubbleReason(ev?.job?.title || "该岗位", 24);
  return `历史已处理，快速划过\n${title}`;
}

function formatScoutRejectBubble(ev) {
  const failures = getScoutHardFailures(ev);
  if (failures.length) {
    const detail =
      failures.length > 1
        ? `${truncateBubbleReason(failures[0], 16)}；${truncateBubbleReason(failures[1], 12)}`
        : truncateBubbleReason(failures[0], 28);
    return `侦察未过\n${detail}`;
  }
  const msg = String(ev?.message || "");
  if (isOfflineInactiveFailure(msg) || /不活跃[：:]\s*离线/.test(msg)) {
    return "";
  }
  const hardMatch = msg.match(/硬性条件不符[：:]\s*(.+)/);
  if (hardMatch) {
    return `侦察未过\n${truncateBubbleReason(hardMatch[1])}`;
  }
  return "侦察未过\n硬性条件不符";
}

function formatAnalysisRejectBubble(ev) {
  const job = ev?.job || {};
  const score = ev?.score ?? job.analysis_score ?? job.profile_score;
  const detail = truncateBubbleReason(resolveAnalysisFilterReason(job, ev), 36);
  const head = score != null ? `分析未过 ${score} 分` : "分析未过";
  return `${head}\n${detail}`;
}

function refreshIdleAgentTasks() {
  if (scheduleOffHours) {
    setAgentTask("ZC", petScoutOffHoursPaused ? "下班暂停搜岗" : "下班中");
    setAgentTask("FX", "下班中");
    setAgentTask("JK", "下班中");
    setAgentTask("MS", "待命中");
  } else if (officeResting) {
    setAgentTask("ZC", "休息中…");
    setAgentTask("FX", "休息中…");
    setAgentTask("JK", "休息中…");
    setAgentTask("MS", "待命中");
  } else if (!petLocalScouting) {
    setAgentTask("ZC", "待命中");
    setAgentTask("FX", "待命中");
    setAgentTask("JK", jkAlert ? "监控异常" : "待命中");
    setAgentTask("MS", "待命中");
  } else {
    setAgentTask("ZC", "搜岗中");
    setAgentTask("FX", "待命分析");
    setAgentTask("JK", jkAlert ? "处理异常" : "监控浏览器");
    setAgentTask("MS", "待命中");
  }
  petMonitorSidebar?.syncFromApp();
}

function handleScoutEvent(ev, opts = {}) {
  const type = ev?.type || "";
  const local = opts.local === true;
  const catchUp = opts.catchUp === true;
  const alwaysHandle = PET_SCOUT_ALWAYS_HANDLE_EVENTS.has(type);
  if (!catchUp || alwaysHandle) {
    petMonitorSidebar?.handleEvent(ev, { local });
  }

  if (type.startsWith("monitor_")) {
    if (isScoutWorkPaused()) {
      if (type === "monitor_token") {
        applyMonitorTokenUsage(ev.usage);
      }
      refreshIdleAgentTasks();
      return;
    }
    if (type === "monitor_token") {
      applyMonitorTokenUsage(ev.usage);
      const total = ev.usage?.session_total?.total_tokens ?? 0;
      const cost = ev.usage?.cost?.formatted || "";
      agents.JK?.showHeadBubble(
        cost ? `Token ${total} · ${cost}` : `Token ${total}`,
        { durationMs: 2800 },
      );
      return;
    }
    if (type === "monitor_alert" || type === "monitor_stall") {
      jkAlert = true;
      if (shouldApplyWorkClips()) agents.JK?.setClip("work");
      setAgentTask("JK", "检测到异常");
      if (ev.message) {
        setStatus(ev.message);
        agents.JK?.showHeadBubble("检测到异常", { durationMs: 4000 });
      }
    } else if (type === "monitor_browser_restart") {
      jkAlert = false;
      if (shouldApplyWorkClips()) agents.JK?.setClip("sit");
      const seq = ev.sequence === "stall_then_close" ? "（先卡后关）" : "";
      setStatus(ev.message || `监控 AI 已重启浏览器${seq}`);
      setAgentTask("JK", "监控浏览器");
      agents.JK?.showHeadBubble(`浏览器已重启${seq}`, { durationMs: 4500 });
    } else if (type === "monitor_recovered" || type === "monitor_ok") {
      jkAlert = false;
      if (shouldApplyWorkClips()) agents.JK?.setClip("sit");
      setAgentTask("JK", "监控浏览器");
      if (ev.message) setStatus(ev.message);
    }
    return;
  }

  if (
    type === "browser_restart_begin"
    || type === "browser_restart_failed"
    || type === "browser_session_lost"
  ) {
    if (type === "browser_restart_begin") {
      if (shouldApplyWorkClips()) agents.JK?.setClip("work", true);
      setAgentTask("JK", "准备重启");
      setStatus(ev.message || "监控 AI：准备关闭并重启自动化 Chromium…");
      agents.JK?.showHeadBubble("准备重启浏览器", { durationMs: 4000 });
    } else {
      jkAlert = true;
      if (shouldApplyWorkClips()) agents.JK?.setClip("work", true);
      setAgentTask("JK", type === "browser_session_lost" ? "窗口已断开" : "重启失败");
      const hint = ev.sequence === "crash_then_stall"
        ? "（先崩窗后卡）"
        : "（先关窗后未能拉起）";
      setStatus(ev.message || `自动化 Chromium 异常${hint}`);
      agents.JK?.showHeadBubble(
        type === "browser_session_lost" ? `窗口已断开${hint}` : `重启失败${hint}`,
        { durationMs: 8000 },
      );
    }
    refreshIdleAgentTasks();
    return;
  }

  if (shouldSkipScoutWorkUi(type)) {
    refreshIdleAgentTasks();
    return;
  }

  if (catchUp && PET_SCOUT_HIGH_FREQ_EVENTS.has(type)) {
    if (type === "job_passed" && ev.job) {
      petJobSidebar?.addJob(ev.job);
      petScoutJobCount += 1;
    }
    return;
  }

  switch (type) {
    case "start":
      if (scheduleOffHours) {
        setStatus(formatOffHoursStatus());
        refreshIdleAgentTasks();
        break;
      }
      officeResting = false;
      jkAlert = false;
      petJobSidebar?.clear();
      resetAllAgents();
      agents.ZC?.setClip("work", true);
      agents.FX?.setClip("sit", true);
      agents.JK?.setClip("sit", true);
      setAgentTask("ZC", "搜岗启动");
      setAgentTask("FX", "待命分析");
      setAgentTask("JK", "监控浏览器");
      setAgentTask("MS", "待命中");
      if (ev.stats) rememberPetScoutHeaderStats(ev.stats);
      refreshPetHeaderScoutStats();
      break;

    case "stopped":
    case "done":
      petScoutOffHoursPaused = false;
      clearOfficeRestTimer();
      officeResting = false;
      jkAlert = false;
      resetAllAgents();
      wakeFromRest(() => {
        agents.ZC?.setClip("sit", true);
        agents.FX?.setClip("sit", true);
        agents.JK?.setClip("sit", true);
        agents.MS?.setClip("sit", true);
      });
      refreshIdleAgentTasks();
      setStatus(local ? "搜岗已结束 · 各 AI 已回到工位" : "侦察已结束 · 保持窗口打开可等待下次同步");
      break;

    case "boss_browser_closed":
      if (ev.message) setStatus(ev.message);
      setAgentTask("JK", "浏览器已关闭");
      break;

    case "page_start":
      if (officeResting) resumeAfterRest();
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", `浏览第 ${ev.page ?? "?"} 页`);
      petMonitorSidebar?.syncFromApp();
      break;

    case "search_fetch":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", "拉取岗位列表");
      break;

    case "scout_seen":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", "发现新岗位");
      break;

    case "scout_glance":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", truncateTaskLabel(ev.job?.title) || "浏览岗位");
      break;

    case "scout_browse_skip":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", "跳过已浏览");
      break;

    case "scout_history_skip":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", "跳过已侦察");
      agents.ZC?.showHeadBubble(formatScoutHistorySkipBubble(ev), {
        durationMs: 3200,
      });
      break;

    case "scout_filter":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", "筛选岗位");
      if (shouldShowScoutRejectBubble(ev)) {
        const bubble = formatScoutRejectBubble(ev);
        if (bubble) {
          agents.ZC?.showHeadBubble(bubble, {
            durationMs: 4800,
            explain: true,
          });
        }
      }
      break;

    case "scout_skip":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", "跳过岗位");
      break;

    case "scout_duplicate":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", "重复岗位");
      break;

    case "scout_transmit":
      if (shouldApplyWorkClips()) {
        agents.ZC?.setClip("work");
        agents.FX?.setClip("work");
      }
      setAgentTask("ZC", "传送岗位");
      setAgentTask("FX", truncateTaskLabel(ev.job?.title) || "接收分析");
      void refreshScoutHistorySidebar();
      break;

    case "analysis_start": {
      if (shouldApplyWorkClips()) agents.FX?.setClip("work");
      let fxLabel = truncateTaskLabel(ev.job?.title) || "分析岗位";
      if (ev.career_stage_mode) {
        const stage = ev.career_stage_label || "职业阶段";
        fxLabel = `${stage} · ${fxLabel}`;
      }
      setAgentTask("FX", fxLabel);
      break;
    }

    case "job_passed":
      if (shouldApplyWorkClips()) agents.FX?.setClip("work");
      setAgentTask("FX", "岗位通过 ✓");
      if (ev.job) {
        petJobSidebar?.addJob(ev.job);
        petScoutJobCount += 1;
      }
      if (ev.stats) rememberPetScoutHeaderStats(ev.stats);
      refreshPetHeaderScoutStats();
      break;

    case "job_filtered":
      if (shouldApplyWorkClips()) agents.FX?.setClip("work");
      setAgentTask("FX", "岗位未通过");
      petDocumentCabinet?.markNew("filtered_analysis");
      agents.FX?.showHeadBubble(formatAnalysisRejectBubble(ev), {
        durationMs: 5600,
        explain: true,
      });
      break;

    case "off_hours_pause":
      officeResting = false;
      if (!scheduleOffHours) {
        scheduleOffHours = true;
      }
      petScoutOffHoursPaused = true;
      ensureOffHoursFreeActivity();
      refreshIdleAgentTasks();
      setStatus(ev.message || formatOffHoursScoutStatus());
      maybeShowDailyPicksAtEndOfDay();
      maybeSendDailyReportEmailAtEndOfDay();
      break;

    case "work_hours_resume":
      scheduleOffHours = false;
      petScoutOffHoursPaused = false;
      endOffHoursMode();
      break;

    case "round_fatigue_pause": {
      const sec = ev.pause_sec ?? ev.remaining_sec ?? petConfig?.restThresholdSec ?? 120;
      setOfficeRest(true, sec, true);
      setStatus(formatRoundRestStatus(sec, ev.message || "疲劳休息"));
      petMonitorSidebar?.syncFromApp();
      break;
    }

    case "round_pause": {
      const sec = ev.pause_sec ?? 60;
      setOfficeRest(true, sec, false);
      setStatus(formatRoundRestStatus(sec, ev.message || "本轮休息"));
      petMonitorSidebar?.syncFromApp();
      break;
    }

    case "page_hidden_pause":
    case "page_hidden_continue":
      setStatus(ev.message || "页面已隐藏，搜岗继续在后台运行…");
      if (petMonitorSidebar && ev.message) {
        petMonitorSidebar.progress = ev.message;
        petMonitorSidebar._pushAction?.(ev.message, ev.type || "page_hidden_continue", ev);
        petMonitorSidebar._render?.();
      }
      break;

    case "page_visible_resume":
      setStatus(ev.message || "页面已恢复，正在同步进度…");
      void syncScoutLiveFromServer({ resumeUi: true });
      break;

    case "scout_ack_warn":
      petMonitorSidebar?.setStreamState?.(
        petMonitorSidebar.streamState || "streaming",
        ev.message || "Web 同步警告",
      );
      petMonitorSidebar?._pushAction?.(ev.message || "同步警告", "scout_ack_warn", ev);
      petMonitorSidebar?._render?.();
      agents.JK?.showHeadBubble("同步警告", { durationMs: 4000 });
      break;

    case "round_resume":
      resumeAfterRest();
      setAgentTask("ZC", "继续搜岗");
      setStatus(ev.message || "休息结束，继续搜岗");
      petMonitorSidebar?.exitRestState();
      petMonitorSidebar?.syncFromApp();
      break;

    case "scout_heartbeat": {
      if (officeResting && !scheduleOffHours) {
        const sec = ev.remaining_sec ?? 0;
        if (sec <= 0) {
          resumeAfterRest();
          petMonitorSidebar?.exitRestState();
          setStatus(petLocalScouting ? "搜岗进行中 · 休息结束，继续工作" : "侦察进行中 · 休息结束，继续工作");
          petMonitorSidebar?.syncFromApp();
          break;
        }
        const isFatigue = /疲劳/.test(ev.message || "");
        applyRestClip("ZC", sec, isFatigue);
        applyRestClip("FX", sec, isFatigue);
        applyRestClip("JK", sec, isFatigue);
        const restLabel = sec > 0 ? `休息 ${Math.ceil(sec)}s` : "休息中…";
        setAgentTask("ZC", restLabel);
        setAgentTask("FX", restLabel);
        setAgentTask("JK", restLabel);
        setStatus(formatRoundRestStatus(sec, ev.message));
      }
      petMonitorSidebar?.syncFromApp();
      break;
    }

    case "round_start":
      if (officeResting) resumeAfterRest();
      setAgentTask("ZC", "新一轮搜岗");
      refreshIdleAgentTasks();
      petMonitorSidebar?.syncFromApp();
      break;

    case "round_home_refresh":
      if (officeResting) resumeAfterRest();
      setAgentTask("ZC", "新一轮搜岗");
      petMonitorSidebar?.syncFromApp();
      break;

    case "browser_stuck":
      jkAlert = true;
      if (shouldApplyWorkClips()) {
        agents.JK?.setClip("work", true);
        agents.ZC?.setClip("sit", true);
      }
      setStatus(ev.message || "浏览器页面卡住，监控 AI 正在处理…");
      setAgentTask("JK", "页面卡住");
      setAgentTask("ZC", "等待恢复");
      agents.JK?.showHeadBubble("页面卡住", { durationMs: 4000 });
      break;

    case "browser_restarted":
      jkAlert = false;
      if (shouldApplyWorkClips()) {
        agents.JK?.setClip("sit", true);
        agents.ZC?.setClip("work", true);
      }
      setStatus(ev.message || "浏览器已重启，继续侦察");
      setAgentTask("JK", "监控浏览器");
      setAgentTask("ZC", "继续搜岗");
      agents.JK?.showHeadBubble("浏览器已重启", { durationMs: 4500 });
      break;

    case "account_risk":
      jkAlert = true;
      if (shouldApplyWorkClips()) agents.JK?.setClip("work");
      setAgentTask("JK", "账号风险");
      break;

    case "scout_query_strategy":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", "生成搜索策略");
      setStatus(ev.message || "侦察 AI 已生成搜索词策略");
      break;

    case "scout_query_switch":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", truncateTaskLabel(ev.query) || "切换搜索词");
      setStatus(ev.message || `侦察 AI 切换搜索词：${ev.query || ""}`);
      break;

    case "scout_query_depth":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("FX", `本组目标 ${ev.pass_target ?? "?"} 个`);
      setAgentTask("ZC", truncateTaskLabel(ev.query) || "搜岗中");
      setStatus(ev.message || "已设定本组关键词通过目标");
      break;

    case "scout_query_depth_progress":
      if (shouldApplyWorkClips()) agents.FX?.setClip("work");
      setAgentTask("FX", `已通过 ${ev.pass_count ?? 0}/${ev.pass_target ?? "?"}`);
      break;

    case "scout_query_depth_met":
      if (shouldApplyWorkClips()) {
        agents.ZC?.setClip("work");
        agents.FX?.setClip("sit");
      }
      setAgentTask("ZC", ev.list_exhausted ? "列表扫完换词" : "准备切换词");
      setAgentTask("FX", "本组已完成");
      setStatus(ev.message || (ev.list_exhausted ? "列表已扫完，切换下一搜索词" : "本组关键词已达通过目标，即将切换"));
      break;

    case "scout_query_cooldown":
      agents.ZC?.setClip("sit");
      setAgentTask("ZC", "搜索词冷却");
      setStatus(ev.message || "列表已扫完，搜索词冷却中");
      agents.ZC?.showHeadBubble(ev.message || "搜索词冷却中，稍后再搜", { durationMs: 4800 });
      break;

    case "scout_query_skip_cooldown":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", truncateTaskLabel(ev.next_query) || "换词搜岗");
      setStatus(ev.message || "跳过冷却中的搜索词");
      break;

    case "page_done":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", "本页完成");
      break;

    case "page_turn":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", truncateTaskLabel(ev.message) || "准备翻页");
      if (ev.message) setStatus(ev.message);
      break;

    case "page_empty":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", "本页无岗位");
      if (ev.message) setStatus(ev.message);
      break;

    case "scout_list_exhausted":
      if (shouldApplyWorkClips()) agents.ZC?.setClip("work");
      setAgentTask("ZC", ev.switch_query ? "换词继续" : "列表已扫完");
      setStatus(ev.message || "本词列表已扫完");
      agents.ZC?.showHeadBubble(
        ev.message || (ev.switch_query ? "列表扫完，切换下一搜索词" : "列表已扫完，从第 1 页重新搜"),
        { durationMs: 5200 },
      );
      break;

    case "scout_strategy_plan": {
      petDocumentCabinet?.markNew("scout_strategy_plan");
      const cap = ev?.plan?.effective_cap;
      const planned = ev?.plan?.planned_cap;
      const summary = ev?.message || ev?.plan?.strategy_summary || "侦察策略已更新";
      setAgentTask("ZC", cap != null && planned != null ? `策略 ${cap}/${planned} 页` : "策略已规划");
      setStatus(summary);
      agents.ZC?.showHeadBubble(truncateBubbleReason(summary, 40), { durationMs: 4500 });
      break;
    }

    case "secretary_report":
    case "secretary_vlog":
    case "secretary_run":
      agents.MS?.setClip("work");
      if (type === "secretary_run") {
        setAgentTask("MS", "整理日报");
        setStatus("秘书 AI 正在整理昨日岗位日报与 vlog…");
      } else if (type === "secretary_vlog") {
        setAgentTask("MS", "生成 vlog");
        setStatus("秘书 AI 正在生成小红书 vlog 文案…");
      } else {
        setAgentTask("MS", "整理日报");
        setStatus("秘书 AI 正在整理岗位日报…");
      }
      break;

    default:
      break;
  }
}

function buildLegend() {
  const el = document.getElementById("petLegend");
  if (!el || !petConfig) return;
  el.innerHTML = "";
  for (const [id, cfg] of Object.entries(petConfig.characters)) {
    if (cfg.enabled === false) continue;
    const chip = document.createElement("span");
    chip.className = "pet-chip";
    chip.dataset.agent = id;
    chip.innerHTML = `<strong>${cfg.label}</strong> 坐`;
    el.appendChild(chip);
  }
  const hint = document.createElement("p");
  hint.className = "pet-sync-hint";
  hint.id = "petSyncHint";
  hint.textContent =
    "点击顶部「开始搜岗」启动各 AI · 左侧可管理侦察历史 · 工位面板配置筛选与登录";
  el.appendChild(hint);
}

function buildDebugPanel() {
  const panel = document.getElementById("petDebugPanel");
  if (!panel || !petConfig) return;
  panel.innerHTML = "";

  for (const [id, cfg] of Object.entries(petConfig.characters)) {
    if (cfg.enabled === false) continue;
    const row = document.createElement("div");
    row.className = "pet-debug-row";
    const title = document.createElement("span");
    title.textContent = cfg.label;
    row.appendChild(title);

    for (const clipKey of ["sit", "work", "walk", "run", "stroll", "sleepShort", "sleepLong"]) {
      if (clipKey === "stroll") {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = CLIP_LABELS.stroll;
        btn.addEventListener("click", () => agents[id]?.beginStroll());
        row.appendChild(btn);
        continue;
      }
      if (clipKey === "sleepLong" && (cfg.sleepVariants ?? 2) < 2 && !cfg.longRest) continue;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = CLIP_LABELS[clipKey] || clipKey;
      if (clipKey === "sleepLong" && agents[id]?.canLongRest()) {
        btn.addEventListener("click", () => agents[id]?.beginLongRest());
      } else {
        btn.addEventListener("click", () => agents[id]?.setClip(clipKey, true));
      }
      row.appendChild(btn);
    }
    panel.appendChild(row);
  }
}

async function loadPetAssetMtimes() {
  try {
    const resp = await fetch(`/api/pet/asset-mtimes?t=${Date.now()}`, { cache: "no-store" });
    if (!resp.ok) return;
    const body = await resp.json();
    if (body?.ok && body.data && typeof body.data === "object") {
      petAssetMtimes = body.data;
    }
  } catch {
    /* 降级为 desks.json 中的 assetVersion */
  }
}

async function initPetOffice() {
  const stage = document.getElementById("petStage");
  const bg = document.getElementById("petBackground");
  if (!stage || !bg) return;

  let config;
  try {
    const resp = await fetch(`${PET_BASE}/desks.json?v=${Date.now()}`, { cache: "no-store" });
    config = await resp.json();
  } catch {
    setStatus("无法加载 desks.json");
    return;
  }

  const baseClips = { ...config.clips };
  const optionalClips = config.futureClips || {};
  petConfig = { ...config, clips: { ...baseClips, ...optionalClips } };
  petAssetVersion = config.assetVersion ?? config.backgroundVersion ?? 1;
  await loadPetAssetMtimes();

  const scale = config.scale ?? 3;
  const logicalW = config.canvas.width;
  const logicalH = config.canvas.height;
  const viewport = document.getElementById("petStageViewport");
  stage.style.width = `${logicalW}px`;
  stage.style.height = `${logicalH}px`;
  stage.style.transform = `scale(${scale})`;
  stage.style.transformOrigin = "top left";

  if (viewport) {
    viewport.style.width = `${logicalW * scale}px`;
    viewport.style.height = `${logicalH * scale}px`;
  }

  if (config.background) {
    bg.width = logicalW;
    bg.height = logicalH;
    bg.src = petAssetUrl(config.background);
    bg.hidden = false;
    bg.onerror = () => {
      bg.hidden = true;
      setStatus(`未找到 ${config.background}，请将场景图放入 static/pet/`);
    };
  }

  if (config.bowls?.length) {
    petBowls = new PetBowls(stage, config.bowls);
  }

  if (config.resumeDesk) {
    petResumeDesk = new PetResumeDesk(stage, config.resumeDesk);
  }

  if (config.documentCabinet) {
    petDocumentCabinet = new PetDocumentCabinet(stage, config.documentCabinet);
  }

  petArchiveManager = new PetArchiveManager();

  if (config.deskPlates?.length) {
    petDeskPlates = new PetDeskPlates(stage, config.deskPlates);
  }

  const globalCharScale = config.characterScale ?? 1;
  for (const [id, cfg] of Object.entries(config.characters)) {
    if (cfg.enabled === false) continue;
    const agent = new PetAgent(
      id,
      cfg,
      baseClips,
      optionalClips,
      config.destinations,
      config.move,
      config.activity,
      globalCharScale,
    );
    agents[id] = agent;
    stage.appendChild(agent.root);
    agent.setClip("sit");
  }

  buildLegend();
  buildDebugPanel();
  initPetScoutControls();
  initScoutHistorySidebar();
  const monitorRoot = document.getElementById("petMonitorSidebar");
  if (monitorRoot) petMonitorSidebar = new PetMonitorSidebar(monitorRoot);
  const sidebarRoot = document.getElementById("petJobSidebar");
  if (sidebarRoot) petJobSidebar = new PetJobSidebar(sidebarRoot);
  startWorkScheduleWatcher();
  // 先尝试恢复已有后端任务，再按工作时段自动开搜岗（需等地区列表加载完）
  void (async () => {
    await loadPetCities();
    await tryResumeScoutSubscription();
    if (scheduleOffHours && isPastWorkDayEnd()) {
      maybeShowDailyPicksAtEndOfDay();
      maybeSendDailyReportEmailAtEndOfDay();
    } else if (!scheduleOffHours && !petLocalScouting) {
      const periodKey = getCurrentWorkPeriodKey();
      if (periodKey && periodKey !== lastWorkPeriodKey) {
        lastWorkPeriodKey = periodKey;
        onWorkPeriodStarted(periodKey);
      } else if (canAutoStartScoutNow()) {
        tryAutoStartScout();
      }
    }
  })();
  if (!scheduleOffHours && !petLocalScouting) {
    const hints = [];
    if (config.documentCabinet) hints.push("点击资料柜查看档案");
    if (config.bowls?.length) hints.push("点击食盆/水碗可加满或清空");
    if (isScoutUserStopped()) {
      hints.push("已手动停止搜岗 · 点击「开始搜岗」恢复");
    } else if (!canAutoStartScoutNow()) {
      hints.push("点击「开始搜岗」启动各 AI");
    }
    if (hints.length) setStatus(hints.join(" · "));
  }

  refreshIdleAgentTasks();
}

initPetOffice();
