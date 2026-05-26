from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

from orchestrator.email_client import InboundMail
from orchestrator.email_filters import is_ignored_inbound
from orchestrator.keyword_review import (
    KeywordReview,
    build_keyword_review,
    build_linkedin_query,
    clean_keywords_input,
    format_approval_email,
    parse_approval_selection,
    strip_email_signature,
    strip_quoted_reply,
)
from orchestrator.user_db import UserDB, UserRecord, parse_schedule_days, sanitize_email


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _data_root():
    from pathlib import Path

    return Path(os.getenv("ORCHESTRATOR_DATA_DIR", str(Path.home() / "orchestrator-data")))


_MAX_CV_BYTES = 10 * 1024 * 1024  # 10 MB


def _save_cv(user: UserRecord, attachments: list[tuple[str, bytes]], body: str) -> Optional[str]:
    work = _data_root() / "users" / sanitize_email(user.email)
    work.mkdir(parents=True, exist_ok=True)
    for name, data in attachments:
        lower = name.lower()
        if lower.endswith((".pdf", ".doc", ".docx", ".txt")):
            if len(data) > _MAX_CV_BYTES:
                print(f"Skipping attachment {name}: {len(data)} bytes exceeds {_MAX_CV_BYTES} limit", flush=True)
                continue
            dest = work / Path(name).name
            dest.write_bytes(data)
            return str(dest)
    cleaned = strip_quoted_reply(body)
    if len(cleaned) > 80 and not re.search(r"^keywords?\s*[:\-]", cleaned, re.I):
        if any(k in cleaned.lower() for k in ("manager", "director", "devops", "engineer", "מנהל")):
            dest = work / "cv.txt"
            dest.write_text(cleaned, encoding="utf-8")
            return str(dest)
    return None


def _extract_keywords(text: str) -> Optional[str]:
    t = strip_quoted_reply(text).strip()
    if not t:
        return None
    m = re.search(r"(?:keywords?|roles?|positions?)\s*[:\-]\s*(.+)", t, re.I | re.S)
    if m:
        return clean_keywords_input(m.group(1))
    if any(
        k in t.lower()
        for k in (
            "devops",
            "manager",
            "director",
            "platform",
            "sre",
            "pmo",
            "project manager",
            "program manager",
            "operations",
            "מנהל",
            "менеджер",
            "инженер",
            "devops",
        )
    ):
        return clean_keywords_input(t)
    return None


def _wants_job_help(text: str) -> bool:
    t = text.lower()
    return any(
        w in t
        for w in (
            "job",
            "jobs",
            "search",
            "assist",
            "help",
            "devops",
            "משרה",
            "משרות",
            "עבודה",
            "חיפוש",
        )
    )


def _normalized_reply(text: str) -> str:
    """First non-empty line after stripping quotes and mobile signatures."""
    t = strip_email_signature(strip_quoted_reply(text)).strip()
    for line in t.splitlines():
        s = line.strip()
        if s:
            return s
    return t


def _wants_run_search(text: str) -> bool:
    t = strip_email_signature(strip_quoted_reply(text)).lower()
    return any(
        w in t
        for w in (
            "run report",
            "send report",
            "generate report",
            "job report",
            "digest",
            "run search",
            "search again",
            "new search",
            "current filter",
            "run jobs",
            "last data",
            "last search",
            "same data",
            "שלח דוח",
            "חפש שוב",
            "הרץ חיפוש",
            "отправь отчет",
            "запусти поиск",
        )
    )


def _classify_user_intent(text: str, user_keywords: str) -> Optional[str]:
    """Use LLM to classify returning user intent.

    Returns: "run_search", "new_data", "schedule", or None (unknown).
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    body = strip_email_signature(strip_quoted_reply(text)).strip()[:400]
    if not api_key or not body:
        return None
    try:
        import json
        import urllib.request

        prompt = (
            "You classify short email messages from a user of a job-search agent.\n"
            "The user already has an active profile with approved search keywords.\n"
            f"Their current saved search: {user_keywords}\n\n"
            "Classify the user's intent:\n"
            '- "run_search": user wants to run/send/get their job report/digest using existing keywords '
            "(e.g. 'send me jobs', 'run search with last data', 'generate report', 'search again', "
            "'use my saved keywords', 'שלח לי דוח', 'חפש שוב')\n"
            '- "new_data": user wants to change keywords, update CV, or start fresh '
            "(e.g. 'new search', 'change keywords', 'update my CV', 'different roles')\n"
            '- "schedule": user wants to set/change schedule '
            "(e.g. 'daily', 'weekdays', 'sunday and tuesday', 'every day except saturday')\n"
            '- null: unclear or unrelated\n\n'
            "The message may be in English, Hebrew, or Russian.\n\n"
            f"Message: {body}\n\n"
            'Return ONLY a JSON object: {"intent": "run_search"} or {"intent": "new_data"} '
            'or {"intent": "schedule"} or {"intent": null}'
        )
        req_body = json.dumps(
            {
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 30,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=req_body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return None
        parsed = json.loads(m.group())
        intent = parsed.get("intent")
        if intent in ("run_search", "new_data", "schedule"):
            return intent
        return None
    except Exception:
        return None


def _classify_admin_intent(body: str) -> Optional[str]:
    """Use LLM to classify whether an admin email is an admin command.

    Returns the command kind ("report", "history", "status") or None.
    Falls back to regex if the API is unavailable.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    text = body.strip()[:300]
    if not api_key or not text:
        return _classify_admin_intent_regex(text)
    try:
        import json
        import urllib.request

        prompt = (
            "You classify short email messages from an admin user of a job-search agent.\n"
            "Decide if the message is asking for an ADMIN command or something else.\n\n"
            "ADMIN commands:\n"
            '- "report": user wants a system activity/conversation report or summary\n'
            '- "history": user wants to see history of interactions/events\n'
            '- "status": user wants system status, health check, or user statuses\n\n'
            "NOT admin commands (return null):\n"
            "- Requesting a job search, digest, or job report\n"
            "- Providing keywords, CV, or job preferences\n"
            "- Saying yes/no/hello or general conversation\n\n"
            "The message may be in English, Hebrew, or Russian.\n\n"
            f"Message: {text}\n\n"
            'Return ONLY a JSON object: {"admin_command": "report"} or {"admin_command": "history"} '
            'or {"admin_command": "status"} or {"admin_command": null}'
        )
        req_body = json.dumps(
            {
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 30,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=req_body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return _classify_admin_intent_regex(text)
        parsed = json.loads(m.group())
        cmd = parsed.get("admin_command")
        if cmd in ("report", "history", "status"):
            return cmd
        return None
    except Exception:
        return _classify_admin_intent_regex(text)


def _classify_admin_intent_regex(body: str) -> Optional[str]:
    """Broad regex fallback for admin intent classification (EN/HE/RU)."""
    lower = (body or "").lower().strip()

    # Negative gate: if the message clearly wants a job search, bail out early
    if re.search(
        r"\b(run|start|launch|send)\s+(search|jobs|digest|report)"
        r"|\bdigest\b"
        r"|\bjob\s+report\b"
        r"|\bsearch\s+(again|for)\b"
        r"|\bcurrent\s+filter\b"
        r"|\bgenerate\s+report\b"
        r"|\bkeywords?\b",
        lower,
    ):
        return None

    _REPORT_RE = re.compile(
        r"admin\s+(report|history|status)"
        # "show/send/give me report/status/history/summary"
        r"|(?:show|send|give|get|email)\s+(?:me\s+)?(?:a\s+)?(?:the\s+)?"
        r"(?:report|status|history|summary|activity|stats|overview|log)"
        # "report/status/summary for/last N"
        r"|(?:report|status|history|summary|activity)\s+(?:for|last|from)\s+\d+"
        # "report please", "summary please"
        r"|(?:report|summary|status|activity)\s*(?:please|pls|plz)"
        # bare leading "report" as the whole message
        r"|^(?:report|status|history|summary)$"
        # "what's happening", "what happened", "how are users/things doing"
        r"|what(?:'?s| is| was)\s+(?:happening|going on|the status|new|up)"
        r"|what\s+happened"
        r"|how\s+(?:are|is)\s+(?:users?|things?|the system|it|everything)\s+doing"
        r"|any\s+(?:activity|news|updates|action)"
        # Hebrew
        r"|(?:תראה|שלח|תן)\s+(?:לי\s+)?(?:דו[\"״]?ח|סטטוס|היסטוריה|סיכום|פעילות)"
        r"|מה\s+(?:המצב|קורה|חדש|קרה|נעשה)"
        r"|(?:דו[\"״]?ח|סטטוס|סיכום)\s+(?:ל|של|מ)?\s*\d+"
        r"|^(?:דו[\"״]?ח|סטטוס|סיכום|מצב)$"
        # Russian
        r"|(?:покажи|пришли|дай|отправь)\s+(?:мне\s+)?(?:отчет|статус|историю|сводку)"
        r"|что\s+(?:происходит|нового|случилось)"
        r"|как\s+(?:дела|обстоят|там)\s+(?:у\s+)?(?:пользовател|систем|дел)"
        r"|(?:отчет|статус|сводка)\s+(?:за|последние)\s+\d+"
        r"|^(?:отчет|статус|сводка)$",
        re.I,
    )
    if not _REPORT_RE.search(lower):
        return None

    if re.search(r"histor|היסטוריה|истори", lower):
        return "history"
    if re.search(r"status|סטטוס|מצב|статус", lower):
        return "status"
    return "report"


def _wants_same_data(text: str) -> bool:
    t = _normalized_reply(text).lower()
    full = strip_email_signature(strip_quoted_reply(text)).lower()
    if t in ("1", "same", "yes", "כן", "אותו דבר"):
        return True
    return any(
        p in full
        for p in (
            "same as",
            "use saved",
            "same search",
            "same check",
            "do the same",
            "run again",
            "same keywords",
        )
    )


def _wants_new_data(text: str) -> bool:
    t = _normalized_reply(text).lower()
    full = strip_email_signature(strip_quoted_reply(text)).lower()
    if t in ("2", "new"):
        return True
    return any(p in full for p in ("new search", "new cv", "new keywords"))


def _wants_replace(text: str) -> bool:
    return "replace" in text.lower() or "החלף" in text


class ConversationEngine:
    def __init__(self, db: UserDB) -> None:
        self.db = db

    def _lang(self, user: UserRecord) -> str:
        from orchestrator.i18n import lang_from_meta

        return lang_from_meta(user.meta)

    def _t(self, user: UserRecord, en: str, he: str, ru: str) -> str:
        from orchestrator.i18n import tr

        return tr(en, he, ru, self._lang(user))

    def _sync_reply_language(self, user: UserRecord, body: str) -> UserRecord:
        from orchestrator.i18n import detect_language_from_text

        text = strip_quoted_reply(body).strip()
        if len(text) < 2:
            return user
        detected = detect_language_from_text(text)
        meta = dict(user.meta)
        meta["reply_language"] = detected
        self.db.update_user(user.id, meta=meta)
        return self.db.get_or_create(user.email)

    def _try_admin_command(
        self, user: UserRecord, mail: InboundMail, thread_meta: dict[str, Any], body: str
    ) -> Optional[str]:
        from orchestrator.admin_report import is_admin, build_report

        if not is_admin(mail.from_email):
            return None
        cmd = _classify_admin_intent(body)
        if cmd is None:
            return None

        lower = body.lower().strip()
        days: Optional[int] = None
        m = re.search(r"(\d+)\s*d(?:ays?)?", lower)
        if m:
            days = int(m.group(1))

        filter_email: Optional[str] = None
        em = re.search(r"user[=:\s]+(\S+@\S+)", lower)
        if em:
            filter_email = em.group(1)

        report_text = build_report(self.db, days=days, user_email=filter_email)
        admin_sent = False
        try:
            self._send_thread_reply(user, mail, thread_meta, report_text)
            admin_sent = True
        except Exception as exc:
            print(f"Failed to send admin report: {exc}", flush=True)
        self.db.log_conversation(
            direction="outbound",
            user_email=mail.from_email,
            subject=mail.subject,
            body_snippet="[admin report]",
            action="admin_report",
            state_before=user.state,
            state_after=user.state,
            message_id=None,
        )
        if admin_sent:
            self.db.mark_replied(mail.message_id)
        return report_text

    @staticmethod
    def _infer_action(state_before: str, state_after: str, body: str) -> str:
        if state_before == "new":
            return "welcome"
        if state_after == "running":
            return "run_search"
        if state_after == "keyword_approval":
            return "keyword_review"
        if state_before == "collecting" and state_after == "collecting":
            return "collect_info"
        if state_before != state_after:
            return f"state:{state_before}->{state_after}"
        return "reply"

    def handle(self, mail: InboundMail) -> list[str]:
        if is_ignored_inbound(mail):
            return []
        if not self.db.log_inbound(mail.message_id, mail.from_email, mail.subject):
            return []
        user = self.db.get_or_create(mail.from_email)
        state_before = user.state
        self.db.update_user(user.id, last_inbound_at=_utc_now())
        replies: list[str] = []
        thread_meta = self._update_thread_meta(user, mail)

        body = strip_quoted_reply(mail.body_text).strip()
        self.db.log_conversation(
            direction="inbound",
            user_email=mail.from_email,
            subject=mail.subject,
            body_snippet=body[:200],
            action=None,
            state_before=state_before,
            state_after=None,
            message_id=mail.message_id,
        )

        admin_reply = self._try_admin_command(user, mail, thread_meta, body)
        if admin_reply is not None:
            return [admin_reply] if admin_reply else []

        user = self._sync_reply_language(user, body)
        cv_path = _save_cv(user, mail.attachments, body)
        keywords = _extract_keywords(body)

        if user.state == "new":
            replies.append(self._welcome_new(user))
            self.db.update_user(user.id, state="collecting")
            user = self.db.get_or_create(mail.from_email)

        if user.state == "collecting":
            updates: dict[str, Any] = {}
            if cv_path:
                updates["cv_path"] = cv_path
            if keywords:
                updates["keywords"] = clean_keywords_input(keywords)
            if updates:
                self.db.update_user(user.id, **updates)
                user = self.db.get_or_create(mail.from_email)
            if user.cv_path and user.keywords:
                replies.append(self._begin_keyword_review(user))
            else:
                missing = []
                if not user.cv_path:
                    missing.append(
                        self._t(user, "CV (PDF attachment or paste)", "קורות חיים (PDF או הדבקה)", "Резюме (PDF или текст)")
                    )
                if not user.keywords:
                    missing.append(
                        self._t(
                            user,
                            "role keywords (e.g. DevOps Manager Israel)",
                            "מילות מפתח לתפקיד (למשל מנהל DevOps ישראל)",
                            "ключевые слова (например DevOps Manager Israel)",
                        )
                    )
                need = ", ".join(missing)
                replies.append(
                    self._t(
                        user,
                        f"Still need: {need}.\nReply to this email with the missing items.",
                        f"עדיין חסר: {need}.\nהשיבו למייל עם הפרטים החסרים.",
                        f"Ещё нужно: {need}.\nОтветьте на письмо с недостающими данными.",
                    )
                )

        elif user.state == "keyword_approval":
            replies.extend(self._handle_keyword_approval(user, mail, body, thread_meta))

        elif user.state in ("ready", "returning", "scheduled", "report_sent"):
            llm_intent = None
            if not _wants_same_data(body) and not _wants_run_search(body) and not _wants_new_data(body):
                saved_q = user.meta.get("approved_keyword_query") or user.keywords or ""
                llm_intent = _classify_user_intent(body, saved_q)
                if llm_intent:
                    print(f"LLM intent for {user.email}: {llm_intent}", flush=True)

            if _wants_same_data(body) or _wants_run_search(body) or llm_intent == "run_search":
                q = user.meta.get("approved_keyword_query") or user.keywords
                ack = self._t(
                    user,
                    f"Using your approved keywords. Running search now.\n({q})",
                    f"משתמשים במילות המפתח שאושרו. מתחיל חיפוש.\n({q})",
                    f"Используем одобренные ключевые слова. Запускаю поиск.\n({q})",
                )
                search_sent = False
                try:
                    self._send_thread_reply(user, mail, thread_meta, ack)
                    search_sent = True
                except Exception as exc:
                    print(
                        f"Failed to send reply to {mail.from_email} subject={mail.subject!r}: {exc}",
                        flush=True,
                    )
                self.db.log_conversation(
                    direction="outbound",
                    user_email=mail.from_email,
                    subject=mail.subject,
                    body_snippet=ack[:200],
                    action="run_search",
                    state_before=state_before,
                    state_after="running",
                    message_id=None,
                )
                if search_sent:
                    self.db.mark_replied(mail.message_id)
                self.db.update_user(user.id, state="running", keywords=q)
                user = self.db.get_or_create(mail.from_email)
                self._run_job(user)
                return []
            elif _wants_new_data(body) or llm_intent == "new_data":
                meta = dict(user.meta)
                meta.pop("keyword_proposals", None)
                meta.pop("approved_keyword_query", None)
                self.db.update_user(user.id, state="collecting", cv_path=None, keywords=None, meta=meta)
                replies.append(
                    self._t(
                        user,
                        "Send new keywords and/or attach a new CV.\nSay 'replace' to overwrite saved data.",
                        "שלחו מילות מפתח חדשות ו/או קורות חיים.\nכתבו 'replace' או 'החלף' לדריסה.",
                        "Пришлите новые ключевые слова и/или резюме.\nНапишите replace для замены данных.",
                    )
                )
            elif user.state == "scheduled" and parse_schedule_days(body):
                days = parse_schedule_days(body)
                self.db.update_user(user.id, schedule_days=days, state="scheduled")
                replies.append(
                    self._t(
                        user,
                        f"Schedule updated: days {days} at {user.schedule_time} ({user.timezone}).",
                        f"לוח זמנים עודכן: ימים {days} בשעה {user.schedule_time} ({user.timezone}).",
                        f"Расписание обновлено: дни {days} в {user.schedule_time} ({user.timezone}).",
                    )
                )
            elif (days := parse_schedule_days(body)):
                self.db.update_user(user.id, schedule_days=days, state="scheduled")
                replies.append(
                    self._t(
                        user,
                        f"Schedule saved: days {days} at {user.schedule_time} ({user.timezone}).\n"
                        "Reply 1 anytime for a search with your saved keywords.",
                        f"לוח זמנים נשמר: ימים {days} בשעה {user.schedule_time} ({user.timezone}).\n"
                        "השיבו 1 בכל עת לחיפוש עם מילות המפתח השמורות.",
                        f"Расписание сохранено: дни {days} в {user.schedule_time} ({user.timezone}).\n"
                        "Ответьте 1 для поиска с сохранёнными ключевыми словами.",
                    )
                )
            elif cv_path or keywords:
                updates: dict[str, Any] = {}
                if cv_path:
                    updates["cv_path"] = cv_path
                if keywords:
                    updates["keywords"] = clean_keywords_input(keywords)
                if updates:
                    self.db.update_user(user.id, **updates)
                    user = self.db.get_or_create(mail.from_email)
                if user.cv_path and (keywords or user.keywords):
                    replies.append(self._begin_keyword_review(user))
                else:
                    replies.append(
                        self._t(
                            user,
                            "Send keywords and CV, then we will prepare a phrase list for your approval.",
                            "שלחו מילות מפתח וקורות חיים, ואז נכין רשימת ניסוחים לאישור.",
                            "Пришлите ключевые слова и резюме — подготовим список фраз на одобрение.",
                        )
                    )
            elif _wants_job_help(body):
                q = user.meta.get("approved_keyword_query") or user.keywords or "(none)"
                replies.append(
                    self._t(
                        user,
                        f"Welcome back. Last approved search: {q}.\n"
                        "Reply 1 = same search · 2 = new CV/keywords · or send schedule (weekdays/daily).",
                        f"שלום שוב. חיפוש אחרון שאושר: {q}.\n"
                        "השיבו 1 = אותו חיפוש · 2 = נתונים חדשים · או שלחו לוח זמנים.",
                        f"Снова здравствуйте. Последний одобренный поиск: {q}.\n"
                        "Ответьте 1 = тот же поиск · 2 = новые данные · или расписание.",
                    )
                )
                self.db.update_user(user.id, state="returning")
            else:
                replies.append(
                    self._t(
                        user,
                        "Reply 1 for saved search, 2 for new data, or describe days for schedule.",
                        "השיבו 1 לחיפוש שמור, 2 לנתונים חדשים, או ציינו ימים ללוח זמנים.",
                        "Ответьте 1 — сохранённый поиск, 2 — новые данные, или укажите дни расписания.",
                    )
                )

        elif user.state == "feedback":
            t = body.lower()
            if any(w in t for w in ("good", "great", "ok", "yes", "thanks", "טוב", "מעולה")):
                self.db.update_user(user.id, state="scheduled", schedule_days=[0, 1, 2, 3, 4])
                replies.append(
                    self._t(
                        user,
                        "Glad it helped! Default schedule: weekdays at 09:00 Israel time.\n"
                        "Reply with 'daily', 'weekdays', or days like 'sun,tue,thu' to change.",
                        "שמחים שעזר! ברירת מחדל: ימי חול ב-09:00 שעון ישראל.\n"
                        "השיבו daily / weekdays או ימים כמו sun,tue,thu לשינוי.",
                        "Рады помочь! По умолчанию: будни в 09:00 (Израиль).\n"
                        "Ответьте daily / weekdays или sun,tue,thu для изменения.",
                    )
                )
            else:
                replies.append(
                    self._t(
                        user,
                        "Thanks for the feedback. Reply when you want another search (1=same, 2=new).",
                        "תודה על המשוב. השיבו כשתרצו חיפוש נוסף (1=אותו דבר, 2=חדש).",
                        "Спасибо за отзыв. Ответьте, когда нужен новый поиск (1=то же, 2=новое).",
                    )
                )
                self.db.update_user(user.id, state="returning")

        elif user.state == "running":
            replies.append(
                self._t(
                    user,
                    "Search is in progress — you'll receive results by email shortly.",
                    "החיפוש בעיצומו — תקבלו תוצאות במייל בקרוב.",
                    "Поиск выполняется — результаты придут на почту вскоре.",
                )
            )

        else:
            if _wants_job_help(body):
                self.db.update_user(user.id, state="returning")
                q = user.meta.get("approved_keyword_query") or user.keywords or "(none)"
                replies.append(
                    self._t(
                        user,
                        f"Hi again. Saved keywords: {q}.\nReply 1=same · 2=new data.",
                        f"שלום שוב. מילות מפתח שמורות: {q}.\nהשיבו 1=אותו דבר · 2=חדש.",
                        f"Снова здравствуйте. Сохранённые ключевые слова: {q}.\nОтветьте 1=то же · 2=новое.",
                    )
                )
            else:
                replies.append(
                    self._t(
                        user,
                        "Email genie4cv@gmail.com with 'job help' to start or continue.",
                        "שלחו מייל ל-genie4cv@gmail.com עם 'job help' להתחלה או המשך.",
                        "Напишите на genie4cv@gmail.com с «job help» для начала или продолжения.",
                    )
                )

        user_after = self.db.get_or_create(mail.from_email)
        state_after = user_after.state

        if not replies and state_before == state_after:
            replies.append(
                self._t(
                    user,
                    "Got your message. Reply 1 for saved search, 2 for new data, or 'help' for options.",
                    "קיבלנו את ההודעה. השיבו 1 לחיפוש שמור, 2 לנתונים חדשים, או 'help' לאפשרויות.",
                    "Получили ваше сообщение. Ответьте 1 — сохранённый поиск, 2 — новые данные, или help.",
                )
            )

        action = self._infer_action(state_before, state_after, body)
        send_ok = False
        for reply in replies:
            try:
                self._send_thread_reply(user, mail, thread_meta, reply)
                send_ok = True
            except Exception as exc:
                print(
                    f"Failed to send reply to {mail.from_email} subject={mail.subject!r}: {exc}",
                    flush=True,
                )
            self.db.log_conversation(
                direction="outbound",
                user_email=mail.from_email,
                subject=mail.subject,
                body_snippet=reply[:200],
                action=action,
                state_before=state_before,
                state_after=state_after,
                message_id=None,
            )
        if send_ok:
            self.db.mark_replied(mail.message_id)
        return replies

    def retry_unreplied(self, min_age_seconds: int = 120, max_retries: int = 3) -> int:
        """Retry sending replies for messages that were received but never got a reply."""
        from orchestrator.email_client import send_reply
        from orchestrator.admin_report import is_admin

        unreplied = self.db.get_unreplied(min_age_seconds=min_age_seconds, max_retries=max_retries)
        retried = 0
        for row in unreplied:
            msg_id = row["message_id"]
            email = row["from_email"]
            subject = row.get("subject") or "Job assistance"
            self.db.increment_retry(msg_id)
            user = self.db.get_or_create(email)

            fallback = self._t(
                user,
                "Sorry for the delay. Reply 1 for saved search, 2 for new data, or 'help'.",
                "מתנצלים על העיכוב. השיבו 1 לחיפוש שמור, 2 לנתונים חדשים, או 'help'.",
                "Извините за задержку. Ответьте 1 — сохранённый поиск, 2 — новые данные, или help.",
            )
            try:
                send_reply(email, subject, fallback, in_reply_to=msg_id, references=msg_id)
                self.db.mark_replied(msg_id)
                retried += 1
            except Exception as exc:
                print(f"Retry failed for {email} msg={msg_id}: {exc}", flush=True)
                if row["retry_count"] + 1 >= max_retries:
                    self.db.mark_dead_letter(msg_id)
                    self._alert_admin_dead_letter(email, subject, msg_id)
        return retried

    def _alert_admin_dead_letter(self, user_email: str, subject: str, message_id: str) -> None:
        from orchestrator.email_client import send_reply
        from orchestrator.admin_report import _ADMIN_EMAIL

        alert = (
            f"ALERT: Failed to reply to user after max retries.\n"
            f"User: {user_email}\n"
            f"Subject: {subject}\n"
            f"Message-ID: {message_id}\n\n"
            f"Please investigate manually."
        )
        try:
            send_reply(_ADMIN_EMAIL, "Dead letter alert", alert)
        except Exception:
            print(f"CRITICAL: Cannot send dead-letter alert for {user_email}", flush=True)

    def _update_thread_meta(self, user: UserRecord, mail: InboundMail) -> dict[str, Any]:
        from orchestrator.email_client import decode_subject

        meta = dict(user.meta)
        subj = decode_subject(mail.subject or "Job assistance")
        if not meta.get("thread_root_id"):
            meta["thread_root_id"] = mail.message_id
            meta["thread_subject"] = subj
        refs = [r for r in (meta.get("thread_references") or "").split() if r]
        for mid in (mail.references or "").split():
            if mid and mid not in refs:
                refs.append(mid)
        if mail.message_id and mail.message_id not in refs:
            refs.append(mail.message_id)
        meta["thread_references"] = " ".join(refs[-30:])
        meta["thread_last_inbound_id"] = mail.message_id
        self.db.update_user(user.id, meta=meta)
        return meta

    def _send_thread_reply(
        self,
        user: UserRecord,
        mail: InboundMail,
        thread_meta: dict[str, Any],
        body: str,
    ) -> None:
        from orchestrator.email_client import send_reply, _clean_header

        subject = _clean_header(
            thread_meta.get("thread_subject") or mail.subject or "Job assistance"
        )
        in_reply_to = _clean_header(
            thread_meta.get("thread_last_inbound_id") or mail.message_id
        )
        references = _clean_header(
            thread_meta.get("thread_references") or in_reply_to
        )
        outbound_id = send_reply(
            mail.from_email,
            subject,
            body,
            in_reply_to=in_reply_to,
            references=references,
        )
        refs = [r for r in references.split() if r]
        if outbound_id not in refs:
            refs.append(outbound_id)
        # Merge thread headers into latest meta (do not wipe keyword_proposals etc.)
        fresh = self.db.get_or_create(mail.from_email)
        meta = dict(fresh.meta)
        meta["thread_references"] = " ".join(refs[-30:])
        meta["thread_last_outbound_id"] = outbound_id
        for key in ("thread_root_id", "thread_subject", "thread_last_inbound_id"):
            if thread_meta.get(key):
                meta[key] = thread_meta[key]
        self.db.update_user(user.id, last_outbound_at=_utc_now(), meta=meta)

    def _begin_keyword_review(self, user: UserRecord) -> str:
        cleaned = clean_keywords_input(user.keywords or "")
        review = build_keyword_review(cleaned)
        meta = dict(user.meta)
        meta.update(review.to_meta())
        self.db.update_user(
            user.id,
            state="keyword_approval",
            keywords=cleaned,
            meta=meta,
        )
        return format_approval_email(review, self._lang(user))

    def _handle_keyword_approval(
        self, user: UserRecord, mail: InboundMail, body: str, thread_meta: dict[str, Any]
    ) -> list[str]:
        review = KeywordReview.from_meta(user.meta)
        if not review:
            return [self._begin_keyword_review(user)]

        selected_ids, edited, mode = parse_approval_selection(body, review)

        if mode == "edit" and edited:
            self.db.update_user(user.id, keywords=edited, state="collecting")
            user = self.db.get_or_create(mail.from_email)
            if user.cv_path:
                return [self._begin_keyword_review(user)]
            return [
                self._t(
                    user,
                    "Got your edits. Please confirm CV is attached or pasted, then we will regenerate the phrase list.",
                    "קיבלתי את העריכה. ודאו שקורות החיים מצורפים או מודבקים, ואז נבנה רשימה מחדש.",
                    "Правки приняты. Приложите или вставьте резюме — затем сформируем список фраз заново.",
                )
            ]

        if mode == "invalid":
            from orchestrator.keyword_review import format_how_to_reply, format_phrase_list

            lang = self._lang(user)
            return [
                self._t(
                    user,
                    "Could not read your reply. Use one of these on the first line:\n\n",
                    "לא הצלחתי לקרוא את התשובה. כתבו בשורה הראשונה:\n\n",
                    "Не удалось разобрать ответ. Напишите в первой строке:\n\n",
                )
                + format_how_to_reply(lang)
                + "\n\n"
                + format_phrase_list(review)
            ]

        id_map = {o.id: o for o in review.options}
        chosen = [id_map[i] for i in (selected_ids or []) if i in id_map]
        if not chosen:
            return [
                self._t(
                    user,
                    "No valid selections. Reply ALL or list numbers from the proposal email.",
                    "לא נבחרו פריטים תקפים. השיבו כולם או רשימת מספרים מהמייל.",
                    "Нет корректного выбора. Ответьте ВСЕ или укажите номера из письма.",
                )
            ]

        approved_query = build_linkedin_query(chosen, review.location_hint)
        meta = dict(user.meta)
        meta["approved_keyword_query"] = approved_query
        meta["approved_option_ids"] = selected_ids

        en_list = "\n".join(f"  • {o.en} / {o.he}" for o in chosen)
        self.db.update_user(user.id, state="running", keywords=approved_query, meta=meta)
        user = self.db.get_or_create(mail.from_email)
        ack = self._t(
            user,
            "Approved — starting job search with:\n"
            f"{en_list}\n\n"
            f"LinkedIn query:\n{approved_query}\n\n"
            "The job digest will arrive in this same email thread shortly.",
            "אושר — מתחיל חיפוש עם:\n"
            f"{en_list}\n\n"
            f"שאילתת LinkedIn:\n{approved_query}\n\n"
            "דוח המשרות יגיע בשרשור המייל הזה בקרוב.",
            "Одобрено — запускаю поиск:\n"
            f"{en_list}\n\n"
            f"Запрос LinkedIn:\n{approved_query}\n\n"
            "Дайджест придёт в этой же цепочке писем.",
        )
        try:
            self._send_thread_reply(user, mail, thread_meta, ack)
        except Exception as exc:
            print(
                f"Failed to send reply to {mail.from_email} subject={mail.subject!r}: {exc}",
                flush=True,
            )
        self._run_job(user)
        return []

    def _welcome_new(self, user: UserRecord) -> str:
        return self._t(
            user,
            "Hi — I'm your job search assistant.\n\n"
            "I can scan LinkedIn/Google and similar sources for roles matching your profile, "
            "then email you a digest.\n\n"
            "To start, please reply with:\n"
            "1) CV as PDF attachment (or pasted text)\n"
            "2) Role keywords (e.g. DevOps Manager OR Head of Platform — Israel)\n\n"
            "Before searching, I will send you an expanded keyword list (English + Hebrew) "
            "for your approval.\n"
            "If anything is missing I'll ask again.",
            "שלום — אני עוזר חיפוש העבודה שלך.\n\n"
            "אני סורק LinkedIn/Google ומקורות דומים למשרות שמתאימות לפרופיל שלך, "
            "ואז שולח דוח במייל.\n\n"
            "כדי להתחיל, השיבו עם:\n"
            "1) קורות חיים בקובץ PDF (או הדביקו טקסט)\n"
            "2) מילות מפתח לתפקיד (למשל מנהל DevOps או Head of Platform — ישראל)\n\n"
            "לפני החיפוש אשלח רשימת ניסוחים מורחבת (עברית + אנגלית) לאישורכם.\n"
            "אם חסר משהו — אבקש שוב.",
            "Здравствуйте — я помощник по поиску работы.\n\n"
            "Сканирую LinkedIn/Google и похожие источники по вашему профилю, "
            "затем присылаю дайджест на почту.\n\n"
            "Чтобы начать, ответьте:\n"
            "1) Резюме PDF (или текст в письме)\n"
            "2) Ключевые слова роли (например DevOps Manager — Israel)\n\n"
            "Перед поиском пришлю расширенный список фраз (английский + иврит) на одобрение.\n"
            "Если чего-то не хватает — напишу ещё раз.",
        )

    def _run_job(self, user: UserRecord) -> None:
        from orchestrator.job_runner import run_docker_job

        run_docker_job(user, self.db)

    def send_feedback_prompts(self, minutes_after: int = 30) -> int:
        if os.getenv("ORCHESTRATOR_FEEDBACK_ENABLED", "0").strip().lower() not in ("1", "true", "yes"):
            return 0
        from orchestrator.email_client import send_reply

        sent = 0
        for user in self.db.users_needing_feedback(minutes_after):
            if not user.meta.get("first_execution_complete"):
                continue
            subject = user.meta.get("thread_subject") or "Job search feedback"
            in_reply_to = user.meta.get("thread_last_outbound_id") or user.meta.get("thread_last_inbound_id")
            references = user.meta.get("thread_references")
            send_reply(
                user.email,
                subject,
                "How was today's job digest? Reply 'good' to get weekday reports at 09:00, "
                "or tell us which days you prefer (daily / weekdays / sun,tue,thu).",
                in_reply_to=in_reply_to,
                references=references,
            )
            self.db.update_user(
                user.id,
                feedback_sent_at=_utc_now(),
                pending_feedback=False,
                state="feedback",
                last_outbound_at=_utc_now(),
            )
            sent += 1
        return sent
