# Hybrid Trainer Durable-Root and PIT-Replay Checkpoint

- Checkpoint UTC: `2026-07-23T10:03:21Z`
- Branch: `codex/strategy-receipt-promotion-20260723`
- Parent checkpoint commit: `e04b4f72c5`
- Implementation commit: `88a26aca656ef71eb62de8c8004e03772fc393ad`
- Implementation pushed: yes; `origin/codex/strategy-receipt-promotion-20260723` was `0/0` ahead/behind immediately after push.
- Runtime scope: trainer/PAPER-shadow data plumbing only.
- Live exchange, order, cancellation, allocator, margin, and risk execution changes: `0`.

## Evidence counts

| Evidence | Count/result |
|---|---:|
| Production modules changed | 3 |
| Test modules changed/added | 5 |
| CLI/runtime durable path inputs checked | 6 |
| Causal, provenance, and tensor contract fields checked | 21 |
| Focused tests passed | 29/29 |
| Production modules compiled | 3/3 |
| New test-file full Ruff findings | 0 |
| Existing tracked files checked on changed lines | 7 |
| Changed-line Ruff findings | 0 |
| Pre-existing whole-file Ruff findings outside changed lines | 111 |
| Exact Redis keys read for runtime regression | 1 |
| Outcome rows checked | 25 |
| Durable snapshots resolved | 25/25 |
| Historical tensors rebuilt | 25/25 |
| Tensor coordinates per row | 446 |
| Nonmissing/source-available coordinates after repair | 282–345 |
| Producer literal `trainer_consumable=true` claims | 0/25 |
| Rows admitted for training | 0/25, correctly fail-closed |
| HTTP routes/endpoints inspected | 0 |
| UI screenshots captured | 0 |
| Frontend/iOS builds | 0; not part of this backend family |
| Services started/stopped/restarted | 0 |

The 21 checked contract fields were:

`model_dir`, `trusted_replay_archive_root`, `trusted_replay_cursor_root`,
`counterfactual_archive_path`, `canonical_5m_label_archive_path`,
`behavior_receipt_archive_root`, `available_at`, `feature_cutoff`,
`generated_at`, `generated_utc`, `decision_time`, `candle_open_time`,
`candle_close_time`, `trainer_consumable`, `content_sha256`,
`feature_snapshot_id`, `source_hashes`, `missing_mask`,
`source_availability`, `row_classification`, and `reject_reasons`.

## Defects fixed in this family

1. The hybrid trainer CLI had no way to select the externally persisted model,
   replay, label, counterfactual, or behavior-receipt roots used by the
   commissioned runtime.
2. Trusted-replay consumer cursors were coupled to the immutable replay archive.
   The cursor now has a separate writable root, creates that root on first
   write, and leaves the immutable archive untouched.
3. Closed-trade replay rebuilt an historical snapshot against the current wall
   clock. That made all 446 tensor coordinates appear missing/stale. Replay now
   uses the original decision time and projects only the immutable snapshot's
   recorded causal clocks onto its source views.

No clock is synthesized, no future candle is accepted, and no producer trust
claim is upgraded.

## Exact PIT/provenance regression

Read-only source: `v2:trainer:feedback:outcomes`.

| Predicate | Result |
|---|---:|
| JSON rows | 25 |
| Rows passing feedback-row shape/clock checks | 25 |
| Immutable snapshots found with matching identities/hashes | 25 |
| Tensor rebuilds returning observed evidence | 25 |
| Producer tensor classification `TRAINABLE` | 11 |
| Producer tensor classification `MISSING_MASKED` | 14 |
| Final classification `MARKET_STATE_REJECTED` | 25 |
| Rejection `PRODUCER_TRAINER_CONSUMABLE_NOT_LITERAL_TRUE` | 25 |

This separates two independent facts:

- The historical-clock reconstruction defect is repaired: every row now has
  282–345 observed coordinates instead of 0/446.
- The old producer never asserted literal trainer consumability. All 25 rows
  therefore remain non-trainable, which preserves the provenance boundary.

## Files in implementation commit

1. `v2/backend/app/cli/v2_native_rl_masa_ppo_cuda_trainer_loop.py`
2. `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py`
3. `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py`
4. `v2/backend/tests/unit/cli/test_v2_native_rl_masa_ppo_cuda_trainer_loop_paths.py`
5. `v2/backend/tests/unit/services/native_trainer/test_archive_tensor_feature_view.py`
6. `v2/backend/tests/unit/services/native_trainer/test_checkpoint_lifecycle.py`
7. `v2/backend/tests/unit/services/native_trainer/test_hybrid_trainer_feedback_labels.py`
8. `v2/backend/tests/unit/services/native_trainer/test_trainer_bounded_feedback_loading.py`

## Verification commands

```bash
PYTHONPATH="$(pwd)" '/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m pytest -q v2/backend/tests/unit/services/native_trainer/test_checkpoint_lifecycle.py::test_ordinary_runtime_holds_lifecycle_lease_across_complete_cycle v2/backend/tests/unit/cli/test_v2_native_rl_masa_ppo_cuda_trainer_loop_paths.py v2/backend/tests/unit/services/native_trainer/test_archive_tensor_feature_view.py v2/backend/tests/unit/services/native_trainer/test_hybrid_trainer_feedback_labels.py v2/backend/tests/unit/services/native_trainer/test_trainer_bounded_feedback_loading.py

PYTHONPATH="$(pwd)" '/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m py_compile v2/backend/app/cli/v2_native_rl_masa_ppo_cuda_trainer_loop.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py

'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m ruff check v2/backend/tests/unit/cli/test_v2_native_rl_masa_ppo_cuda_trainer_loop_paths.py

git diff --check
git diff --cached --check
git commit -m "fix(trainer): wire durable roots and PIT replay clocks"
git push origin HEAD
git rev-list --left-right --count @{upstream}...HEAD
```

Additional read-only evidence commands used in this family:

```bash
git status --short --untracked-files=all
git diff --stat
git diff --numstat
git diff -U0 -- <the seven tracked implementation/test files>
redis-cli --raw GET v2:trainer:feedback:outcomes | jq <shape-and-row-count projection>
rg -n <bounded loader/runtime symbol searches> <named trainer source/test files>
sed -n <bounded line ranges> <named trainer source/test files>
```

The exact-key PIT diagnostic was an inline, read-only Python invocation using
`redis.Redis(...).get("v2:trainer:feedback:outcomes")`,
`V2HybridTrainerDataLoader._closed_trade_feature_snapshot`, and
`V2HybridTrainerDataLoader._closed_trade_snapshot_training_example`. It made no
Redis, archive, service, or repository writes.

## Parallel bounded bridge trace

The single helper stayed read-only and made no edits or service changes.

| Trace evidence | Count |
|---|---:|
| Direct modules | 11 |
| Direct test files / focused test functions read | 6 / 25 |
| Explicit safety predicates | at least 75 |
| Installed units inspected | 4 |
| Exact Redis keys inspected | 13 |
| Tests/builds/screenshots/routes | 0/0/0/0 |
| Remaining bridge blockers | 6 |

Result: no authenticated path currently connects the local profiled research
candidate to strategy materialization or matured PAPER outcomes. A safe
shadow-only adapter boundary exists, but it cannot confer serving, PAPER-fill,
risk, allocator, margin, live, exchange, or order authority.

Process deviation: the helper accidentally issued one read-only
`redis-cli --scan` availability probe, discarded the output, retained no key
enumeration, and performed no state change. It stopped immediately; all later
runtime reads were exact-key reads.

## Remaining defects/blockers

1. All 25 historical outcome snapshots lack the producer-owned literal
   `trainer_consumable=true` claim. They must not be upgraded retrospectively.
2. The current local candidate is research-only/non-promotable and has no
   authenticated inference API or per-inference tensor/clock receipt.
3. The authenticated resident lineage and the hybrid loader's admitted lineage
   are incompatible; an evidence-preserving admission adapter is absent.
4. No verified serving checkpoint or three-way activation manifest exists.
5. The hybrid publisher service/timer is not installed.
6. Confidence/profitability calibration remains unfitted because no admitted
   PIT-safe explicit-cost target set exists.
7. Strategy-supply publication is inactive, and the edge-replay factory remains
   held after its prior unbounded rewrite defect.
8. Canonical prediction storage contains stale, non-expiring historical residue;
   it must not be mistaken for a current publisher heartbeat.

## Next bounded family

Build and test the dedicated
`LOCAL_PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1` receipt boundary, or prove a
smaller existing authenticated boundary is sufficient. It must use exact
candidate identity, immutable feature-snapshot identity, final-candle/PIT
clocks, masks, source hashes, and explicit pre-decision costs. Its confidence
and profit probability stay null/unfitted, and every downstream execution
authority stays false. Commit and push that family before any service action.
