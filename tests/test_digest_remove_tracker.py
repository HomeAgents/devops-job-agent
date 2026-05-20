"""Tracker Status Remove must hide jobs from digest (link or title+company)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from job_agent.digest_remove import _apply_remove
from job_agent.job_tracker_excel import (
    filter_jobs_for_digest,
    load_tracker_df,
    set_job_tracker_status,
)
from job_agent.models import Job


class DigestRemoveTrackerTests(unittest.TestCase):
    def test_tracker_remove_excludes_by_title_company_when_link_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = {
                "_project_root": str(root),
                "job_tracker": {
                    "enabled": True,
                    "path": "job_tracker.xlsx",
                    "status_values": ["New", "In Progress", "Interview", "Rejected", "Remove"],
                    "status_on_digest_remove": "Remove",
                },
                "digest_remove": {"ignore_store_path": str(root / "ignore.json"), "secret": "t"},
            }
            old_link = "https://www.linkedin.com/jobs/view/100"
            new_link = "https://il.linkedin.com/jobs/view/devops-lead-100"
            set_job_tracker_status(
                old_link,
                "Remove",
                cfg,
                root=root,
                job_snapshot={"Job Title": "DevOps Lead", "Company": "Acme Corp", "Link": old_link},
            )
            jobs = [
                Job("linkedin_browser", "Acme Corp", "DevOps Lead", "Israel", new_link),
                Job("linkedin_browser", "Other Co", "SRE", "Israel", "https://example.com/j/1"),
            ]
            out = filter_jobs_for_digest(jobs, cfg, root=root)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0].company, "Other Co")

    def test_apply_remove_sets_tracker_status_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = {
                "_project_root": str(root),
                "job_tracker": {
                    "enabled": True,
                    "path": "job_tracker.xlsx",
                    "status_values": ["New", "Remove"],
                    "status_on_digest_remove": "Remove",
                },
                "digest_remove": {"ignore_store_path": str(root / "ignore.json"), "secret": "t"},
            }
            link = "https://www.linkedin.com/jobs/view/555"
            _apply_remove(
                link,
                {
                    **cfg,
                    "digest_remove": {**cfg["digest_remove"], "ignore_store_path": str(root / "ignore.json")},
                },
            )
            tracker = load_tracker_df(cfg, root=root)
            self.assertFalse(tracker.empty)
            statuses = {str(r.get("Status") or "") for _, r in tracker.iterrows()}
            self.assertIn("Remove", statuses)


if __name__ == "__main__":
    unittest.main()
