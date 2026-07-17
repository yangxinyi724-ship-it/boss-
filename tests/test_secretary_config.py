"""秘书配置 — SMTP 推断与宠物页邮箱同步。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pet_boss.secretary.config import (
	SecretaryConfigStore,
	apply_secretary_email_settings,
	infer_smtp_from_email,
	secretary_email_api_view,
)


def test_infer_smtp_from_qq_email():
	smtp = infer_smtp_from_email("user@qq.com")
	assert smtp["host"] == "smtp.qq.com"
	assert smtp["username"] == "user@qq.com"
	assert smtp["port"] == 587


def test_apply_secretary_email_settings_writes_smtp(tmp_path: Path):
	store = SecretaryConfigStore(tmp_path)
	cfg = store.load()
	apply_secretary_email_settings(
		cfg,
		recipient_email="me@163.com",
		smtp_auth_code="auth-token-123",
		max_daily_picks=6,
	)
	store.save(cfg)

	saved = json.loads((tmp_path / "secretary.json").read_text(encoding="utf-8"))
	assert saved["recipient_email"] == "me@163.com"
	assert saved["smtp"]["host"] == "smtp.163.com"
	assert saved["smtp"]["password"] == "auth-token-123"
	assert saved["smtp"]["username"] == "me@163.com"
	assert saved["report"]["max_daily_picks"] == 6


def test_apply_secretary_email_keeps_password_when_auth_empty(tmp_path: Path):
	store = SecretaryConfigStore(tmp_path)
	cfg = store.load()
	apply_secretary_email_settings(
		cfg, recipient_email="a@qq.com", smtp_auth_code="secret",
	)
	store.save(cfg)

	cfg = store.load()
	apply_secretary_email_settings(
		cfg,
		recipient_email="a@qq.com",
		smtp_auth_code="",
		max_daily_picks=8,
	)
	assert cfg["smtp"]["password"] == "secret"
	assert cfg["report"]["max_daily_picks"] == 8


def test_apply_secretary_email_clears_password_on_email_change():
	cfg = {
		"recipient_email": "old@qq.com",
		"smtp": {"password": "secret", "host": "smtp.qq.com"},
		"report": {},
	}
	apply_secretary_email_settings(cfg, recipient_email="new@163.com", smtp_auth_code="")
	assert cfg["recipient_email"] == "new@163.com"
	assert cfg["smtp"]["password"] == ""
	assert cfg["smtp"]["host"] == "smtp.163.com"


def test_secretary_email_api_view_hides_password():
	view = secretary_email_api_view(
		{
			"recipient_email": "a@qq.com",
			"smtp": {"host": "smtp.qq.com", "password": "secret"},
			"report": {"max_daily_picks": 5},
		},
		configured=True,
	)
	assert view["has_smtp_password"] is True
	assert "password" not in view
	assert view["smtp_host"] == "smtp.qq.com"


def test_infer_smtp_invalid_email():
	with pytest.raises(ValueError):
		infer_smtp_from_email("not-an-email")
