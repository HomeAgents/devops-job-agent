#!/usr/bin/env python3
"""CLI entry: python run.py [--dry-run] [--skip-contacts] [--sources ...]"""

from job_agent.main import run

if __name__ == "__main__":
    raise SystemExit(run())
