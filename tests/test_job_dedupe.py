"""Digest dedupe: same posting across different URLs and company name variants."""

from __future__ import annotations

import unittest

from job_agent.job_dedupe import dedupe_jobs, jobs_same_posting
from job_agent.models import Job


class JobDedupeTests(unittest.TestCase):
    def test_cross_source_same_title_company_collapses(self) -> None:
        jobs = [
            Job(
                "linkedin_browser",
                "Riverbed Technology",
                "Director of DevOps",
                "Israel",
                "https://www.linkedin.com/jobs/view/riverbed-devops-1",
                score=80,
            ),
            Job(
                "google_site_ats",
                "Riverbed",
                "Director of DevOps",
                "Israel",
                "https://boards.greenhouse.io/riverbed/jobs/999",
                score=90,
            ),
        ]
        out = dedupe_jobs(jobs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].score, 90)
        self.assertIn("greenhouse", out[0].link)

    def test_different_roles_same_company_stay_separate(self) -> None:
        jobs = [
            Job("x", "Acme", "DevOps Director", "IL", "https://example.com/a", score=70),
            Job("x", "Acme", "DevOps Manager", "IL", "https://example.com/b", score=70),
        ]
        self.assertEqual(len(dedupe_jobs(jobs)), 2)

    def test_linkedin_url_variants_one_row(self) -> None:
        a = "https://www.linkedin.com/jobs/view/4405599372"
        b = "https://il.linkedin.com/jobs/view/devops-manager-4405599372"
        jobs = [
            Job("linkedin_browser", "Co", "DevOps Manager", "IL", a, score=50),
            Job("linkedin_browser", "Co", "DevOps Manager", "IL", b, score=60),
        ]
        out = dedupe_jobs(jobs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].score, 60)

    def test_jobs_same_posting_company_suffix(self) -> None:
        a = Job("x", "Acme Corp", "Lead", "IL", "https://a.example/j1")
        b = Job("x", "Acme", "Lead", "IL", "https://b.example/j2")
        self.assertTrue(jobs_same_posting(a, b))


if __name__ == "__main__":
    unittest.main()
