"""Digest main vs removed tables and job link identity."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from job_agent.ignore_store import (
    add_removed_record,
    filter_dataframe_not_removed,
    filter_jobs_not_removed,
    filter_removed_dataframe_not_in_main,
    is_link_ignored,
)
from job_agent.job_tracker_excel import apply_tracker_to_digest_df, set_job_tracker_status, sync_digest_jobs_to_tracker
from job_agent.models import Job
from job_agent.util import job_link_identity, job_links_same_posting, normalize_url


class DigestTablesTests(unittest.TestCase):
    def test_linkedin_identity_matches_www_and_il(self) -> None:
        a = "https://www.linkedin.com/jobs/view/4405599372"
        b = "https://il.linkedin.com/jobs/view/devops-manager-4405599372"
        self.assertTrue(job_links_same_posting(a, b))
        self.assertEqual(job_link_identity(a), job_link_identity(b))

    def test_removed_job_excluded_from_digest_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ignore.json"
            removed = "https://www.linkedin.com/jobs/view/111"
            digest = "https://il.linkedin.com/jobs/view/role-111"
            path.write_text(
                json.dumps({"removed": [{"link": normalize_url(removed)}]}),
                encoding="utf-8",
            )
            cfg = {"digest_remove": {"ignore_store_path": str(path)}}
            self.assertTrue(is_link_ignored(digest, cfg))
            jobs = [
                Job("linkedin_browser", "Acme", "DevOps Manager", "Israel", digest),
                Job("linkedin_browser", "Other", "DevOps Director", "Israel", "https://example.com/j/2"),
            ]
            out = filter_jobs_not_removed(jobs, cfg)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0].link, "https://example.com/j/2")

    def test_removed_table_drops_rows_in_main_digest(self) -> None:
        main = pd.DataFrame(
            [
                {
                    "Job Title": "DevOps Manager",
                    "Company": "Acme",
                    "Link": "https://www.linkedin.com/jobs/view/111",
                }
            ]
        )
        removed = pd.DataFrame(
            [
                {
                    "Job Title": "DevOps Manager",
                    "Company": "Acme",
                    "Link": "https://il.linkedin.com/jobs/view/devops-111",
                },
                {
                    "Job Title": "Other",
                    "Company": "X",
                    "Link": "https://example.com/hidden",
                },
            ]
        )
        out = filter_removed_dataframe_not_in_main(removed, main)
        self.assertEqual(len(out), 1)
        self.assertIn("example.com", str(out.iloc[0]["Link"]))

    def test_tracker_status_before_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = {
                "job_tracker": {
                    "enabled": True,
                    "path": "job_tracker.xlsx",
                    "status_values": ["New", "In Progress", "Interview", "Rejected"],
                }
            }
            link = "https://www.linkedin.com/jobs/view/999"
            set_job_tracker_status(link, "Interview", cfg, root=root, job_snapshot={"Job Title": "Mgr", "Company": "Co"})
            df = pd.DataFrame(
                [{"Job Title": "Mgr", "Company": "Co", "Link": link, "Source": "x", "Location": "IL", "Network": ""}]
            )
            merged = apply_tracker_to_digest_df(df, cfg, root=root)
            self.assertEqual(str(merged.iloc[0]["Status"]), "Interview")
            sync_digest_jobs_to_tracker(merged, cfg, root=root)
            merged2 = apply_tracker_to_digest_df(merged, cfg, root=root)
            self.assertEqual(str(merged2.iloc[0]["Status"]), "Interview")


if __name__ == "__main__":
    unittest.main()
