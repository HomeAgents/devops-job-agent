"""LinkedIn meta description snippet for CV fit."""

from job_agent.linkedin_og import fetch_linkedin_job_snippet_http


def test_fetch_linkedin_job_snippet_parses_meta(monkeypatch):
    html = """
    <html><head>
    <meta property="og:description" content="Posted 10:00:00 PM. DevOps Manager role. Kubernetes and Terraform required. See this and similar jobs on LinkedIn." />
    </head></html>
    """

    def fake_open(req, timeout=20):
        class R:
            def read(self):
                return html.encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        return R()

    import job_agent.linkedin_og as mod

    monkeypatch.setattr(mod, "urlopen", fake_open)
    text = fetch_linkedin_job_snippet_http("https://www.linkedin.com/jobs/view/12345")
    assert "kubernetes" in text.lower()
    assert "similar jobs" not in text.lower()
