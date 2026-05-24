from orchestrator.email_client import decode_subject, reply_subject


def test_reply_subject_decodes_mime() -> None:
    raw = "=?utf-8?Q?Job_help?="
    assert "Job help" in decode_subject(raw)
    assert reply_subject(raw).lower().startswith("re:")
    assert "Job help" in reply_subject(raw)
