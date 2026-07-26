# Permanent System Recovery — Resume Audit

Generated: 2026-07-26 18:21 UTC
Scope: audit Claude's interrupted recovery work, resume safe repairs, exercise runtime acceptance, and preserve the live block.

## Executive result

**LIVE NO-GO.** The system is materially safer and more truthful than at handoff, but it is not A+ or ready for live submission.

| Area | Result | Evidence |
|---|---|---|
| systemd unit verification | PASS | `systemd-analyze --user verify ...` emits no diagnostics |
| durable repair holds | PASS | boot validator loads and validates `RepairHoldV1` records from disk and publishes them to Redis |
| trainer/serving independence | PASS from inherited evidence | one canonical writer; serving remains independent of trainer |
| boot validator honesty | PASS | it now fails closed when directional supply is zero instead of treating fresh HOLD records as healthy supply |
| point-in-time clock semantics | PASS for repaired paths | exact-cost microseconds preserved; microstructure source/producer/record/decision clocks are distinct |
| G12 rare-event suite | PASS, 17/17 | S13 production-binding transport canary added; no warning or failure |
| focused unit tests | PASS, 143/143 | lifecycle, cost model, validator, serving status, microstructure monitor |
| normal paper lifecycle | NOT PROVEN | no fresh natural entry-to-close lifecycle during this acceptance window |
| restart reconstruction | NOT PROVEN | depends on a natural open paper position and restart exercise |
| canonical directional supply | FAIL | fresh canonical records exist, but directional record count is zero |
| G03 | FAIL | F049–F054 evidence chain remains open |
| G11 | FAIL | refreshed counterfactual sweep is 0/5 |
| G13 | FAIL | notional-weighted after-cost expectancy is -18.126 bps; simple expectancy is -14.868 bps on 91 eligible outcomes |
| G14 | FAIL | profit factor 0.658; drawdown 0.80% |
| live gate | BLOCKED | `blocked_human_only`; no real order and no exchange action taken |

## Where Claude stopped

The inherited recovery status overstated readiness in three important places:

1. G12 was 16/17 because S13 was missing.
2. The boot validator declared serving healthy based on fresh records even though every prediction was HOLD and directional supply was zero.
3. `systemd-analyze verify` emitted unit diagnostics while the recorded recovery status said verification was clean.

The inherited status correctly identified the larger unresolved critical path: `ServingFeatureABIV2` and train/serve distribution parity were absent, the provisional checkpoint was HOLD-degenerate, and G03/G11/G13/G14 remained red.

## Repairs completed

- Made the boot validator fail closed on zero directional supply, invalid systemd diagnostics, malformed/active repair holds, and missing credential evidence fields.
- Made durable repair holds authoritative from `goal_state/PERMANENT_SYSTEM_RECOVERY/repair_holds.json` and republished validated records to Redis.
- Fixed systemd unit quoting and invalid Documentation URIs. Verification now produces zero diagnostics.
- Preserved microseconds for adaptive exact-cost observations. This fixes the sub-millisecond rounding defect that produced `exact_cost_observation_age_invalid`.
- Separated microstructure `source_available_at`, `producer_generated_at`, `record_available_at`, `available_at`, and `decision_time` without changing trust thresholds or admission actions.
- Made canonical serving status report real exact-cost and microstructure evidence validity instead of optimistic constants.
- Added explicit paper-close attestations for reduce-only behavior, position-to-flat transition, fully consumed quantity, remaining quantity, and required margin release.
- Added the missing S13 max-hold transport canary against the production lifecycle function. It uses isolated paper state, a 10-second max hold, no Redis, no live API, and does not count as economic evidence.
- Updated the durable recovery status to reflect G12 PASS and the remaining NO-GO state.

## Remaining critical path

1. Define and version `ServingFeatureABIV2`, then produce a reproducible dataset whose feature order, units, missingness policy, and point-in-time cutoffs exactly match serving.
2. Retrain and independently evaluate a checkpoint with train/serve distribution-parity evidence. The active provisional model has holdout accuracy 0.10 and severe distribution drift; `fee_bps` alone is approximately one million training standard deviations from the serving value because training recorded a near-zero variance around 5 while serving supplies 4.
3. Promote only through the normal governed path; do not force directional predictions or weaken feature/cost/microstructure gates.
4. Observe a natural paper entry, partial/multi-fill behavior where available, ordinary close, accounting reconciliation, and a restart while the position is open.
5. Accumulate fresh natural closes, then recompute G11/G13/G14. The current economics are negative and cannot be repaired honestly with synthetic canary evidence.
6. Complete a clean reboot proof only after the validator is green. Live submission remains human-blocked throughout.

## Files changed by this resumed audit

Repository files:

- `claude_worklog/systemd/user/ai-bot-v2-live-canary-dry-run.service`
- `claude_worklog/systemd/user/ai-bot-v2-public-website-backend.service`
- `claude_worklog/systemd/user/ai-bot-v2-shadow-outcome-metrics.service`
- `goal_state/PERMANENT_SYSTEM_RECOVERY/RECOVERY_STATUS.json`
- `scripts/guardian_phase10_rare_event_tests.py`
- `scripts/s13_max_hold_transport_canary.py` (created)
- `v2/backend/app/cli/v2_boot_validator.py`
- `v2/backend/app/cli/v2_canonical_prediction_serving_runtime.py`
- `v2/backend/app/cli/v2_microstructure_feed_quality_monitor.py`
- `v2/backend/app/cli/v2_paper_provisional_prediction_publisher.py`
- `v2/backend/app/services/paper_trade_management/adaptive_cost_model.py`
- `v2/backend/app/services/paper_trade_management/outcomes.py`
- `v2/backend/tests/unit/cli/test_v2_boot_validator.py` (created)
- `v2/backend/tests/unit/cli/test_v2_canonical_prediction_serving_runtime.py` (created)
- `v2/backend/tests/unit/cli/test_v2_microstructure_feed_quality_monitor.py`
- `v2/backend/tests/unit/services/paper_trade_management/test_adaptive_cost_model.py`
- `v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py`
- `claude_worklog/codex/PERMANENT_SYSTEM_RECOVERY_RESUME_AUDIT_2026_07_26.md` (created)

Runtime user-unit files (outside the repository, reached through the user's systemd configuration):

- `~/.config/systemd/user/ai-bot-v2-portfolio-cascade-guard.service`
- `~/.config/systemd/user/ai-bot-v2-orderbook-features-publisher.service`
- `~/.config/systemd/user/ai-bot-v2-cascade-context-publisher.service`
- `~/.config/systemd/user/ai-bot-v2-autonomous-mission-execution-burndown.service`
- `~/.config/systemd/user/ai-bot-v2-report-center-indexer.service`
- `~/.config/systemd/user/vscode-codex-state-trimmer.service`

Generated evidence:

- `goal_state/PERMANENT_SYSTEM_RECOVERY/s13_max_hold_transport_canary_result.json`

The pre-existing modification to `.claude/hooks/block_dangerous.sh` and all other unrelated untracked files were preserved and not edited by this resumed audit.

## Verification performed

```text
.venv/bin/pytest -q v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py v2/backend/tests/unit/services/paper_trade_management/test_adaptive_cost_model.py v2/backend/tests/unit/cli/test_v2_boot_validator.py v2/backend/tests/unit/cli/test_v2_canonical_prediction_serving_runtime.py v2/backend/tests/unit/cli/test_v2_microstructure_feed_quality_monitor.py
# 143 passed in 0.41s

.venv/bin/python scripts/s13_max_hold_transport_canary.py
# all_pass=true; exchange_action_taken=false

.venv/bin/python scripts/guardian_phase10_rare_event_tests.py
# 17 PASS / 0 WARNING / 0 FAIL

systemd-analyze --user verify ai-bot-v2-stack.target default.target timers.target
# no output

git diff --check
# no output
```

Runtime services restarted after their scoped code/unit changes:

```text
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-all-timeframe-prediction-publisher.service
systemctl --user restart ai-bot-v2-microstructure-feed-quality-monitor.service
systemctl --user restart ai-bot-v2-canonical-prediction-serving.service
systemctl --user restart ai-bot-v2-adaptive-cost-model-publisher.service
```

The boot-validator oneshot is currently failed by design because directional supply is zero. This is an honest acceptance failure, not an infrastructure success claim.

## Command ledger

The audit used the following read-only and verification command families, with repository paths resolved from `/home/wali/Desktop/AI BOT REBUILD`:

```text
pwd
wc -l /home/wali/.codex/attachments/281a8edb-3335-45b3-a93e-e573bbc6eeca/pasted-text.txt
sed -n '1,240p' /home/wali/.codex/attachments/281a8edb-3335-45b3-a93e-e573bbc6eeca/pasted-text.txt
sed -n '241,520p' /home/wali/.codex/attachments/281a8edb-3335-45b3-a93e-e573bbc6eeca/pasted-text.txt
sed -n '521,760p' /home/wali/.codex/attachments/281a8edb-3335-45b3-a93e-e573bbc6eeca/pasted-text.txt
sed -n '761,940p' /home/wali/.codex/attachments/281a8edb-3335-45b3-a93e-e573bbc6eeca/pasted-text.txt
rg --files
git status --short --branch
git status --short --untracked-files=all
git diff -- .claude/hooks/block_dangerous.sh
git diff --check
git show --stat --oneline HEAD
find goal_state/PERMANENT_SYSTEM_RECOVERY -maxdepth 2 -type f -print
jq . goal_state/PERMANENT_SYSTEM_RECOVERY/RECOVERY_STATUS.json
jq . goal_state/PERMANENT_SYSTEM_RECOVERY/baseline.json
jq . goal_state/PERMANENT_SYSTEM_RECOVERY/repair_holds.json
jq . goal_state/PERMANENT_SYSTEM_RECOVERY/s13_max_hold_transport_canary_result.json
rg -n 'G03|G11|G12|G13|G14|S13|ServingFeatureABIV2|available_at|decision_time|exact_cost' goal_state claude_worklog scripts v2
systemd-analyze --user verify ai-bot-v2-stack.target default.target timers.target
systemctl --user status ai-bot-v2-stack.target ai-bot-v2-boot-validator.service
systemctl --user --failed
systemctl --user cat <audited-unit>
systemctl --user daemon-reload
systemctl --user restart <scoped-service>
systemctl --user is-active <scoped-service>
redis-cli MGET <audited-status-keys>
redis-cli GET <audited-status-key>
redis-cli SCAN 0 MATCH '<audited-key-pattern>' COUNT 1000
.venv/bin/python -m py_compile <changed-python-files>
.venv/bin/pytest -q <focused-test-files>
.venv/bin/python scripts/s13_max_hold_transport_canary.py
.venv/bin/python scripts/guardian_phase10_rare_event_tests.py
.venv/bin/python scripts/verify_claude_guardian_completion.py
.venv/bin/python scripts/guardian_phase9_counterfactual_sweep.py
.venv/bin/python -m v2.backend.app.cli.v2_boot_validator
date -u +%Y-%m-%dT%H:%M:%S.%6NZ
```

Small inline Python diagnostics were also run read-only to inspect exact-cost timestamp deltas, canonical feature distributions, prediction actions, checkpoint statistics, and paper outcome aggregates. No diagnostic submitted an order or modified exchange state. All file edits were performed with patch application, not shell redirection.
