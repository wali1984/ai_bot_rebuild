"""Operational escalation supervisor — FINAL PASS operator item #2.

The guiding correction this module encodes:

    A persistent FLAT policy output must NEVER be interpreted as "wait for more
    data".  It is a *failure of the current policy to discover edge* and MUST
    deterministically drive one of two outcomes:

      1. LAUNCH_WORKER      — dispatch a REAL, named, tracked adaptation worker
                              (recalibrate / incrementally train / rebuild
                              features / horizon-symbol-regime-arch challengers /
                              alternative strategy families / hedged policies /
                              bounded information-seeking exploration / promote a
                              superior challenger), OR
      2. AWAITING_TRIGGER   — only when every controllable lever this cycle is
                              exhausted; and even then it persists the EXACT
                              quantitative condition that will unblock the next
                              worker (e.g. ``matured_outcomes >= 4161`` or
                              ``effective_N >= 206.0``) — never a passive wait.

The step-selection ladder itself is NOT reimplemented here — it is delegated to
``escalation_ladder_v2.decide`` (the pure state machine).  This module adds the
LAUNCH-vs-AWAIT wrapper, the corpus-information-gain test, the worker-command
mapping, and the Redis/ledger runtime plumbing.

Paper-only.  Planning remains side-effect free.  When explicitly enabled, the
durable dispatcher below may run an exact non-activating challenger command
after authenticating its dataset release and persisting a single-run receipt.
It never places an order, activates a checkpoint, or touches the live gate.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import importlib.util
import json
import logging
import os
import stat
import subprocess
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

from v2.backend.app.services.adaptive_system.escalation_ladder_v2 import (
    LADDER,
    PROHIBITED_TERMINAL_RESPONSES,
    EscalationDecision,
    decide,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "escalation_supervisor_v2"
STATUS_REDIS_KEY = "v2:adaptive_system:escalation_supervisor:status"
DEFAULT_LEDGER_PATH = Path("claude_worklog/adaptive_system/escalation_supervisor_ledger.jsonl")
DEFAULT_DISPATCH_ROOT = Path(
    "/home/wali/ai_bot_local_data/adaptive_candidate_dataset_v3/escalation_dispatches"
)
DEFAULT_DISPATCH_STATE_PATH = Path(
    "/home/wali/ai_bot_local_data/adaptive_candidate_dataset_v3/"
    "escalation_dispatch_state_v1.json"
)
DEFAULT_DISPATCH_LOCK_PATH = Path(
    "/run/user/1000/ai-bot-v2-adaptive-escalation-dispatch.lock"
)
DISPATCH_SCHEMA_VERSION = "adaptive_escalation_dispatch_v1"
DISPATCH_TIMEOUT_SECONDS = 3600

# Authoritative source keys (read-only) — the adaptive-policy authority publishes
# per-cycle directional/flat authorization counts; the candidate-outcome publisher
# publishes matured-outcome counts under a nested ``maturation`` object.
POLICY_AUTHORITY_STATUS_KEY = "v2:adaptive_system:paper_policy_authority:status"
CANDIDATE_OUTCOMES_STATUS_KEY = "v2:adaptive_system:candidate_outcomes:status"
CHAMPION_CHALLENGER_STATUS_KEY = "v2:trainer:champion_challenger_status"

# Latest gen-5 serving-compatible dataset (corpus effective-N is computed from it).
DEFAULT_GEN5_DATASET = Path(
    "/home/wali/ai_bot_local_data/gen5_snapshot_backfill_v1/gen5_model/"
    "serving_compatible_dataset_v2.json"
)
DEFAULT_GEN5_MANIFEST = Path(
    "/home/wali/ai_bot_local_data/gen5_snapshot_backfill_v1/gen5_model/"
    "serving_compatible_dataset_manifest_v2.json"
)

# Action verbs the supervisor may emit.
ACTION_LAUNCH = "LAUNCH_WORKER"
ACTION_AWAIT = "AWAITING_TRIGGER"
ACTION_NO_ESCALATION = "NO_ESCALATION_POLICY_HEALTHY"

# The prohibited passive responses.  An AWAITING_TRIGGER that does not carry an
# exact numeric threshold + metric (or a named external resolution) is a passive
# wait and is rejected by ``EscalationWorkPlan.validate``.
PASSIVE_WAIT_MARKERS = (
    "wait for more data",
    "wait for data",
    "waiting for data",
    "wait for the market",
    "wait for market",
    "insufficient data",
    "more data needed",
    "leave stack running",
    "leave running",
    "external market opportunity",
    "no positive edge",
)

# Ladder steps that CONSUME new training information (matured outcomes / larger
# effective sample). They are only launchable when new information exists; when it
# does not, they define the exact numeric trigger the supervisor awaits.
INFO_DEPENDENT_STEPS: frozenset[str] = frozenset(
    {
        "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES",
        "REBUILD_FEATURE_SELECTION_OR_REPRESENTATION",
        "TRAIN_HORIZON_SPECIFIC_CHALLENGERS",
        "TRAIN_SYMBOL_OR_REGIME_SPECIFIC_CHALLENGERS",
        "TRAIN_ALTERNATIVE_MODEL_ARCHITECTURES",
        "TRAIN_HEDGED_AND_RELATIVE_VALUE_POLICIES",
    }
)

# The first info-dependent step is what an AWAITING_TRIGGER promises to launch
# once its numeric threshold is met.
FIRST_INFO_DEPENDENT_STEP = "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES"

# Real, in-repo worker descriptors per ladder step.  ``argv`` uses ONLY flags that
# exist on the referenced entrypoint; ``scope`` carries the intent the executor
# resolves.  These are DESCRIPTORS — a separate operator/service executes them.
_VENV_PY = ".venv/bin/python"
_SIGNED_DATASET = "{dataset_release_root}/adaptive_serving_compatible_dataset_v2.json"
_SIGNED_MANIFEST = (
    "{dataset_release_root}/adaptive_serving_compatible_dataset_manifest_v2.json"
)
_SIGNED_PARITY = (
    "{dataset_release_root}/adaptive_train_serve_feature_parity_report_v2.json"
)
_SIGNED_RECEIPT = (
    "{dataset_release_root}/candidate_outcome_dataset_build_receipt_v3.json"
)
_DISPATCH_MODELS = "{dispatch_run_root}/models"
_DISPATCH_EVIDENCE = "{dispatch_run_root}/evidence"


def _worker(
    step: str, entrypoint: str, kind: str, argv: Sequence[str], scope: str, desc: str
) -> dict:
    return {
        "ladder_step": step,
        "entrypoint": entrypoint,
        "entrypoint_kind": kind,  # "script" (path) or "module" (-m importable)
        "argv": list(argv),
        "scope": scope,
        "description": desc,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
        "exchange_action_taken": False,
    }


WORKER_COMMANDS: Mapping[str, dict] = {
    "RECALIBRATE_CURRENT_MODELS": _worker(
        "RECALIBRATE_CURRENT_MODELS",
        "scripts/train_serving_profitability_v3_checkpoint.py",
        "script",
        (
            _VENV_PY,
            "scripts/train_serving_profitability_v3_checkpoint.py",
            "--dataset",
            _SIGNED_DATASET,
            "--manifest",
            _SIGNED_MANIFEST,
            "--parity",
            _SIGNED_PARITY,
            "--build-receipt",
            _SIGNED_RECEIPT,
            "--model-dir",
            _DISPATCH_MODELS,
            "--evidence-dir",
            _DISPATCH_EVIDENCE,
        ),
        "confidence_recalibration_via_checkpoint_refit",
        # Standalone external confidence calibration (the former
        # v2_trainer_fit_confidence_calibration command) is a deprecated,
        # fail-closed no-op: fitting calibration from a held-out slice leaks
        # forward validation into inference (CG-F053). The only real, non-leaking
        # recalibration is a bounded serving-checkpoint refit that fits the
        # calibration head IN-checkpoint from the purged matured-outcome partition.
        "Recalibrate confidence via a bounded serving-checkpoint refit that fits "
        "calibration in-checkpoint from matured outcomes (standalone external "
        "calibration is leakage-unsafe/deprecated per CG-F053).",
    ),
    "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES": _worker(
        "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES",
        "scripts/train_serving_profitability_v3_checkpoint.py",
        "script",
        (
            _VENV_PY,
            "scripts/train_serving_profitability_v3_checkpoint.py",
            "--dataset",
            _SIGNED_DATASET,
            "--manifest",
            _SIGNED_MANIFEST,
            "--parity",
            _SIGNED_PARITY,
            "--build-receipt",
            _SIGNED_RECEIPT,
            "--model-dir",
            _DISPATCH_MODELS,
            "--evidence-dir",
            _DISPATCH_EVIDENCE,
        ),
        "gen5_serving_checkpoint_incremental_train",
        "Retrain the serving-profitability-v3 challenger on the incrementally "
        "expanded authenticated matured-outcome corpus.",
    ),
    "REBUILD_FEATURE_SELECTION_OR_REPRESENTATION": _worker(
        "REBUILD_FEATURE_SELECTION_OR_REPRESENTATION",
        "v2.backend.app.cli.v2_native_trainer_dataset_builder",
        "module",
        (_VENV_PY, "-m", "v2.backend.app.cli.v2_native_trainer_dataset_builder"),
        "feature_representation_rebuild",
        "Rebuild the training dataset / feature representation from matured outcomes.",
    ),
    "TRAIN_HORIZON_SPECIFIC_CHALLENGERS": _worker(
        "TRAIN_HORIZON_SPECIFIC_CHALLENGERS",
        "v2.backend.app.cli.v2_challenger_v2_reproducible_pipeline",
        "module",
        (_VENV_PY, "-m", "v2.backend.app.cli.v2_challenger_v2_reproducible_pipeline"),
        "horizon_scoped_challenger",
        "Train horizon-specific challengers against the current champion.",
    ),
    "TRAIN_SYMBOL_OR_REGIME_SPECIFIC_CHALLENGERS": _worker(
        "TRAIN_SYMBOL_OR_REGIME_SPECIFIC_CHALLENGERS",
        "v2.backend.app.cli.v2_model_edge_recovery_champion_challenger",
        "module",
        (_VENV_PY, "-m", "v2.backend.app.cli.v2_model_edge_recovery_champion_challenger"),
        "symbol_or_regime_scoped_challenger",
        "Train symbol/regime-scoped challengers for edge recovery.",
    ),
    "TRAIN_ALTERNATIVE_MODEL_ARCHITECTURES": _worker(
        "TRAIN_ALTERNATIVE_MODEL_ARCHITECTURES",
        "v2.backend.app.cli.v2_challenger_v2_reproducible_pipeline",
        "module",
        (_VENV_PY, "-m", "v2.backend.app.cli.v2_challenger_v2_reproducible_pipeline"),
        "alternative_architecture_challenger",
        "Train alternative model-architecture challengers under the same corpus.",
    ),
    "ACTIVATE_ALTERNATIVE_STRATEGY_FAMILIES": _worker(
        "ACTIVATE_ALTERNATIVE_STRATEGY_FAMILIES",
        "v2.backend.app.cli.v2_strategy_supply_runtime_evaluator",
        "module",
        (
            _VENV_PY,
            "-m",
            "v2.backend.app.cli.v2_strategy_supply_runtime_evaluator",
            "--max-age-seconds",
            "180",
        ),
        "alternative_strategy_family_runtime_evaluation",
        "Read and authenticate the existing canonical strategy-family supply; "
        "never start a duplicate publisher or write its Redis keys.",
    ),
    "TRAIN_HEDGED_AND_RELATIVE_VALUE_POLICIES": _worker(
        "TRAIN_HEDGED_AND_RELATIVE_VALUE_POLICIES",
        "v2.backend.app.cli.v2_runtime_alpha_remediated_dynamic_strategy_leverage_margin",
        "module",
        (
            _VENV_PY,
            "-m",
            "v2.backend.app.cli.v2_runtime_alpha_remediated_dynamic_strategy_leverage_margin",
        ),
        "hedged_relative_value_policy",
        "Evaluate hedged / relative-value policy families (paper).",
    ),
    "INCREASE_BOUNDED_INFORMATION_SEEKING_EXPLORATION": _worker(
        "INCREASE_BOUNDED_INFORMATION_SEEKING_EXPLORATION",
        "v2.backend.app.cli.v2_bounded_exploration_runtime_evaluator",
        "module",
        (
            _VENV_PY,
            "-m",
            "v2.backend.app.cli.v2_bounded_exploration_runtime_evaluator",
            "--max-authority-age-seconds",
            "300",
        ),
        "bounded_information_seeking_exploration_limit_evaluation",
        "Authenticate that adaptive information-seeking already reached its "
        "configured paper-only bound; fail when controllable increase remains.",
    ),
    "PROMOTE_SUPERIOR_CHALLENGER": _worker(
        "PROMOTE_SUPERIOR_CHALLENGER",
        "v2.backend.app.cli.v2_checkpoint_promotion_status",
        "module",
        (
            _VENV_PY,
            "-m",
            "v2.backend.app.cli.v2_checkpoint_promotion_status",
            "--once",
        ),
        "governed_promotion_readiness",
        "Recompute governed paper promotion readiness for a challenger that "
        "already proved superiority. Registry activation remains fail-closed "
        "until its independent smoke and atomic-CAS predicates pass.",
    ),
}


# --------------------------------------------------------------------------- #
# Corpus effective independent-N (Kish) — reuse of the logic in
# scripts/gen5_corpus_diversity.py (decision-minute grouping + Kish n_eff).
# --------------------------------------------------------------------------- #
def _decision_minute(decision_time: str) -> str:
    """Bucket a decision timestamp to the minute (YYYY-MM-DDTHH:MM)."""
    return str(decision_time)[:16]


def kish_effective_n(decision_times: Sequence[str]) -> float:
    """Kish effective independent sample size over decision-minute groups.

    ``n_eff = (sum n_g)^2 / sum(n_g^2)`` — collapses toward the number of distinct
    decision-minutes when rows cluster at the same timestamp across symbols.  This
    mirrors scripts/gen5_corpus_diversity.py exactly (same minute bucketing and
    same Kish formula) so the supervisor's "effective N" matches the corpus report.
    """
    if not decision_times:
        return 0.0
    per_ts = Counter(_decision_minute(t) for t in decision_times)
    sizes = list(per_ts.values())
    sum_n = sum(sizes)
    sum_n2 = sum(n * n for n in sizes)
    if sum_n2 <= 0:
        return 0.0
    return round((sum_n * sum_n) / sum_n2, 1)


def load_gen5_corpus_effective_n(dataset_path: Path = DEFAULT_GEN5_DATASET) -> tuple[float, int]:
    """Return (effective_N, row_count) for the latest gen-5 dataset.

    Reads decision_time per row and computes the Kish effective-N.  Returns
    (0.0, 0) when the dataset is absent (missing corpus is a real, honest state,
    never silently treated as edge).
    """
    p = Path(dataset_path)
    if not p.exists():
        return 0.0, 0
    ds = json.loads(p.read_text())
    rows = ds.get("rows") or []
    times = [r.get("decision_time", "") for r in rows]
    return kish_effective_n(times), len(rows)


def _dataset_identity(dataset_path: Path) -> str:
    path = Path(dataset_path)
    if not path.is_file():
        return ""
    try:
        dataset = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    identity = dataset.get("dataset_sha256") if isinstance(dataset, dict) else None
    return identity if isinstance(identity, str) else ""


# --------------------------------------------------------------------------- #
# Pure decision core
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SupervisorInputs:
    """Everything the pure planner needs — all explicit, all Redis-independent."""

    # Policy-authority signal (per current cycle).
    directional_authorized_count: int
    flat_authorized_count: int
    candidate_count: int
    # Persistence of the flat state across recent supervisor cycles.
    persistent_flat_cycles: int
    min_persistent_flat_cycles: int = 3
    # Corpus / matured-outcome information state.
    matured_outcome_count: int = 0
    effective_n: float = 0.0
    baseline_matured_outcome_count: int | None = None
    baseline_effective_n: float | None = None
    min_new_matured_outcomes: int = 250
    min_new_effective_n: float = 25.0
    # Optional after-cost edge (bps); negative -> negative_after_cost_edge trigger.
    after_cost_edge_bps: float | None = None
    # Promotion availability + already-attempted steps this escalation cycle.
    superior_challenger_available: bool = False
    exhausted_steps: frozenset[str] = field(default_factory=frozenset)
    # A signed release may remain a valid input for later, not-yet-attempted
    # representation/model-family workers even after the incremental trainer has
    # consumed its information gain and advanced the training high-water mark.
    # Without this explicit release-scoped availability, advancing the baseline
    # after incremental training makes every later information-dependent ladder
    # rung unavailable and silently starves the escalation sequence.
    release_scoped_information_steps: frozenset[str] = field(default_factory=frozenset)
    # Provenance + external gating.
    input_manifest_sha: str = ""
    external_blocker: str | None = None

    def new_matured_since_baseline(self) -> int:
        return self.matured_outcome_count - int(self.baseline_matured_outcome_count or 0)

    def new_effective_n_since_baseline(self) -> float:
        return self.effective_n - float(self.baseline_effective_n or 0.0)

    def new_information_exists(self) -> bool:
        """New training information exists since the last recorded challenger."""
        return (
            self.new_matured_since_baseline() >= self.min_new_matured_outcomes
            or self.new_effective_n_since_baseline() >= self.min_new_effective_n
        )

    def matured_threshold(self) -> int:
        return int(self.baseline_matured_outcome_count or 0) + self.min_new_matured_outcomes

    def effective_n_threshold(self) -> float:
        return round(float(self.baseline_effective_n or 0.0) + self.min_new_effective_n, 1)


def derive_conditions(inp: SupervisorInputs) -> dict[str, bool]:
    """Map the runtime inputs onto ``escalation_ladder_v2`` trigger conditions.

    Only the four operator-item-#2 conditions are produced here; each is a member
    of ``escalation_ladder_v2.TRIGGER_CONDITIONS``.
    """
    persistent_flat = (
        inp.directional_authorized_count == 0
        and inp.persistent_flat_cycles >= inp.min_persistent_flat_cycles
    )
    info_gain = inp.new_information_exists()
    return {
        # Persistently flat AND no new information to learn from -> the genuinely
        # information-gated case (drives the exact-threshold AWAIT).
        "persistent_flat_without_information_gain": persistent_flat and not info_gain,
        # Zero directional authorizations while candidates exist -> policy is
        # producing only FLAT despite having material to act on.
        "admission_starved": inp.directional_authorized_count == 0 and inp.candidate_count > 0,
        # The corpus has not grown meaningfully since the last recorded challenger.
        "corpus_stagnation": (
            inp.new_effective_n_since_baseline() < inp.min_new_effective_n
            and inp.new_matured_since_baseline() < inp.min_new_matured_outcomes
        ),
        # After-cost edge is negative (when measured).
        "negative_after_cost_edge": (
            inp.after_cost_edge_bps is not None and inp.after_cost_edge_bps < 0.0
        ),
    }


def _controllable_available(inp: SupervisorInputs) -> dict[str, bool]:
    """Per-step availability handed to ``decide``.

    Recalibration needs SOME matured outcomes; the info-dependent training steps
    need NEW information; promotion needs a proven superior challenger.  Config /
    information-GENERATING steps (alt strategy family, bounded exploration) stay
    available so the ladder always has a controllable action before it can await.
    """
    info_gain = inp.new_information_exists()
    available: dict[str, bool] = {}
    available["RECALIBRATE_CURRENT_MODELS"] = inp.matured_outcome_count > 0
    for step in INFO_DEPENDENT_STEPS:
        available[step] = info_gain or step in inp.release_scoped_information_steps
    available["PROMOTE_SUPERIOR_CHALLENGER"] = inp.superior_challenger_available
    return available


def _next_ladder_step(step: str | None) -> str | None:
    if step is None or step not in LADDER:
        return None
    idx = LADDER.index(step)
    return LADDER[idx + 1] if idx + 1 < len(LADDER) else None


@dataclass(frozen=True)
class EscalationWorkPlan:
    trigger: Sequence[str]
    interpretation: str
    action: str
    selected_step: str | None
    next_step: str | None
    worker_command: dict | None
    exact_trigger_condition: str | None
    input_manifest_sha: str
    is_operator_gated: bool
    external_blocker: str | None
    rationale: str
    decision: EscalationDecision
    failure_cycle_id: str | None = None
    schema_version: str = SCHEMA_VERSION

    # ------------------------------------------------------------------ #
    def validate(self) -> list[str]:
        r: list[str] = []
        if self.action not in (ACTION_LAUNCH, ACTION_AWAIT, ACTION_NO_ESCALATION):
            r.append(f"UNKNOWN_ACTION:{self.action}")

        # No prohibited terminal / passive-wait language anywhere.
        scan_fields = (
            self.interpretation,
            self.exact_trigger_condition or "",
            self.rationale,
            str(self.selected_step or ""),
        )
        blob = " ".join(scan_fields).lower()
        for bad in PROHIBITED_TERMINAL_RESPONSES:
            if bad.lower() in blob:
                r.append(f"PROHIBITED_TERMINAL_RESPONSE_EMITTED:{bad}")
        for marker in PASSIVE_WAIT_MARKERS:
            if marker in blob:
                r.append(f"PASSIVE_WAIT_LANGUAGE_EMITTED:{marker}")

        if self.action == ACTION_LAUNCH:
            if self.selected_step not in LADDER:
                r.append("LAUNCH_WITHOUT_LADDER_STEP")
            if not self.worker_command:
                r.append("LAUNCH_WITHOUT_WORKER_COMMAND")

        if self.action == ACTION_AWAIT:
            cond = self.exact_trigger_condition or ""
            if not cond:
                r.append("AWAIT_WITHOUT_TRIGGER_CONDITION")
            elif self.is_operator_gated:
                # Operator-gated: must name the exact external resolution, not a wait.
                if "operator_resolves:" not in cond:
                    r.append("OPERATOR_GATED_AWAIT_WITHOUT_NAMED_RESOLUTION")
            else:
                # Data-gated: MUST carry a numeric threshold + a comparison + a metric.
                has_digit = any(ch.isdigit() for ch in cond)
                has_cmp = ">=" in cond or ">" in cond or "==" in cond
                has_metric = "matured_outcomes" in cond or "effective_N" in cond
                if not (has_digit and has_cmp and has_metric):
                    r.append(f"AWAIT_TRIGGER_NOT_QUANTITATIVE:{cond!r}")
            # An AWAIT must still point at the worker it will launch next.
            if self.next_step is None:
                r.append("AWAIT_WITHOUT_NEXT_STEP")

        # Escalation is never terminal: a triggered plan always carries a forward
        # action (launch a worker now, or an exact trigger + the step it unblocks).
        if self.trigger and self.action == ACTION_AWAIT and self.next_step is None:
            r.append("TERMINAL_AWAIT_WITHOUT_FORWARD_STEP")
        return r

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "redis_key": STATUS_REDIS_KEY,
            "trigger": list(self.trigger),
            "interpretation": self.interpretation,
            "action": self.action,
            "selected_step": self.selected_step,
            "next_step": self.next_step,
            "worker_command": self.worker_command,
            "exact_trigger_condition": self.exact_trigger_condition,
            "input_manifest_sha": self.input_manifest_sha,
            "is_operator_gated": self.is_operator_gated,
            "external_blocker": self.external_blocker,
            "failure_cycle_id": self.failure_cycle_id,
            "rationale": self.rationale,
            "ladder_decision": {
                "next_action": self.decision.next_action,
                "ladder_step_index": self.decision.ladder_step_index,
                "is_operator_gated_stop": self.decision.is_operator_gated_stop,
                "interpretation": self.decision.interpretation,
            },
            "validation_errors": self.validate(),
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }


def plan_escalation(inp: SupervisorInputs) -> EscalationWorkPlan:
    """Pure planner: conditions -> ladder step -> LAUNCH_WORKER | AWAITING_TRIGGER.

    Delegates step SELECTION to ``escalation_ladder_v2.decide`` and wraps it with
    the launch-vs-await policy.  Never emits a passive wait; an AWAIT always
    carries the exact numeric threshold (or a named external resolution).
    """
    conditions = derive_conditions(inp)
    available = _controllable_available(inp)
    exhausted = frozenset(inp.exhausted_steps)

    decision = decide(
        conditions=conditions,
        exhausted_steps=set(exhausted),
        controllable_available=available,
        external_blocker=inp.external_blocker,
    )

    active_triggers = sorted(c for c, on in conditions.items() if on)

    # No trigger at all -> policy is healthy; this is NOT a passive wait.
    if not decision.triggered:
        return EscalationWorkPlan(
            trigger=[],
            interpretation=decision.interpretation,
            action=ACTION_NO_ESCALATION,
            selected_step=None,
            next_step=None,
            worker_command=None,
            exact_trigger_condition=None,
            input_manifest_sha=inp.input_manifest_sha,
            is_operator_gated=False,
            external_blocker=None,
            rationale=(
                "No adaptation trigger condition detected "
                f"(directional_authorized={inp.directional_authorized_count}); "
                "continue exploitation + monitoring."
            ),
            decision=decision,
        )

    # Is there ANY controllable step that is neither exhausted nor unavailable?
    actionable = [s for s in LADDER if s not in exhausted and available.get(s, True)]

    # Case A: every controllable lever is exhausted/unavailable AND the sole
    # remaining blocker is genuinely external -> operator-gated AWAIT with a named
    # resolution (still not a passive market wait).
    if decision.is_operator_gated_stop and decision.external_blocker:
        return EscalationWorkPlan(
            trigger=active_triggers,
            interpretation=decision.interpretation,
            action=ACTION_AWAIT,
            selected_step=None,
            next_step=FIRST_INFO_DEPENDENT_STEP,
            worker_command=None,
            exact_trigger_condition=f"operator_resolves:{decision.external_blocker}",
            input_manifest_sha=inp.input_manifest_sha,
            is_operator_gated=True,
            external_blocker=decision.external_blocker,
            rationale=(
                "All controllable escalation levers exhausted/unavailable; the "
                f"remaining blocker is external ({decision.external_blocker}). "
                "Policy failed to discover edge — this is NOT a market verdict."
            ),
            decision=decision,
        )

    # Case B: nothing controllable is actionable this cycle and it is a DATA gate
    # (no new information to train on, cheaper levers already exhausted) -> AWAIT
    # with the EXACT numeric threshold that unblocks the next training worker.
    if not actionable:
        cond = (
            f"matured_outcomes >= {inp.matured_threshold()} "
            f"OR effective_N >= {inp.effective_n_threshold()}"
        )
        return EscalationWorkPlan(
            trigger=active_triggers,
            interpretation="CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE",
            action=ACTION_AWAIT,
            selected_step=FIRST_INFO_DEPENDENT_STEP,
            next_step=FIRST_INFO_DEPENDENT_STEP,
            worker_command=None,
            exact_trigger_condition=cond,
            input_manifest_sha=inp.input_manifest_sha,
            is_operator_gated=False,
            external_blocker=None,
            rationale=(
                "Every controllable lever exhausted this cycle and no NEW training "
                f"information exists (matured={inp.matured_outcome_count}, "
                f"effective_N={inp.effective_n}, baseline_matured="
                f"{inp.baseline_matured_outcome_count}, baseline_effective_N="
                f"{inp.baseline_effective_n}). Awaiting an EXACT data threshold, "
                "not a passive wait — the next training worker fires on: " + cond
            ),
            decision=decision,
        )

    # Case C: a controllable step is actionable -> LAUNCH the real worker now.
    selected = decision.next_action
    worker = dict(WORKER_COMMANDS[selected]) if selected in WORKER_COMMANDS else None
    return EscalationWorkPlan(
        trigger=active_triggers,
        interpretation=decision.interpretation,
        action=ACTION_LAUNCH,
        selected_step=selected,
        next_step=_next_ladder_step(selected),
        worker_command=worker,
        exact_trigger_condition=None,
        input_manifest_sha=inp.input_manifest_sha,
        is_operator_gated=False,
        external_blocker=None,
        rationale=(
            f"Trigger(s) {active_triggers} -> current policy failed to discover "
            f"edge; launching controllable worker '{selected}'. Persistent FLAT is "
            "a policy failure, not a reason to wait."
        ),
        decision=decision,
    )


# --------------------------------------------------------------------------- #
# Durable paper-only worker dispatch.  The planner above remains pure; callers
# must explicitly request execution.  Every training dispatch is bound to a
# loader-verified, Ed25519-signed dataset release and is idempotent by content.
# --------------------------------------------------------------------------- #
def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_regular_bytes(path: Path, field: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ValueError(f"{field}:REGULAR_FILE_REQUIRED") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"{field}:REGULAR_FILE_REQUIRED")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def _safe_directory(path: Path, field: str, *, create: bool) -> Path:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise ValueError(f"{field}:SAFE_DIRECTORY_REQUIRED") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{field}:SAFE_DIRECTORY_REQUIRED")
    return path.absolute()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic_private_json(path: Path, value: Mapping[str, Any]) -> None:
    parent = _safe_directory(path.parent, "dispatch_state_parent", create=True)
    if path.exists() or path.is_symlink():
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("dispatch_state_path:REGULAR_FILE_REQUIRED")
    data = _canonical_bytes(dict(value)) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600, follow_symlinks=False)
        _fsync_directory(parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _write_immutable_private_bytes(path: Path, data: bytes) -> str:
    parent = _safe_directory(path.parent, "dispatch_receipt_parent", create=True)
    digest = _sha256_bytes(data)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except FileExistsError:
        if _read_regular_bytes(path, "dispatch_receipt") != data:
            raise ValueError(f"dispatch_receipt:IMMUTABLE_COLLISION:{path}") from None
        return digest
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return digest


def _load_json_if_present(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(_read_regular_bytes(path, "dispatch_state_path"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("dispatch_state_path:STRICT_JSON_REQUIRED") from exc
    if type(value) is not dict:
        raise ValueError("dispatch_state_path:OBJECT_REQUIRED")
    return value


def _authenticated_dataset_release_evidence(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load one signed release snapshot and return projection + source counts.

    The source counts are taken from the receipt object returned by the signed
    artifact loader.  The receipt is never reopened later for authoritative
    fields, closing an auth-then-reread substitution window.
    """

    from v2.backend.app.services.prediction_serving.serving_training_artifact_v2 import (
        load_validated_training_artifacts,
    )

    release_root = _safe_directory(Path(root), "dataset_release_root", create=False)
    paths = {
        "dataset": release_root / "adaptive_serving_compatible_dataset_v2.json",
        "manifest": release_root
        / "adaptive_serving_compatible_dataset_manifest_v2.json",
        "parity": release_root
        / "adaptive_train_serve_feature_parity_report_v2.json",
        "build_receipt": release_root
        / "candidate_outcome_dataset_build_receipt_v3.json",
    }
    dataset, manifest, parity, receipt = load_validated_training_artifacts(
        dataset_path=paths["dataset"],
        manifest_path=paths["manifest"],
        parity_path=paths["parity"],
        build_receipt_path=paths["build_receipt"],
    )
    if receipt.get("schema_version") != "candidate_outcome_dataset_build_receipt_v3":
        raise ValueError("dataset_release_root:SIGNED_V3_RECEIPT_REQUIRED")
    receipt_bytes = _read_regular_bytes(paths["build_receipt"], "build_receipt")
    try:
        receipt_readback = json.loads(receipt_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("dataset_release_root:RECEIPT_READBACK_INVALID") from exc
    if receipt_readback != receipt:
        raise ValueError("dataset_release_root:RECEIPT_CHANGED_DURING_AUTHENTICATION")
    receipt_file_sha256 = _sha256_bytes(receipt_bytes)
    archive = receipt.get("candidate_archive_verification")
    if type(archive) is not dict:
        raise ValueError("dataset_release_root:ARCHIVE_VERIFICATION_REQUIRED")
    matured = archive.get("matured_revision_count")
    decisions = archive.get("decision_revision_count")
    terminal = archive.get("terminal_chain_sha256")
    if (
        type(matured) is not int
        or matured < 0
        or type(decisions) is not int
        or decisions < matured
        or type(terminal) is not str
        or len(terminal) != 64
    ):
        raise ValueError("dataset_release_root:SOURCE_COUNTS_INVALID")
    projection = {
        "root": str(release_root),
        "paths": {key: str(value) for key, value in paths.items()},
        "dataset_sha256": dataset["dataset_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "parity_sha256": _sha256_bytes(
            _read_regular_bytes(paths["parity"], "parity")
        ),
        "build_receipt_file_sha256": receipt_file_sha256,
        "source_terminal_chain_sha256": receipt["candidate_archive_verification"][
            "terminal_chain_sha256"
        ],
        "training_rows": receipt["training_rows"],
        "validation_rows": receipt["validation_rows"],
        "holdout_rows": receipt["holdout_rows"],
    }
    return projection, {
        "matured_revision_count": matured,
        "decision_revision_count": decisions,
        "terminal_chain_sha256": terminal,
    }


def _authenticated_dataset_release(root: Path) -> dict[str, Any]:
    projection, _source = _authenticated_dataset_release_evidence(root)
    return projection


def _resolved_worker_argv(
    worker: Mapping[str, Any],
    *,
    dataset_release_root: Path,
    dispatch_run_root: Path,
) -> list[str]:
    argv = worker.get("argv")
    if type(argv) is not list or not argv or any(type(item) is not str for item in argv):
        raise ValueError("worker_command:EXACT_ARGV_REQUIRED")
    replacements = {
        "dataset_release_root": str(dataset_release_root),
        "dispatch_run_root": str(dispatch_run_root),
    }
    resolved = [item.format_map(replacements) for item in argv]
    if resolved[0] != _VENV_PY:
        raise ValueError("worker_command:PINNED_PYTHON_REQUIRED")
    if any("train_serving_feature_abi_v2_checkpoint.py" in item for item in resolved):
        raise ValueError("worker_command:LEGACY_UNAUTHENTICATED_TRAINER_FORBIDDEN")
    if any("v2_trainer_h2l_promote" in item for item in resolved):
        raise ValueError("worker_command:LEGACY_H2L_PROMOTION_FORBIDDEN")
    return resolved


def _worker_code_sha256(worker: Mapping[str, Any]) -> str:
    entrypoint = worker.get("entrypoint")
    kind = worker.get("entrypoint_kind")
    if type(entrypoint) is not str or not entrypoint:
        raise ValueError("worker_command:ENTRYPOINT_REQUIRED")
    if kind == "script":
        path = Path(__file__).resolve().parents[5] / entrypoint
    elif kind == "module":
        spec = importlib.util.find_spec(entrypoint)
        if spec is None or spec.origin is None:
            raise ValueError("worker_command:IMPORTABLE_MODULE_REQUIRED")
        path = Path(spec.origin)
    else:
        raise ValueError("worker_command:ENTRYPOINT_KIND_INVALID")
    return _sha256_bytes(_read_regular_bytes(path, "worker_entrypoint"))


def _default_runner(
    argv: Sequence[str], timeout_seconds: int | float
) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - argv is descriptor-pinned and shell=False
        list(argv),
        cwd=Path(__file__).resolve().parents[5],
        check=False,
        capture_output=True,
        timeout=timeout_seconds,
        shell=False,
    )


def _result_bytes(value: object) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8", "replace")


def _replay_terminal_receipt(
    path: Path,
    *,
    dispatch_material: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        receipt = json.loads(_read_regular_bytes(path, "dispatch_terminal_receipt"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("dispatch_terminal_receipt:STRICT_JSON_REQUIRED") from exc
    if type(receipt) is not dict:
        raise ValueError("dispatch_terminal_receipt:OBJECT_REQUIRED")
    required_matches = (
        "schema_version",
        "selected_step",
        "trigger",
        "input_manifest_sha",
        "worker_scope",
        "worker_entrypoint",
        "worker_entrypoint_file_sha256",
        "worker_argv_template",
        "dataset_release",
        "argv",
        "dispatch_id",
        "failure_cycle_id",
    )
    for receipt_field in required_matches:
        if receipt.get(receipt_field) != dispatch_material.get(receipt_field):
            raise ValueError(
                "dispatch_terminal_receipt:DISPATCH_MATERIAL_MISMATCH:"
                f"{receipt_field}"
            )
    if receipt.get("status") not in {"COMPLETED", "FAILED"}:
        raise ValueError("dispatch_terminal_receipt:TERMINAL_STATUS_REQUIRED")
    timed_out = receipt.get("timed_out")
    returncode = receipt.get("returncode")
    if type(timed_out) is not bool or (
        returncode is not None and type(returncode) is not int
    ):
        raise ValueError("dispatch_terminal_receipt:RESULT_TYPES_INVALID")
    succeeded = returncode == 0 and not timed_out
    expected_status = "COMPLETED" if succeeded else "FAILED"
    if receipt.get("status") != expected_status:
        raise ValueError("dispatch_terminal_receipt:RESULT_STATUS_INCONSISTENT")
    if receipt.get("launch_baseline_success") is not succeeded:
        raise ValueError("dispatch_terminal_receipt:BASELINE_SUCCESS_INCONSISTENT")
    failure_reason = receipt.get("failure_reason")
    if (succeeded and failure_reason is not None) or (
        not succeeded and (type(failure_reason) is not str or not failure_reason)
    ):
        raise ValueError("dispatch_terminal_receipt:FAILURE_REASON_INCONSISTENT")
    for stream_name in ("stdout", "stderr"):
        claimed_sha256 = receipt.get(f"{stream_name}_sha256")
        if type(claimed_sha256) is not str or len(claimed_sha256) != 64:
            raise ValueError(
                f"dispatch_terminal_receipt:{stream_name.upper()}_SHA256_INVALID"
            )
        stream_bytes = _read_regular_bytes(path.parent / f"{stream_name}.bin", stream_name)
        if not hmac.compare_digest(claimed_sha256, _sha256_bytes(stream_bytes)):
            raise ValueError(
                f"dispatch_terminal_receipt:{stream_name.upper()}_HASH_MISMATCH"
            )
    if (
        receipt.get("paper_only") is not True
        or receipt.get("live_gate") != "blocked_human_only"
        or receipt.get("routes_to_live") is not False
        or receipt.get("places_real_order") is not False
        or receipt.get("exchange_action_taken") is not False
    ):
        raise ValueError("dispatch_terminal_receipt:UNSAFE_AUTHORITY")
    replay = dict(receipt)
    replay["idempotent_replay"] = True
    return replay


def dispatch_worker(
    plan: EscalationWorkPlan,
    *,
    dataset_release_root: Path,
    dispatch_root: Path,
    state_path: Path,
    lock_path: Path,
    runner: Callable[[Sequence[str], int | float], Any] = _default_runner,
    timeout_seconds: int | float = DISPATCH_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute one content-addressed paper-only worker exactly once.

    The signed release is fully loaded and verified before the worker is
    started.  The latest state file is mutable but private and atomic; every
    started/terminal receipt and output stream is immutable under its dispatch
    ID.  Terminal replay returns the prior receipt without executing again.
    """

    errors = plan.validate()
    if errors or plan.action != ACTION_LAUNCH or not plan.worker_command:
        raise ValueError(f"dispatch_plan:INVALID:{','.join(errors) or plan.action}")
    worker = plan.worker_command
    expected_worker = WORKER_COMMANDS.get(plan.selected_step or "")
    if expected_worker is None or worker != expected_worker:
        raise ValueError("worker_command:UNAUTHORIZED_DESCRIPTOR")
    if (
        worker.get("paper_only") is not True
        or worker.get("live_gate") != "blocked_human_only"
        or worker.get("routes_to_live") is not False
        or worker.get("places_real_order") is not False
        or worker.get("exchange_action_taken") is not False
    ):
        raise ValueError("UNSAFE_DISPATCH_AUTHORITY")
    environment_live_gate = os.environ.get("LIVE_GATE")
    if environment_live_gate != "blocked_human_only":
        raise ValueError("dispatch_authority:LIVE_GATE_BLOCK_REQUIRED")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int | float)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds:POSITIVE_NUMBER_REQUIRED")

    release = _authenticated_dataset_release(Path(dataset_release_root))
    if plan.input_manifest_sha != release["dataset_sha256"]:
        raise ValueError("dataset_release_root:PLAN_DATASET_IDENTITY_MISMATCH")
    dispatch_parent = _safe_directory(Path(dispatch_root), "dispatch_root", create=True)
    dispatch_material = {
        "schema_version": DISPATCH_SCHEMA_VERSION,
        "selected_step": plan.selected_step,
        "trigger": list(plan.trigger),
        "input_manifest_sha": plan.input_manifest_sha,
        "worker_scope": worker.get("scope"),
        "worker_entrypoint": worker.get("entrypoint"),
        "worker_entrypoint_file_sha256": _worker_code_sha256(worker),
        "worker_argv_template": list(worker.get("argv") or []),
        "dataset_release": release,
    }
    if plan.failure_cycle_id is not None:
        if (
            type(plan.failure_cycle_id) is not str
            or not plan.failure_cycle_id.startswith("adaptive_failure_cycle_")
            or len(plan.failure_cycle_id) != len("adaptive_failure_cycle_") + 32
        ):
            raise ValueError("failure_cycle_id:INVALID")
        dispatch_material["failure_cycle_id"] = plan.failure_cycle_id
    dispatch_id = "adaptive_dispatch_" + _sha256_bytes(
        _canonical_bytes(dispatch_material)
    )[:32]
    run_root = dispatch_parent / dispatch_id
    argv = _resolved_worker_argv(
        worker,
        dataset_release_root=Path(release["root"]),
        dispatch_run_root=run_root,
    )
    dispatch_material["argv"] = argv
    dispatch_material["dispatch_id"] = dispatch_id

    lock_parent = _safe_directory(Path(lock_path).parent, "dispatch_lock_parent", create=True)
    try:
        lock_descriptor = os.open(
            lock_parent / Path(lock_path).name,
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise ValueError("dispatch_lock_path:REGULAR_FILE_REQUIRED") from exc
    try:
        if not stat.S_ISREG(os.fstat(lock_descriptor).st_mode):
            raise ValueError("dispatch_lock_path:REGULAR_FILE_REQUIRED")
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {
                **dispatch_material,
                "status": "FAILED",
                "failure_reason": "DISPATCH_LOCK_CONTENDED",
                "returncode": None,
                "timed_out": False,
                "stdout_sha256": _sha256_bytes(b""),
                "stderr_sha256": _sha256_bytes(b""),
                "launch_baseline_success": False,
                "idempotent_replay": False,
                "paper_only": True,
                "live_gate": "blocked_human_only",
                "routes_to_live": False,
                "places_real_order": False,
                "exchange_action_taken": False,
            }

        terminal_replay = _replay_terminal_receipt(
            run_root / "dispatch_terminal_v1.json",
            dispatch_material=dispatch_material,
        )
        if terminal_replay is not None:
            return terminal_replay

        prior = _load_json_if_present(Path(state_path))
        if prior and prior.get("dispatch_id") == dispatch_id:
            # The mutable latest-state file is operational telemetry only.  It
            # must never authorize completion (or failure) when the canonical
            # immutable terminal receipt is absent.  A matching RUNNING state
            # also means the earlier attempt ended without a terminal receipt;
            # the dispatch lock proves it is no longer executing here, but it
            # does not prove that retrying the worker would be side-effect free.
            raise ValueError(
                "dispatch_state:IMMUTABLE_TERMINAL_RECEIPT_REQUIRED"
            )

        run_root = _safe_directory(run_root, "dispatch_run_root", create=True)
        started = {
            **dispatch_material,
            "status": "RUNNING",
            "generated_utc": _utc_iso(),
            "returncode": None,
            "timed_out": False,
            "stdout_sha256": None,
            "stderr_sha256": None,
            "launch_baseline_success": False,
            "idempotent_replay": False,
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }
        _write_atomic_private_json(Path(state_path), started)
        _write_immutable_private_bytes(
            run_root / "dispatch_started_v1.json",
            _canonical_bytes(started) + b"\n",
        )

        timed_out = False
        failure_reason: str | None = None
        try:
            completed = runner(argv, timeout_seconds)
            returncode = int(completed.returncode)
            stdout = _result_bytes(getattr(completed, "stdout", b""))
            stderr = _result_bytes(getattr(completed, "stderr", b""))
        except subprocess.TimeoutExpired as exc:
            returncode = None
            timed_out = True
            failure_reason = "WORKER_TIMEOUT"
            stdout = _result_bytes(exc.stdout)
            stderr = _result_bytes(exc.stderr)
        stdout_sha256 = _write_immutable_private_bytes(run_root / "stdout.bin", stdout)
        stderr_sha256 = _write_immutable_private_bytes(run_root / "stderr.bin", stderr)
        succeeded = returncode == 0 and not timed_out
        if not succeeded and failure_reason is None:
            failure_reason = f"WORKER_EXIT_{returncode}"
        terminal = {
            **started,
            "status": "COMPLETED" if succeeded else "FAILED",
            "completed_utc": _utc_iso(),
            "returncode": returncode,
            "timed_out": timed_out,
            "failure_reason": failure_reason,
            "stdout_sha256": stdout_sha256,
            "stderr_sha256": stderr_sha256,
            "launch_baseline_success": succeeded,
        }
        _write_atomic_private_json(Path(state_path), terminal)
        _write_immutable_private_bytes(
            run_root / "dispatch_terminal_v1.json",
            _canonical_bytes(terminal) + b"\n",
        )
        return terminal
    finally:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(lock_descriptor)


# --------------------------------------------------------------------------- #
# Thin runtime wrapper (Redis read -> plan -> optional durable dispatch ->
# Redis/ledger persist).
# --------------------------------------------------------------------------- #
def _get_json(client, key: str) -> dict | None:
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _trailing_flat_cycles(history: Sequence[int], current_directional: int) -> int:
    """Count trailing consecutive samples (incl. current) with directional == 0."""
    seq = list(history) + [current_directional]
    n = 0
    for v in reversed(seq):
        if v == 0:
            n += 1
        else:
            break
    return n


def build_inputs_from_redis(
    client,
    *,
    dataset_path: Path = DEFAULT_GEN5_DATASET,
    min_persistent_flat_cycles: int = 3,
    min_new_matured_outcomes: int = 250,
    min_new_effective_n: float = 25.0,
    history_window: int = 20,
) -> SupervisorInputs:
    """Read the authoritative Redis status keys + corpus + prior supervisor state."""
    authority = _get_json(client, POLICY_AUTHORITY_STATUS_KEY) or {}
    outcomes = _get_json(client, CANDIDATE_OUTCOMES_STATUS_KEY) or {}
    champion = _get_json(client, CHAMPION_CHALLENGER_STATUS_KEY) or {}
    prior = _get_json(client, STATUS_REDIS_KEY) or {}

    directional = int(authority.get("directional_authorized_count") or 0)
    flat = int(authority.get("flat_authorized_count") or 0)
    candidate_count = int(
        authority.get("source_candidate_count")
        or authority.get("adaptive_decision_count")
        or 0
    )

    maturation = outcomes.get("maturation") if isinstance(outcomes.get("maturation"), dict) else {}
    matured = maturation.get("matured_revision_count")
    if matured is None:
        matured = outcomes.get("matured_revision_count")
    matured = int(matured or 0)

    effective_n, _rows = load_gen5_corpus_effective_n(dataset_path)

    # Baseline "last recorded challenger": prefer this supervisor's own last launch
    # baseline; fall back to the trainer champion/challenger's last trained rows.
    prior_baseline = prior.get("launch_baseline")
    if not isinstance(prior_baseline, dict):
        prior_baseline = {}
    baseline_matured = prior_baseline.get("matured_outcome_count")
    baseline_effective_n = prior_baseline.get("effective_n")
    if baseline_matured is None:
        # last_successful_train_rows is a proxy for matured outcomes already learned.
        ls = champion.get("last_successful_train_rows")
        baseline_matured = int(ls) if isinstance(ls, int | float) else None

    # Persistent-flat history from the supervisor's own prior status.
    prior_hist = prior.get("directional_history")
    history: list[int] = [int(x) for x in prior_hist] if isinstance(prior_hist, list) else []
    history = history[-history_window:]
    persistent_flat_cycles = _trailing_flat_cycles(history, directional)

    manifest_sha = (
        _dataset_identity(dataset_path)
        or outcomes.get("recorded_candidate_ids_sha256")
        or authority.get("source_candidate_ids_sha256")
        or ""
    )
    superior_challenger_available = (
        bool(champion.get("best_challenger_id"))
        and champion.get("best_challenger_superior") is True
        and champion.get("paper_only") is True
        and champion.get("live_eligible") is not True
    )

    completed_steps: frozenset[str] = frozenset()
    if prior.get("input_manifest_sha") == manifest_sha:
        prior_steps = prior.get("completed_steps_for_input_manifest")
        if isinstance(prior_steps, list) and all(
            type(step) is str and step in LADDER for step in prior_steps
        ):
            completed_steps = frozenset(prior_steps)

    return SupervisorInputs(
        directional_authorized_count=directional,
        flat_authorized_count=flat,
        candidate_count=candidate_count,
        persistent_flat_cycles=persistent_flat_cycles,
        min_persistent_flat_cycles=min_persistent_flat_cycles,
        matured_outcome_count=matured,
        effective_n=effective_n,
        baseline_matured_outcome_count=baseline_matured,
        baseline_effective_n=baseline_effective_n,
        min_new_matured_outcomes=min_new_matured_outcomes,
        min_new_effective_n=min_new_effective_n,
        superior_challenger_available=superior_challenger_available,
        exhausted_steps=completed_steps,
        input_manifest_sha=str(manifest_sha),
    )


def _utc_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def run_once(
    client,
    *,
    dataset_path: Path = DEFAULT_GEN5_DATASET,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    persist: bool = True,
    execute_worker: bool = False,
    dataset_release_root: Path | None = None,
    dispatch_root: Path = DEFAULT_DISPATCH_ROOT,
    dispatch_state_path: Path = DEFAULT_DISPATCH_STATE_PATH,
    dispatch_lock_path: Path = DEFAULT_DISPATCH_LOCK_PATH,
    dispatch_timeout_seconds: int | float = DISPATCH_TIMEOUT_SECONDS,
) -> EscalationWorkPlan:
    """Read Redis, plan, optionally dispatch, then persist status and ledger."""
    inp = build_inputs_from_redis(client, dataset_path=dataset_path)
    plan = plan_escalation(inp)
    dispatch_result: dict[str, Any] | None = None
    if execute_worker and plan.action == ACTION_LAUNCH:
        if dataset_release_root is None:
            raise ValueError("dataset_release_root:REQUIRED_FOR_WORKER_EXECUTION")
        dispatch_result = dispatch_worker(
            plan,
            dataset_release_root=dataset_release_root,
            dispatch_root=dispatch_root,
            state_path=dispatch_state_path,
            lock_path=dispatch_lock_path,
            timeout_seconds=dispatch_timeout_seconds,
        )

    payload = plan.to_dict()
    payload["generated_utc"] = _utc_iso()
    payload["worker_execution_enabled"] = execute_worker
    payload["dispatch_result"] = dispatch_result
    completed_steps = set(inp.exhausted_steps)
    if dispatch_result and dispatch_result.get("launch_baseline_success") is True:
        if plan.selected_step in LADDER:
            completed_steps.add(plan.selected_step)
    payload["completed_steps_for_input_manifest"] = [
        step for step in LADDER if step in completed_steps
    ]

    # Roll the directional-history window forward (so persistence is real over runs).
    prior = _get_json(client, STATUS_REDIS_KEY) or {}
    prior_hist = prior.get("directional_history")
    history: list[int] = [int(x) for x in prior_hist] if isinstance(prior_hist, list) else []
    history = (history + [inp.directional_authorized_count])[-20:]
    payload["directional_history"] = history

    # Record the launch baseline only after a real successful dispatch. Merely
    # describing a LAUNCH_WORKER plan must never advance the learning state.
    if dispatch_result and dispatch_result.get("launch_baseline_success") is True:
        payload["launch_baseline"] = {
            "matured_outcome_count": inp.matured_outcome_count,
            "effective_n": inp.effective_n,
            "launched_step": plan.selected_step,
            "dispatch_id": dispatch_result["dispatch_id"],
            "dataset_build_receipt_file_sha256": dispatch_result["dataset_release"][
                "build_receipt_file_sha256"
            ],
            "recorded_utc": payload["generated_utc"],
        }
    elif isinstance(prior.get("launch_baseline"), dict):
        payload["launch_baseline"] = prior["launch_baseline"]

    if persist:
        try:
            client.set(STATUS_REDIS_KEY, json.dumps(payload, sort_keys=True))
        except Exception:
            logger.debug("escalation supervisor status write failed", exc_info=True)
        try:
            lp = Path(ledger_path)
            lp.parent.mkdir(parents=True, exist_ok=True)
            with lp.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, sort_keys=True) + "\n")
        except Exception:
            logger.debug("escalation supervisor ledger append failed", exc_info=True)
    return plan


def _build_redis_client(url: str):
    import redis

    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=5.0,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Operational escalation supervisor (paper-only).")
    parser.add_argument(
        "--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--execute-worker", action="store_true")
    parser.add_argument("--dataset-release-root", type=Path)
    parser.add_argument("--dispatch-root", type=Path, default=DEFAULT_DISPATCH_ROOT)
    parser.add_argument(
        "--dispatch-state", type=Path, default=DEFAULT_DISPATCH_STATE_PATH
    )
    parser.add_argument("--dispatch-lock", type=Path, default=DEFAULT_DISPATCH_LOCK_PATH)
    parser.add_argument(
        "--dispatch-timeout-seconds", type=int, default=DISPATCH_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--no-persist", action="store_true", help="Compute and print the plan but do not write."
    )
    args = parser.parse_args(argv)
    if args.execute_worker and args.no_persist:
        parser.error("--execute-worker cannot be combined with --no-persist")
    if args.execute_worker and args.dataset_release_root is None:
        parser.error("--execute-worker requires --dataset-release-root")
    dataset_path = args.dataset
    if dataset_path is None and args.dataset_release_root is not None:
        dataset_path = (
            args.dataset_release_root / "adaptive_serving_compatible_dataset_v2.json"
        )
    if dataset_path is None:
        dataset_path = DEFAULT_GEN5_DATASET

    client = _build_redis_client(args.redis_url)
    plan = run_once(
        client,
        dataset_path=dataset_path,
        ledger_path=args.ledger,
        persist=not args.no_persist,
        execute_worker=args.execute_worker,
        dataset_release_root=args.dataset_release_root,
        dispatch_root=args.dispatch_root,
        dispatch_state_path=args.dispatch_state,
        dispatch_lock_path=args.dispatch_lock,
        dispatch_timeout_seconds=args.dispatch_timeout_seconds,
    )
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    errors = plan.validate()
    return 0 if not errors else 1


__all__ = [
    "SCHEMA_VERSION",
    "STATUS_REDIS_KEY",
    "POLICY_AUTHORITY_STATUS_KEY",
    "CANDIDATE_OUTCOMES_STATUS_KEY",
    "CHAMPION_CHALLENGER_STATUS_KEY",
    "ACTION_LAUNCH",
    "ACTION_AWAIT",
    "ACTION_NO_ESCALATION",
    "DISPATCH_SCHEMA_VERSION",
    "INFO_DEPENDENT_STEPS",
    "WORKER_COMMANDS",
    "SupervisorInputs",
    "EscalationWorkPlan",
    "kish_effective_n",
    "load_gen5_corpus_effective_n",
    "derive_conditions",
    "plan_escalation",
    "dispatch_worker",
    "build_inputs_from_redis",
    "run_once",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
