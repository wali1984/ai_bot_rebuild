# Codex Permanent Migration Governor Status

Generated: `2026-05-15T18:03:35Z`

GO/NO-GO: `CODEX_PERMANENT_SHUTDOWN_AND_MIGRATION_GOVERNOR_READY`

Mode: no new script/service was created because the operator explicitly requested this be run here. Existing takeover and observatory services remain active.

## Simple Status

- Are we live? **No.** `live_gate=blocked_human_only`, `live_symbols=[]`.
- Are we paper/shadow? **Yes**, V2 paper/shadow only with a strict expected-edge gate.
- Can legacy be shut down? **No.** Current recommendation: `BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE`.
- Main P0 blocker: `PAPER_EDGE_UNPROVEN`.
- Shadow observations: `273` completed, `107` false blocks, `166` no-trade correct.
- Expected-move review: `V2_EXPECTED_MOVE_MODEL_REVIEW_READY_KEEP_GATE_STRICT` with action `KEEP_GATE_STRICT`.
- Active stale public payloads: `0`.
- Next action: `{'blocker_id': 'PAPER_EDGE_UNPROVEN', 'follow_up': 'continue observing blocked paper intents over 5m/15m/30m/1h horizons; do not loosen fill gate or claim positive edge without completed after-cost evidence', 'kind': 'monitor_shadow_outcome_observer', 'task_id': 'paper_shadow_outcome_observer'}`.

## Safety

- No live approval was created.
- No Redis trim approval was created.
- Old Redis write status remains absent.
- Exchange action status remains absent.
- Legacy is read-only reference only.
