"""Digest jobs table sort order."""

from __future__ import annotations

import unittest

import pandas as pd

from job_agent.cv_fit import CV_FIT_COLUMN
from job_agent.excel_email import _sort_digest_jobs


class DigestSortTests(unittest.TestCase):
    def test_sort_by_cv_fit_then_company(self) -> None:
        df = pd.DataFrame(
            [
                {"Job Title": "B", "Company": "Zeta", CV_FIT_COLUMN: "40%"},
                {"Job Title": "A", "Company": "Alpha", CV_FIT_COLUMN: "90%"},
                {"Job Title": "C", "Company": "Alpha", CV_FIT_COLUMN: "70%"},
                {"Job Title": "D", "Company": "Beta", CV_FIT_COLUMN: "NA"},
            ]
        )
        out = _sort_digest_jobs(df)
        companies = list(out["Company"])
        fits = list(out[CV_FIT_COLUMN])
        self.assertEqual(companies, ["Alpha", "Alpha", "Zeta", "Beta"])
        self.assertEqual(fits, ["90%", "70%", "40%", "NA"])

    def test_sort_by_company_when_no_cv_fit_column(self) -> None:
        df = pd.DataFrame(
            [
                {"Job Title": "B", "Company": "Zeta"},
                {"Job Title": "A", "Company": "Alpha"},
            ]
        )
        out = _sort_digest_jobs(df)
        self.assertEqual(list(out["Company"]), ["Alpha", "Zeta"])


if __name__ == "__main__":
    unittest.main()
