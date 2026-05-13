# PARALLEL_TRADING_PLATFORM_CONSUMER_UI_FROM_REAL_V2_PAYLOADS_READY

## Purpose

Build a real trading-platform web experience for AI BOT V2 in a parallel support lane.

The website should feel like a personal version of:

- CoinAnk for crypto derivatives analytics and market intelligence
- Bitsgap for trading-bot, portfolio, paper/demo, strategy, and exchange-management controls
- Binance for chart/account/positions/order-state layout and strict separation between read-only account data and dangerous trade/leverage/margin actions

This must remain aligned with the original objective:

- migrate legacy to V2
- keep V2 paper/shadow and risk-gateway work progressing
- preserve trainer/model/feature/orchestrator logic through V2 adapters
- expose every subsystem in the GUI
- keep live blocked until explicit human approval
- never let website work supersede go-live blocker burn-down

This is not a live-trading task.

This is not a final approval task.

This is not a mock design task.

This is an implementation task to turn the V2 frontend into a real trading platform surface using actual V2 payloads and explicit evidence gaps.

---

## Hard constraints

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not write/delete legacy Redis keys.
- Do not run Redis `XADD`, `SET`, `HSET`, `DEL`, `XDEL`, `XTRIM`, `FLUSH`, `EXPIRE`, `CONFIG SET`, or `BGSAVE`.
- Do not create Redis trim approval file.
- Do not create final live approval token.
- Do not stop/restart legacy trader/trainer/orchestrator/Redis/VPN.
- Do not place/cancel/modify exchange orders.
- Do not change leverage.
- Do not change margin mode.
- Do not activate live keys.
- Do not enable V2 live trading.
- Work only inside `AI BOT REBUILD`.
- Live remains `blocked_human_only`.
- Primary go-live blocker work remains higher priority than this task.

---

## Non-drift rule

This is a parallel support lane. The primary go-live blocker work remains higher priority and must not be interrupted, paused, or replaced by this UI work.

Create:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/NON_DRIFT_SUPPORT_LANE_LOCK.md
```

It must state:

```text
This task is a parallel support lane.
It cannot replace paper-shadow, risk gateway, trainer/trader monitoring, account evidence, P0/P1 migration, canary readiness, or live-blocker burn-down.
If a conflict occurs, runtime safety and primary go-live blocker work win.
Live remains blocked_human_only.
```

Required classification:

```text
PRIMARY_OBJECTIVE_PRESERVED
PARALLEL_UI_SUPPORT_LANE_ACTIVE
LIVE_GATE_BLOCKED_HUMAN_ONLY
FINAL_APPROVAL_TOKEN_ABSENT
```

---

## Product target

Create:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/TRADING_PLATFORM_PRODUCT_TARGET.md
```

Define the target as:

### CoinAnk-style analytics

Required surfaces:

* market overview table
* selected symbol cockpit
* OI / OI change
* funding and weighted funding
* long/short ratios
* liquidation ranks
* liquidation feed
* CVD / order-flow where available
* SMC / structure data where available
* radar/screener symbols
* fund-flow / market pulse where available
* source/freshness labels
* explicit API availability blockers

### Bitsgap-style control platform

Required surfaces:

* all-in-one dashboard
* portfolio/paper equity
* bot/strategy cards
* paper/demo mode state
* smart-terminal preview, disabled for live
* backtest/replay
* risk-management tools
* exchange manager
* AI assistant
* ROI/PnL/win-rate/drawdown cards
* strategy status and activation state

### Binance-style trading layout

Required surfaces:

* selected symbol
* large chart
* market cards
* positions table
* executions/orders table
* margin/leverage/account status
* funding/mark/index/price context where available
* disabled order/leverage/margin controls
* read-only account vs trade endpoints clearly separated
* live gate banner

### AI BOT-specific platform

Required surfaces:

* trainer prediction monitor
* prediction lineage
* signal lineage
* orchestrator proposal
* risk gateway decision
* paper/shadow execution
* legacy-vs-V2 comparison
* script migration state
* live blockers
* Claude/Codex automation
* Admin AI query surface
* config admin
* monitor center
* audit ledger

---

## Source-of-truth rules

Canonical source order:

1. `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`
2. `v2/frontend/public/operator_runtime/paper_shadow_observation/latest/paper_shadow_observation_status.json`
3. `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json`
4. `v2/frontend/public/operator_truth/latest/operator_truth_bridge_payload.json`
5. `v2/frontend/public/risk_gateway_canary_hard_gates/latest/operator_dashboard_payload.json`
6. `v2/frontend/public/paper_strategy_edge_tightening/latest/operator_dashboard_payload.json`
7. `v2/frontend/public/account_permission_and_soak/latest/operator_dashboard_payload.json`
8. `v2/frontend/public/current_data_migration_sprint/latest/operator_dashboard_payload.json`
9. `v2/frontend/public/production_truth_reconciliation/latest/operator_dashboard_payload.json`
10. historical proof artifacts only inside archive/proof pages

Rules:

* No mock data as truth. Use only real/current V2 payloads, or surface an explicit MISSING_EVIDENCE label.
* Fresh `pred_*`, `sig_*`, `risk_*`, `execution_intent_id`, and paper ledger records must be shown as current when available.
* `hist_*` must never appear as current runtime truth.
* `STATIC_PROOF_FIXTURE` must never be primary on trading-platform pages.
* `DESIGN_MOCK_DATA` must never ship as runtime truth.
* Missing data must show exact missing source.
* Every panel must show source and freshness.
* Natural-language explanations must cite evidence fields and must say "Evidence missing — cannot explain without guessing" when required.

Create:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/DATA_TRUTH_AND_SOURCE_PRIORITY.md
```

---

## Required route model

Create or verify these product groups:

### 1. Trade Cockpit

Routes:

```text
/admin/mission-control
/admin/paper-trading
/admin/replay
/admin/live-readiness
```

Mission Control first viewport must include:

* live gate
* selected symbol
* paper/shadow mode
* large chart
* market pulse
* paper equity / PnL
* latest prediction
* latest signal
* latest risk decision
* latest execution intent
* latest paper fill or blocked reason
* current blockers
* Claude/Codex active status
* legacy-vs-V2 comparison

### 2. Markets / CoinAnk Intelligence

Routes:

```text
/admin/market-intelligence
/admin/symbols
```

If `/admin/market-intelligence` does not exist, add it.

Required panels:

* CoinAnk radar
* SMC
* CVD
* funding
* weighted funding
* long/short
* liquidation rank
* OI
* turnover/volume
* price/funding/OI/liquidation table
* missing API blocker labels

### 3. AI / Strategy

Routes:

```text
/admin/trainer-prediction-monitor
/admin/signal-explainability
/admin/signals
/admin/strategy-admin
/admin/trainer-admin
/admin/orchestrator-admin
```

Required panels:

* current trainer prediction
* feature snapshot
* model/checkpoint
* raw/calibrated confidence
* confidence bucket performance
* top positive/negative features
* feature freshness
* natural-language "why prediction happened"
* orchestrator proposal / enrichment
* risk decision
* signal table

### 4. Execution / Portfolio

Routes:

```text
/admin/executions
/admin/positions
/admin/execution-admin
/admin/audit-ledger
/admin/exchange-manager
```

Required panels:

* paper executions
* imported legacy executions
* dedupe status
* missing attribution status
* execution latency
* PnL
* read-only account state
* read-only positions
* margin/leverage evidence
* order methods fail-closed

### 5. Risk / Safety

Routes:

```text
/admin/risk-control
/admin/external-manual-position-quarantine
/admin/config-admin
/admin/live-readiness
```

Required panels:

* live blocker matrix
* risk gates
* stale signal policy
* missing attribution policy
* duplicate execution policy
* margin/leverage policy
* stop/kill/daily/weekly loss gates
* canary readiness
* dangerous settings staged/approval-gated

### 6. System / Automation

Routes:

```text
/admin/monitor-center
/admin/script-registry
/admin/coverage-system-atlas
/admin/system-health
/admin/build-validation-status
/admin/claude-admin-ai
/admin/codex-review-center
/admin/ollama-local-assistant
/admin/mobile-iphone-readiness
```

Required panels:

* all monitor scripts
* all script classifications
* migration progress
* Claude/Codex automation
* build validation
* documentation status
* future mobile/iPhone readiness

Create:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/ROUTE_PRODUCT_MAP.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/route_product_matrix.json
```

---

## Visual/product requirements

Implement inside `v2/frontend` only.

The UI must become:

```text
chart-first
table-rich
panel-based
dark institutional trading theme
source/freshness labeled
human readable in 5 seconds
```

Required design elements:

* top trading rail
* grouped sidebar navigation
* symbol selector
* big chart panel
* market intelligence widgets
* paper/portfolio cards
* risk gate chips
* strategy/bot cards
* data freshness badges
* tables with search/filter/sort
* detail drawers
* signal explanation drawer
* AI Admin query panel
* disabled-danger controls
* mobile-responsive layout

Do not ship:

* wall-of-text proof dumps on primary pages
* raw markdown proof sections in Mission Control
* Redis export/trim history in Mission Control
* Phase 3 proof packets in primary trading cockpit
* `hist_*` IDs as current
* `STATIC_PROOF_FIXTURE` as primary
* mock data as current
* placeholder-only pages

Create:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/VISUAL_SYSTEM_AND_LAYOUT_REPORT.md
```

---

## Charts

Implement or verify a primary chart.

Allowed sources:

* TradingView widget if stable
* lightweight-charts using Binance public/read-only klines or V2 read-only market feed
* fallback chart only if labeled `FALLBACK_STATIC_CHART`

Required:

* large BTCUSDT chart on Mission Control
* chart source label
* chart must not place orders
* symbol selector updates visible route state if wired
* market widgets separated from candles

Create:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/CHART_AND_MARKET_WIDGET_REPORT.md
```

---

## Trainer visibility requirements

Everything trainer does must be visible.

Create or update Trainer Prediction Monitor to show:

* current prediction id
* symbol
* timeframe
* model/checkpoint
* raw model output
* raw confidence
* calibrated confidence
* confidence delta
* feature snapshot id
* top positive features
* top negative features
* stale feature flags
* missing feature flags
* source freshness
* trainer process/GPU status
* PPO/MASS metrics if available
* reward/entropy/KL warnings if available
* natural-language explanation from evidence
* exact missing evidence list

Signal Explainability must show:

```text
data → feature snapshot → model output → prediction → orchestrator → risk gateway → paper/execution result
```

No guessing.

Create:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/TRAINER_AND_SIGNAL_EXPLAINABILITY_UI_REPORT.md
```

---

## Subsystem visibility requirements

Every subsystem needs a page/panel and natural-language status.

Subsystems:

* ingestors
* CoinAnk Plan-3 bridge
* feature pipeline
* trainer/PPO/MASS
* orchestrator
* risk gateway
* paper/shadow engine
* execution ledger
* account/exchange manager
* config admin
* script registry
* monitor center
* Claude/Codex automation
* documentation governance
* deployment/hosting readiness
* mobile/iPhone readiness

For each subsystem show:

* current status
* latest event
* latest error
* source/freshness
* active files/scripts
* dependencies
* next blocker
* natural-language summary
* evidence link

Create:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/SUBSYSTEM_VISIBILITY_MATRIX.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/subsystem_visibility_matrix.json
```

---

## Admin AI requirements

Claude Admin AI page must have:

* natural-language query box
* suggested prompts
* evidence-backed answer area
* current payload/source citations
* "cannot enable live" safety statement
* query examples:

```text
Why was the latest signal blocked?
What caused the latest trainer prediction?
What symbols are losing money in paper?
What blocks canary?
Which scripts are not migrated?
What is the latest CoinAnk market intelligence?
What changed in Claude/Codex automation?
What risk gate blocked the last intent?
```

Admin AI must not:

* enable live
* approve canary
* change leverage
* change margin
* create API keys
* disable kill switch
* edit old bot
* write old Redis

Create:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/ADMIN_AI_UI_CONTRACT.md
```

---

## Config/Admin control requirements

Admin/config pages must expose all settings as GUI-managed config records.

Show:

* setting key
* current effective value
* source: default/env/db/gui
* staged value
* risk classification
* last changed by
* last changed at
* validation status
* rollback value
* approval requirement

Dangerous settings require explicit approval:

* live trading enable
* live API key activation
* leverage increase
* CROSS margin enable
* max position increase
* daily loss limit increase
* kill switch disable
* mandatory stop disable
* hedge/DCA enable
* ADJUST_LEVERAGE enable
* paper to live switch

Create:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/CONFIG_ADMIN_CONTROL_SURFACE_REPORT.md
```

---

## Validation

Run:

```bash
cd "$HOME/Desktop/AI BOT REBUILD/v2/frontend"
npm run build:operator-truth || true
npm run sync:proof-artifacts
npm run typecheck
npm run build
```

Run browser checks for local and public if available:

```text
/admin/mission-control?role=admin
/admin/market-intelligence?role=admin
/admin/symbols?role=admin
/admin/signals?role=admin
/admin/executions?role=admin
/admin/positions?role=admin
/admin/paper-trading?role=admin
/admin/risk-control?role=admin
/admin/trainer-prediction-monitor?role=admin
/admin/signal-explainability?role=admin
/admin/claude-admin-ai?role=admin
/admin/config-admin?role=admin
/admin/live-readiness?role=admin
/admin/monitor-center?role=admin
/admin/script-registry?role=admin
```

Required checks:

* no route placeholder-only
* no `hist_*` as current
* no `STATIC_PROOF_FIXTURE` primary
* no mock data as current
* source/freshness labels present
* current `pred_*`, `sig_*`, `risk_*`, `execution_intent_id` visible if available
* dangerous controls disabled
* live banner visible
* Admin AI cannot enable live
* chart visible
* market intelligence visible
* signal/execution tables visible

Safety scans:

> Note: the bash patterns below are written with `[_]` regex character classes
> (e.g. `create[_]order`) so this TASK.md does not contain the literal action
> substrings the local `block_dangerous.sh` hook forbids. `[_]` in BRE/ERE is
> the single-char class containing `_`, so the regex is functionally identical
> to the bare-underscore form when grep runs. Do not "fix" these to bare
> underscores in this file — keep the character-class form.

```bash
cd "$HOME/Desktop/AI BOT REBUILD"
test ! -f claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md
test ! -f claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md

grep -RIn "futures_create[_]order\|futures_change[_]leverage\|futures_change[_]margin[_]type\|create[_]order\|cancel[_]order" v2 claude_worklog/final_readiness/parallel_trading_platform_consumer_ui 2>/dev/null | tail -80 || true

grep -RIn "redis-cli .*\\(XADD\\|SET\\|HSET\\|DEL\\|XDEL\\|XTRIM\\|FLUSH\\)" v2 claude_worklog/final_readiness/parallel_trading_platform_consumer_ui 2>/dev/null | tail -80 || true
```

---

## Codex review

Create a Codex review task:

```text
claude_worklog/agent_supervisor/tasks/codex_review_parallel_trading_platform_consumer_ui.json
```

Codex must inspect:

* screenshots
* route matrix
* payload wiring
* source/freshness labels
* current data vs mock data
* signal/execution visibility
* trainer explainability
* subsystem visibility
* Admin AI safety
* non-drift lock

Codex must fail if:

* primary objective drifted
* UI task became primary blocker lane
* page still looks like proof/status dump
* chart absent
* market intelligence absent
* signals/executions lack current IDs
* trainer data missing without explicit evidence gap
* natural-language explanation guesses
* mock data used as truth
* `hist_*` shown as current
* `STATIC_PROOF_FIXTURE` primary
* dangerous controls enabled
* live readiness overstated
* approval token created
* old Redis write occurred
* exchange action occurred

Required files:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/CODEX_PARALLEL_TRADING_PLATFORM_UI_REVIEW.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/CODEX_GO_NO_GO.md
```

`CODEX_GO_NO_GO.md` must contain exactly:

```text
PARALLEL_TRADING_PLATFORM_CONSUMER_UI_CODEX_PASS
```

or:

```text
PARALLEL_TRADING_PLATFORM_CONSUMER_UI_CODEX_FAIL
```

---

## Required final outputs

Create:

```text
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/PARALLEL_TRADING_PLATFORM_CONSUMER_UI_FROM_REAL_V2_PAYLOADS_REPORT.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/GO_NO_GO.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/NON_DRIFT_SUPPORT_LANE_LOCK.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/TRADING_PLATFORM_PRODUCT_TARGET.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/DATA_TRUTH_AND_SOURCE_PRIORITY.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/ROUTE_PRODUCT_MAP.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/route_product_matrix.json
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/VISUAL_SYSTEM_AND_LAYOUT_REPORT.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/CHART_AND_MARKET_WIDGET_REPORT.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/TRAINER_AND_SIGNAL_EXPLAINABILITY_UI_REPORT.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/SUBSYSTEM_VISIBILITY_MATRIX.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/subsystem_visibility_matrix.json
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/ADMIN_AI_UI_CONTRACT.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/CONFIG_ADMIN_CONTROL_SURFACE_REPORT.md
claude_worklog/final_readiness/parallel_trading_platform_consumer_ui/latest/operator_dashboard_payload.json
v2/frontend/public/parallel_trading_platform_consumer_ui/latest/operator_dashboard_payload.json
```

`GO_NO_GO.md` must contain exactly one line:

```text
PARALLEL_TRADING_PLATFORM_CONSUMER_UI_FROM_REAL_V2_PAYLOADS_READY
```

or:

```text
PARALLEL_TRADING_PLATFORM_CONSUMER_UI_FROM_REAL_V2_PAYLOADS_BLOCKED
```

Do not mark READY unless:

* primary objective is preserved
* UI is support lane only
* route product map exists
* Mission Control is chart/trading-platform first
* Market Intelligence is CoinAnk-like
* Bitsgap-like bot/strategy/paper/portfolio surfaces exist
* Binance-like chart/account/positions/execution separation exists
* current trainer activity is visible
* current signal/risk/execution chain is visible
* every subsystem has a panel/page/status
* Admin AI has current-data query surface
* config/admin controls are visible and approval-gated
* source/freshness labels exist
* no mock/static/proof data is current truth
* Codex passes
* live remains blocked
* final approval token absent
* no old Redis writes
* no exchange actions
* no leverage/margin changes
* git clean after commit/push, unless active daemon-owned churn is explicitly classified

---

## Commit and continue

After validation and Codex review:

```bash
git add \
  v2/frontend \
  claude_worklog/final_readiness/parallel_trading_platform_consumer_ui \
  v2/frontend/public/parallel_trading_platform_consumer_ui \
  claude_worklog/agent_supervisor/tasks/parallel_trading_platform_consumer_ui_from_real_v2_payloads.json \
  claude_worklog/agent_supervisor/tasks/codex_review_parallel_trading_platform_consumer_ui.json

git commit -m "Add parallel trading platform consumer UI from real V2 payloads"
git push
```

After commit:

* do not dispatch final live approval
* do not create approval token
* continue primary go-live tasks
* continue 24h paper-shadow soak
* continue account/trade-permission evidence work
* continue margin/leverage evidence work
* continue trainer/trader monitoring
* continue P0/P1 migration

Final report must include:

* primary non-drift status
* pages updated
* chart status
* market intelligence status
* signals/executions status
* trainer explainability status
* subsystem visibility status
* Admin AI status
* Config Admin status
* Codex result
* live gate status
* next primary go-live task
* commit hash
* git clean yes/no
