from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class KeywordOption:
    id: int
    en: str
    he: str
    source: str  # user | generated | translation
    notes: str = ""


@dataclass
class KeywordReview:
    raw_input: str
    cleaned_input: str
    grammar_notes: list[str]
    options: list[KeywordOption]
    location_hint: str = "Israel"

    def to_meta(self) -> dict[str, Any]:
        return {
            "raw_keywords": self.raw_input,
            "cleaned_keywords": self.cleaned_input,
            "grammar_notes": self.grammar_notes,
            "keyword_proposals": [asdict(o) for o in self.options],
            "location_hint": self.location_hint,
        }

    @classmethod
    def from_meta(cls, meta: dict[str, Any]) -> Optional["KeywordReview"]:
        props = meta.get("keyword_proposals")
        if not props:
            return None
        options = [KeywordOption(**p) for p in props if isinstance(p, dict)]
        return cls(
            raw_input=str(meta.get("raw_keywords", "")),
            cleaned_input=str(meta.get("cleaned_keywords", "")),
            grammar_notes=list(meta.get("grammar_notes") or []),
            options=options,
            location_hint=str(meta.get("location_hint") or "Israel"),
        )


# Common DevOps leadership phrases (EN → HE) for expansion
_ROLE_EXPANSIONS: list[tuple[str, str, list[str]]] = [
    (
        "devops manager",
        "מנהל DevOps",
        ["DevOps Manager", "Manager, DevOps", "Manager of DevOps", "DevOps team manager"],
    ),
    (
        "devops director",
        "דירקטור DevOps",
        ["DevOps Director", "Director of DevOps", "Director, DevOps"],
    ),
    (
        "head of devops",
        "ראש צוות DevOps",
        ["Head of DevOps", "Head, DevOps", "DevOps Head"],
    ),
    (
        "vp devops",
        "VP DevOps",
        ["VP DevOps", "VP of DevOps", "Vice President DevOps"],
    ),
    (
        "platform engineering manager",
        "מנהל הנדסת פלטפורמה",
        ["Platform Engineering Manager", "Manager, Platform Engineering", "Platform Manager"],
    ),
    (
        "sre manager",
        "מנהל SRE",
        ["SRE Manager", "Site Reliability Manager", "Manager, Site Reliability"],
    ),
    (
        "infrastructure manager",
        "מנהל תשתיות",
        ["Infrastructure Manager", "Manager, Infrastructure", "IT Infrastructure Manager"],
    ),
    (
        "cloud manager",
        "מנהל ענן",
        ["Cloud Manager", "Manager, Cloud"],
    ),
    (
        "program manager",
        "מנהל תוכנית",
        ["Program Manager", "Manager, Program", "Senior Program Manager"],
    ),
    (
        "project manager",
        "מנהל פרויקט",
        ["Project Manager", "Manager, Project", "Senior Project Manager"],
    ),
    (
        "pmo",
        "משרד ניהול פרויקטים (PMO)",
        [
            "PMO",
            "Project Management Office",
            "PMO Manager",
            "Head of PMO",
            "PMO Lead",
        ],
    ),
    (
        "operations",
        "תפעול",
        [
            "Operations Manager",
            "Head of Operations",
            "Director of Operations",
            "Manager, Operations",
        ],
    ),
]

_HE_TO_EN_HINTS = {
    "מנהל devops": ("מנהל DevOps", "DevOps Manager"),
    "מנהל דבאופס": ("מנהל DevOps", "DevOps Manager"),
    "מנהל תשתיות": ("מנהל תשתיות", "Infrastructure Manager"),
    "מנהל ענן": ("מנהל ענן", "Cloud Manager"),
    "מנהל פלטפורמה": ("מנהל הנדסת פלטפורמה", "Platform Engineering Manager"),
}


def strip_quoted_reply(text: str) -> str:
    t = text.replace("\ufeff", "").replace("\ufffc", "").strip()
    t = re.split(
        r"\nOn .+ wrote:\n|\n-----Original Message-----|\nFrom: .+\n|\n> ?On ",
        t,
        maxsplit=1,
        flags=re.I,
    )[0]
    t = re.sub(r"^>.*$", "", t, flags=re.M).strip()
    return t.strip()


_SIGNATURE_MARKERS = re.compile(
    r"\n\s*(?:thanks|thank you|thx|best regards|kind regards|regards|cheers|"
    r"sent from my|בברכה|תודה)\s*\.?\s*(?:\n|$)",
    re.I,
)


_NUMBERED_MARKER = re.compile(r"^\d+[\.\)]\s*$")
_NON_KEYWORD_LINE = re.compile(
    r"^(?:cv|resume|attached|see attached|please find|hereby|enclosed)\b",
    re.I,
)
_JOB_TERM = re.compile(
    r"\b(devops|manager|director|engineer|platform|sre|operations|"
    r"program|project|pmo|head|vp|lead|architect|מנהל|ראש|תפעול)\b",
    re.I,
)


def strip_email_signature(text: str) -> str:
    """Remove trailing thanks / name / email lines from pasted or forwarded body."""
    t = strip_quoted_reply(text)
    t = _SIGNATURE_MARKERS.split(t, maxsplit=1)[0]
    kept: list[str] = []
    for line in t.splitlines():
        s = line.strip()
        if not s:
            continue
        if _NUMBERED_MARKER.match(s):
            continue
        if _NON_KEYWORD_LINE.match(s):
            continue
        # Standalone email line (not a job keyword)
        if re.fullmatch(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", s, re.I):
            break
        # Name + email on one line
        if re.search(r"@[\w.-]+\.[a-z]{2,}", s, re.I) and not _JOB_TERM.search(s):
            break
        # Likely full name only (2–4 words, no job terms)
        if (
            kept
            and 2 <= len(s.split()) <= 4
            and "@" not in s
            and not _JOB_TERM.search(s)
        ):
            break
        kept.append(s)
    return " ".join(kept).strip()


def normalize_phrase(phrase: str) -> str:
    p = re.sub(r"\s+", " ", phrase).strip()
    p = re.sub(r"\s*@[\w.-]+\.\w+.*$", "", p, flags=re.I)
    return p.strip(" .,-")


def clean_keywords_input(text: str) -> str:
    """Keywords only — no signatures, quotes, or keyword label prefix."""
    t = strip_email_signature(text)
    t = re.sub(r"^(?:keywords?|roles?|positions?)\s*[:\-]\s*", "", t, flags=re.I).strip()
    t, _ = extract_location_hint(t)
    t = re.sub(r"[()]", "", t)
    return normalize_phrase(t)


def extract_location_hint(text: str) -> tuple[str, str]:
    """Return (text_without_location, location)."""
    loc = "Israel"
    m = re.search(r"(?:location|country|in)\s*[:\-]\s*([^\n]+)", text, re.I)
    if m:
        loc = m.group(1).strip()
        text = text[: m.start()] + text[m.end() :]
    if re.search(r"\bisrael\b|ישראל", text, re.I):
        loc = "Israel"
        text = re.sub(r"\s*[-–—]\s*(?:israel|ישראל)\s*", " ", text, flags=re.I).strip()
    return text.strip(), loc


def _split_phrases(text: str) -> list[str]:
    text = re.sub(r"\bor\b", "|", text, flags=re.I)
    text = re.sub(r"\band\b", "|", text, flags=re.I)
    text = re.sub(r"[,;/]+", "|", text)
    parts: list[str] = []
    for p in text.split("|"):
        p = normalize_phrase(p.strip(" \"'"))
        if not p or _is_noise_phrase(p):
            continue
        parts.append(p)
    return parts


def _is_noise_phrase(p: str) -> bool:
    if re.search(r"@[\w.-]+\.", p):
        return True
    if re.match(r"^(thanks|thank you|arkadiy|kats)\b", p, re.I):
        return True
    return len(p) < 3


def _normalize_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def _grammar_check(text: str, phrases: list[str]) -> list[str]:
    notes: list[str] = []
    if not phrases:
        notes.append("No clear role phrases detected — please confirm intent.")
    if re.search(r"[\r\n]{2,}", text):
        notes.append("Removed quoted reply text from your message.")
    for p in phrases:
        if len(p) < 4:
            notes.append(f"Very short phrase: «{p}» — may be too broad or incomplete.")
        if p.lower() in ("devops", "manager", "director"):
            notes.append(f"«{p}» alone is vague — expanded variants added below.")
        if re.search(r"\b(devop|manger|engeneer|enginering)\b", p, re.I):
            notes.append(f"Possible typo in «{p}» — check spelling.")
    return notes


def _token_set(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalize_key(s)))


def _matches_role(phrase: str, anchor: str, variants: list[str]) -> bool:
    """Match user phrase to a role anchor without false positives (e.g. Operations ≠ Cloud)."""
    key = _normalize_key(phrase)
    if not key:
        return False
    ak = _normalize_key(anchor)
    if key == ak:
        return True
    for v in variants:
        if key == _normalize_key(v):
            return True
    # Acronyms (PMO, VP): word-boundary match in variants only
    if len(key) <= 4:
        pat = re.compile(rf"\b{re.escape(key)}\b", re.I)
        if pat.search(ak):
            return True
        return any(pat.search(v) for v in variants)
    words = _token_set(key)
    if len(words) == 1:
        word = next(iter(words))
        if word == ak or ak.startswith(word + " ") or ak.endswith(" " + word):
            return True
        return any(_normalize_key(v) == key for v in variants)
    if len(key) >= 6 and (key in ak or ak in key):
        return True
    for v in variants:
        vk = _normalize_key(v)
        if key == vk or (len(key) >= 8 and key in vk):
            return True
        vw = _token_set(vk)
        if words and words <= vw and len(words) >= 2:
            return True
    return False


def _match_expansions(phrase: str) -> list[tuple[str, str, str]]:
    """Return list of (en, he, source) variants for a phrase."""
    out: list[tuple[str, str, str]] = []
    key = _normalize_key(phrase)
    if not key:
        return out

    # Direct user phrase as first option
    he_guess = _guess_hebrew(phrase)
    out.append((phrase.strip(), he_guess, "user"))

    for anchor, he_label, variants in _ROLE_EXPANSIONS:
        if _matches_role(phrase, anchor, variants):
            for v in variants:
                out.append((v, he_label, "generated"))
            out.append((variants[0], he_label, "generated"))

    for he_key, (he, en) in _HE_TO_EN_HINTS.items():
        if he_key in key or key in he_key:
            out.append((en, he, "translation"))

    return out


def _guess_hebrew(phrase: str) -> str:
    if re.search(r"[\u0590-\u05ff]", phrase):
        return phrase.strip()
    key = _normalize_key(phrase)
    for anchor, he_label, _ in _ROLE_EXPANSIONS:
        if anchor in key:
            return he_label
    return ""


def _dedupe_options(items: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for en, he, src in items:
        k = _normalize_key(en)
        if k in seen:
            continue
        seen.add(k)
        out.append((en, he or _guess_hebrew(en), src))
    return out


def _llm_enrich(cleaned: str, phrases: list[str]) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Optional OpenAI enrichment. Returns extra (en, he, source) tuples and grammar notes."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return [], []
    try:
        import urllib.request

        prompt = (
            "You help refine job-search keywords for DevOps leadership roles in Israel.\n"
            f"User input: {cleaned}\n"
            f"Parsed phrases: {phrases}\n"
            "Return JSON only: "
            '{"grammar_notes":["..."], "options":[{"en":"...","he":"...","notes":"..."}]}\n'
            "Add Hebrew translation for each EN phrase and 2-4 sensible alternate EN phrasings per role. "
            "Fix grammar typos in notes if any."
        )
        body = json.dumps(
            {
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return [], []
        parsed = json.loads(m.group())
        notes = [str(x) for x in parsed.get("grammar_notes") or []]
        extras: list[tuple[str, str, str]] = []
        for opt in parsed.get("options") or []:
            if isinstance(opt, dict) and opt.get("en"):
                extras.append((str(opt["en"]), str(opt.get("he") or ""), "generated"))
        return extras, notes
    except Exception as exc:
        return [], [f"AI assist unavailable ({exc}); using rule-based expansions only."]


def build_keyword_review(raw: str) -> KeywordReview:
    raw_input = raw.strip()
    cleaned = clean_keywords_input(raw_input)
    _, location = extract_location_hint(strip_email_signature(raw_input))

    phrases = _split_phrases(cleaned)
    if not phrases and cleaned:
        phrases = [cleaned]

    grammar_notes = _grammar_check(raw_input, phrases)
    collected: list[tuple[str, str, str]] = []
    for phrase in phrases:
        collected.extend(_match_expansions(phrase))

    llm_extras, llm_notes = _llm_enrich(cleaned, phrases)
    grammar_notes.extend(llm_notes)
    collected.extend(llm_extras)
    collected = _dedupe_options(collected)

    options: list[KeywordOption] = []
    for i, (en, he, src) in enumerate(collected, start=1):
        en = normalize_phrase(en)
        he = normalize_phrase(he) if he else ""
        if not en or _is_noise_phrase(en):
            continue
        notes = ""
        if src == "user":
            notes = "from your message"
        elif src == "generated":
            notes = "suggested variant"
        options.append(KeywordOption(id=i, en=en, he=he or "—", source=src, notes=notes))
    # Re-number ids after filtering
    options = [
        KeywordOption(id=i, en=o.en, he=o.he, source=o.source, notes=o.notes)
        for i, o in enumerate(options, start=1)
    ]

    if not options and cleaned:
        options.append(KeywordOption(id=1, en=cleaned, he=_guess_hebrew(cleaned) or "—", source="user", notes="from your message"))

    return KeywordReview(
        raw_input=raw_input,
        cleaned_input=cleaned,
        grammar_notes=grammar_notes,
        options=options,
        location_hint=location,
    )


def format_how_to_reply(lang: str | None = None) -> str:
    from orchestrator.i18n import tr

    if lang == "he":
        return "\n".join(
            [
                "איך לענות",
                "──────────",
                "השיבו למייל הזה. כתבו את התשובה בשורה הראשונה:",
                "",
                "  כולם / אשר הכל / ALL  → לאשר את כל הניסוחים",
                "  1,3,5                 → לאשר רק מספרים אלה",
                "  ערוך: … / EDIT: …     → מילות מפתח חדשות (נבנה רשימה מחדש)",
                "",
                "החיפוש יתחיל רק אחרי אישורכם.",
            ]
        )
    if lang == "ru":
        return "\n".join(
            [
                "Как ответить",
                "───────────",
                "Ответьте на это письмо. Ответ — в первой строке:",
                "",
                "  ВСЕ / ALL / да все     → одобрить все фразы",
                "  1,3,5                  → только эти номера",
                "  EDIT: … / правка: …    → новые ключевые слова",
                "",
                "Поиск начнётся только после вашего одобрения.",
            ]
        )
    return "\n".join(
        [
            "How to reply",
            "────────────",
            "Reply to this email. Put your answer on the first line:",
            "",
            "  ALL          → approve every phrase below",
            "  1,3,5        → approve only those numbers",
            "  EDIT: …      → send new keywords (we rebuild the list)",
            "",
            "Hebrew: כולם · אשר הכל · 1,3,5",
            "Russian: ВСЕ · да · 1,3,5",
            "",
            "Search starts only after you approve.",
        ]
    )


def format_phrase_list(review: KeywordReview) -> str:
    lines = [
        f"Suggested phrases ({len(review.options)}) · {review.location_hint}",
        f"ניסוחים מוצעים ({len(review.options)}) · {review.location_hint}",
        "",
    ]
    for opt in review.options:
        en = normalize_phrase(opt.en)
        he = normalize_phrase(opt.he) if opt.he and opt.he != "—" else ""
        he_part = f" · {he}" if he else ""
        lines.append(f"  {opt.id}. {en}{he_part}")
    return "\n".join(lines)


def format_approval_email(review: KeywordReview, lang: str | None = None) -> str:
    from orchestrator.i18n import tr

    if lang is None:
        parts = [
            "Keyword review — please approve before we search",
            "בדיקת מילות מפתח — אשרו לפני החיפוש",
            "",
            "We expanded your role keywords into search phrases (English + Hebrew).",
            "הרחבנו את מילות המפתח לניסוחי חיפוש (אנגלית + עברית).",
            "",
            format_how_to_reply(None),
            "",
            format_phrase_list(review),
        ]
    else:
        parts = [
            tr(
                "Keyword review — please approve before we search",
                "בדיקת מילות מפתח — אשרו לפני החיפוש",
                "Проверка ключевых слов — подтвердите перед поиском",
                lang,
            ),
            "",
            tr(
                "We expanded your role keywords into search phrases (English + Hebrew).",
                "הרחבנו את מילות המפתח לניסוחי חיפוש (אנגלית + עברית).",
                "Мы развернули ключевые слова в поисковые фразы (английский + иврит).",
                lang,
            ),
            "",
            format_how_to_reply(lang),
            "",
            format_phrase_list(review),
        ]
    if review.grammar_notes:
        notes = [n for n in review.grammar_notes if "quoted reply" not in n.lower()]
        if notes:
            parts.extend(["", "Note / הערה:", *[f"• {n}" for n in notes[:3]]])
    return "\n".join(parts)


def parse_approval_selection(body: str, review: KeywordReview) -> tuple[Optional[list[int]], Optional[str], str]:
    """
    Returns (selected_ids, edited_text, mode).
    mode: all | partial | edit | invalid
    """
    text = strip_quoted_reply(body).strip()
    lower = text.lower()

    if re.match(
        r"^(all|approve all|yes all|כולם|אשר הכל|הכל|все|всё|одобрить все|да все)\b",
        lower,
    ) or lower.strip() in ("all", "все", "всё"):
        return [o.id for o in review.options], None, "all"

    m_edit = re.match(
        r"^(?:edit|EDIT|ערוך|תיקון|правка|изменить)\s*[:\-]\s*(.+)", text, re.S | re.I
    )
    if m_edit:
        return None, m_edit.group(1).strip(), "edit"

    nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", text)]
    valid = {o.id for o in review.options}
    picked = [n for n in nums if n in valid]
    if picked:
        return sorted(set(picked)), None, "partial"

    if lower in ("yes", "ok", "approve", "כן", "מאשר", "да", "ок", "одобрить", "подтвердить"):
        return [o.id for o in review.options], None, "all"

    return None, None, "invalid"


def _anchor_for_phrase(phrase: str) -> str | None:
    key = _normalize_key(phrase)
    for anchor, _, variants in _ROLE_EXPANSIONS:
        if _matches_role(phrase, anchor, variants):
            return anchor
    return None


def _linkedin_label(anchor: str) -> str:
    """Short LinkedIn Jobs label for a known anchor."""
    labels = {
        "pmo": "PMO",
        "program manager": "Program Manager",
        "project manager": "Project Manager",
        "operations": "Operations Manager",
    }
    return labels.get(anchor, anchor)


_HEBREW_RE = re.compile(r"[\u0590-\u05ff]")


def _quote_linkedin_term(term: str) -> str:
    """Format one token for LinkedIn Jobs boolean keywords (OR-joined)."""
    t = re.sub(r"\s+", " ", (term or "").strip())
    if not t:
        return ""
    if " " in t or _HEBREW_RE.search(t):
        escaped = t.replace('"', "")
        return f'"{escaped}"'
    return t


def normalize_linkedin_keywords(raw: str, *, location: str = "Israel") -> str:
    """Strip a trailing location suffix; LinkedIn UI pipes → OR for jobs search URL."""
    s = (raw or "").strip()
    if "|" in s:
        parts = [p.strip() for p in s.split("|") if p.strip()]
        if parts:
            quoted = []
            for p in parts:
                p = p.strip().strip('"')
                if " OR " in p.upper():
                    quoted.append(p)
                else:
                    quoted.append(f'"{p}"')
            s = " OR ".join(quoted)
    loc = (location or "").strip()
    if loc and s.lower().endswith(loc.lower()):
        s = s[: -len(loc)].strip()
    return s.strip()


def build_linkedin_query(selected: list[KeywordOption], location: str) -> str:
    """One LinkedIn Jobs keywords string: English role anchors OR Hebrew phrases."""
    _ = location  # location is stored in linkedin.jobs_search.location, not keywords
    en_anchors: list[str] = []
    he_phrases: list[str] = []
    seen_en: set[str] = set()
    seen_he: set[str] = set()

    for o in selected:
        en = (o.en or "").strip()
        if not en or _HEBREW_RE.search(en):
            continue
        anchor = _anchor_for_phrase(en) or _normalize_key(en)
        if anchor in seen_en:
            continue
        seen_en.add(anchor)
        label = _linkedin_label(anchor) if anchor in {a for a, _, _ in _ROLE_EXPANSIONS} else en
        en_anchors.append(label)
        if len(en_anchors) >= 6:
            break

    for o in selected:
        he = (o.he or "").strip()
        if not he:
            continue
        key = he.lower()
        if key in seen_he:
            continue
        seen_he.add(key)
        he_phrases.append(he)
        if len(he_phrases) >= 6:
            break

    if not en_anchors:
        for o in selected:
            en = (o.en or "").strip()
            if en and _HEBREW_RE.search(en):
                key = en.lower()
                if key not in seen_he:
                    seen_he.add(key)
                    he_phrases.append(en)

    if not en_anchors and not he_phrases:
        en_anchors = ["devops manager"]

    parts = [_quote_linkedin_term(p) for p in en_anchors + he_phrases]
    parts = [p for p in parts if p]
    return " OR ".join(parts)
