from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

import pandas as pd

from job_agent import db
from job_agent.contacts import find_contacts
from job_agent.excel_email import save_excel, send_email_with_attachment
from job_agent.models import Job
from job_agent.outreach import outreach_message
from job_agent.settings import get_setting
from job_agent.sources.google_jobs import fetch_google_jobs
from job_agent.sources.greenhouse import fetch_greenhouse
from job_agent.sources.lever import fetch_lever
from job_agent.sources.rss_feeds import fetch_rss_jobs


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_sources_arg(raw: str | None) -> Set[str] | None:
    if not raw:
        return None
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def collect_all(cfg: Dict[str, Any], only: Set[str] | None) -> List[Job]:
    jobs: List[Job] = []
    seen: Set[str] = set()

    def add_many(new: List[Job]) -> None:
        for j in new:
            if j.link not in seen:
                seen.add(j.link)
                jobs.append(j)

    if only is None or "serpapi" in only or "google_jobs" in only:
        add_many(fetch_google_jobs(cfg.get("serpapi_google_jobs_queries") or [], cfg))

    if only is None or "greenhouse" in only:
        add_many(fetch_greenhouse(cfg.get("greenhouse_boards") or [], cfg))

    if only is None or "lever" in only:
        add_many(fetch_lever(cfg.get("lever_sites") or [], cfg))

    if only is None or "rss" in only:
        add_many(fetch_rss_jobs(cfg.get("rss_feeds") or [], cfg))

    return jobs


def run(argv: List[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    root = project_root()
    parser = argparse.ArgumentParser(description="DevOps Manager/Director job agent")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("JOB_AGENT_CONFIG", str(root / "config.json"))),
        help="Path to config.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + build Excel; do not write jobs.db or send email",
    )
    parser.add_argument(
        "--skip-contacts",
        action="store_true",
        help="Skip SerpAPI Google search for LinkedIn profiles",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="",
        help="Comma list: serpapi,greenhouse,lever,rss (default: all)",
    )
    parser.add_argument("--db", type=Path, default=root / "jobs.db", help="SQLite path")

    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    only = parse_sources_arg(args.sources or None)

    conn = db.connect(args.db)
    try:
        jobs = collect_all(cfg, only)
        if not jobs:
            print("No jobs fetched from any source.")
            return 0

        existing = db.existing_links(conn)
        new_jobs = [j for j in jobs if j.link not in existing]
        if not new_jobs:
            print("No new jobs (all links already in jobs.db).")
            return 0

        rows = [j.as_row() for j in new_jobs]
        df = pd.DataFrame(rows)

        top_jobs = df.sort_values("Score", ascending=False).head(5)
        contacts: List[dict] = []
        if not args.skip_contacts:
            if get_setting("SERPAPI_KEY", "GOOGLE_JOBS_API_KEY"):
                for _, row in top_jobs.iterrows():
                    contacts.extend(find_contacts(str(row["Company"]), str(row["Job Title"])))
            else:
                print("Skipping contacts: no SERPAPI_KEY", file=sys.stderr)

        contacts_df = pd.DataFrame(contacts)
        if not contacts_df.empty:
            contacts_df["Message"] = contacts_df.apply(
                lambda r: outreach_message(str(r["Company"]), str(r["Role Hint"])),
                axis=1,
            )

        out_dir = root if not args.dry_run else Path("/tmp")
        xlsx = save_excel(df, contacts_df if not contacts_df.empty else pd.DataFrame(), out_dir)
        print(f"Wrote {xlsx} ({len(new_jobs)} new jobs).")

        if args.dry_run:
            print("Dry-run: not updating jobs.db or sending email.")
            return 0

        db.insert_links(conn, [j.link for j in new_jobs])
        send_email_with_attachment(xlsx)
        print("Sent digest email.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(run())
