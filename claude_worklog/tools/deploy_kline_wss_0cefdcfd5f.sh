#!/usr/bin/env bash
# WQ-R35 deploy: repoint ai-bot-v2-binance-kline-wss-loop to snapshot
# 0cefdcfd5f362a103f83d63f7ff1a528aac77d16 (receive-stall fix: no inline
# 5m-durability await; close_events_received_{tf} counters).
#
# Snapshot already built, validated (import check + git attestation), and
# chmod'd read-only. This script only swaps the SHA in the drop-in,
# daemon-reloads, and restarts at a candle-safe second so the restart
# itself cannot shed a close event.
#
# Rollback: re-run with OLD/NEW swapped, or restore the backup:
#   ~/.config/systemd/user/.../90-immutable-release.conf.bak-82c7fbfb (scratchpad copy noted in worklog)
set -euo pipefail

OLD=82c7fbfb4441e4357b8adc17e0018a0d4c023d55
NEW=0cefdcfd5f362a103f83d63f7ff1a528aac77d16
DROPIN="$HOME/.config/systemd/user/ai-bot-v2-binance-kline-wss-loop.service.d/90-immutable-release.conf"
SNAP="/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/$NEW"

[[ -x "$SNAP/.venv/bin/python3" ]] || { echo "snapshot venv missing"; exit 1; }
git -C "$SNAP" diff --quiet --exit-code "$NEW" -- || { echo "snapshot attestation failed"; exit 1; }
grep -q "$OLD" "$DROPIN" || { echo "drop-in does not reference $OLD (already deployed?)"; exit 1; }

cp "$DROPIN" "$DROPIN.bak-$(date -u +%Y%m%dT%H%M%SZ)"
sed -i "s/$OLD/$NEW/g" "$DROPIN"
systemctl --user daemon-reload

# Candle-safe restart window: 5-20s past a minute whose successor minute is
# not 5m-aligned (so no 1m or 5m close event can land inside the ~10-20s
# restart+resubscribe downtime).
echo "waiting for candle-safe restart window..."
while true; do
  sec=$(date -u +%-S); min=$(date -u +%-M)
  if (( sec >= 5 && sec <= 20 )) && (( (min + 1) % 5 != 0 )); then break; fi
  sleep 1
done
systemctl --user restart ai-bot-v2-binance-kline-wss-loop.service
sleep 20
systemctl --user is-active ai-bot-v2-binance-kline-wss-loop.service
python3 - <<'PYEOF'
import json, time
p = "/home/wali/Desktop/AI BOT REBUILD/v2/frontend/public/operator_runtime/v2_binance_kline_wss/latest/v2_binance_kline_wss_status.json"
for _ in range(12):
    try:
        d = json.load(open(p))
        if d.get("stream_connected"):
            s = d.get("stats", {})
            print("RECONNECTED streams:", d.get("stream_count"),
                  "| close_events_received counters present:",
                  any(k.startswith("close_events_received_") for k in s))
            break
    except Exception:
        pass
    time.sleep(10)
else:
    print("WARNING: stream not reconnected after 2min - check logs")
PYEOF
echo "DEPLOYED $NEW"
