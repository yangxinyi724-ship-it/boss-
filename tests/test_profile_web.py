import json
from pathlib import Path

import pytest

from pet_boss.web.profile_api import ProfileWebError, ProfileWebService
from pet_boss.web.server import create_app


def test_save_and_status(tmp_path: Path):
	svc = ProfileWebService(tmp_path)
	svc.save_resume(name="web-test", title="工程师", content="Golang AI Agent 5年经验")
	st = svc.status()
	assert st["ai_configured"] is False
	assert any(r["name"] == "web-test" for r in st["resumes"])


def test_delete_resume(tmp_path: Path):
	svc = ProfileWebService(tmp_path)
	svc.save_resume(name="del-test", title="工程师", content="测试内容")
	svc.delete_resume("del-test")
	st = svc.status()
	assert not any(r["name"] == "del-test" for r in st["resumes"])
	assert st["has_parsed_resume"] is False


def test_delete_resume_endpoint(tmp_path: Path):
	from starlette.testclient import TestClient

	svc = ProfileWebService(tmp_path)
	svc.save_resume(name="default", title="工程师", content="测试")
	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.delete("/api/resume?name=default")
	assert resp.status_code == 200
	body = resp.json()
	assert body["ok"]
	assert body["data"]["deleted"]


def test_parse_requires_resume(tmp_path: Path):
	svc = ProfileWebService(tmp_path)
	with pytest.raises(ProfileWebError) as exc:
		svc.parse_resume("missing")
	assert exc.value.code == "RESUME_NOT_FOUND"


def test_create_app_routes(tmp_path: Path):
	app = create_app(tmp_path)
	paths = {getattr(r, "path", None) for r in app.routes}
	assert "/" in paths
	assert "/pet" in paths
	assert "/api/status" in paths
	assert "/api/resume/upload-pdf" in paths
	assert "/api/boss/scout/stream" in paths


def test_index_redirects_to_pet(tmp_path: Path):
	from starlette.testclient import TestClient

	client = TestClient(create_app(tmp_path), follow_redirects=False)
	resp = client.get("/")
	assert resp.status_code == 302
	assert resp.headers.get("location") == "/pet"


def test_boss_auth_status(tmp_path: Path):
	from pet_boss.web.boss_service import BossWebService

	svc = BossWebService(tmp_path)
	st = svc.auth_status()
	assert "logged_in" in st
	assert "persisted" in st
	assert st["platform"] == "zhipin"
	assert st["persisted"] is False


def test_boss_logout_clears_session(tmp_path: Path):
	from pet_boss.auth.token_store import TokenStore
	from pet_boss.web.boss_service import BossWebService

	store = TokenStore(tmp_path / "auth")
	store.save({"cookies": {"wt2": "x"}, "stoken": "s"})
	svc = BossWebService(tmp_path)
	assert svc.auth_status()["persisted"] is True
	data = svc.logout()
	assert "清除" in data["message"]
	assert svc.auth_status()["persisted"] is False


def test_boss_auth_status_stale_session_not_logged_in(tmp_path: Path):
	from unittest.mock import patch

	from pet_boss.auth.token_store import TokenStore
	from pet_boss.web.boss_service import BossWebService

	TokenStore(tmp_path / "auth").save({"cookies": {"wt2": "stale"}, "stoken": "s"})
	svc = BossWebService(tmp_path)
	with patch(
		"pet_boss.web.boss_service.AuthManager.resolve_session",
		return_value=({"cookies": {"wt2": "stale"}}, False),
	):
		st = svc.auth_status(sync=True)
	assert st["persisted"] is True
	assert st["logged_in"] is False
	assert st["session_stale"] is True
	assert st["verified"] is False


def test_boss_auth_status_local_logged_in_without_sync(tmp_path: Path):
	from pet_boss.auth.token_store import TokenStore
	from pet_boss.web.boss_service import BossWebService

	TokenStore(tmp_path / "auth").save({"cookies": {"wt2": "ok"}, "stoken": "s"})
	svc = BossWebService(tmp_path)
	st = svc.auth_status(sync=False)
	assert st["logged_in"] is True
	assert st["verified"] is False
	assert st["session_stale"] is False


def test_api_status_skips_boss_sync_by_default(tmp_path: Path):
	from unittest.mock import patch

	from starlette.testclient import TestClient

	from pet_boss.web.server import create_app

	app = create_app(tmp_path)
	client = TestClient(app)
	with patch("pet_boss.web.boss_service.BossWebService.auth_status") as mock_auth:
		mock_auth.return_value = {"logged_in": False, "persisted": False, "platform": "zhipin"}
		resp = client.get("/api/status")
	assert resp.status_code == 200
	mock_auth.assert_called_once_with(sync=False)


def test_api_status_boss_sync_query(tmp_path: Path):
	from unittest.mock import patch

	from starlette.testclient import TestClient

	from pet_boss.web.server import create_app

	app = create_app(tmp_path)
	client = TestClient(app)
	with patch("pet_boss.web.boss_service.BossWebService.auth_status") as mock_auth:
		mock_auth.return_value = {"logged_in": True, "verified": True, "persisted": True, "platform": "zhipin"}
		resp = client.get("/api/status?boss_sync=1")
	assert resp.status_code == 200
	mock_auth.assert_called_once_with(sync=True)


def test_boss_login_routes_exist(tmp_path: Path):
	app = create_app(tmp_path)
	paths = {getattr(r, "path", None) for r in app.routes}
	assert "/api/boss/login" in paths
	assert "/api/boss/sync" in paths
	assert "/api/boss/logout" in paths
	assert "/api/boss/scout/history" in paths
	assert "/api/boss/scout/history/clear" in paths
	assert "/api/boss/open-job" in paths


def test_reject_job_saves_learning_log(tmp_path: Path):
	from pet_boss.profile.store import ProfileStore
	from pet_boss.web.boss_service import BossWebService

	svc = BossWebService(tmp_path)
	data = svc.reject_job(
		security_id="sec1",
		job_id="job1",
		title="Go 开发",
		company="测试公司",
		reason="不想外包",
		tags=["外包/派遣", "工作强度"],
		analysis_score=72,
		analysis_reason=["技能匹配"],
		analysis_risk=["加班较多"],
	)
	assert data["rejected"] is True
	assert data["learning_log_id"] > 0
	assert data["weight_changes"]
	assert data["ai_memory_added"]

	with ProfileStore(tmp_path) as store:
		logs = store.list_preference_learning_logs(limit=10)
	assert len(logs) == 1
	assert logs[0]["user_reason"] == "不想外包"
	assert "外包/派遣" in logs[0]["user_tags"]
	assert logs[0]["analysis_score"] == 72


def test_api_profile_learning_log(tmp_path: Path):
	from starlette.testclient import TestClient

	from pet_boss.web.boss_service import BossWebService
	from pet_boss.web.server import create_app

	BossWebService(tmp_path).reject_job(
		security_id="sec2",
		job_id="job2",
		title="Java 开发",
		company="另一公司",
		reason="通勤太远",
		tags=["通勤太远"],
	)

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.get("/api/profile/learning-log")
	assert resp.status_code == 200
	body = resp.json()
	assert body["ok"]
	assert body["data"]["total"] == 1
	assert body["data"]["items"][0]["title"] == "Java 开发"


def test_api_profile_learning_log_clear(tmp_path: Path):
	from starlette.testclient import TestClient

	from pet_boss.web.boss_service import BossWebService
	from pet_boss.web.server import create_app

	svc = BossWebService(tmp_path)
	svc.reject_job(
		security_id="sec3",
		job_id="job3",
		title="测试岗",
		company="公司",
		reason="薪资偏低",
		tags=["薪资偏低"],
	)

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.delete("/api/profile/learning-log")
	assert resp.status_code == 200
	data = resp.json()["data"]
	assert data["logs_removed"] == 1
	resp2 = client.get("/api/profile/learning-log")
	assert resp2.json()["data"]["total"] == 0


def test_api_boss_shortlist_list(tmp_path: Path):
	from starlette.testclient import TestClient

	from pet_boss.cache.store import CacheStore
	from pet_boss.web.server import create_app

	app = create_app(tmp_path)
	cache = CacheStore(tmp_path / "cache" / "boss_agent.db")
	cache.add_shortlist({
		"security_id": "s1",
		"job_id": "j1",
		"title": "Python 工程师",
		"company": "测试公司",
		"city": "深圳",
		"salary": "15-20K",
		"source": "web-profile",
	})
	cache.close()

	client = TestClient(app)
	resp = client.get("/api/boss/shortlist")
	assert resp.status_code == 200
	data = resp.json()["data"]
	assert data["total"] == 1
	assert data["items"][0]["title"] == "Python 工程师"

	resp2 = client.post("/api/boss/shortlist/remove", json={"security_id": "s1", "job_id": "j1"})
	assert resp2.status_code == 200
	resp3 = client.get("/api/boss/shortlist")
	assert resp3.json()["data"]["total"] == 0


def test_build_job_detail_page_url():
	from pet_boss.api.browser_client import build_job_detail_page_url

	url = build_job_detail_page_url("abc123", "sec456")
	assert url.endswith("/job_detail/abc123.html?securityId=sec456")


def test_api_boss_analysis_filtered_list(tmp_path: Path):
	from starlette.testclient import TestClient

	from pet_boss.cache.store import CacheStore
	from pet_boss.web.server import create_app

	app = create_app(tmp_path)
	cache = CacheStore(tmp_path / "cache" / "boss_agent.db")
	cache.record_analysis_job(
		{
			"security_id": "s2",
			"job_id": "j2",
			"title": "Java 开发",
			"company": "华为",
			"city": "深圳",
			"salary": "20-30K",
			"analysis_score": 42,
			"analysis_filter_reason": "院校层级与公司招聘偏好不匹配",
			"analysis_risk": ["华为几乎不考虑三本/民办本科"],
			"school_company_fit": {"exclude": True, "fit_level": "low"},
		},
		"filtered",
	)
	cache.close()

	client = TestClient(app)
	resp = client.get("/api/boss/analysis/filtered")
	assert resp.status_code == 200
	data = resp.json()["data"]
	assert data["total"] == 1
	assert data["items"][0]["title"] == "Java 开发"
	assert "三本" in data["items"][0]["filter_reason"] or "院校" in data["items"][0]["filter_reason"]


def test_api_boss_open_job(tmp_path: Path):
	from unittest.mock import patch

	from starlette.testclient import TestClient

	from pet_boss.web.server import create_app

	app = create_app(tmp_path)
	client = TestClient(app)
	with patch("pet_boss.web.server._run_browser_blocking") as mock_run:
		mock_run.return_value = {"mode": "browser", "url": "https://www.zhipin.com/job_detail/j1.html", "message": "ok"}
		resp = client.post("/api/boss/open-job", json={"job_id": "j1", "security_id": "s1"})
	assert resp.status_code == 200
	assert resp.json()["data"]["mode"] == "browser"
	mock_run.assert_called_once()


def test_api_boss_scout_history_clear(tmp_path: Path):
	from starlette.testclient import TestClient

	from pet_boss.agents.scout_memory import record_scout_outcome
	from pet_boss.cache.store import CacheStore
	from pet_boss.profile.store import ProfileStore
	from pet_boss.web.server import create_app

	app = create_app(tmp_path)
	cache = CacheStore(tmp_path / "cache" / "boss_agent.db")
	job = {"security_id": "s1", "job_id": "j1", "title": "Go", "company": "测试"}
	record_scout_outcome(cache, job, "seen")
	cache.record_analysis_job(job, "passed")
	cache.add_shortlist({**job, "city": "", "salary": "", "source": "test"})
	cache.close()
	with ProfileStore(tmp_path) as store:
		store.record_feedback(security_id="s1", job_id="j1", action="shortlisted")
		store.add_ai_memory("analysis", "reject_pattern", "测试记忆", source_job_key="s1:j1")

	client = TestClient(app)
	resp = client.get("/api/boss/scout/history")
	assert resp.status_code == 200
	assert resp.json()["data"]["total"] >= 1

	resp2 = client.post("/api/boss/scout/history/clear")
	assert resp2.status_code == 200
	body2 = resp2.json()
	assert body2["ok"] is True
	assert body2["data"]["history_removed"] >= 1
	assert body2["data"]["analysis_removed"] >= 1
	assert body2["data"]["shortlist_removed"] >= 1
	assert body2["data"]["feedback_removed"] >= 1
	assert body2["data"]["analysis_memory_removed"] >= 1

	resp3 = client.get("/api/boss/scout/history")
	assert resp3.json()["data"]["total"] == 0
	resp4 = client.get("/api/boss/shortlist")
	assert resp4.json()["data"]["total"] == 0


def test_boss_list_cities(tmp_path: Path):
	from pet_boss.web.boss_service import BossWebService

	cities = BossWebService(tmp_path).list_cities()
	assert len(cities) >= 10
	assert "广州" in cities
	assert cities.index("北京") < cities.index("长沙")


def test_upload_pdf_endpoint(tmp_path: Path):
	pytest.importorskip("multipart")
	from io import BytesIO
	from pypdf import PdfWriter
	from starlette.testclient import TestClient

	writer = PdfWriter()
	writer.add_blank_page(width=200, height=200)
	buf = BytesIO()
	writer.write(buf)
	pdf_bytes = buf.getvalue()

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.post(
		"/api/resume/upload-pdf",
		files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
		data={"name": "pdf-test", "auto_parse": "false"},
	)
	assert resp.status_code in (200, 422, 503)
	body = resp.json()
	assert "ok" in body


def test_resume_pdf_endpoint(tmp_path: Path):
	from io import BytesIO

	from pypdf import PdfWriter
	from starlette.testclient import TestClient

	writer = PdfWriter()
	writer.add_blank_page(width=200, height=200)
	buf = BytesIO()
	writer.write(buf)
	pdf_bytes = buf.getvalue()

	upload_dir = tmp_path / "resumes" / "uploads"
	upload_dir.mkdir(parents=True, exist_ok=True)
	(upload_dir / "pdf-view.pdf").write_bytes(pdf_bytes)

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.get("/api/resume/pdf?name=pdf-view")
	assert resp.status_code == 200
	assert resp.headers["content-type"].startswith("application/pdf")
	assert resp.content[:4] == b"%PDF"

	missing = client.get("/api/resume/pdf?name=missing")
	assert missing.status_code == 404


def test_pet_office_route(tmp_path: Path):
	from starlette.testclient import TestClient

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.get("/pet")
	assert resp.status_code == 200
	assert "pet.js" in resp.text
	assert "AI 办公室" in resp.text


def test_secretary_daily_report_endpoint(tmp_path: Path):
	from starlette.testclient import TestClient

	app = create_app(tmp_path)
	client = TestClient(app)
	paths = {getattr(r, "path", None) for r in app.routes}
	assert "/api/secretary/daily-report" in paths
	assert "/api/secretary/send-daily-email" in paths
	resp = client.get("/api/secretary/daily-report?date=today")
	assert resp.status_code == 200
	body = resp.json()
	assert body["ok"] is True
	assert "daily_picks" in body["data"]
	assert "summary" in body["data"]


def test_secretary_daily_pick_dates_endpoint(tmp_path: Path):
	from datetime import datetime

	from starlette.testclient import TestClient

	from pet_boss.cache.store import CacheStore

	with CacheStore(tmp_path / "cache" / "boss_agent.db") as cache:
		ts = datetime(2026, 6, 28, 15, 0, 0).timestamp()
		cache.record_analysis_job(
			{
				"security_id": "s1",
				"job_id": "j1",
				"title": "Python",
				"company": "ACME",
				"city": "上海",
				"salary": "20K",
				"analysis_score": 88,
			},
			"passed",
			search_query="python",
			search_city="上海",
			analyzed_at=ts,
		)

	app = create_app(tmp_path)
	client = TestClient(app)
	paths = {getattr(r, "path", None) for r in app.routes}
	assert "/api/secretary/daily-picks/dates" in paths
	resp = client.get("/api/secretary/daily-picks/dates")
	assert resp.status_code == 200
	body = resp.json()
	assert body["ok"] is True
	assert "today" in body["data"]
	assert any(item["date"] == "2026-06-28" for item in body["data"]["dates"])
	assert body["data"]["dates"][0]["passed_count"] >= 1


def test_pet_desks_config(tmp_path: Path):
	from starlette.testclient import TestClient

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.get("/static/pet/desks.json")
	assert resp.status_code == 200
	data = resp.json()
	assert data["canvas"]["width"] == 300
	assert len(data["bowls"]) == 2
	assert data["bowls"][0]["full"] == "wan2.png"
	assert data["resumeDesk"]["upload"]["image"] == "jian.png"
	assert data["resumeDesk"]["display"]["image"] == "jianli.png"
	assert data["resumeDesk"]["delete"]["image"] == "shan.gif"
	assert data["documentCabinet"]["image"] == "资料柜.png"
	assert data["futureClips"]["eat"] == ["eat1.gif", "eat2.gif"]
	assert data["workSchedule"]["periods"][0]["start"] == "09:00"
	assert data["workSchedule"]["periods"][1]["end"] == "17:00"
	assert data["secretary"]["duties"][0] == "resume_parse"
	assert "daily_report_six_dim" in data["secretary"]["duties"]
	assert data["secretary"]["sixDimensions"][0] == "skill"
	assert data["scout"]["autoKeywords"] is True
	assert data["deskPlates"][0]["nameplate"] == "监控员.png"
	assert data["deskPlates"][0]["panel"]["image"] == "分析设置.png"
	assert data["deskPlates"][0]["panel"]["bossLoginText"] == "登录 BOSS"
	assert data["deskPlates"][0]["panel"]["bossSyncText"] == "同步登录态"
	assert data["deskPlates"][0]["panel"]["tokenPricing"]["inputPerM"] == 1
	assert data["deskPlates"][0]["panel"]["tokenPricing"]["inputCacheHitPerM"] == 0.02
	assert data["deskPlates"][1]["nameplate"] == "侦察员.png"
	assert data["deskPlates"][1]["panel"]["confirmButtonText"] == "确认"
	assert data["deskPlates"][2]["nameplate"] == "分析员.png"
	assert data["deskPlates"][2]["plateText"]["text"] == "分析员"
	assert data["deskPlates"][3]["nameplate"] == "秘书.png"
	assert data["deskPlates"][3]["plateText"]["text"] == "秘书"
	assert data["deskPlates"][3]["panel"]["emailGuideText"] == "设置邮箱"
	assert data["deskPlates"][3]["panel"]["inputImage"] == "输入框.png"
	assert data["deskPlates"][3]["panel"]["buttonImage"] == "小按钮.png"
	assert data["deskPlates"][3]["panel"]["actions"]["careerChat"]["text"] == "职业方向对话"
	assert data["deskPlates"][3]["panel"]["confirmButtonText"] == "确认"
	assert data["deskPlates"][3]["panel"]["layout"]["emailGuideText"]["fontSize"] == 5
	assert data["deskPlates"][3]["panel"]["layout"]["emailRow"]["marginTop"] == 20
	assert data["deskPlates"][2]["panel"]["image"] == "分析设置.png"
	assert data["characters"]["JK"]["sleepVariants"] == 1
	assert data["characters"]["MS"]["enabled"] is True
	assert data["characters"]["MS"]["role"] == "secretary"


def test_pet_asset_mtimes_endpoint(tmp_path: Path):
	from starlette.testclient import TestClient

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.get("/api/pet/asset-mtimes")
	assert resp.status_code == 200
	body = resp.json()
	assert body["ok"] is True
	assert isinstance(body["data"], dict)
	assert body["data"].get("分析员.png", 0) > 0


def test_secretary_email_api(tmp_path: Path):
	from starlette.testclient import TestClient

	app = create_app(tmp_path)
	client = TestClient(app)

	resp = client.get("/api/secretary/email")
	assert resp.status_code == 200
	data = resp.json()["data"]
	assert data["recipient_email"] == ""
	assert data["has_smtp_password"] is False
	assert "password" not in data

	resp = client.post(
		"/api/secretary/email",
		json={
			"recipient_email": "user@qq.com",
			"smtp_auth_code": "test-auth-code",
		},
	)
	assert resp.status_code == 200
	body = resp.json()["data"]
	assert body["recipient_email"] == "user@qq.com"
	assert body["email_configured"] is True
	assert body["has_smtp_password"] is True
	assert body["smtp_host"] == "smtp.qq.com"

	cfg = json.loads((tmp_path / "secretary.json").read_text(encoding="utf-8"))
	assert cfg["smtp"]["password"] == "test-auth-code"
	assert cfg["smtp"]["username"] == "user@qq.com"

	resp = client.get("/api/secretary/email")
	assert resp.json()["data"]["recipient_email"] == "user@qq.com"
	assert resp.json()["data"]["max_daily_picks"] == 5

	resp = client.post(
		"/api/secretary/email",
		json={"recipient_email": "user@qq.com", "max_daily_picks": 8},
	)
	assert resp.status_code == 200
	assert resp.json()["data"]["max_daily_picks"] == 8

	resp = client.post("/api/secretary/email", json={"recipient_email": "bad-email"})
	assert resp.status_code == 400

	resp = client.post(
		"/api/secretary/email",
		json={"recipient_email": "user@qq.com", "max_daily_picks": 0},
	)
	assert resp.status_code == 400

	resp = client.post(
		"/api/secretary/email",
		json={"recipient_email": "new@qq.com"},
	)
	assert resp.status_code == 400


def test_secretary_portrait_api(tmp_path: Path):
	from starlette.testclient import TestClient

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.get("/api/secretary/portrait")
	assert resp.status_code == 200
	body = resp.json()
	assert body["ok"] is True
	assert body["data"]["has_portrait"] is False


def test_secretary_parse_resume_api_missing(tmp_path: Path):
	from starlette.testclient import TestClient

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.post("/api/secretary/parse-resume", json={"resume_name": "default"})
	assert resp.status_code == 404
	assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_secretary_send_daily_email_not_configured(tmp_path: Path):
	from starlette.testclient import TestClient

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.post("/api/secretary/send-daily-email", json={"date": "today"})
	assert resp.status_code == 400
	assert resp.json()["error"]["code"] == "EMAIL_NOT_CONFIGURED"


def test_secretary_send_daily_email_skipped_without_content(tmp_path: Path):
	from starlette.testclient import TestClient

	from pet_boss.secretary.config import SecretaryConfigStore, apply_secretary_email_settings

	store = SecretaryConfigStore(tmp_path)
	cfg = store.load()
	apply_secretary_email_settings(
		cfg, recipient_email="user@qq.com", smtp_auth_code="auth",
	)
	store.save(cfg)

	app = create_app(tmp_path)
	client = TestClient(app)
	resp = client.post("/api/secretary/send-daily-email", json={"date": "today"})
	assert resp.status_code == 200
	body = resp.json()
	assert body["ok"] is True
	assert body["data"]["sent"] is False
	assert body["data"]["skipped"] is True


def test_secretary_send_daily_email_sent(tmp_path: Path):
	import time
	from unittest.mock import patch

	from starlette.testclient import TestClient

	from pet_boss.cache.store import CacheStore
	from pet_boss.secretary.config import SecretaryConfigStore, apply_secretary_email_settings

	store = SecretaryConfigStore(tmp_path)
	cfg = store.load()
	apply_secretary_email_settings(
		cfg, recipient_email="user@qq.com", smtp_auth_code="auth",
	)
	store.save(cfg)

	cache = CacheStore(tmp_path / "cache" / "boss_agent.db")
	cache.record_analysis_job(
		{
			"security_id": "sec-1",
			"job_id": "job-1",
			"title": "Python",
			"company": "测试",
			"city": "杭州",
			"salary": "20K",
			"analysis_score": 88,
			"analysis_status": "passed",
			"analysis_reason": [],
			"analysis_risk": [],
			"analysis_dimensions": {},
		},
		"passed",
		analyzed_at=time.time(),
	)
	cache.close()

	app = create_app(tmp_path)
	client = TestClient(app)
	with patch(
		"pet_boss.agents.secretary_ai.send_markdown_email",
		return_value={"sent": True, "to": "user@qq.com", "subject": "test", "from": "user@qq.com"},
	):
		resp = client.post("/api/secretary/send-daily-email", json={"date": "today"})
	assert resp.status_code == 200
	body = resp.json()
	assert body["ok"] is True
	assert body["data"]["sent"] is True
	assert body["data"]["to"] == "user@qq.com"
