import smtplib
import os
from email.mime.text import MIMEText

def send_email(to, subject, html):
    msg = MIMEText(html, "html")
    msg["Subject"] = subject
    msg["From"] = os.getenv("SMTP_USERNAME")
    msg["To"] = to

    with smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT", 587))) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD"))
        server.send_message(msg)
        