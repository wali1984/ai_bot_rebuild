# V2 Checkpoint Promotion Lane — Report

GO/NO-GO: `V2_CHECKPOINT_PROMOTION_OPERATOR_REQUIRED`

This packet does NOT approve live trading, canary trading, leverage/margin
changes, exchange mutation, legacy shutdown, or Redis trim. It does NOT
load any pickle/checkpoint into the V2 process. It does NOT touch legacy.

## Why this lane exists

The V2 6h runtime soak has Codex PASS, but V2-vs-legacy action mismatches
remain. They are entirely explained by V2 running on deterministic-init
policy weights (no operator-approved trained checkpoint loaded). The
production-equivalence comparator now states this explicitly:

- `schema_version = v2_production_equivalence_comparison_v3`
- `primary_mismatch_source_when_unmatched = CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`
- `all_mismatches_attributable_to_checkpoint_blocker = true`
- `deterministic_init_policy_active = true`
- `strict_paper_gate_active = true`
- `positive_edge_claimed = false`

Per-symbol (this cycle):

| Symbol | Legacy action | V2 action | Match | Source |
| --- | --- | --- | :---: | --- |
| BTCUSDT | `CLOSE_LONG`  | `hold` | False | `CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED` |
| ETHUSDT | `HOLD`        | `hold` | True  | (matched) |
| SOLUSDT | `CLOSE_SHORT` | `hold` | False | `CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED` (+ strict paper-fill gate `NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK`) |

## What this lane provides

A safe operator-controlled promotion path with zero auto-load:

1. **Protocol document** ([CHECKPOINT_PROMOTION_PROTOCOL.md](claude_worklog/final_readiness/v2_checkpoint_promotion/latest/CHECKPOINT_PROMOTION_PROTOCOL.md))
   defines: approved local path (`.local_models/` only), required sidecar
   metadata fields, V2 policy shape contract, and rules.
2. **Machine-readable protocol** ([checkpoint_promotion_protocol.json](claude_worklog/final_readiness/v2_checkpoint_promotion/latest/checkpoint_promotion_protocol.json)).
3. **Scanner service** ([v2/backend/app/services/rl_core/checkpoint_promotion.py](v2/backend/app/services/rl_core/checkpoint_promotion.py)):
   reads `.local_models/`, validates the sidecar metadata against the V2
   policy shape contract, never imports torch, never deserializes the
   blob, never reads outside the approved root, never touches legacy.
4. **CLI** ([v2/backend/app/cli/v2_checkpoint_promotion_status.py](v2/backend/app/cli/v2_checkpoint_promotion_status.py)):
   emits the worklog + public dashboard payloads.
5. **Tests** ([test_v2_checkpoint_promotion_status.py](v2/backend/tests/integration/cli/test_v2_checkpoint_promotion_status.py)):
   10 cases covering absent root, empty root, blob-without-metadata,
   metadata-without-blob, good pair, shape mismatch, live-approval
   refusal, paper-only enforcement, CLI emit, and a guard test that
   confirms importing the scanner does NOT import torch.
6. **Frontend** ([Monitor Center cards](v2/frontend/src/pages/monitor-center/index.tsx)):
   surface the soak-PASS state, the missing checkpoint, the V2 policy
   shape contract, the explicit mismatch source, and the operator
   instruction.

## Current scan result (live filesystem)

```
go_no_go             = V2_CHECKPOINT_PROMOTION_OPERATOR_REQUIRED
overall_state        = CHECKPOINT_OPERATOR_REQUIRED
approved_root        = .local_models
approved_root_status = ABSENT
candidate_count      = 0
operator_instruction = Place approved checkpoint + metadata under .local_models/ and rerun checkpoint promotion status.
```

## Outcome state matrix

The scanner emits exactly one of:

- `CHECKPOINT_PROMOTION_READY_FOR_CODEX_SHAPE_REVIEW` — good blob + good sidecar + shape contract matches
- `CHECKPOINT_METADATA_PRESENT_SHAPE_MISMATCH` — sidecar present but shape disagrees with V2 policy contract
- `CHECKPOINT_METADATA_MISSING` — blob present, sidecar missing or invalid (includes safety failures such as `paper_only=false` or `approves_live=true`)
- `CHECKPOINT_BLOB_MISSING` — sidecar present, blob missing
- `CHECKPOINT_OPERATOR_REQUIRED` — directory absent or empty (today's state)

GO/NO-GO collapse:
- `READY_FOR_CODEX_SHAPE_REVIEW` -> `V2_CHECKPOINT_PROMOTION_READY_FOR_CODEX_SHAPE_REVIEW`
- `OPERATOR_REQUIRED` -> `V2_CHECKPOINT_PROMOTION_OPERATOR_REQUIRED`
- all other failure states -> `V2_CHECKPOINT_PROMOTION_BLOCKED`

## Required operator action

> Place an approved checkpoint blob and its sidecar metadata under
> `.local_models/`:
>
> 1. `.local_models/<name>.pt` or `.local_models/<name>.safetensors`
> 2. `.local_models/<name>_metadata.json` with all required fields and
>    matching shape contract (see protocol doc).
>
> Then rerun:
> `./.venv/bin/python3 -m v2.backend.app.cli.v2_checkpoint_promotion_status --once`
>
> Do NOT commit `.local_models/` to Git. Do NOT modify legacy. Do NOT
> enable live. The next gate after promotion is a separate
> Codex shape-only review, not a runtime swap.

## What this report does NOT do or claim

- Does not load any pickle or safetensors blob into the V2 process.
- Does not auto-promote any legacy `.backups/collapsed_checkpoint_*` file.
- Does not approve live, canary, leverage/margin, exchange mutation,
  legacy shutdown, or Redis trim.
- Does not create any approval token.
- Does not modify legacy in any way.
- Does not stop, start, or restart legacy.
- Does not write to any old-Redis namespace.
- Does not loosen the strict paper-fill gate.
- Does not claim positive edge.

## Safety invariants (raw)

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- no torch import in scanner module
- no legacy filesystem read
- no pickle deserialization attempted
- no checkpoint blob committed to Git
