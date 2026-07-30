#!/usr/bin/env bash
# WQ-R35 deploy (v2): repoint ai-bot-v2-binance-kline-wss-loop to snapshot
# af0276c36c077e43a27a5d6e15b7468da8e6e622 = deployed line 82c7fbfb44
# (ohlcv window adoption) + cherry-pick of receive-stall fix 0cefdcfd5f.
# Supersedes deploy_kline_wss_0cefdcfd5f.sh, which would have reverted the
# window-adoption feature (diverged branch lines; guardian merge 2026-07-26,
# 347/347 kline+window tests pass on the merged commit).
#
# Rollback: restore the drop-in backup written below, daemon-reload, restart.
set -euo pipefail

OLD=82c7fbfb4441e4357b8adc17e0018a0d4c023d55
NEW=af0276c36c077e43a27a5d6e15b7468da8e6e622
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
