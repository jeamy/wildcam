import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate


DEFAULT_EMAIL_CONFIG = {
    "enabled": False,
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_username": "",
    "smtp_password": "",
    "use_tls": True,
    "from": "",
    "to": [],
}


def send_detection_email(
    config: dict | None,
    subject: str,
    body: str,
    image_path: str | None = None,
    require_enabled: bool = True,
):
    merged = dict(DEFAULT_EMAIL_CONFIG)
    if config:
        merged.update(config)
    if require_enabled and not merged.get("enabled"):
        return

    host = str(merged.get("smtp_host") or "").strip()
    recipients = merged.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    recipients = [str(item).strip() for item in recipients if str(item).strip()]
    if not host:
        raise ValueError("SMTP host fehlt")
    if not recipients:
        raise ValueError("Empfänger fehlt")

    sender = str(merged.get("from") or merged.get("smtp_username") or "").strip()
    if not sender:
        raise ValueError("Absender fehlt")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body)

    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as fh:
            msg.add_attachment(
                fh.read(),
                maintype="image",
                subtype="jpeg",
                filename=os.path.basename(image_path),
            )

    port = int(merged.get("smtp_port") or 587)
    username = str(merged.get("smtp_username") or "").strip()
    password = str(merged.get("smtp_password") or "")
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if merged.get("use_tls", True):
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(msg)
