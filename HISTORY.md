# Project history (devops-job-agent)

Working log of how this repo evolved and how to run it. **Do not commit secrets**; keep API keys in `.env` or Genie4CV `local.settings.json` only.

---

## 2026-05-04 — Multi-source agent refactor

### Goal

Turn the single `script.py` job fetcher into a **modular agent** that aggregates **DevOps Manager / Director** (and related) roles from several places, dedupes, writes **Excel**, optionally emails via **Gmail SMTP**, and supports **dry-run** testing.

### Layout (current)

| Path | Purpose |
|------|---------|
| `run.py` | Preferred CLI entry |
| `script.py` | Legacy shim → same as `run.py` |
| `config.json` | Queries, Greenhouse boards, Lever sites, RSS URLs, scoring knobs |
| `requirements.txt` | Python dependencies |
| `.env` / `.env.example` | Local overrides (see below) |
| `job_agent/main.py` | Orchestration, `argparse`, merge sources, DB + Excel + email |
| `job_agent/settings.py` | Loads `.env` (python-dotenv), then Genie4CV JSON `Values` |
| `job_agent/db.py` | SQLite `jobs(link)` dedupe |
| `job_agent/scoring.py` | Title scoring from `config.json` |
| `job_agent/util.py` | URL normalize (strip tracking query params) |
| `job_agent/serpapi_client.py` | Shared SerpAPI HTTP helper |
| `job_agent/contacts.py` | Optional LinkedIn profile hints via SerpAPI Google search |
| `job_agent/excel_email.py` | Excel writer + Gmail attachment MIME type for `.xlsx` |
| `job_agent/outreach.py` | Template outreach text |
| `job_agent/sources/google_jobs.py` | SerpAPI `google_jobs` |
| `job_agent/sources/greenhouse.py` | Greenhouse public jobs API |
| `job_agent/sources/lever.py` | Lever public postings JSON |
| `job_agent/sources/rss_feeds.py` | RSS/Atom feeds |

### CLI flags

- `--dry-run` — write Excel under `/tmp`, **no** `jobs.db` updates, **no** email  
- `--skip-contacts` — skip SerpAPI Google search for LinkedIn (saves quota)  
- `--sources serpapi,greenhouse,lever,rss` — subset of sources  
- `--db path` — alternate SQLite file (useful for tests)  
- `--config path` — alternate `config.json`

### SerpAPI / Genie4CV configuration

- `get_setting("SERPAPI_KEY", "GOOGLE_JOBS_API_KEY")` — **environment wins first**, then Genie `Values`.
- **Lesson learned:** a placeholder `SERPAPI_KEY=your_key` in `devops-job-agent/.env` **blocked** the real `GOOGLE_JOBS_API_KEY` from Genie4CV.
- **Fix applied:** `.env` now sets `GENIE4CV_SETTINGS` to the Genie `local.settings.json` path and **does not** set `SERPAPI_KEY`, so `GOOGLE_JOBS_API_KEY` from Genie is used.
- If SerpAPI returns **401**, the key in Genie is invalid/expired/not a SerpAPI key — update `GOOGLE_JOBS_API_KEY` (or add `SERPAPI_KEY`) in Genie or `.env`.
- **Without any SerpAPI key:** Google Jobs + contacts are skipped; **Greenhouse, Lever, RSS** still run.

### Dependencies

`requests`, `pandas`, `openpyxl`, `tenacity`, `feedparser`, `python-dotenv`

### Tests run during development

- `python run.py --dry-run --skip-contacts --sources rss,greenhouse,lever --db /tmp/jagent-test.db` — produced a small Excel file with rows from non-SerpAPI sources.
- Full `--dry-run` with invalid SerpAPI key: SerpAPI skipped after 401 handling; other sources still contributed.

### CV

Not required for the pipeline. Future idea: optional CV/profile path for LLM fit scoring or personalized outreach.

### Security reminders

- Never commit `local.settings.json`, real `.env`, or `jobs.db` if it embeds sensitive links.
- If settings files were ever exposed in a chat or screenshot, **rotate** affected passwords/API keys.

---

## Earlier state (pre-refactor)

- Single `script.py`: SerpAPI Google Jobs only (keyword loop), SQLite dedupe, Excel, Gmail, optional Genie4CV path **hard-coded** to `~/genie4cv/local.settings.json`.
- `find_contacts` via SerpAPI Google organic for `linkedin.com/in/`.

---

## How to record future changes

Append dated sections under this file when you change sources, scoring, or scheduling (e.g. cron for `python run.py`).
