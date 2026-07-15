import smtplib
import os
from email.mime.text import MIMEText
        
def send_email(to, subject, html):
    smtp_server = os.getenv("SMTP_SERVER")
    if not smtp_server:
        raise RuntimeError("Missing required environment variable: SMTP_SERVER")

    smtp_port = os.getenv("SMTP_PORT", 587)
    smtp_user = os.getenv("SMTP_USERNAME")
    if not smtp_user:
        raise RuntimeError("Missing required environment variable: SMTP_USERNAME")

    smtp_password = os.getenv("SMTP_PASSWORD")
    if not smtp_password:
        raise RuntimeError("Missing required environment variable: SMTP_PASSWORD")

    msg = MIMEText(html, "html")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to

    with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)