#!/usr/bin/env python3
"""Legacy entry point — use `python run.py` instead."""

from job_agent.main import run

if __name__ == "__main__":
    raise SystemExit(run())
