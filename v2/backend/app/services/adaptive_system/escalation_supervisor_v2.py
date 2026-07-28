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

Paper-only.  This module NEVER spawns training, never places an order, never
promotes a challenger, never touches the live gate.  It only *describes* the
worker; a separate operator/service executes it.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path

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
        "places_real_order": False,
        "routes_to_live": False,
    }


WORKER_COMMANDS: Mapping[str, dict] = {
    "RECALIBRATE_CURRENT_MODELS": _worker(
        "RECALIBRATE_CURRENT_MODELS",
        "scripts/train_serving_feature_abi_v2_checkpoint.py",
        "script",
        (
            _VENV_PY,
            "scripts/train_serving_feature_abi_v2_checkpoint.py",
            "--dataset",
            str(DEFAULT_GEN5_DATASET),
            "--manifest",
            str(DEFAULT_GEN5_MANIFEST),
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
        "scripts/train_serving_feature_abi_v2_checkpoint.py",
        "script",
        (
            _VENV_PY,
            "scripts/train_serving_feature_abi_v2_checkpoint.py",
            "--dataset",
            str(DEFAULT_GEN5_DATASET),
            "--manifest",
            str(DEFAULT_GEN5_MANIFEST),
        ),
        "gen5_serving_checkpoint_incremental_train",
        "Train the serving-ABI-v2 checkpoint on the latest matured gen-5 corpus.",
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
        "v2.backend.app.cli.v2_strategy_supply_publish_hypotheses",
        "module",
        (_VENV_PY, "-m", "v2.backend.app.cli.v2_strategy_supply_publish_hypotheses"),
        "alternative_strategy_family",
        "Publish/activate alternative strategy-family hypotheses for evaluation.",
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
        "v2.backend.app.cli.v2_adaptive_policy_shadow_runtime",
        "module",
        (_VENV_PY, "-m", "v2.backend.app.cli.v2_adaptive_policy_shadow_runtime"),
        "bounded_information_seeking_exploration",
        "Increase bounded, hard-gated exploration to GENERATE the missing information.",
    ),
    "PROMOTE_SUPERIOR_CHALLENGER": _worker(
        "PROMOTE_SUPERIOR_CHALLENGER",
        "v2.backend.app.cli.v2_trainer_h2l_promote",
        "module",
        (_VENV_PY, "-m", "v2.backend.app.cli.v2_trainer_h2l_promote"),
        "promote_superior_challenger",
        "Promote a challenger that beats the champion on held-out validation "
        "(operator/gate-controlled; paper evaluation only here).",
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
        available[step] = info_gain
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
# Thin runtime wrapper (Redis read -> plan -> Redis/ledger persist).  No worker
# is spawned here; the plan only DESCRIBES the worker.
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

    superior_challenger_available = bool(champion.get("best_challenger_id"))

    manifest_sha = (
        outcomes.get("recorded_candidate_ids_sha256")
        or authority.get("source_candidate_ids_sha256")
        or ""
    )

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
) -> EscalationWorkPlan:
    """Read Redis -> plan -> persist status + jsonl ledger.  Spawns NO worker."""
    inp = build_inputs_from_redis(client, dataset_path=dataset_path)
    plan = plan_escalation(inp)

    payload = plan.to_dict()
    payload["generated_utc"] = _utc_iso()

    # Roll the directional-history window forward (so persistence is real over runs).
    prior = _get_json(client, STATUS_REDIS_KEY) or {}
    prior_hist = prior.get("directional_history")
    history: list[int] = [int(x) for x in prior_hist] if isinstance(prior_hist, list) else []
    history = (history + [inp.directional_authorized_count])[-20:]
    payload["directional_history"] = history

    # Record the launch baseline when we actually dispatch a worker (so the next
    # cycle measures "new information since the last recorded challenger").
    if plan.action == ACTION_LAUNCH:
        payload["launch_baseline"] = {
            "matured_outcome_count": inp.matured_outcome_count,
            "effective_n": inp.effective_n,
            "launched_step": plan.selected_step,
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
    parser.add_argument("--dataset", type=Path, default=DEFAULT_GEN5_DATASET)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument(
        "--no-persist", action="store_true", help="Compute and print the plan but do not write."
    )
    args = parser.parse_args(argv)

    client = _build_redis_client(args.redis_url)
    plan = run_once(
        client,
        dataset_path=args.dataset,
        ledger_path=args.ledger,
        persist=not args.no_persist,
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
    "INFO_DEPENDENT_STEPS",
    "WORKER_COMMANDS",
    "SupervisorInputs",
    "EscalationWorkPlan",
    "kish_effective_n",
    "load_gen5_corpus_effective_n",
    "derive_conditions",
    "plan_escalation",
    "build_inputs_from_redis",
    "run_once",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
