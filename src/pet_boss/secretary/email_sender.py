"""秘书 AI — SMTP 邮件发送。"""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any


class EmailSendError(Exception):
	pass


def send_markdown_email(
	*,
	config: dict[str, Any],
	subject: str,
	markdown_body: str,
	to_address: str | None = None,
) -> dict[str, Any]:
	smtp_cfg = config.get("smtp") or {}
	recipient = to_address or config.get("recipient_email") or ""
	host = smtp_cfg.get("host") or ""
	port = int(smtp_cfg.get("port") or 587)
	username = smtp_cfg.get("username") or ""
	password = smtp_cfg.get("password") or ""
	use_tls = smtp_cfg.get("use_tls", True)
	from_address = smtp_cfg.get("from_address") or username

	if not recipient:
		raise EmailSendError("未配置收件邮箱 recipient_email")
	if not host or not username or not password:
		raise EmailSendError("SMTP 配置不完整（host / username / password）")

	msg = MIMEMultipart("alternative")
	msg["Subject"] = subject
	msg["From"] = from_address
	msg["To"] = recipient
	msg.attach(MIMEText(markdown_body, "plain", "utf-8"))

	with smtplib.SMTP(host, port, timeout=30) as server:
		if use_tls:
			server.starttls()
		server.login(username, password)
		server.sendmail(from_address, [recipient], msg.as_string())

	return {
		"sent": True,
		"to": recipient,
		"from": from_address,
		"subject": subject,
	}
