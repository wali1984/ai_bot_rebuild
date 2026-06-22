# V2 Realtime User Website — Route × Product Map

This map binds every user/admin route to the **real V2 payloads** that
back it. The wiring rule is simple: a panel renders only if its source
payload exists and is fresh; otherwise the panel renders an explicit
MISSING / STALE chip with the exact source string from the payload.
No mock data ever masquerades as current truth.

## User-facing routes

### `/market` — Market Overview (L0 public)

| Panel | Kind | Source |
|---|---|---|
| TradingView chart | chart | TradingView embed or labeled fallback |
| Binance spot 12h volume top-10 | table | `v2:dashboards:binance_top10:spot_volume_12h` |
| Binance futures 12h volume top-10 | table | `v2:dashboards:binance_top10:futures_volume_12h` |
| Binance spot 12h trades top-10 | table | `v2:dashboards:binance_top10:spot_trades_12h` |
| Binance futures 12h trades top-10 | table | `v2:dashboards:binance_top10:futures_trades_12h` |
| Binance spot 12h volatility top-10 | table | `v2:dashboards:binance_top10:spot_volatility_12h` |
| Binance futures 12h volatility top-10 | table | `v2:dashboards:binance_top10:futures_volatility_12h` |
| Funding / OI movers | panel | `v2:market:funding:{symbol}` + `v2:market:open_interest:{symbol}` |
| Liquidation tape | stream | `v2:market:liquidations:latest:{symbol}` + `:aggregate:{symbol}` |
| Nansen status | provider status | `v2:altdata:nansen:status` (`API_FORBIDDEN_403` → null scores with explicit blocker) |
| LunarCrush status | provider status | `v2:altdata:lunarcrush:status` (same handling) |
| Symbol-universe alt-data ranking | table | `v2:symbol_universe:altdata_candidates` |

### `/bot-intelligence` — Trainer + Signal Explainability (L0 public)

| Panel | Kind | Source |
|---|---|---|
| V2 trainer feed | panel | `v2:trainer:heartbeat` |
| Current predictions per symbol | table | `v2:prediction:{symbol}:1m` |
| Full-observation builder progress | panel | `full_observation_builder_status.json` (state, target_dim, per-symbol generated dim, subfamily counts) |
| Feature missing/stale flags | list | `v2:features:latest:{symbol}:1m` (`missing_feature_flags`, `stale_feature_flags`, `feature_freshness_state`) |
| Checkpoint blocker | warning chip | `paper:intents_held_by_paper_fill_gate[].checkpoint_blocker` |
| Paper-fill gate block reasons | list | `paper:intents_held_by_paper_fill_gate[].paper_fill_gate_block_reasons` |

The page MUST surface `checkpoint_compatibility_claimed=false` and
`policy_architecture_parity_claimed=false` as persistent visible
chips. It MUST display `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
when state is partial. No 1911-dim completion is implied or claimed.

### `/paper` — Paper Trading (L0 public)

| Panel | Kind | Source |
|---|---|---|
| Paper positions | table | `v2:paper:positions` |
| Paper intents | table | `v2:paper:intents` |
| Held-by-gate reasons | list | `v2:paper:intents_held_by_paper_fill_gate` |
| Paper ledger summary | panel | `v2:paper:ledger` |
| Paper PnL running | panel | derived from `v2:paper:position_price_track:{symbol}` (MFE/MAE/ROE when present, explicit MISSING otherwise) |

No live order buttons. The page is labeled "paper / shadow only" in
every header band.

### `/risk` — Risk & Safety (L0 public)

| Panel | Kind | Source |
|---|---|---|
| Live blocker matrix | matrix | governor + soak + remediation status |
| Risk gate status | matrix | `v2:risk:decisions` |
| Strict paper-fill gate | panel | derived from `v2:paper:intents_held_by_paper_fill_gate` |
| Liquidation WSS health | panel | `v2:market:liquidations:heartbeat` |
| Old-Redis / exchange-mutation status | panel | governor scanner output (must show 0 hits) |

The `live_gate=blocked_human_only` chip is sticky at the top of this
page and never dismissible.

### `/automation` — Automation Status (L0 public)

| Panel | Kind | Source |
|---|---|---|
| War-room cycle timeline | timeline | `v2/frontend/public/v2_8h_war_room/latest/operator_dashboard_payload.json` |
| Continuous remediation governor | panel | `codex_5m_status.json` |
| Legacy log observer status | panel | governor summary |
| Legacy↔V2 comparator status | panel | governor summary |
| Codex review queue | table | `codex_review_queue.json` |

## Admin-only routes (RBAC L2+)

| Route | Source |
|---|---|
| `/admin/task-queue` | `claude_worklog/agent_supervisor/tasks/*.json` |
| `/admin/codex-reviews` | `claude_worklog/final_readiness/**/codex_review/CODEX_GO_NO_GO.md` + `codex_review_queue.json` |
| `/admin/raw-payload-explorer` | every `v2:*` Redis key + every `v2/frontend/public/**` payload |
| `/admin/safety-scan` | governor safety-scan outputs |
| `/admin/frontend-truth-builder` | frontend-truth payloads under v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/ |
| `/admin/approval-status` | must show zero active live/canary/legacy-shutdown/Redis-trim approvals |

Admin routes are reachable only through the hidden/protected route
prefix `/admin/...` and require RBAC L2 or higher. No dangerous
control surface appears on user-facing pages.

## Persistent must-show across every page

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `checkpoint_compatibility_claimed = false`
- `policy_architecture_parity_claimed = false`
- `shutdown_status = blocked`
- `full_observation_state = FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` (until target dim 1911 is genuinely present)
- Nansen / LunarCrush `API_FORBIDDEN_403` with per-symbol scores `null` and explicit blocker text — never a fabricated score

## What this packet does NOT do

This packet specifies the contract. It does NOT ship TSX route /
page changes; the frontend wiring follows in a separate packet that
matches each panel to a real payload reader and renders the explicit
MISSING / STALE chip when the payload is absent or older than its
freshness window.
