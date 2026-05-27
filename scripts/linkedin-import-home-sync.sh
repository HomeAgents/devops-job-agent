#!/usr/bin/env bash
# On VM: verify home-sync file exists (import happens automatically during run.py / orchestrator).
set -euo pipefail
USER_EMAIL="${1:-arkadiy.kats@gmail.com}"
ROOT="${HOME}/apps/devops-job-agent"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
SAFE="$(PYTHONPATH=. python3 -c "from orchestrator.user_db import sanitize_email; print(sanitize_email('${USER_EMAIL}'))")"
PATH_FILE="${HOME}/orchestrator-data/users/${SAFE}/linkedin_home/jobs.json"
if [ ! -f "$PATH_FILE" ]; then
  echo "No home sync file: $PATH_FILE"
  exit 1
fi
ls -la "$PATH_FILE"
PYTHONPATH=. python3 -c "
import json, sys
sys.path.insert(0, '.')
from pathlib import Path
from job_agent.main import load_config
from job_agent.linkedin_home_sync import load_home_sync_jobs
cfg = load_config(Path.home() / 'orchestrator-data/users/${SAFE}/config.json')
cfg['_user_email'] = '${USER_EMAIL}'
li = cfg.setdefault('linkedin', {})
hs = li.setdefault('home_sync', {})
hs.setdefault('enabled', True)
hs.setdefault('skip_vm_linkedin_when_fresh', True)
if not hs.get('import_path'):
    hs['import_path'] = str(Path.home() / 'orchestrator-data/users/${SAFE}/linkedin_home/jobs.json')
jobs, msg = load_home_sync_jobs(cfg)
print(msg)
print('jobs:', len(jobs))
"
