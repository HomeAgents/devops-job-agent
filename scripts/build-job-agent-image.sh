#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -f docker/Dockerfile -t job-agent:latest .
echo "Built job-agent:latest"
