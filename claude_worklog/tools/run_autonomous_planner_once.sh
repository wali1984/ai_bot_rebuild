#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"
python3 claude_worklog/tools/agent_supervisor.py --planner-once "$@"
