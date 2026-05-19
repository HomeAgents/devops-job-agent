"""Remove → Yes must hide jobs across URL variants and DB rows."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from job_agent import db as job_db
from job_agent.digest_remove import _apply_remove
from job_agent.ignore_store import is_link_ignored, load_stored_ignore_links
from job_agent.models import Job


class RemovePersistenceTests(unittest.TestCase):
    def test_remove_deletes_all_url_variants_and_hides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "jobs.db"
            ignore_path = root / "ignore.json"
            cfg = {
                "_project_root": str(root),
                "digest_remove": {"ignore_store_path": str(ignore_path), "secret": "test"},
            }
            canonical = "https://www.linkedin.com/jobs/view/4328549807"
            variant = "https://il.linkedin.com/jobs/view/infrastructure-team-leader-4328549807"
            job = Job(
                "linkedin_browser",
                "VAST Data",
                "Infrastructure Team Leader",
                "Israel",
                variant,
                score=3,
            )
            conn = job_db.connect(db_path)
            job_db.upsert_jobs(conn, [job], mark_emailed=False)
            conn.close()

            ok, _ = _apply_remove(canonical, cfg)
            self.assertTrue(ok)

            conn = job_db.connect(db_path)
            self.assertEqual(len(conn.execute("SELECT link FROM jobs").fetchall()), 0)
            conn.close()

            cfg["digest_remove"] = {**cfg["digest_remove"], "ignore_store_path": str(ignore_path)}
            self.assertTrue(is_link_ignored(variant, cfg))
            self.assertTrue(is_link_ignored(canonical, cfg))
            self.assertTrue(load_stored_ignore_links(cfg))


if __name__ == "__main__":
    unittest.main()
