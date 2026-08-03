"""V2 RL core service (paper-only).

This service wires the partially-ported RL core pieces (observation schema
descriptor, constrained reward, checkpoint metadata, confidence calibration)
into one paper-only facade.

It does NOT:

- import torch or stable_baselines3
- write to any Redis instance
- import any exchange SDK
- run a Gymnasium env loop
- train a PPO/MASA policy
- approve live, canary, or legacy shutdown
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .checkpoint_metadata import CheckpointMetadata, parse_legacy_checkpoint_filename
from .observation_schema import (
    LEGACY_OBS_SHA256,
    V2_OBSERVATION_SCHEMA,
    observation_field_names,
    observation_schema_completeness,
)
from .reward import (
    LEGACY_CONSTRAINED_REWARD_SHA256,
    LEGACY_FEE_RATIO_REWARD_SHAPING_SHA256,
    LEGACY_REWARD_FUNCTIONS_SHA256,
    RewardComponents,
    compute_constrained_reward,
)

LIVE_GATE_STATUS = "blocked_human_only"
"""Constant safety invariant: live gate is always blocked_human_only here."""

RL_CORE_SUBPROJECT_PARTIALLY_MIGRATED = (
    "SUBPROJECT_1_RL_CORE_PARTIALLY_MIGRATED_PAPER_ONLY"
)
RL_CORE_SUBPROJECT_BLOCKED = "SUBPROJECT_1_RL_CORE_BLOCKED"

# SHA256 of additional legacy files cited as informational (not ported here).
_LEGACY_ENVIRONMENT_SHA256 = (
    "39866005417554c7f9552a64eddc14ec1024db7e22b432c844cfd1a8e7800b1d"
)
_LEGACY_GYM_WRAPPER_SHA256 = (
    "61a086cb4a0a406ca67fe2035cf776b0c991bb9d7391572ce86e77aea0a16574"
)
_LEGACY_MASA_AGENT_SHA256 = (
    "0c7496336ca00c0f006d9a294ea67e736e2c3f2a3e4202b98cd6925dff891080"
)
_LEGACY_ENHANCED_ARCH_SHA256 = (
    "d7b2071a6c83edee5eb940d50e5578fb0b4dd14d54f9e577c65d2533409b8236"
)
_LEGACY_HYBRID_TRAINER_SHA256 = (
    "b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102"
)
_LEGACY_CALIBRATED_CONF_SHA256 = (
    "03c56d7e3345444e9f285de3bee596573b3ca8d05ee4f3a26aef56e032806d90"
)
_LEGACY_TEMPERATURE_CALIBRATION_SHA256 = (
    "302355f82bbed15dd4db75600eb058406a0a08bd44ef86ef44f19c43f54cc221"
)


def calibrate_confidence(
    raw_logit: float, temperature: float, *, calibration_enabled: bool = True
) -> dict[str, float | bool]:
    """Apply temperature scaling to a raw logit and return diagnostics.

    Ported math from
    ``v2/legacy_preserved/full_runtime_closure/rl/calibrated_confidence.py``
    (sha256 ``03c56d7e3345444e9f285de3bee596573b3ca8d05ee4f3a26aef56e032806d90``).

    Behavior:

    - If ``calibration_enabled`` is False, or temperature is ``None``/<=0/NaN,
      the function returns the raw sigmoid probability (identity fallback).
    - Otherwise applies ``logit / T`` then sigmoid. T=1 is identity; T>1 is
      softer (closer to 0.5); T<1 is sharper.

    Args:
        raw_logit: pre-temperature logit.
        temperature: temperature parameter T (positive float).
        calibration_enabled: explicit feature flag, defaults to True.

    Returns:
        Dict with keys ``raw_prob``, ``calibrated_prob``, ``temperature``,
        ``used_calibration``, ``scaled_logit``.
    """
    try:
        logit_value = float(raw_logit)
    except (TypeError, ValueError):
        logit_value = 0.0

    def _sigmoid(x: float) -> float:
        # Numerically stable sigmoid.
        if x >= 0:
            z = math.exp(-x)
            return 1.0 / (1.0 + z)
        z = math.exp(x)
        return z / (1.0 + z)

    raw_prob = _sigmoid(logit_value)

    try:
        temp_value = float(temperature) if temperature is not None else None
    except (TypeError, ValueError):
        temp_value = None
    bad_temp = (
        temp_value is None
        or temp_value <= 0.0
        or math.isnan(temp_value)
        or math.isinf(temp_value)
    )

    if not calibration_enabled or bad_temp:
        return {
            "raw_prob": float(raw_prob),
            "calibrated_prob": float(raw_prob),
            "temperature": float(temp_value) if temp_value is not None else 1.0,
            "used_calibration": False,
            "scaled_logit": float(logit_value),
        }

    assert temp_value is not None  # for type checkers
    scaled_logit = logit_value / temp_value
    calibrated = _sigmoid(scaled_logit)
    used = abs(temp_value - 1.0) > 1e-12
    return {
        "raw_prob": float(raw_prob),
        "calibrated_prob": float(calibrated),
        "temperature": float(temp_value),
        "used_calibration": bool(used),
        "scaled_logit": float(scaled_logit),
    }


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
    )


class RLCoreService:
    """Paper-only facade over the partially-ported RL core."""

    def __init__(self, *, now_iso: Optional[str] = None) -> None:
        self._now_iso = now_iso

    # ------------------------------------------------------------------ #
    # Observation
    # ------------------------------------------------------------------ #
    def build_observation_status(self) -> dict[str, Any]:
        """Return a snapshot of the V2 observation schema completeness."""
        summary = observation_schema_completeness()
        return {
            "fields": list(observation_field_names()),
            **summary,
        }

    # ------------------------------------------------------------------ #
    # Reward
    # ------------------------------------------------------------------ #
    def compute_reward_for_paper_outcome(
        self, outcome: dict[str, Any]
    ) -> RewardComponents:
        """Wire a paper outcome dict to :func:`compute_constrained_reward`.

        Recognized keys (all optional except ``realized_pnl`` for trades):

        - ``realized_pnl``
        - ``notional_usd``
        - ``fee_bps``
        - ``slippage_bps``
        - ``expected_move_bps``
        - ``drawdown_pct``
        - ``trade_executed``
        - ``no_trade_outcome_bps``
        """
        return compute_constrained_reward(
            realized_pnl=outcome.get("realized_pnl", 0.0),
            notional_usd=outcome.get("notional_usd", 0.0),
            fee_bps=outcome.get("fee_bps", 0.0),
            slippage_bps=outcome.get("slippage_bps", 0.0),
            expected_move_bps=outcome.get("expected_move_bps", 0.0),
            drawdown_pct=outcome.get("drawdown_pct", 0.0),
            trade_executed=bool(outcome.get("trade_executed", True)),
            no_trade_outcome_bps=outcome.get("no_trade_outcome_bps", 0.0),
        )

    # ------------------------------------------------------------------ #
    # Checkpoint
    # ------------------------------------------------------------------ #
    def parse_checkpoint(
        self, path_str: str, *, sha256_if_known: Optional[str] = None
    ) -> Optional[CheckpointMetadata]:
        """Parse a legacy checkpoint filename without loading weights."""
        return parse_legacy_checkpoint_filename(
            path_str, sha256_if_known=sha256_if_known
        )

    # ------------------------------------------------------------------ #
    # Confidence
    # ------------------------------------------------------------------ #
    def calibrate_confidence(
        self,
        raw_logit: float,
        temperature: float,
        *,
        calibration_enabled: bool = True,
    ) -> dict[str, float | bool]:
        return calibrate_confidence(
            raw_logit, temperature, calibration_enabled=calibration_enabled
        )

    # ------------------------------------------------------------------ #
    # Public payload
    # ------------------------------------------------------------------ #
    def current_paper_only_status(self) -> dict[str, Any]:
        """Build the JSON payload written by the CLI worker.

        Safety invariants are intentionally hard-coded here. Any caller that
        tries to flip them must edit the source.
        """
        components_present = [
            "observation_schema_descriptor",
            "constrained_reward_paper",
            "fee_ratio_shaping_paper",
            "drawdown_penalty_paper",
            "no_trade_correct_credit_paper",
            "checkpoint_metadata_filename_parser",
            "temperature_calibration_math",
        ]
        components_missing = [
            "ppo_masa_policy_network_MISSING_IN_V2",
            "gymnasium_env_step_reset_loop_MISSING_IN_V2",
            "gpu_training_loop_MISSING_IN_V2",
            "unified_feature_builder_tensor_assembly_MISSING_IN_V2",
            "checkpoint_weight_loader_MISSING_IN_V2",
            "lagrangian_multiplier_state_persistence_MISSING_IN_V2",
        ]
        legacy_sha256_citations = {
            "rl/obs_schema.py": LEGACY_OBS_SHA256,
            "rl/reward_functions.py": LEGACY_REWARD_FUNCTIONS_SHA256,
            "rl/constrained_reward.py": LEGACY_CONSTRAINED_REWARD_SHA256,
            "rl/fee_ratio_reward_shaping.py": LEGACY_FEE_RATIO_REWARD_SHAPING_SHA256,
            "rl/calibrated_confidence.py": _LEGACY_CALIBRATED_CONF_SHA256,
            "rl/temperature_calibration.py": _LEGACY_TEMPERATURE_CALIBRATION_SHA256,
            "rl/environment.py": _LEGACY_ENVIRONMENT_SHA256,
            "rl/gymnasium_wrapper.py": _LEGACY_GYM_WRAPPER_SHA256,
            "rl/agents/masa_agent.py": _LEGACY_MASA_AGENT_SHA256,
            "rl/enhanced_architectures.py": _LEGACY_ENHANCED_ARCH_SHA256,
            "rl/hybrid_trainer.py": _LEGACY_HYBRID_TRAINER_SHA256,
        }
        return {
            "subproject": "1_rl_core",
            "subproject_label": "v2_native_algorithmic_core_migration/subproject_1_rl_core",
            "scope": "PAPER_ONLY",
            "live_gate": LIVE_GATE_STATUS,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "evidence_classification": "PARTIALLY_MIGRATED",
            "go_no_go": RL_CORE_SUBPROJECT_PARTIALLY_MIGRATED,
            "components_present": components_present,
            "components_missing": components_missing,
            "observation_schema_summary": observation_schema_completeness(),
            "legacy_sha256_citations": legacy_sha256_citations,
            "config_env_mapping": {
                "OBS_SCHEMA_VERSION": "informational only, not a V2 runtime knob",
                "rl:config:features:calibrated_confidence": (
                    "legacy Redis hash key referenced; V2 does NOT read or write it"
                ),
                "rl:calibration:temperature": (
                    "legacy Redis hash key referenced; V2 does NOT read or write it"
                ),
            },
            "safety_invariants": {
                "no_legacy_redis_writes": True,
                "no_exchange_mutation": True,
                "no_policy_weight_loading": True,
                "no_training_loop": True,
                "paper_only": True,
            },
            "generated_at": self._now_iso or _utc_now_iso(),
            "generated_utc": self._now_iso or _utc_now_iso(),
        }

    # ------------------------------------------------------------------ #
    # Convenience: write payload to disk
    # ------------------------------------------------------------------ #
    def write_status_payload(self, destination: Path) -> Path:
        """Atomically write the status payload to ``destination``.

        Creates parent directories. Returns the resolved destination path.
        """
        import json
        import os
        import tempfile

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self.current_paper_only_status()
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(destination.parent),
            prefix=destination.name + ".",
            suffix=".tmp",
            delete=False,
        ) as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            tmp_path = Path(fh.name)
        os.replace(tmp_path, destination)
        return destination


# Re-exports for convenience and documentation.
__all__ = [
    "LIVE_GATE_STATUS",
    "RL_CORE_SUBPROJECT_BLOCKED",
    "RL_CORE_SUBPROJECT_PARTIALLY_MIGRATED",
    "RLCoreService",
    "V2_OBSERVATION_SCHEMA",
    "calibrate_confidence",
]
