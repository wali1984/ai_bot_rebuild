# Legacy vs V2 Improvement Review

Generated: 2026-05-13T04:22:07.783209Z

- Current V2 paper runtime emits pred_*/fs_*/sig_*/orch_*/risk_*/pei_* lineage from real-time payload, not hist_* fixtures.
- Risk Gateway is final authority; the current V2 paper intent is approved for paper only and still produces no exchange_order_id.
- V2 paper ledger records paper-only outcomes, including simulated fills or risk blocks, without live orders.
- Legacy live bridge is read-only and V2 shadow risk blocks legacy-observed signals missing prediction_id/feature_snapshot_id.
- CoinAnk Plan-3 remediation is recorded as READY and market-intelligence payload labels source as LIVE_COINANK_READONLY.
- Website route rebuild and PageShell data layer expose current paper runtime IDs, risk status, and live-blocked banner from runtime payloads.

Critical distinction: V2 has improved lineage, risk blocking, and paper ledger evidence, but full production migration is incomplete. Legacy real execution evidence remains visible in read-only bridge payloads, including exchange_order_id `49657465674` and margin type `cross` on the latest observed legacy executed signal.
