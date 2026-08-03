# Codex 5.5 Review - Dynamic Symbol + Copied Component Runtime Remediation

**Result: `V2_DYNAMIC_SYMBOL_COPIED_COMPONENT_RUNTIME_REMEDIATION_CODEX_FAIL`**

Claude claimed
`V2_DYNAMIC_SYMBOL_AND_COPIED_COMPONENT_RUNTIME_REMEDIATION_READY`. Codex cannot
clear it. The four previously flagged CLIs now have a dynamic resolver path, but
the active runtime still contains BTC/ETH/SOL and BTC-only production scopes.

## Findings

1. **FAIL - active runtime lanes still use BTC/ETH/SOL without smoke-test
   mode.**
   - `ai-bot-v2-feature-pipeline-native-loop.service` runs
     `v2_feature_pipeline_native_loop` without `--symbols`; that source still
     has `DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")`.
   - `ai-bot-v2-native-ingestors-live-loop.service` runs
     `v2_native_ingestors_live_loop` without `--symbols`; that source still has
     the same 3-symbol default.
   - `ai-bot-v2-rl-core-inference-loop.service` runs
     `v2_rl_core_inference_loop` without `--symbols`; current public runtime
     status still reports `["BTCUSDT", "ETHUSDT", "SOLUSDT"]`.
   - `ai-bot-v2-liquidation-wss-paper-shadow.service` runs
     `v2_liquidation_wss_loop` without a dynamic symbol override.
   - `ai-bot-v2-position-history-persistent-tracker.service` explicitly passes
     `--symbols BTCUSDT,ETHUSDT,SOLUSDT` with no smoke-test flag.

2. **FAIL - BTC-only defaults remain.**
   - `ai-bot-v2-paper-online-runtime.service` runs `paper_online_runtime`
     without `--symbol`; that CLI still defaults to `BTCUSDT`.
   - `ai-bot-v2-feature-snapshot-builder.service` runs
     `v2_feature_snapshot_builder` without `--symbol`; that CLI still defaults
     to `BTCUSDT`.
   - Additional BTC-only defaults remain in CLI files that were not remediated.

3. **FAIL - copied safe ingestors are not all proven persistent.**
   - `copied_component_persistent_runtime_status.json` marks CoinAnk,
     liquidation bridge/levels, and TA worker components persistent even where
     `v2_systemd_active=false`.
   - The GNOME logs show a visible loop, but the loop reruns `--once` commands.
     That is not the same as a reviewed persistent runtime service.
   - CoinAnk evidence still has `v2:market:coinank:* = 0`.

4. **PARTIAL - trainer writes are v2:* but labels are inconsistent.**
   - Active `v2_trainer_bridge` reports `PARITY_BRIDGE`.
   - The remediation packet summary says
     `current_runtime_mode=V2_NATIVE_BASELINE_PAPER_SHADOW`.
   - Copied/bridge-derived trainer evidence must not be called V2-native.

5. **FAIL - website proof is not strong enough.**
   - `website_trading_platform_runtime_status.json` is declarative.
   - Report Center did not include this remediation lane before the Codex fix.
   - The runtime website must expose the active service scope failures and
     copied-component blockers, not just report-lane readiness.

## Verification Matrix

| # | Check | Codex result |
| --- | --- | --- |
| 1 | No BTC-only default remains | FAIL |
| 2 | No BTC/ETH/SOL default remains outside smoke-test | FAIL |
| 3 | Dynamic universe or 25-symbol baseline is default | PARTIAL |
| 4 | Copied safe ingestors persistent, not one-shot | FAIL |
| 5 | Old Redis writes blocked/adapted to v2:* | PASS WITH CAVEAT |
| 6 | Trainer copied mode honest and writes only `v2:prediction:*` | PARTIAL |
| 7 | Website shows trading-platform runtime state | FAIL |
| 8 | GNOME terminals show visible output | PASS WITH CAVEAT |
| 9 | No legacy root runtime restarted | PASS |
| 10 | No live/canary/order/leverage/margin endpoint | PASS |
| 11 | No old Redis writes | PARTIAL |
| 12 | `LIVE_GATE=blocked_human_only` | PASS |
| 13 | `live_symbols=[]` | PASS |

## Safety State

- `LIVE_GATE`: `blocked_human_only`
- `live_symbols`: `[]`
- `orchestrator:*`: `0`
- `live_orders:*`: `0`
- `exchange:order:*`: `0`
- `order:*`: `0`
- `*leverage*`: `0`
- `*margin*`: `0`
- No legacy root runtime process observed.
- No Codex live/canary/order/shutdown approval.
- No Redis trim/delete.

## Required Remediation

1. Patch every active runtime entrypoint to use the central dynamic resolver
   with the 25-symbol baseline minimum.
2. Require explicit `--smoke-test` for every BTC/ETH/SOL path.
3. Remove BTC-only production defaults or require explicit per-run `--symbol`.
4. Replace recurring `--once` GNOME loops with reviewed persistent units, or
   classify the copied component blocked.
5. Make the website/Report Center show active service symbol scopes,
   missing runtime components, and copied-component blockers.
6. Keep copied/bridge trainer modes labelled as bridge/copied, never V2-native.

Until those are fixed and rerun:
**`V2_DYNAMIC_SYMBOL_COPIED_COMPONENT_RUNTIME_REMEDIATION_CODEX_FAIL`**.
