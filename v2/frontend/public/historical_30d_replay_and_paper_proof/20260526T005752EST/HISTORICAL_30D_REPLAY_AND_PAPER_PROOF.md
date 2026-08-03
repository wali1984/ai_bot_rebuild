# Historical 30D Replay And Paper Proof

- marker: `HISTORICAL_30D_REPLAY_AND_PAPER_PROOF_READY`
- generated_at: `2026-05-09T00:00:00Z`
- live_gate_status: `blocked_human_only`
- period_days: 30
- scenario_count: 5
- v2_block_count: 3
- v2_preserved_winner_count: 2
- v2_reduced_or_rejected_count: 3
- legacy_realized_pnl_fixture_sum: `-413.30`
- v2_paper_pnl_fixture_sum: `+125.60`
- estimated_loss_avoided_by_v2: `+538.90`

## Operator Interpretation

V2 preserves deterministic winner scenarios and blocks or reduces stale, duplicate,
and hedge-unwind residual exposure scenarios. The LAB short-squeeze failure case is
represented as a blocked-or-reduced paper decision.

## Artifacts

- `HISTORICAL_30D_REPLAY_AND_PAPER_PROOF.md`
- `GO_NO_GO.md`
- `historical_30d_summary.json`
- `legacy_vs_v2_decision_comparison.json`
- `v2_risk_blocks.json`
- `v2_preserved_winners.json`
- `v2_reduced_or_rejected_trades.json`
- `paper_ledger_30d.json`
- `shadow_comparison_30d.json`
- `operator_dashboard_payload.json`
- `evidence_manifest.json`
- `limitations_and_data_gaps.md`
