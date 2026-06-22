# V2 Checkpoint Weight Blob Burndown (during soak)

Generated: 2026-05-17T02:25:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541
GO/NO-GO: V2_CHECKPOINT_WEIGHT_BURNDOWN_OPERATOR_REQUIRED

## What this packet did (without interrupting anything)

- Scanned approved V2-owned local paths (.local_models/,
  .local_secrets/, v2/runtime/) for checkpoint candidates. Result:
  0 .pt/.pth/.ckpt/.zip files in any approved path. .local_models/
  is absent on this host.
- Confirmed the legacy filesystem inventory contains 73,794 .pt-
  shaped entries (legacy_reference/.backups/collapsed_checkpoint_*).
  These are inventory references only; V2 control plane is NOT
  authorized to load them.
- Captured the V2 policy shape contract for the operator's future
  blob preparation: obs_dim=26, hidden_dim=16, action_count=5,
  action_labels=hold/long/short/close/hedge.
- Linked the per-symbol mismatch to the weight state: BTCUSDT v2=hold
  vs legacy=close_short_open_long, SOLUSDT v2=hold vs legacy=open_short
  - both root-caused to deterministic-init weights. ETHUSDT
  currently matches by coincidence.
- Added 7 focused tests at
  v2/backend/tests/integration/cli/test_v2_checkpoint_weight_burndown.py.
  All 14 checkpoint-related tests pass (7 new + 7 prior P0.2C).
- Did NOT load torch weights. Did NOT copy any blob into Git.
- Did NOT stop legacy. Did NOT stop the V2 runtime loops (10
  processes still running).
- Did NOT loosen the strict P0.2F paper-fill gate.
- Did NOT claim positive paper edge.

## Why operator action is required

The V2 control plane will not deserialize PyTorch state because:

1. The CLAUDE.md protected runtime policy forbids mutating or
   importing the legacy ML runtime.
2. Pickle-loading legacy `.pt` is a remote-code-execution vector
   even from trusted sources.
3. Operator + Codex must sign off before V2 references any
   external model artifact.

The legitimate promotion path is:

- Operator places an approved blob and sidecar metadata under
  `.local_models/<name>.pt` and `.local_models/<name>_metadata.json`.
- Sidecar metadata states tensor_shapes_per_layer, obs_dim=26,
  action_count=5, training_source_legacy_path,
  training_source_legacy_sha256, training_window_utc, and
  operator_signature_id.
- A read-only subprocess in the legacy trainer venv inspects the
  tensor shapes against the V2 policy contract and writes a
  shape-only manifest. V2 never imports torch in its own process.
- Codex reviews the manifest before V2 references it.

Alternative: operator creates
`claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md`
with the required paper-only language and no live/canary approval.
This leaves V2 on deterministic-init weights and accepts the
known limitation for paper-only-shutdown evaluation.

## V2 policy shape contract (for future operator metadata)

| Layer | Expected size |
| --- | --- |
| w1 | 26 * 16 = 416 floats |
| b1 | 16 floats |
| w2 | 16 * 5 = 80 floats |
| b2 | 5 floats |
| w_exp (expected-move scalar head) | 16 floats |
| b_exp | 1 float |

A compatible checkpoint must match these shapes exactly. Anything
else fails the shape contract.

## V2-vs-legacy mismatch reduced to weight state

| Symbol | Legacy action | V2 action | Cause |
| --- | --- | --- | --- |
| BTCUSDT | close_short_open_long | hold | deterministic-init weights |
| ETHUSDT | matches V2 | matches legacy | coincidental match |
| SOLUSDT | open_short | hold | deterministic-init weights |

Both mismatches resolve to the same blocker. No new remediation
task. No runtime failure.

## Validation

- Focused tests in
  test_v2_checkpoint_weight_burndown.py and
  test_v2_rl_core_p0_2c_checkpoint.py: 14 passed.
- py_compile for checkpoints.py and policy.py: PASS.
- Old-Redis-write scan over burndown artifacts: clean.
- Exchange-mutation scan over burndown artifacts: clean.
- Live-approval / Redis-trim approval scan: no tokens present.
- Raw secret scan over burndown payload + this report: clean.

## Safety posture

- live_gate: blocked_human_only
- live_symbols: []
- approves_live: false
- approves_canary: false
- approves_legacy_shutdown: false
- approves_redis_trim: false
- final_live_approval_token_created: false
- torch_weights_loaded_into_v2_process: false
- checkpoint_blob_committed_to_git: false
- legacy_was_stopped_by_this_packet: false
- v2_runtime_was_stopped_by_this_packet: false

## V2 runtime continues during this packet

- 10/10 V2 processes still alive.
- Runtime guard: V2_PRODUCTION_REPLACEMENT_RUNTIME_READY_STABLE.
- Soak window: ~17 minutes observed (15m milestone crossed; 1h/6h
  still pending and unaffected by this packet).

## Decision

V2_CHECKPOINT_WEIGHT_BURNDOWN_OPERATOR_REQUIRED.

The blocker is honestly retained as operator-required. The runtime
keeps running paper/shadow; the mismatch is explained; the gate is
not loosened; live and shutdown remain blocked.
