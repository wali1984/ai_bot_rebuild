# CODEX FINDING + HANDOFF — PPO is not training: ~0 valid on-policy rows (root-caused)

Date: 2026-07-18 | From: Claude | Corrects Claude's earlier stale "cost-blind reward" claim.
Live gate: BLOCKED. Trainer lane (files are Codex's uncommitted).

## Codex's feedback (accepted, and now precisely located)
- CONFIRMED: confidence head trained on move MAGNITUDE not P(after-cost profit); calibration poor,
  no fitted temperature active. (Claude's diagnosis stands.)
- CORRECTED: Claude's "active PPO applies a cost-blind reward" was STALE/WRONG. Reality: the PPO lane
  consumes ~ZERO valid on-policy rows, so PPO is NOT TRAINING AT ALL — the reward code never runs.

## Evidence (live v2:paper:closed_trades, 92 post-policy)
  ppo_on_policy_entry_fields_present: True=2, False=42, None=48
  old_log_prob populated: 2 / 92  (90 EMPTY)
  distinct acting policy_fingerprint: 1 (so NOT a policy-mismatch; the fields are simply absent)
=> PPO's _has_on_policy_ppo_fields() (ppo_trainer.py:479,841) admits ~2 rows -> effectively zero -> no PPO update.

## Exact root cause (v2_trade_management_paper_loop.py:44177-44225)
On-policy eligibility requires _entry_is_exact_on_policy_sample:
    _entry_sampling_mode == "CATEGORICAL_SAMPLE"  AND
    _entry_distribution_contract == "RAW_LOGITS_SOFTMAX_V1"
plus _entry_log_prob is not None and _entry_policy_value is not None.
~98% of paper entries are NOT sampled from the CUDA policy this way — they come from strategy-supply /
deterministic gate-driven selection, so they hit the else branch (:44222) with reason
"STRATEGY_SUPPLY_ACTION_NOT_SAMPLED_FROM_CUDA_POLICY" and old_log_prob stays empty. The 2 rows that DID
record it (old_log_prob=-0.47, fields_present=True) prove the plumbing works — it just rarely fires.

## Why this matters (the deadlock)
- Trainer is INFERENCE_ONLY (serving a prior checkpoint after promotion rejection).
- The RL policy can only improve via PPO on on-policy samples; those require CATEGORICAL_SAMPLE from the
  current CUDA policy. The runtime overwhelmingly acts deterministically/strategy-supply -> no on-policy data
  -> PPO can't update -> candidate never improves -> promotion stays rejected -> stays INFERENCE_ONLY. Loop.

## Fix design (Codex trainer/paper-loop lane)
1. On-policy exploration lane: route a bounded, safety-gated FRACTION of paper entries through a TRUE
   on-policy action: CATEGORICAL_SAMPLE from the current CUDA policy's RAW_LOGITS_SOFTMAX_V1, recording
   selected_action_log_prob/old_log_prob/policy_value at entry (the :44181 block already does this when the
   sample is exact — the gap is that the ACTION SELECTION rarely uses that path). Reuse the existing
   PAPER_BOOTSTRAP_EXPLORATION lever; ensure the explored action is actually the sampled one, not a
   strategy-supply override. Keep all hard gates (positive-EV floor, bounded loss, never A+/live).
2. Target a minimum on-policy batch per cycle (e.g. >= N rows) before a PPO update; log
   ppo_on_policy_rows so the guardian can see it climb from ~0.
3. Alternative/complement: off-policy correction (importance sampling) using recorded behavior
   probabilities for deterministic entries — but that STILL requires persisting the behavior action
   distribution, which the strategy-supply path currently omits. On-policy sampling is the cleaner fix.
4. Independently: the confidence head relabel to P(after-cost profit) + fitted temperature calibration
   (CG-F053) — the supervised head can improve even while PPO is being unblocked.

## Acceptance
- ppo_on_policy_rows per cycle rises from ~0 to a real batch; PPO loss/updates become non-trivial.
- effective_trainer_mode can leave INFERENCE_ONLY once a candidate earns positive PIT-safe post-cost edge.
See claude_worklog/MASTER_PATH_TO_1000X_AND_SESSION_FINDINGS.md Part 6 for the training-loop + longer-TF context.
