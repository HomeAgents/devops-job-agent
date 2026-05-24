from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from job_agent import db as job_db
from job_agent.digest_remove import (
    _apply_remove,
    find_user_cfg_by_email,
    find_user_cfg_for_link,
    resolve_cfg_for_token,
    sign_action_token,
)
from job_agent.models import Job


class DigestRemoveMultitenantTests(unittest.TestCase):
    def test_resolve_cfg_by_user_in_token(self) -> None:
        secret = "shared-secret"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_a = root / "users" / "alice_example.com"
            user_b = root / "users" / "bob_example.com"
            for d in (user_a, user_b):
                d.mkdir(parents=True)
                (d / "config.json").write_text(
                    json.dumps(
                        {
                            "digest_remove": {
                                "secret": secret,
                                "ignore_store_path": str(d / "ignore.json"),
                            },
                            "_user_email": "alice@example.com" if d == user_a else "bob@example.com",
                            "_project_root": str(d),
                            "_jobs_db": str(d / "jobs.db"),
                        }
                    ),
                    encoding="utf-8",
                )
            link = "https://www.linkedin.com/jobs/view/999/"
            conn = job_db.connect(user_b / "jobs.db")
            try:
                job_db.upsert_jobs(
                    conn,
                    [
                        Job(
                            source="test",
                            company="Co",
                            title="DevOps Manager",
                            location="Israel",
                            link=link,
                            posted="recent",
                            score=1,
                        )
                    ],
                    mark_emailed=False,
                )
            finally:
                conn.close()

            import os

            os.environ["ORCHESTRATOR_DATA_DIR"] = str(root)
            try:
                default_cfg = json.loads((user_a / "config.json").read_text())
                token = sign_action_token(link, default_cfg, action="remove", user_email="bob@example.com")
                cfg, payload, err = resolve_cfg_for_token(token, default_cfg)
                self.assertIsNone(err)
                self.assertIsNotNone(payload)
                self.assertEqual(str(cfg.get("_user_email")), "bob@example.com")
                self.assertEqual(find_user_cfg_by_email("bob@example.com"), cfg)
                self.assertEqual(find_user_cfg_for_link(link), cfg)
                ok, _ = _apply_remove(link, cfg)
                self.assertTrue(ok)
            finally:
                os.environ.pop("ORCHESTRATOR_DATA_DIR", None)


if __name__ == "__main__":
    unittest.main()
