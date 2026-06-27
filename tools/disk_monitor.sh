#!/usr/bin/env bash
# Disk usage monitor — warns at 80%, rotates logs at 85%, alerts at 90%
# Cron: */15 * * * * /home/wali/Desktop/AI\ BOT\ REBUILD/tools/disk_monitor.sh >> /home/wali/Desktop/AI\ BOT\ REBUILD/logs/disk_monitor.log 2>&1

set -euo pipefail

THRESHOLD_WARN=80
THRESHOLD_ROTATE=85
THRESHOLD_CRITICAL=90
LOGROTATE_CONF="/home/wali/Desktop/AI BOT REBUILD/.claude/logrotate_v2.conf"
LOGROTATE_STATE="/home/wali/.logrotate_v2_state"
CONTROL_PLANE="/home/wali/Desktop/AI BOT REBUILD/claude_worklog/agent_supervisor/logs/control_plane"

USED_PCT=$(df / | awk 'NR==2{gsub(/%/,""); print $5}')
AVAIL=$(df -h / | awk 'NR==2{print $4}')
TS=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$TS] disk=${USED_PCT}% avail=${AVAIL}"

if [ "$USED_PCT" -ge "$THRESHOLD_CRITICAL" ]; then
    echo "[$TS] CRITICAL: disk ${USED_PCT}% >= ${THRESHOLD_CRITICAL}% — emergency truncating largest logs"
    for f in "$CONTROL_PLANE"/*.log "$CONTROL_PLANE"/*.err; do
        [ -f "$f" ] || continue
        SIZE=$(stat -c%s "$f" 2>/dev/null || echo 0)
        if [ "$SIZE" -gt 52428800 ]; then  # >50MB
            truncate -s 0 "$f"
            echo "[$TS] EMERGENCY truncated: $f (was $(numfmt --to=iec $SIZE))"
        fi
    done
elif [ "$USED_PCT" -ge "$THRESHOLD_ROTATE" ]; then
    echo "[$TS] WARNING: disk ${USED_PCT}% >= ${THRESHOLD_ROTATE}% — running logrotate"
    logrotate --state "$LOGROTATE_STATE" "$LOGROTATE_CONF" && echo "[$TS] logrotate OK"
elif [ "$USED_PCT" -ge "$THRESHOLD_WARN" ]; then
    echo "[$TS] NOTICE: disk ${USED_PCT}% >= ${THRESHOLD_WARN}% — approaching threshold"
fi
