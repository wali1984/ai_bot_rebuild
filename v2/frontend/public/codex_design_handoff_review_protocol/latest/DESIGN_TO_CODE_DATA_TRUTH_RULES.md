# Design-To-Code Data Truth Rules

Claude Design may define layout, visual hierarchy, interaction model, mobile behavior, and implementation notes. It cannot decide whether runtime data is true, whether a signal is valid, whether the system is live-ready, or whether a trade is safe.

## Source-Of-Truth Labels

- `READONLY_MARKET_FEED`: read-only market feed data.
- `READONLY_ACCOUNT_FEED`: read-only account data.
- `STATIC_PROOF_FIXTURE`: static proof fixture, replay fixture, or local fallback chart.
- `V2_PROOF_ARTIFACT`: final-readiness or proof artifact produced by V2 tooling.
- `RUNTIME_MONITOR_PAYLOAD`: runtime monitor packet or carried-forward runtime evidence.
- `MISSING_EVIDENCE`: required evidence is absent.
- `DESIGN_MOCK_DATA_TO_REMOVE`: prototype or mock data that cannot ship as runtime truth.

## Required Missing-Evidence Text

Missing data must show:

`Evidence missing - cannot explain without guessing.`

## Forbidden Upgrades

Codex must fail a design-to-code review if implementation upgrades mock, stale, fixture, or missing evidence into apparent live runtime truth.

## Safety Doctrine

V2 artifacts, runtime monitor payloads, read-only market/account payloads, audit ledger, risk decisions, trainer lineage, script registry, and GO/NO-GO markers remain source of truth.

The orchestrator proposes, coordinates, enriches, and deconflicts. The Risk Gateway is final authority before execution.
