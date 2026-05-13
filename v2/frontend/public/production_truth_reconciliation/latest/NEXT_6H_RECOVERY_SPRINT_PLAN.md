# Next 6h Recovery Sprint Plan

Generated: 2026-05-13T04:43:38.228869Z

## 1. Fix website current signals/predictions/executions display

- Objective: Make Mission Control, Trainer Monitor, Signal Explainability, Signals, and Executions show current pred/fs/sig/risk/intent IDs first.
- Files/artifacts: frontend route components, operator runtime payload readers, website_current_data_matrix.json
- Expected runtime proof: Browser crawl shows current IDs on local and public routes with no static fixture primary.
- Codex audit: website current-data truth audit
- GUI output: current lineage cards and explicit missing evidence
- Live impact: prevents operator from approving based on stale proof

## 2. Convert P0/P1 migration backlog into actual V2 wrappers/ports

- Objective: Move highest-risk legacy execution/risk/trainer dependencies from backlog to V2 wrappers or ports.
- Files/artifacts: script_migration_backlog.json, V2 adapter modules, tests
- Expected runtime proof: P0/P1 counts move from backlog_not_migrated/unknown to wrapper or migrated classifications.
- Codex audit: script migration coverage audit
- GUI output: Script Registry migration status by priority
- Live impact: reduces dependency on legacy live stack

## 3. Produce 6h/24h paper-shadow result summary

- Objective: Turn current paper ticks into a durable result window.
- Files/artifacts: paper ledger rollup, paper_shadow_results.json
- Expected runtime proof: counts, PnL, blocks/allows, fees/slippage over 6h/24h.
- Codex audit: paper runtime truth audit
- GUI output: Paper Trading performance rollup
- Live impact: avoids treating alive runtime as profitability proof

## 4. Expand legacy-vs-V2 comparison for live recent events

- Objective: Compare recent legacy executions to V2 shadow risk decisions.
- Files/artifacts: legacy bridge payload, shadow comparison report
- Expected runtime proof: legacy would-do vs V2 did/block reasons for recent events.
- Codex audit: legacy bridge read-only audit
- GUI output: Legacy Comparison panel
- Live impact: proves V2 prevents specific old failure modes

## 5. Build Admin AI answers from current runtime data

- Objective: Admin AI should answer from runtime payloads, not proof archive.
- Files/artifacts: Admin AI read-only data provider, current payload contracts
- Expected runtime proof: query returns latest IDs and blockers with sources.
- Codex audit: Admin AI no-live-side-effects audit
- GUI output: read-only operator query answers
- Live impact: reduces manual misinterpretation

## 6. Continue risk gateway runtime tests

- Objective: Cover weekly loss/account/trade-permission and durable dedupe/stop gates.
- Files/artifacts: risk tests, hard gate checklist
- Expected runtime proof: missing evidence items converted to PASS or explicit blocker.
- Codex audit: risk fail-closed audit
- GUI output: Risk Control gate matrix
- Live impact: required before tiny canary consideration

## 7. Continue trainer parity/safe bridge

- Objective: Prove or clearly reject parity between legacy PPO/MASA path and V2 wrapper.
- Files/artifacts: trainer bridge status, feature snapshots, parity tests
- Expected runtime proof: current legacy prediction mapped to V2 feature snapshot or explicit mismatch.
- Codex audit: trainer parity truth audit
- GUI output: Trainer Monitor parity board
- Live impact: prevents canary based on wrong model assumptions

## 8. Keep live approval blocked unless tiny canary checklist is green

- Objective: Final live gate remains human-only.
- Files/artifacts: final gate checklist, approval packet, approval token absence check
- Expected runtime proof: approval token absent and no exchange mutations.
- Codex audit: final no-live-side-effects audit
- GUI output: Live Readiness hard gate
- Live impact: prevents accidental live activation
