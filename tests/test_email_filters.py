import os
import unittest

from orchestrator.email_client import InboundMail
from orchestrator.email_filters import ignore_reason, is_ignored_inbound


class EmailFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = os.environ.copy()
        os.environ["ORCHESTRATOR_SMTP_USER"] = "genie4cv@gmail.com"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)

    def test_ignore_birthday_copilot_sent_from_own_mailbox(self) -> None:
        mail = InboundMail(
            message_id="1",
            from_email="genie4cv@gmail.com",
            subject="[Birthday Copilot] : VM Test User Birthday",
            body_text="",
            attachments=[],
        )
        self.assertTrue(is_ignored_inbound(mail))
        self.assertIn("orchestrator mailbox", ignore_reason(mail) or "")

    def test_allow_birthday_approval_reply_from_user(self) -> None:
        mail = InboundMail(
            message_id="1b",
            from_email="arkadiy.kats@gmail.com",
            subject="Re: [Birthday Copilot] : VM Test User Birthday",
            body_text="yes",
            attachments=[],
        )
        self.assertFalse(is_ignored_inbound(mail))

    def test_ignore_scoutsignal_subject(self) -> None:
        mail = InboundMail(
            message_id="2",
            from_email="genie4cv@gmail.com",
            subject="[ScoutSignal] ScoutSignal report — no new listings",
            body_text="",
            attachments=[],
        )
        self.assertTrue(is_ignored_inbound(mail))

    def test_ignore_mailer_daemon(self) -> None:
        mail = InboundMail(
            message_id="3",
            from_email="mailer-daemon@googlemail.com",
            subject="Delivery Status Notification (Failure)",
            body_text="",
            attachments=[],
        )
        self.assertTrue(is_ignored_inbound(mail))

    def test_allow_user_job_reply(self) -> None:
        mail = InboundMail(
            message_id="4",
            from_email="arkadiy.kats@gmail.com",
            subject="Re: Job assistance",
            body_text="1",
            attachments=[],
        )
        self.assertFalse(is_ignored_inbound(mail))


if __name__ == "__main__":
    unittest.main()
