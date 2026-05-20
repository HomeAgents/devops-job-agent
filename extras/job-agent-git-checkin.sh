#!/usr/bin/env bash
# Stage and commit safe job-agent project files (respects .gitignore).
# Usage: extras/job-agent-git-checkin.sh
#   JOB_AGENT_ROOT=/path/to/devops-job-agent  (optional)
#   JOB_AGENT_GIT_MSG="custom message"        (optional, skips prompt)

set -euo pipefail

ROOT="${JOB_AGENT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"

NEVER_COMMIT=(
  .env
  .env.local
  .env.production
  .env.development
)

die() {
  echo "Error: $*" >&2
  exit 1
}

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not a git repo: $ROOT"

for tracked_secret in "${NEVER_COMMIT[@]}"; do
  if git ls-files --error-unmatch "$tracked_secret" &>/dev/null; then
    die "$tracked_secret is tracked in git — remove it from the index before using this script"
  fi
done

echo "Repository: $ROOT"
echo ""
git status -sb
echo ""

if git diff --quiet && git diff --cached --quiet; then
  untracked="$(git ls-files --others --exclude-standard)"
  if [[ -z "$untracked" ]]; then
    echo "Nothing to commit (working tree clean)."
    exit 0
  fi
fi

git add -A

for f in "${NEVER_COMMIT[@]}"; do
  if [[ -f "$f" ]]; then
    git reset -q HEAD -- "$f" 2>/dev/null || true
  fi
done

if git diff --cached --quiet; then
  echo "Nothing to commit after excluding secrets (.env, etc.)."
  echo "Note: jobs.db, job_tracker.xlsx, and ~/.job-agent/ are gitignored by design."
  exit 0
fi

echo "Staged for commit:"
git diff --cached --name-status
echo ""

default_msg="job alert: $(date '+%Y-%m-%d %H:%M')"
if [[ -n "${JOB_AGENT_GIT_MSG:-}" ]]; then
  msg="$JOB_AGENT_GIT_MSG"
else
  read -r -p "Commit message [$default_msg]: " reply
  if [[ -n "${reply// }" ]]; then
    msg="$reply"
  else
    msg="$default_msg"
  fi
fi

git commit -m "$msg"
echo ""
echo "Committed."
git log -1 --oneline
echo ""
git status -sb
echo ""
echo "Not committed (gitignored): .env, *.db, job_tracker.xlsx, .venv/, ~/.job-agent/"
echo "Push when ready:  cd \"$ROOT\" && git push origin main"
echo "Remote: https://github.com/HomeAgents/devops-job-agent.git"
