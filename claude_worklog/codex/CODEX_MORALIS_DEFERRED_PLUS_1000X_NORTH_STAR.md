# CODEX HANDOFF — 1000x North Star + Moralis feature bridge (DEFERRED: do LAST)

Author: Claude main session (read-only audit lane; did NOT edit Codex code)
Date: 2026-07-19
Guardrails (unchanged): paper/shadow only · live_gate blocked_human_only · never A+/never real-trading ·
PIT-safe · keep Moralis CU within the 2M/month budget.

## READ FIRST — priority, sequencing, and what "done" means

**North star: 1000x equity growth in ~90 days.** Per CLAUDE.md this is a *research objective*, not a
promise, and the priority order is: survival → liquidation avoidance → auditability → positive expectancy
→ controlled drawdown → high-quality signal → compounding only after evidence. Keep this in view on every
slice: the point of each fix is to move the system toward that objective, honestly.

**The single most important thing right now is to BRING THE SYSTEM ONLINE** — i.e., get the paper loop
actually *trading fresh, coherent, positive-EV closes* again. Today it is candidate-starved
(`intents_accepted=0`), so it produces no new closes, so it learns nothing, so it makes zero progress
toward 1000x. Restoring the trading flywheel is THE unblock.

**Paper trading is the TEST HARNESS, not the goal.** It exists so the system can *self-tune* — learn from
real closed outcomes and adapt its gates, sizing, edge model, and calibration — and iterate toward the
actual objective. A stalled loop = no learning = no compounding. So the win condition for the current work
is not "gates green on frozen data," it is "the loop is online, trading, and self-improving on fresh
evidence." Getting there is what unlocks 1000x; everything else is scaffolding.

**Therefore: finish ALL current blockers first. Moralis is explicitly the LAST item — do not start it
until the system is online and the current issues are closed.** Moralis is an enhancement (extra on-chain
signal); it cannot help a system that is not trading.

## DO THESE FIRST (the critical path — already documented; do not re-scope)
In priority order, to get online + self-tuning:
1. **Trainer provenance receipts** (446 slots / 1,784 inputs) → then release the 5 fail-closed services and
   swap the v1 feature worker, one verified slice at a time. (Keystone — gates the cascade.)
2. **Restore candidate supply** (exploration generator emitting again + trainer A-grade) so the loop TRADES
   and self-tuning resumes. This is what "bring the system online" means concretely.
3. **Land the two leverage safety fixes** — `dynamic_envelope.py:182` must intersect caps
   (`min(symbol, global, configured, dynamic, liquidation_safe)`), not select the symbol ceiling; and scale
   dynamic leverage with the edge lower-bound magnitude. Fix the 1 red lifecycle test, commit the allocator
   rework.
4. Then G10/G13/G14 recover on FRESH closes; operator runs `tools/g10_capital_invariant_repair.py` for the
   46 historical rows.
Refs: `CODEX_BLOCKER_AUDIT_AND_UNBLOCK_ANALYSIS_2026_07_19.md`,
`CODEX_CANDIDATE_SUPPLY_STARVATION_CRITICAL_PATH.md`, `CODEX_PPO_ON_POLICY_STARVATION_FINDING.md`,
`CODEX_PER_SYMBOL_LEVERAGE_ENVELOPE_HANDOFF.md`.

Only when the system is online and trading fresh coherent closes, proceed to Moralis below.

---

## ONLY AFTER THE ABOVE — Moralis feature bridge (paid subscription producing ~0 value)

### Diagnosis (read-only evidence, 2026-07-19)
Not a subscription/key problem. Verified: `MORALIS_API_KEY` set; `plan: starter`, `monthly_budget:
2,000,000` CU; `backoff active: False`, `consecutive_failures: 0`; provider loop service running and
fetching real raw data for a hardcoded UNI/LINK/WBTC (`v2:moralis:swaps|token_transfers|token_holders|
token_price:eth:0x...`) plus `v2:smart_money:signals:BTCUSDT` and `v2:provider:moralis:symbol_score:BTCUSDT`.

The break is the **feature bridge**: `v2:provider:moralis:feature_bridge_status` shows
`feature_bridge_ready: False`, `feature_count: 0`, `actual_payload_present: False`, `missing_mask_true: True`.
Every trainer-facing Moralis feature is MISSING, so the wired consumers
(`masa_consumption/ppo_consumption/allocator_consumption/paper_consumption/orchestrator_consumption = True`)
all receive the missing-mask → **Moralis contributes ZERO to training** despite the loop being fully plumbed
for it (`native_trainer/dataset_builder.py` + `hybrid_cuda_trainer/data_loader.py` read
`v2:features:moralis:{symbol}:{tf}`; only `...:BTCUSDT:1m` exists, with feature_count 0).

### The 15 missing feature flags the trainer expects (must be produced per `v2:features:moralis:{symbol}:{tf}`)
- moralis_whale_buy_usd, moralis_whale_sell_usd, moralis_whale_net_flow_usd
- moralis_exchange_inflow_usd, moralis_exchange_outflow_usd, moralis_net_exchange_flow_usd
- moralis_dex_buy_pressure_usd, moralis_dex_sell_pressure_usd, moralis_dex_flow_imbalance_usd
- moralis_smart_wallet_accumulation_score, moralis_smart_wallet_distribution_score
- moralis_top_holder_concentration, moralis_holder_count, moralis_holder_delta, moralis_onchain_risk_score

### Two gaps to close
1. **Token map / watchlist coverage** — map traded symbols → on-chain contract addresses for the majors +
   liquid alts that have genuine on-chain presence. Currently only 3 hardcoded ETH tokens are fetched.
   **HONEST CAVEAT:** Moralis is on-chain / ERC-20; predictive fit is real for alts with actual on-chain
   accumulation, but weak/proxy for BTC-perp (WBTC ≠ native BTC, and Moralis-ETH has no native BTC flow).
   Do NOT force every perp to a token address — spend CU only where there is genuine on-chain signal, so the
   2M/month budget buys signal, not noise.
2. **Feature bridge** — compute the 15 features above from the raw swaps/transfers/holders payloads and
   publish `v2:features:moralis:{symbol}:{tf}` **with PIT/finality receipts** (same provenance contract as
   the trainer keystone above — no unsafe snapshots; decision-time-safe cutoffs).

### Acceptance
- `feature_bridge_ready: True`, `feature_count > 0`, `missing_mask_true: False` for covered symbols.
- Wired consumers show NON-masked Moralis features (trainer/PPO/allocator/paper/orchestrator).
- CU spend stays within the 2M/month budget; no backoff.
- Covered symbols are only those with real on-chain signal (per the caveat) — auditable token-map.

### Files (Codex lane — already in-flight)
`smart_money_wallets/moralis_feature_bridge.py`, `smart_money_wallets/publisher.py`, + the token-map source.
Spec context: `claude_worklog/codex/V2_MORALIS_WATCHLIST_TOKEN_MAP_AND_SMART_WALLET_BOOTSTRAP_GOAL.md`.

## Not in my lane
Claude will not edit the Moralis bridge / trainer / allocator (Codex-owned + protected runtime). Claude will
re-validate read-only once Codex lands each slice and reports it. The frontend already shows Moralis honestly
as degraded — no frontend change needed until real features flow.
