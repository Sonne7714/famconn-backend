from __future__ import annotations
import os
import smtplib
from email.message import EmailMessage

def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()

SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587") or "587")
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_FROM = _env("SMTP_FROM", SMTP_USER)
SMTP_FROM_NAME = _env("SMTP_FROM_NAME", "FamConn")

def send_email(to: str, subject: str, text: str) -> None:
    if not SMTP_HOST:
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM}>"
    msg["To"] = to
    msg.set_content(text)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        if SMTP_USER:
            s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)
