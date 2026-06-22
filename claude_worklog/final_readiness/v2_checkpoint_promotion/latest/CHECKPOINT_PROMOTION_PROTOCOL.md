# V2 Checkpoint Promotion Protocol (torch-native shape contract)

Scope: how an operator-provided checkpoint blob (PyTorch `.pt` /
`.safetensors`) becomes promotable for paper-only V2 inference without ever
loading raw legacy pickle weights into the V2 process or approving any live
trading.

This protocol does NOT approve live, canary, leverage/margin changes,
exchange mutation, legacy shutdown, or Redis trim. It does NOT auto-load
any blob. Codex shape review must pass before any subsequent step.

## Approved local path

Only `.local_models/` is approved for operator-provided checkpoint
artifacts. The V2 control plane is the only writer/reader on this
directory. The path is gitignored and must never be committed.

## Required operator-provided files

For each candidate checkpoint, the operator must place TWO files in
`.local_models/`:

1. The blob:
   - `.local_models/<name>.pt`, or
   - `.local_models/<name>.safetensors`
2. The sidecar metadata:
   - `.local_models/<name>_metadata.json`

The promotion lane never inspects, opens, or attempts to deserialize the
blob unless the sidecar metadata is present and Codex has approved a
shape-only inspection.

## Required metadata fields (sidecar JSON)

Canonical torch-native sidecar (recommended):

```
{
  "checkpoint_id":          "<operator-assigned unique id>",
  "source_legacy_path":     "<filesystem path the operator copied this from>",
  "source_legacy_sha256":   "<sha256 hex of the source blob>",
  "training_window_utc":    "<ISO8601 start..end>",
  "obs_dim":                26,
  "action_count":           5,
  "action_labels":          ["hold","long","short","close","hedge"],
  "tensor_shape_layout":    "TORCH_OUTPUT_FIRST",
  "tensor_shapes_per_layer": {
    "w1":    [16, 26],
    "b1":    [16],
    "w2":    [5, 16],
    "b2":    [5],
    "w_exp": [1, 16],
    "b_exp": [1]
  },
  "operator_signature_id":  "<operator key id>",
  "paper_only":             true,
  "approves_live":          false,
  "approves_canary":        false,
  "approves_legacy_shutdown": false
}
```

If `tensor_shape_layout` is absent the scanner defaults to
`TORCH_OUTPUT_FIRST`. If any required field is missing or has the wrong
shape, promotion is refused; the status output names exactly which field
failed.

## Tensor shape contract (torch-native output-first)

V2's native CPU forward in `v2/backend/app/services/rl_core/policy.py`
indexes the flat weight buffer as `w[j*in_dim + i]` with `j` iterating the
output dimension. That matches torch's `nn.Linear(in, out).weight` shape
of `[out, in]`. The promotion contract therefore declares per-layer
shapes in torch-native output-first form:

```
obs_dim         = 26
hidden_dim      = 16
action_count    = 5
action_labels   = ["hold", "long", "short", "close", "hedge"]
w1              = [16, 26]   (416 floats)
b1              = [16]       ( 16 floats)
w2              = [ 5, 16]   ( 80 floats)
b2              = [ 5]       (  5 floats)
w_exp           = [ 1, 16]   ( 16 floats)
b_exp           = [ 1]       (  1 float)
```

Flat counts are invariant under transpose, so the input-first legacy
encoding has the same flat counts.

## Legacy input-first sidecar (opt-in normalization)

Legacy producers that emit shapes as `[in, out]` may still be accepted,
but the sidecar must declare the orientation explicitly:

```
"tensor_shape_layout": "INPUT_FIRST",
"tensor_shapes_per_layer": {
  "w1":    [26, 16],
  "b1":    [16],
  "w2":    [16,  5],
  "b2":    [ 5],
  "w_exp": [16,  1],
  "b_exp": [ 1]
}
```

The scanner transposes each weight tensor to torch-native form and tags
the candidate with `shape_contract_orientation =
METADATA_INPUT_FIRST_NORMALIZED`.

If `tensor_shape_layout` is missing AND the shapes are encoded
input-first, promotion fails closed (`SHAPE_MISMATCH`). Any value other
than `TORCH_OUTPUT_FIRST` or `INPUT_FIRST` also fails closed.

## Shape contract orientation (output field)

Each candidate result carries `shape_contract_orientation`:

- `TORCH_OUTPUT_FIRST` — shapes match the torch-native contract directly.
- `METADATA_INPUT_FIRST_NORMALIZED` — shapes were declared `INPUT_FIRST`
  and matched after transpose.
- `SHAPE_MISMATCH` — shapes did not match either orientation, or the
  layout marker was invalid.
- `NOT_EVALUATED` — the candidate had no metadata, no blob, or
  pre-validation failed before shape comparison.

## Rules

- No raw checkpoint may be committed to Git.
- No V2 process loads an arbitrary pickle without Codex approval.
- Scanner must not import `torch` and must not deserialize pickle.
- Shape inspection is paper-only and never enables live trading.
- The legacy bot directory must not be modified, started, stopped, or
  read for checkpoint contents.
- No exchange-mutation call, no order placement / cancellation.
- The V2 paper-fill strict gate stays active. Promotion does not relax it.
- A successful promotion only means "ready for Codex shape review" — it
  does not by itself swap V2's runtime policy weights.

## Outcome states (one of)

- `CHECKPOINT_PROMOTION_READY_FOR_CODEX_SHAPE_REVIEW`
- `CHECKPOINT_METADATA_PRESENT_SHAPE_MISMATCH`
- `CHECKPOINT_METADATA_MISSING`
- `CHECKPOINT_BLOB_MISSING`
- `CHECKPOINT_OPERATOR_REQUIRED` (default: directory absent or empty)

## Operator instruction when CHECKPOINT_OPERATOR_REQUIRED

> Place an approved checkpoint blob and its sidecar metadata under
> `.local_models/`:
>
> 1. `.local_models/<name>.pt` or `.local_models/<name>.safetensors`
> 2. `.local_models/<name>_metadata.json` (see required fields above)
>
> Then re-run:
> `PYTHONPATH=. ./.venv/bin/python3 -m v2.backend.app.cli.v2_checkpoint_promotion_status --once`
>
> Do NOT commit `.local_models/` to Git. Do NOT modify legacy. Do NOT
> enable live.
