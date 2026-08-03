"""V2 RL core worker CLI (paper-only).

This CLI prints the V2 RL core paper-only status payload or writes it to the
operator runtime location for the frontend to consume.

It does NOT:

- restart any legacy service
- mutate Redis (legacy or V2)
- place / cancel / modify any exchange action
- load PyTorch weights
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2.backend.app.services.market_state_integrity import (
    build_market_state_envelope_from_snapshot,
)
from v2.backend.app.services.rl_core.service import RLCoreService
from v2.backend.app.services.rl_core.environment import (
    ACTION_CLOSE,
    ACTION_HOLD,
    ACTION_LONG,
    ACTION_SHORT,
    PaperOnlyEnv,
    env_invariants_snapshot,
)
from v2.backend.app.services.rl_core.observation_builder import (
    build_observation_from_snapshot,
    load_snapshot_from_disk,
    observation_metadata,
)
from v2.backend.app.services.rl_core.rewards import (
    HEDGE_REWARD_CLASSIFICATION,
    compute_reward_suite,
    reward_invariants_snapshot,
)
from v2.backend.app.services.rl_core.policy import (
    V2NativeCPUPolicy,
    policy_invariants_snapshot,
)
from v2.backend.app.services.rl_core.masa_adapter import (
    V2MASAAdapter,
    masa_invariants_snapshot,
)
from v2.backend.app.services.rl_core.ppo_policy import (
    V2NativePPOPolicy,
    ppo_invariants_snapshot,
)
from v2.backend.app.services.rl_core.trainer_algo_status import (
    compute_trainer_algo_completion_status,
    trainer_algo_invariants_snapshot,
)
from v2.backend.app.services.rl_core.trainer_output import (
    ALL_BLOCK_REASONS,
    DEFAULT_EDGE_AFTER_COST_MIN_BPS,
    emit_trainer_output,
    trainer_output_invariants_snapshot,
    validate_for_paper_fill_gate,
)

DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json"
)
DEFAULT_NATIVE_SNAPSHOT_PATH = Path(
    "v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"
)
DEFAULT_NATIVE_SNAPSHOT_PUBLIC_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "V2 RL core worker (paper-only). Emits a status payload with the "
            "components present in V2 and the components still missing from "
            "the legacy RL core."
        )
    )
    parser.add_argument(
        "--write-evidence",
        action="store_true",
        help=(
            "Write the status JSON to "
            "v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json "
            "(or --output if provided)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the status JSON to stdout and exit (no file write).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional explicit output path for --write-evidence. Defaults to "
            "the operator_runtime path."
        ),
    )
    parser.add_argument(
        "--require-paper-only",
        action="store_true",
        help=(
            "Exit non-zero if the payload's safety invariants are not all "
            "true (defense-in-depth)."
        ),
    )
    parser.add_argument(
        "--p0-2a-rollout",
        action="store_true",
        help=(
            "Run the P0.2A paper-only env + observation + reward rollout. "
            "Reads the trainer-consumable feature snapshot, builds the "
            "observation tensor, runs N env steps with a scripted action "
            "policy, computes the reward suite, and includes the rollout "
            "summary in the emitted status payload."
        ),
    )
    parser.add_argument(
        "--snapshot-path",
        type=Path,
        default=None,
        help=(
            "Override the trainer-consumable feature snapshot path. "
            "Defaults to the runtime mirror then the public mirror."
        ),
    )
    parser.add_argument(
        "--rollout-steps",
        type=int,
        default=8,
        help="Number of env steps to run in the P0.2A rollout (default 8).",
    )
    parser.add_argument(
        "--p0-2b-policy-forward",
        action="store_true",
        help=(
            "Run the P0.2B CPU policy forward pass over the current native "
            "feature snapshot. Emits action_logits, action_probabilities, "
            "selected_action, value head, and policy invariants."
        ),
    )
    parser.add_argument(
        "--p0-2g-trainer-algo-completion",
        action="store_true",
        help=(
            "Attach the P0.2G trainer-algo completion status block "
            "(ppo_clip, gae, adamw, checkpoint, hedge, migration)."
        ),
    )
    parser.add_argument(
        "--p0-2f-paper-fill-gate",
        action="store_true",
        help=(
            "Emit the P0.2F trainer output record and the strict paper "
            "fill gate decision (paper_fill_allowed + block reasons)."
        ),
    )
    parser.add_argument(
        "--expected-move-after-cost-min-bps",
        type=float,
        default=DEFAULT_EDGE_AFTER_COST_MIN_BPS,
        help=(
            "Minimum after-cost edge (bps) required to open the paper "
            "fill gate; default 8.0."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    service = RLCoreService()
    payload = service.current_paper_only_status()

    if args.p0_2a_rollout:
        # Resolve snapshot path (runtime first, public fallback, or explicit override).
        snapshot_path = args.snapshot_path
        if snapshot_path is None:
            if DEFAULT_NATIVE_SNAPSHOT_PATH.exists():
                snapshot_path = DEFAULT_NATIVE_SNAPSHOT_PATH
            elif DEFAULT_NATIVE_SNAPSHOT_PUBLIC_PATH.exists():
                snapshot_path = DEFAULT_NATIVE_SNAPSHOT_PUBLIC_PATH
            else:
                print(
                    "ERROR: no trainer-consumable feature snapshot found; "
                    "expected at "
                    "v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json "
                    "or the public mirror.",
                    file=sys.stderr,
                )
                return 2

        snapshot = load_snapshot_from_disk(snapshot_path)
        envelope = build_market_state_envelope_from_snapshot(snapshot)
        obs = build_observation_from_snapshot(snapshot, market_state_envelope=envelope)
        obs_meta = observation_metadata(snapshot, market_state_envelope=envelope)

        env = PaperOnlyEnv(max_steps=max(8, int(args.rollout_steps)))
        env.reset()
        # Scripted action policy: deterministic sequence covering hold/long/close/short.
        scripted = [ACTION_HOLD, ACTION_LONG, ACTION_HOLD, ACTION_CLOSE, ACTION_SHORT, ACTION_HOLD, ACTION_CLOSE, ACTION_HOLD]
        rollout_steps: list[dict] = []
        for i in range(min(args.rollout_steps, env.max_steps - 1)):
            action = scripted[i % len(scripted)]
            obs_dict, components = env.step(action)
            reward = compute_reward_suite(
                realized_bps=obs_dict["realized_bps"],
                unrealized_bps=obs_dict["unrealized_bps"],
                realized_bps_delta=components["realized_bps_delta"],
                position_just_closed=(action == ACTION_CLOSE and components["realized_bps_delta"] != 0.0),
                drawdown_bps_abs=max(0.0, -obs_dict["realized_bps"]),
                time_in_trade_seconds=60 * obs_dict["step_index"],
                position_size_abs=1.0 if obs_dict["position_side"] != 0 else 0.0,
            )
            rollout_steps.append({
                "step_index": obs_dict["step_index"],
                "action": int(action),
                "price": obs_dict["price"],
                "position_side": obs_dict["position_side"],
                "realized_bps": obs_dict["realized_bps"],
                "unrealized_bps": obs_dict["unrealized_bps"],
                "reward_components": {
                    "base_pnl_reward_bps": reward.base_pnl_reward_bps,
                    "fee_aware_reward_bps": reward.fee_aware_reward_bps,
                    "constrained_safety_penalty_bps": reward.constrained_safety_penalty_bps,
                    "hedge_reward_bps": reward.hedge_reward_bps,
                    "hedge_reward_classification": reward.hedge_reward_classification,
                    "total_reward_bps": reward.total_reward_bps,
                    "clamped": reward.clamped,
                },
                "done": obs_dict["done"],
            })
            if obs_dict["done"]:
                break

        payload["p0_2a_rollout"] = {
            "snapshot_path": str(snapshot_path),
            "observation_metadata": obs_meta,
            "observation_tensor_shape": list(obs.tensor_shape),
            "rollout_steps_run": len(rollout_steps),
            "steps": rollout_steps,
            "env_invariants": env_invariants_snapshot(),
            "reward_invariants": reward_invariants_snapshot(),
            "hedge_reward_classification": HEDGE_REWARD_CLASSIFICATION,
            "scope": "PAPER_ONLY_ENV_OBS_REWARD_ROLLOUT",
            "migration_classification": "PARTIALLY_MIGRATED_P0_2A",
        }
        env.close()

    if args.p0_2b_policy_forward:
        snapshot_path = args.snapshot_path
        if snapshot_path is None:
            if DEFAULT_NATIVE_SNAPSHOT_PATH.exists():
                snapshot_path = DEFAULT_NATIVE_SNAPSHOT_PATH
            elif DEFAULT_NATIVE_SNAPSHOT_PUBLIC_PATH.exists():
                snapshot_path = DEFAULT_NATIVE_SNAPSHOT_PUBLIC_PATH
            else:
                print(
                    "ERROR: no trainer-consumable feature snapshot found for P0.2B forward",
                    file=sys.stderr,
                )
                return 2
        snapshot = load_snapshot_from_disk(snapshot_path)
        envelope = build_market_state_envelope_from_snapshot(snapshot)
        obs = build_observation_from_snapshot(snapshot, market_state_envelope=envelope)
        pol = V2NativeCPUPolicy()
        fr = pol.forward(obs.tensor, feature_snapshot_id=obs.feature_snapshot_id)
        masa = V2MASAAdapter(policy=pol).get_action_and_value(
            obs.tensor,
            feature_snapshot_id=obs.feature_snapshot_id,
            observation_contract=obs,
        )
        ppo = V2NativePPOPolicy(policy=pol).predict(
            obs.tensor, feature_snapshot_id=obs.feature_snapshot_id
        )
        # placeholder retained for ordering; the actual P0.2B block follows.
        payload["p0_2b_policy_forward"] = {
            "snapshot_path": str(snapshot_path),
            "policy_id": fr.policy_id,
            "observation_feature_snapshot_id": fr.observation_feature_snapshot_id,
            "action_labels": list(fr.action_labels),
            "action_logits": list(fr.action_logits),
            "action_probabilities": list(fr.action_probabilities),
            "selected_action": fr.selected_action,
            "selected_action_index": fr.selected_action_index,
            "expected_move_bps_head": fr.expected_move_bps_head,
            "model_source_classification": fr.model_source_classification,
            "hedge_action_classification": fr.hedge_action_classification,
            "missing_policy_components": list(fr.missing_policy_components),
            "schema_version": fr.schema_version,
            "masa_adapter": {
                "selected_action": masa.selected_action,
                "value_estimate_bps": masa.value_estimate_bps,
                "is_finite": masa.is_finite,
            },
            "ppo_predict": {
                "selected_action": ppo.selected_action,
                "log_prob_selected": ppo.log_prob_selected,
                "deterministic": ppo.deterministic,
            },
            "policy_invariants": policy_invariants_snapshot(),
            "masa_invariants": masa_invariants_snapshot(),
            "ppo_invariants": ppo_invariants_snapshot(),
            "scope": "PAPER_ONLY_CPU_POLICY_FORWARD",
            "migration_classification": "PARTIALLY_MIGRATED_P0_2B",
        }

    if args.p0_2f_paper_fill_gate:
        snapshot_path = args.snapshot_path
        if snapshot_path is None:
            if DEFAULT_NATIVE_SNAPSHOT_PATH.exists():
                snapshot_path = DEFAULT_NATIVE_SNAPSHOT_PATH
            elif DEFAULT_NATIVE_SNAPSHOT_PUBLIC_PATH.exists():
                snapshot_path = DEFAULT_NATIVE_SNAPSHOT_PUBLIC_PATH
            else:
                print(
                    "ERROR: no trainer-consumable feature snapshot found for P0.2F gate",
                    file=sys.stderr,
                )
                return 2
        snapshot = load_snapshot_from_disk(snapshot_path)
        rec = emit_trainer_output(snapshot)
        gate = validate_for_paper_fill_gate(
            rec,
            expected_move_after_cost_min_bps=float(args.expected_move_after_cost_min_bps),
        )
        payload["p0_2f_paper_fill_gate"] = {
            "snapshot_path": str(snapshot_path),
            "prediction_id": rec.prediction_id,
            "feature_snapshot_id": rec.feature_snapshot_id,
            "trainer_source": rec.trainer_source,
            "checkpoint_id": rec.checkpoint_id,
            "checkpoint_blocker": rec.checkpoint_blocker,
            "expected_move_bps": rec.expected_move_bps,
            "expected_move_after_cost_bps": rec.expected_move_after_cost_bps,
            "confidence_raw": rec.confidence_raw,
            "confidence_calibrated": rec.confidence_calibrated,
            "feature_freshness_state": rec.feature_freshness_state,
            "missing_feature_flags": list(rec.missing_feature_flags),
            "stale_feature_flags": list(rec.stale_feature_flags),
            "prediction_live_gate": rec.prediction_live_gate,
            "prediction_live_symbols": list(rec.prediction_live_symbols),
            "selected_action": rec.selected_action,
            "policy_action_probabilities": list(rec.policy_action_probabilities),
            "hedge_action_classification": rec.hedge_action_classification,
            "paper_fill_gate_status": gate["paper_fill_gate_status"],
            "paper_fill_allowed": gate["paper_fill_allowed"],
            "paper_fill_gate_block_reasons": list(gate["paper_fill_gate_block_reasons"]),
            "paper_fill_gate_blockers": list(gate["blockers"]),
            "expected_move_after_cost_min_bps": gate["expected_move_after_cost_min_bps"],
            "all_known_block_reasons": list(ALL_BLOCK_REASONS),
            "default_edge_after_cost_min_bps": DEFAULT_EDGE_AFTER_COST_MIN_BPS,
            "invariants": trainer_output_invariants_snapshot(),
            "scope": "PAPER_ONLY_STRICT_PAPER_FILL_GATE",
        }

    if args.p0_2g_trainer_algo_completion:
        status = compute_trainer_algo_completion_status()
        payload["p0_2g_trainer_algo_completion"] = {
            "ppo_clip_status": status.ppo_clip_status,
            "gae_status": status.gae_status,
            "optimizer_state_status": status.optimizer_state_status,
            "checkpoint_weight_status": status.checkpoint_weight_status,
            "hedge_status": status.hedge_status,
            "hedge_block_reason": status.hedge_block_reason,
            "migration_classification": status.migration_classification,
            "checkpoint_id": status.checkpoint_id,
            "checkpoint_blockers": list(status.checkpoint_blockers),
            "generated_utc": status.generated_utc,
            "invariants": trainer_algo_invariants_snapshot(),
            "scope": "PAPER_ONLY_TRAINER_ALGO_COMPLETION",
        }

    if args.require_paper_only:
        invariants = payload.get("safety_invariants", {})
        if not all(bool(v) for v in invariants.values()):
            print(
                "SAFETY_INVARIANT_VIOLATION: not all invariants true: "
                f"{invariants}",
                file=sys.stderr,
            )
            return 2
        if payload.get("live_gate") != "blocked_human_only":
            print(
                f"SAFETY_INVARIANT_VIOLATION: live_gate={payload.get('live_gate')}",
                file=sys.stderr,
            )
            return 2
        if payload.get("live_symbols") != []:
            print(
                f"SAFETY_INVARIANT_VIOLATION: live_symbols={payload.get('live_symbols')}",
                file=sys.stderr,
            )
            return 2

    if args.dry_run and args.write_evidence:
        print(
            "ERROR: --dry-run and --write-evidence are mutually exclusive",
            file=sys.stderr,
        )
        return 2

    if args.write_evidence:
        destination = args.output or DEFAULT_PAYLOAD_PATH
        # If P0.2A rollout data is attached to the in-memory payload, write
        # the mutated payload directly so the rollout summary is preserved.
        # Otherwise, delegate to service.write_status_payload for atomicity.
        if (
            "p0_2a_rollout" in payload
            or "p0_2b_policy_forward" in payload
            or "p0_2f_paper_fill_gate" in payload
            or "p0_2g_trainer_algo_completion" in payload
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            written = destination
        else:
            written = service.write_status_payload(destination)
        print(
            json.dumps(
                {
                    "wrote": str(written),
                    "go_no_go": payload["go_no_go"],
                    "live_gate": payload["live_gate"],
                    "components_present_count": len(payload["components_present"]),
                    "components_missing_count": len(payload["components_missing"]),
                    "p0_2a_rollout_included": "p0_2a_rollout" in payload,
                    "p0_2b_policy_forward_included": "p0_2b_policy_forward" in payload,
                    "p0_2f_paper_fill_gate_included": "p0_2f_paper_fill_gate" in payload,
                    "p0_2g_trainer_algo_completion_included": "p0_2g_trainer_algo_completion" in payload,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    # Default / --dry-run path: print payload to stdout.
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
