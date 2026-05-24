import os
import unittest
from unittest.mock import MagicMock, patch

from orchestrator.email_client import InboundMail
from orchestrator.wake_poll import has_actionable_unseen, run_wake_cycle, start_vm_if_needed


class WakePollTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = os.environ.copy()
        os.environ["ORCHESTRATOR_SMTP_USER"] = "genie4cv@gmail.com"
        os.environ["GMAIL_EMAIL"] = "genie4cv@gmail.com"
        os.environ["GMAIL_APP_PASSWORD"] = "test-pass"
        os.environ["AZURE_SUBSCRIPTION_ID"] = "00000000-0000-0000-0000-000000000001"
        os.environ["AZURE_VM_RG"] = "rg-home-agents"
        os.environ["AZURE_VM_NAME"] = "vm-home-agents"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)

    @patch("orchestrator.wake_poll.fetch_unseen_envelopes")
    def test_no_unseen(self, fetch: MagicMock) -> None:
        fetch.return_value = []
        ok, reasons = has_actionable_unseen()
        self.assertFalse(ok)
        self.assertIn("no_unseen", reasons)

    @patch("orchestrator.wake_poll.fetch_unseen_envelopes")
    def test_actionable_unseen(self, fetch: MagicMock) -> None:
        fetch.return_value = [
            InboundMail(
                message_id="1",
                from_email="amnon.meron@gmail.com",
                subject="Job search",
                body_text="",
                attachments=[],
            )
        ]
        ok, reasons = has_actionable_unseen()
        self.assertTrue(ok)
        self.assertTrue(any("actionable" in r for r in reasons))

    @patch("orchestrator.wake_poll.fetch_unseen_envelopes")
    def test_ignore_birthday_copilot(self, fetch: MagicMock) -> None:
        fetch.return_value = [
            InboundMail(
                message_id="1",
                from_email="genie4cv@gmail.com",
                subject="[Birthday Copilot] test",
                body_text="",
                attachments=[],
            )
        ]
        ok, _ = has_actionable_unseen()
        self.assertFalse(ok)

    @patch("orchestrator.wake_poll.vm_power_state", return_value="PowerState/running")
    @patch("orchestrator.wake_poll.has_actionable_unseen", return_value=(True, ["actionable"]))
    def test_wake_cycle_vm_already_running(self, *_mocks: MagicMock) -> None:
        result = run_wake_cycle()
        self.assertTrue(result["ok"])
        self.assertFalse(result["started"])
        self.assertEqual(result["detail"], "already_PowerState/running")

    @patch("orchestrator.wake_poll._arm_request")
    @patch("orchestrator.wake_poll.vm_power_state", return_value="PowerState/deallocated")
    def test_start_vm_arm(self, _state: MagicMock, arm: MagicMock) -> None:
        os.environ.pop("WAKE_LOGIC_APP_URL", None)
        started, detail = start_vm_if_needed()
        self.assertTrue(started)
        self.assertIn("started_from", detail)
        arm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
