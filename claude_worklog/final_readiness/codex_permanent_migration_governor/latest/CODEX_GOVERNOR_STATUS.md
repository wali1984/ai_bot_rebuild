# Codex Permanent Migration Governor Status

Generated: `2026-05-15T19:53:11Z`

GO/NO-GO: `CODEX_PERMANENT_SHUTDOWN_AND_MIGRATION_GOVERNOR_READY`

Mode: no new service was installed. Existing takeover and observatory services remain active.

## Simple Status

- Are we live? **No.** `live_gate=blocked_human_only`, `live_symbols=[]`.
- Can legacy be shut down? **No.** `BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE`.
- Active shutdown P0 count: `1`.
- Main P0 blocker: `PAPER_EDGE_UNPROVEN`.
- Shadow observations: `326` completed, `125` false blocks, `201` no-trade correct.
- Expected-move review: `V2_EXPECTED_MOVE_MODEL_REVIEW_READY_KEEP_GATE_STRICT` with action `KEEP_GATE_STRICT`.
- Expected-move review freshness: reviewed false blocks `95`, current false blocks `125`, current=`False`.
- Public freshness stale count: `0`.
- Next action: `{'kind': 'refresh_expected_move_model_review_from_shadow_observer', 'task_id': 'claude_v2_expected_move_model_review_and_false_block_calibration', 'blocker_id': 'PAPER_EDGE_UNPROVEN', 'follow_up': 'current shadow false blocks exceed reviewed sample; rerun expected-move review, keep strict fill gate, do not loosen thresholds or claim positive edge'}`.

## Safety

- No live approval was created.
- No Redis trim approval was created.
- Old Redis write status remains absent.
- Exchange action status remains absent.
- Legacy is read-only reference only.
