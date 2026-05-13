# devops-job-agent

Aggregates **DevOps Manager / Director** (and related) roles from several sources, dedupes against SQLite, writes an **Excel** digest, and optionally emails it via **Gmail SMTP**.

## Sources (pluggable)

| Source | Config key | Notes |
|--------|------------|--------|
| **SerpAPI Google Jobs** | `serpapi_google_jobs_queries` in `config.json` | Needs `SERPAPI_KEY` in `.env` |
| **Greenhouse** public API | `greenhouse_boards` | Board slug from URL `boards.greenhouse.io/{slug}` |
| **Lever** public API | `lever_sites` | Site name from `jobs.lever.co/{site}` |
| **RSS** | `rss_feeds` | e.g. We Work Remotely category feed |

URLs are **normalized** (tracking query params stripped) for deduplication.

## Setup

```bash
cd devops-job-agent
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
cp .env.example .env
# Edit .env: SERPAPI_KEY, EMAIL_USER, EMAIL_PASS, EMAIL_TO (Gmail app password)
```

Optional: shared JSON settings (same as before):

- `GENIE4CV_SETTINGS` — path to `local.settings.json` (defaults to `~/genie4cv/local.settings.json`).

Tune targets in **`config.json`**: queries, Greenhouse/Lever slugs, RSS URLs, scoring keywords.

## Run

```bash
# Safe test: no DB update, no email; optional empty DB to see fresh rows
python run.py --dry-run --skip-contacts --db /tmp/jagent-test.db

# All sources, real DB + email (production)
python run.py

# Only some sources
python run.py --sources greenhouse,rss

# Legacy entry (same as run.py)
python script.py --dry-run --skip-contacts
```

### Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Build `jobs_<date>.xlsx` under `/tmp`, **no** `jobs.db` updates, **no** email |
| `--skip-contacts` | Skip SerpAPI Google search for LinkedIn profiles (saves API quota) |
| `--sources a,b,c` | `serpapi`, `greenhouse`, `lever`, `rss` (comma-separated; default: all) |
| `--config path` | Alternate `config.json` |
| `--db path` | Alternate SQLite file |

## CV

**Not required** for the current pipeline. Later you can add a `CV.pdf` / `profile.md` and use it for LLM-based fit scoring or outreach personalization.

## Legal / etiquette

- Respect **SerpAPI**, **Greenhouse**, **Lever**, and site **terms of use**.
- **LinkedIn**: use public search results only; avoid logged-in scraping.

## Layout

```
devops-job-agent/
  run.py                 # preferred CLI
  script.py              # legacy shim → same CLI
  config.json
  requirements.txt
  job_agent/
    main.py              # orchestration + argparse
    settings.py          # .env + optional Genie JSON
    db.py
    scoring.py
    contacts.py
    excel_email.py
    outreach.py
    sources/
      google_jobs.py
      rss_feeds.py
      greenhouse.py
      lever.py
```
