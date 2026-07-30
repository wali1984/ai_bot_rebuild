# CG-F049 / CG-F050 Independent Runtime Re-Validation — 2026-07-21

Guardian lane, read-only. Re-run of WQ-R34 per gating_next_step item 3.
Verifier context: stop-hook run 2026-07-21T16:06:34Z (10/16 gates, G03/G10/G11/G12/G13/G14 red).

## Result: SAMPLE-STARVED (cannot confirm or refute fix efficacy)

The 2026-07-17 validation was NEGATIVE because the running PID predated the fix.
That dependency has since CLEARED — but zero new outcomes exist to validate against.

## Raw evidence

1. **Restart dependency (WQ-R34 gating step 2) is DONE.**
   - Running loop: PID 1816509, started `Sat Jul 18 20:45:20 EDT` = **2026-07-19T00:45:20Z**
     (`ps -o lstart= -p 1816509`). Replaces PID 2215061 (started 2026-07-17T16:00:26Z) cited in WQ-R34.
   - CG-F049/F050 fixes were applied to the working tree before WQ-R34 creation (2026-07-18T01:29Z),
     i.e. before this restart → the running loop **contains the fixes**.
   - Note: further trainer-lane edits landed Jul 20 07:39–09:45 EDT (paper loop + allocator mtimes,
     both still uncommitted `M` on codex/pipeline-trust-refresh) — those are NOT in the running PID.

2. **Zero post-restart samples.**
   - `v2:paper:closed_trades` (string key, 92 rows): rows with entry ts > 2026-07-19T00:45:20Z = **0**;
     rows with exit ts > cutoff = **0**. Latest close: 2026-07-17T22:48:28.020Z (TUSDT).
   - Open positions: 0 (`v2:paper:positions`). `v2:paper:session.generated_utc` = 2026-07-13T19:09:04Z.
   - Therefore the 46 G10 invariant violations are all pre-restart history; no new-close coherence
     evidence can exist yet, and L/S rebalance (F049) cannot be observed.

3. **Starvation root cause pinned (trainer-lane authenticated-sample chain incomplete → CG-F054).**
   - `ai-bot-v2-native-cuda-trainer-persistent.service` ACTIVE since 2026-07-21 11:25:33 EDT as
     "Authenticated-Sample Waiting Observer": `--mode waiting-for-authenticated-samples`,
     `--trusted-cost-store-root ~/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/profiled-training-enrichment-cas`,
     deployment-pinned to SHA 0f9b5c93b7 with ExecStartPre git-diff integrity check, StandardOutput=null.
   - The watched CAS path **does not exist**. Parent dir contains only: atomic-capture-cas,
     capture-set-cas, profiled-model-evidence-cas, repair-receipts (ls 2026-07-21).
   - Producer `v2_profiled_base_feature_publisher`: **not running** (pgrep empty), **no systemd unit**
     (`list-unit-files 'ai-bot-v2*' | grep -c profiled` = 0). Last activity 2026-07-21T09:43:50Z
     (`profiled_base_publisher_state_v1.json`): cycle_count=3, coverage=2 symbols
     (1000BONKUSDT, 1000FLOKIUSDT). Bounded/manual morning run; writer lock left behind (05:42 EDT).
   - `v2:trainer:hybrid_cuda:status` and `:metrics` = type none (MISSING); the legacy hybrid trainer
     loop was replaced by the observer, so nothing publishes routable predictions.
   - `v2:trainer:preemptive_blocked_candidates` IS fresh (2026-07-21T16:08Z) — counterfactual stream alive.
   - Durable ledger `durable_feature_snapshot_ledger.sqlite3` last write 2026-07-21T09:43Z.

## Lane boundary

The observer-mode reconfiguration is deliberate trainer-lane (Codex) migration work
(unit drop-in + SHA pin + integrity gate). Guardian does NOT restart/modify it
(change protocol: trainer changes require approval). Documented as CG-F054 instead.

## Gate impact

- G03: CG-F049/F050 remain FIX_APPLIED_PENDING_INDEPENDENT_RUNTIME_VALIDATION (now sample-starved,
  no longer stale-PID). CG-F051/F052 Codex lane; CG-F053 trainer edge — unchanged.
- G10: 46 historical violations need operator-authorized `tools/g10_capital_invariant_repair.py`;
  new coherent closes impossible until CG-F054 resolves.
- G13/G14: cannot move without new trades → blocked on CG-F054 then CG-F053.
- G11: downstream of G10 + edge; re-running the sweep now would reproduce FAIL (no new data since 07-17).

## Verification commands

```
ps -o lstart= -p 1816509
.venv/bin/python3 - <<'EOF'  # post-restart sample count
import json, redis; r=redis.Redis(decode_responses=True)
rows=json.loads(r.get('v2:paper:closed_trades')); CUT='2026-07-19T00:45:20'
print(len(rows), sum(1 for x in rows if (x.get('exit_price_utc') or '')>CUT))
EOF
systemctl --user show ai-bot-v2-native-cuda-trainer-persistent -p ExecStart -p ActiveEnterTimestamp
ls ~/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/
systemctl --user list-unit-files 'ai-bot-v2*' | grep -c profiled
```
