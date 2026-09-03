"""Minimal zero-dependency SMTP mailer using Python stdlib.

Configure via env vars:
- MAIL_HOST, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD
- MAIL_FROM, MAIL_FROM_NAME, MAIL_USE_TLS (default true)

If MAIL_HOST is unset, sending is silently skipped so the app still works
without an email provider configured.
"""

import html
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_CSS = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #f4f6f8; margin: 0; padding: 0; }
  .card { max-width: 560px; margin: 24px auto; background: #ffffff; border-radius: 12px; padding: 24px; border: 1px solid #e5e7eb; }
  .title { font-size: 18px; font-weight: 700; color: #111827; margin-bottom: 8px; }
  .text { font-size: 14px; color: #374151; line-height: 1.5; }
  .button { display: inline-block; margin-top: 16px; padding: 10px 16px; background: #2563eb; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: 600; }
  .footer { font-size: 12px; color: #6b7280; margin-top: 16px; }
</style>
"""


def _get_smtp_config():
    host = (os.getenv("MAIL_HOST") or "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.getenv("MAIL_PORT", "587")),
        "username": (os.getenv("MAIL_USERNAME") or "").strip(),
        "password": os.getenv("MAIL_PASSWORD", ""),
        "use_tls": (os.getenv("MAIL_USE_TLS", "true").strip().lower() in ("1", "true", "yes")),
        "from": (os.getenv("MAIL_FROM") or os.getenv("MAIL_USERNAME") or "").strip(),
        "from_name": (os.getenv("MAIL_FROM_NAME") or "CCTV Console").strip(),
    }


def _build_message(to_email, subject, text, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{html.escape(_get_smtp_config()['from_name'])} <{_get_smtp_config()['from']}>"
    msg["To"] = to_email
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def send_email(to_email, subject, text, html_body=None):
    cfg = _get_smtp_config()
    if not cfg or not cfg["from"]:
        print("[email] skipped: MAIL_HOST or MAIL_FROM not configured")
        return False

    if html_body is None:
        html_body = f"<p>{html.escape(text)}</p>"
    else:
        html_body = _CSS + html_body

    msg = _build_message(to_email, subject, text, html_body)

    try:
        if cfg["use_tls"]:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=10)

        if cfg["username"]:
            server.login(cfg["username"], cfg["password"])

        server.sendmail(cfg["from"], [to_email], msg.as_string())
        server.quit()
        print(f"[email] sent invite to {to_email}")
        return True
    except Exception as e:
        print(f"[email] failed to send to {to_email}: {type(e).__name__}: {e}")
        return False


def _get_api_base_url() -> str:
    return (os.getenv("API_BASE_URL", "http://localhost:5000").rstrip("/"))


def _get_public_app_url() -> str:
    return (os.getenv("PUBLIC_APP_URL", _get_api_base_url()).rstrip("/"))


def send_invite_email(to_email, invite_token, organization_name, inviter_name=""):
    base = _get_public_app_url()
    invite_link = f"{base}/accept-invite?token={invite_token}"
    subject = f"You're invited to join {organization_name} on CCTV Console"

    text = (
        f"Hi,\n\n"
        f"{inviter_name or 'A team member'} invited you to join {organization_name}.\n\n"
        f"Accept invite: {invite_link}\n\n"
        f"If you did not expect this, you can ignore this message."
    )

    html_body = (
        f"<p>Hi,</p>"
        f"<p>{html.escape(inviter_name or 'A team member')} invited you to join <strong>{html.escape(organization_name)}</strong>.</p>"
        f"<p><a class='button' href='{html.escape(invite_link)}'>Accept Invite</a></p>"
        f"<p class='footer'>If you did not expect this, you can ignore this message.</p>"
    )

    return send_email(to_email, subject, text, html_body)
