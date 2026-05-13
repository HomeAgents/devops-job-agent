from __future__ import annotations

import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pandas as pd

from job_agent.settings import get_setting


def save_excel(jobs_df: pd.DataFrame, contacts_df: pd.DataFrame, out_dir: Path) -> Path:
    filename = out_dir / f"jobs_{datetime.now().date()}.xlsx"
    top = jobs_df.sort_values("Score", ascending=False).head(5)
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        top.to_excel(writer, sheet_name="Top Jobs", index=False)
        jobs_df.to_excel(writer, sheet_name="All Jobs", index=False)
        contacts_df.to_excel(writer, sheet_name="Contacts", index=False)
    return filename


def send_email_with_attachment(xlsx_path: Path) -> None:
    email_user = get_setting("EMAIL_USER", "GMAIL_EMAIL")
    email_pass = get_setting("EMAIL_PASS", "GMAIL_APP_PASSWORD")
    email_to = get_setting("EMAIL_TO", "SENDER_EMAIL", "GMAIL_EMAIL")

    if not email_user or not email_pass or not email_to:
        raise RuntimeError(
            "Missing email config: set EMAIL_USER, EMAIL_PASS, EMAIL_TO (or GMAIL_* in Genie settings)."
        )

    msg = EmailMessage()
    msg["Subject"] = "DevOps Manager/Director roles — digest + recruiter radar"
    msg["From"] = email_user
    msg["To"] = email_to
    msg.set_content("Aggregated jobs (SerpAPI, Greenhouse, Lever, RSS) + recruiter contacts in the Excel attachment.")

    data = xlsx_path.read_bytes()
    msg.add_attachment(
        data,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=xlsx_path.name,
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(email_user, email_pass)
        smtp.send_message(msg)
