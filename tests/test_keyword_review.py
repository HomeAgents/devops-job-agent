from orchestrator.keyword_review import (
    build_keyword_review,
    build_linkedin_query,
    clean_keywords_input,
    format_approval_email,
    parse_approval_selection,
    strip_quoted_reply,
)


def test_strip_quoted_reply() -> None:
    raw = "DevOps Manager Israel\n\n> On 24 May wrote:\n> Hi assistant"
    assert "DevOps Manager" in strip_quoted_reply(raw)
    assert "On 24 May" not in strip_quoted_reply(raw)


def test_build_keyword_review_expands() -> None:
    review = build_keyword_review("DevOps Manager OR Head of DevOps — Israel")
    assert review.cleaned_input
    assert len(review.options) >= 2
    assert any("DevOps Manager" in o.en for o in review.options)
    assert any(o.he for o in review.options)


def test_approval_all_and_partial() -> None:
    review = build_keyword_review("DevOps Manager")
    sel, edited, mode = parse_approval_selection("ALL", review)
    assert mode == "all"
    assert sel and len(sel) == len(review.options)

    sel2, _, mode2 = parse_approval_selection("1, 2", review)
    assert mode2 == "partial"
    assert sel2 == [1, 2]


def test_build_linkedin_query() -> None:
    review = build_keyword_review("DevOps Manager")
    q = build_linkedin_query(review.options[:2], "Israel")
    assert "devops" in q.lower()
    assert "Israel" not in q
    assert " OR " in q


def test_strip_signature_from_keywords() -> None:
    raw = (
        "DevOps Manager, platform engineering manager\n\n"
        "Thanks\n\n"
        "Arkadiy Kats\n"
        "arkadiy.kats@gmail.com"
    )
    cleaned = clean_keywords_input(raw)
    assert "Thanks" not in cleaned
    assert "arkadiy" not in cleaned.lower()
    assert "platform engineering manager" in cleaned.lower()
    review = build_keyword_review(raw)
    body = format_approval_email(review)
    assert "Thanks" not in body
    assert "arkadiy.kats@gmail.com" not in body
    for opt in review.options:
        assert "\n" not in opt.en
        assert "@" not in opt.en


def test_pmo_and_operations_linkedin_query() -> None:
    review = build_keyword_review(
        "Program Manager OR Project Manager OR PMO OR Operations Israel"
    )
    q = build_linkedin_query(review.options, "Israel")
    assert "cloud manager" not in q.lower()
    assert "PMO" in q
    assert "Operations" in q or "operations" in q
    pmo_opt = next(o for o in review.options if o.en.upper() == "PMO" or "PMO" in o.en)
    assert "ניהול פרויקטים" in pmo_opt.he or "PMO" in pmo_opt.he


def test_format_approval_email_bilingual() -> None:
    review = build_keyword_review("DevOps Manager")
    body = format_approval_email(review)
    assert "Keyword review" in body
    assert "בדיקת מילות מפתח" in body
    assert "How to reply" in body
    assert "Suggested phrases" in body
    assert "What we received" not in body
    assert body.index("How to reply") < body.index("Suggested phrases")
