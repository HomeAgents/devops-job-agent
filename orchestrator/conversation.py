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


def _save_cv(user: UserRecord, attachments: list[tuple[str, bytes]], body: str) -> Optional[str]:
    work = _data_root() / "users" / sanitize_email(user.email)
    work.mkdir(parents=True, exist_ok=True)
    for name, data in attachments:
        lower = name.lower()
        if lower.endswith((".pdf", ".doc", ".docx", ".txt")):
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
            "report",
            "digest",
            "run search",
            "search again",
            "new search",
            "current filter",
            "generate report",
        )
    )


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

    def handle(self, mail: InboundMail) -> list[str]:
        if is_ignored_inbound(mail):
            return []
        if not self.db.log_inbound(mail.message_id, mail.from_email, mail.subject):
            return []
        user = self.db.get_or_create(mail.from_email)
        self.db.update_user(user.id, last_inbound_at=_utc_now())
        replies: list[str] = []
        thread_meta = self._update_thread_meta(user, mail)

        body = strip_quoted_reply(mail.body_text).strip()
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
            replies.extend(self._handle_keyword_approval(user, mail, body))

        elif user.state in ("ready", "returning", "scheduled", "report_sent"):
            if _wants_same_data(body) or _wants_run_search(body):
                q = user.meta.get("approved_keyword_query") or user.keywords
                replies.append(
                    self._t(
                        user,
                        f"Using your approved keywords. Running search now.\n({q})",
                        f"משתמשים במילות המפתח שאושרו. מתחיל חיפוש.\n({q})",
                        f"Используем одобренные ключевые слова. Запускаю поиск.\n({q})",
                    )
                )
                self.db.update_user(user.id, state="running", keywords=q)
                user = self.db.get_or_create(mail.from_email)
                self._run_job(user)
            elif _wants_new_data(body):
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

        for reply in replies:
            try:
                self._send_thread_reply(user, mail, thread_meta, reply)
            except Exception as exc:
                print(
                    f"Failed to send reply to {mail.from_email} subject={mail.subject!r}: {exc}",
                    flush=True,
                )
        return replies

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
        from orchestrator.email_client import send_reply

        subject = thread_meta.get("thread_subject") or mail.subject or "Job assistance"
        in_reply_to = thread_meta.get("thread_last_inbound_id") or mail.message_id
        references = thread_meta.get("thread_references") or in_reply_to
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

    def _handle_keyword_approval(self, user: UserRecord, mail: InboundMail, body: str) -> list[str]:
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
        self._run_job(user)
        return [
            self._t(
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
                "Дайджест придёт в этом же почтовом потоке.",
            )
        ]

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
