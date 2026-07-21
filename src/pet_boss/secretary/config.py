"""秘书 AI 配置 — 收件邮箱、SMTP、日报。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFAULT_CONFIG: dict[str, Any] = {
	"recipient_email": "",
	"smtp": {
		"host": "",
		"port": 587,
		"username": "",
		"password": "",
		"use_tls": True,
		"from_address": "",
	},
	"report": {
		"title_prefix": "【AI 办公室】岗位筛选日报",
		"include_filtered_summary": True,
		"max_passed_in_email": 20,
		"max_daily_picks": 5,
	},
}

# 常见邮箱 SMTP 服务器（按域名）
_DOMAIN_SMTP: dict[str, tuple[str, int]] = {
	"qq.com": ("smtp.qq.com", 587),
	"foxmail.com": ("smtp.qq.com", 587),
	"163.com": ("smtp.163.com", 587),
	"126.com": ("smtp.126.com", 587),
	"yeah.net": ("smtp.yeah.net", 587),
	"sina.com": ("smtp.sina.com", 587),
	"sina.cn": ("smtp.sina.com", 587),
	"gmail.com": ("smtp.gmail.com", 587),
	"outlook.com": ("smtp.office365.com", 587),
	"hotmail.com": ("smtp.office365.com", 587),
	"live.com": ("smtp.office365.com", 587),
	"icloud.com": ("smtp.mail.me.com", 587),
}


def infer_smtp_from_email(email: str) -> dict[str, Any]:
	"""根据收件邮箱推断 SMTP 连接参数（用户名/发件人与收件相同）。"""
	addr = email.strip().lower()
	if "@" not in addr:
		raise ValueError("邮箱格式不正确")
	domain = addr.rsplit("@", 1)[-1]
	host, port = _DOMAIN_SMTP.get(domain, (f"smtp.{domain}", 587))
	return {
		"host": host,
		"port": port,
		"username": email.strip(),
		"from_address": email.strip(),
		"use_tls": True,
	}


def apply_secretary_email_settings(
	cfg: dict[str, Any],
	*,
	recipient_email: str,
	smtp_auth_code: str | None = None,
	max_daily_picks: int | None = None,
) -> dict[str, Any]:
	"""合并宠物页/ API 提交的邮箱与 SMTP 授权码到 secretary 配置。"""
	email = recipient_email.strip()
	old_email = str(cfg.get("recipient_email") or "").strip()
	cfg["recipient_email"] = email

	auth_code = (smtp_auth_code or "").strip() if smtp_auth_code is not None else ""
	if email:
		smtp = cfg.setdefault("smtp", {})
		smtp.update(infer_smtp_from_email(email))
		if email.lower() != old_email.lower() and not auth_code:
			smtp["password"] = ""
	elif not email:
		cfg["recipient_email"] = ""

	if auth_code:
		smtp = cfg.setdefault("smtp", {})
		smtp["password"] = auth_code

	if max_daily_picks is not None:
		if not 1 <= max_daily_picks <= 20:
			raise ValueError("每日精选数量须在 1～20 之间")
		report_cfg = cfg.setdefault("report", {})
		report_cfg["max_daily_picks"] = max_daily_picks

	return cfg


def secretary_email_api_view(cfg: dict[str, Any], *, configured: bool) -> dict[str, Any]:
	"""API 对外暴露的邮箱配置（不含密码明文）。"""
	smtp = cfg.get("smtp") or {}
	report_cfg = cfg.get("report") or {}
	return {
		"recipient_email": cfg.get("recipient_email") or "",
		"email_configured": configured,
		"max_daily_picks": int(report_cfg.get("max_daily_picks") or 5),
		"smtp_host": smtp.get("host") or "",
		"has_smtp_password": bool(smtp.get("password")),
	}


class SecretaryConfigStore:
	def __init__(self, data_dir: Path) -> None:
		self._path = data_dir / "secretary.json"

	def load(self) -> dict[str, Any]:
		cfg = json.loads(json.dumps(_DEFAULT_CONFIG))
		if not self._path.exists():
			return cfg
		try:
			raw = json.loads(self._path.read_text(encoding="utf-8"))
		except json.JSONDecodeError:
			return cfg
		if isinstance(raw, dict):
			self._merge(cfg, raw)
		return cfg

	@staticmethod
	def _merge(base: dict[str, Any], override: dict[str, Any]) -> None:
		for key, value in override.items():
			if isinstance(value, dict) and isinstance(base.get(key), dict):
				SecretaryConfigStore._merge(base[key], value)
			else:
				base[key] = value

	def save(self, config: dict[str, Any]) -> None:
		self._path.parent.mkdir(parents=True, exist_ok=True)
		self._path.write_text(
			json.dumps(config, ensure_ascii=False, indent=2) + "\n",
			encoding="utf-8",
		)

	def is_email_configured(self, config: dict[str, Any] | None = None) -> bool:
		cfg = config or self.load()
		smtp = cfg.get("smtp") or {}
		return bool(
			cfg.get("recipient_email")
			and smtp.get("host")
			and smtp.get("username")
			and smtp.get("password")
		)
