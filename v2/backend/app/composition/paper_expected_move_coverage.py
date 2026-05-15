"""V2 paper expected_move coverage.

Inspects trainer, feature, risk, and signal payloads to find or label
expected-move evidence used by the V2 paper fill gates.

- Native, native after-cost, and explicitly accepted expected-move
  sources are labelled ``NATIVE_EXPECTED_MOVE_PRESENT`` and are
  eligible to feed the downstream fill gates.
- Heuristic/proxy values are labelled
  ``PROXY_CANDIDATE_UNVALIDATED_NON_FILL_ELIGIBLE``. The proxy value
  is exposed for explainability but is *never* fed into the gate as a
  fill permission until the operator/model validation token is
  delivered (which is intentionally not produced by this module).
- Absent values are labelled
  ``EXPECTED_MOVE_MISSING_NON_FILL_ELIGIBLE`` and the downstream gate
  must keep blocking with ``missing_expected_move_after_costs``.

The module is pure and V2-local: it never touches external services
or legacy runtime processes, and it cannot enable live trading.

The remediation explicitly forbids using future shadow outcomes as an
entry signal: this module reads only payloads available at signal
generation time. It does not accept future-looking excursion data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


LIVE_GATE_STATUS = "blocked_human_only"

EXPECTED_MOVE_COVERAGE_STATUS_NATIVE = "NATIVE_EXPECTED_MOVE_PRESENT"
EXPECTED_MOVE_COVERAGE_STATUS_PROXY = (
    "PROXY_CANDIDATE_UNVALIDATED_NON_FILL_ELIGIBLE"
)
EXPECTED_MOVE_COVERAGE_STATUS_MISSING = (
    "EXPECTED_MOVE_MISSING_NON_FILL_ELIGIBLE"
)

EXPECTED_MOVE_SOURCE_NATIVE_TRAINER = "native_trainer_expected_move_bps"
EXPECTED_MOVE_SOURCE_NATIVE_RISK = "native_risk_expected_move_after_cost_bps"
EXPECTED_MOVE_SOURCE_NATIVE_SIGNAL = "native_signal_expected_move_bps"
EXPECTED_MOVE_SOURCE_PROXY_CANDIDATE = "proxy_candidate_unvalidated"
EXPECTED_MOVE_SOURCE_MISSING = "missing"

PROXY_VALIDATION_REQUIREMENT = (
    "PROXY_REQUIRES_OPERATOR_APPROVAL_AND_BACKTEST_VALIDATION"
)


@dataclass(frozen=True)
class PaperExpectedMoveCoverageConfig:
    accepted_native_sources: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                EXPECTED_MOVE_SOURCE_NATIVE_TRAINER,
                EXPECTED_MOVE_SOURCE_NATIVE_RISK,
                EXPECTED_MOVE_SOURCE_NATIVE_SIGNAL,
            }
        )
    )
    proxy_validation_requirements: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "operator_proxy_validation_approval_token",
                "backtest_realized_vs_predicted_consistent",
                "shadow_after_cost_correctness_minimum_sample_met",
            }
        )
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 8)


def _native_result(
    *,
    source: str,
    expected_move_bps: float | None,
    expected_move_after_cost_bps: float,
    cost_bps: float,
) -> dict[str, Any]:
    return {
        "expected_move_source": source,
        "expected_move_coverage_status": EXPECTED_MOVE_COVERAGE_STATUS_NATIVE,
        "expected_move_bps": _round(expected_move_bps),
        "expected_move_after_cost_bps": _round(expected_move_after_cost_bps),
        "expected_move_after_cost_bps_for_fill_gate": _round(
            expected_move_after_cost_bps
        ),
        "expected_move_bps_for_fill_gate": (
            _round(expected_move_bps)
            if expected_move_bps is not None
            else _round(expected_move_after_cost_bps + cost_bps)
        ),
        "cost_bps": _round(cost_bps),
        "fill_eligible_from_expected_move": True,
        "proxy_validation_approved": False,
        "validation_requirement": PROXY_VALIDATION_REQUIREMENT,
        "live_gate_status": LIVE_GATE_STATUS,
        "non_fill_reasons": [],
    }


def _proxy_result(
    *,
    expected_move_bps: float,
    cost_bps: float,
    proxy_validation_approved: bool,
) -> dict[str, Any]:
    after_cost = expected_move_bps - cost_bps
    return {
        "expected_move_source": EXPECTED_MOVE_SOURCE_PROXY_CANDIDATE,
        "expected_move_coverage_status": EXPECTED_MOVE_COVERAGE_STATUS_PROXY,
        "expected_move_bps": _round(expected_move_bps),
        "expected_move_after_cost_bps": _round(after_cost),
        "expected_move_after_cost_bps_for_fill_gate": None,
        "expected_move_bps_for_fill_gate": None,
        "cost_bps": _round(cost_bps),
        "fill_eligible_from_expected_move": False,
        "proxy_validation_approved": bool(proxy_validation_approved),
        "validation_requirement": PROXY_VALIDATION_REQUIREMENT,
        "live_gate_status": LIVE_GATE_STATUS,
        "non_fill_reasons": [
            "proxy_expected_move_unvalidated_cannot_permit_fill",
        ],
    }


def _missing_result(*, cost_bps: float) -> dict[str, Any]:
    return {
        "expected_move_source": EXPECTED_MOVE_SOURCE_MISSING,
        "expected_move_coverage_status": EXPECTED_MOVE_COVERAGE_STATUS_MISSING,
        "expected_move_bps": None,
        "expected_move_after_cost_bps": None,
        "expected_move_after_cost_bps_for_fill_gate": None,
        "expected_move_bps_for_fill_gate": None,
        "cost_bps": _round(cost_bps),
        "fill_eligible_from_expected_move": False,
        "proxy_validation_approved": False,
        "validation_requirement": PROXY_VALIDATION_REQUIREMENT,
        "live_gate_status": LIVE_GATE_STATUS,
        "non_fill_reasons": ["missing_expected_move_after_costs"],
    }


def expected_move_bps_for_fill_gate(coverage: Mapping[str, Any]) -> float | None:
    """Return the gross expected_move_bps that may be forwarded to the
    canary tightening gate / paper edge scorer, or ``None`` when the
    source is not native (proxy/missing). The canary gate compares this
    gross value against costs; the paper edge scorer compares the
    after-cost value separately. Both must refuse a fill when this
    helper returns ``None``.
    """
    return _number(coverage.get("expected_move_bps_for_fill_gate"))


def evaluate_paper_expected_move_coverage(
    *,
    trainer_prediction: Mapping[str, Any] | None = None,
    feature_snapshot: Mapping[str, Any] | None = None,
    risk_payload: Mapping[str, Any] | None = None,
    signal_record: Mapping[str, Any] | None = None,
    fee_bps: float = 0.0,
    spread_bps: float = 0.0,
    slippage_bps: float = 0.0,
    funding_bps: float = 0.0,
    proxy_validation_approved: bool = False,
    config: PaperExpectedMoveCoverageConfig | None = None,
) -> dict[str, Any]:
    """Label expected-move coverage and decide fill eligibility.

    Future-looking shadow outcomes / excursions are intentionally not
    accepted by this function — only payloads available at signal
    generation time.
    """
    cfg = config or PaperExpectedMoveCoverageConfig()
    cost_bps = float(
        (fee_bps or 0.0)
        + (spread_bps or 0.0)
        + (slippage_bps or 0.0)
        + (funding_bps or 0.0)
    )

    risk = risk_payload or {}
    trainer = trainer_prediction or {}
    signal = signal_record or {}

    raw_output = trainer.get("raw_output") if isinstance(trainer, Mapping) else {}
    if not isinstance(raw_output, Mapping):
        raw_output = {}

    native_risk_after_cost = _number(
        risk.get("expected_move_after_cost_bps")
        or risk.get("expected_move_after_costs_bps")
    )
    native_trainer_bps = _number(
        trainer.get("expected_move_bps")
        or trainer.get("native_expected_move_bps")
        or raw_output.get("expected_move_bps")
        or raw_output.get("native_expected_move_bps")
    )
    native_trainer_after_cost = _number(
        trainer.get("expected_move_after_cost_bps")
        or raw_output.get("expected_move_after_cost_bps")
    )
    native_signal_bps = _number(signal.get("expected_move_bps"))
    proxy_bps = _number(
        trainer.get("proxy_expected_move_bps")
        or raw_output.get("proxy_expected_move_bps")
    )

    if (
        native_risk_after_cost is not None
        and EXPECTED_MOVE_SOURCE_NATIVE_RISK in cfg.accepted_native_sources
    ):
        return _native_result(
            source=EXPECTED_MOVE_SOURCE_NATIVE_RISK,
            expected_move_bps=None,
            expected_move_after_cost_bps=native_risk_after_cost,
            cost_bps=cost_bps,
        )

    if (
        native_trainer_after_cost is not None
        and EXPECTED_MOVE_SOURCE_NATIVE_TRAINER in cfg.accepted_native_sources
    ):
        return _native_result(
            source=EXPECTED_MOVE_SOURCE_NATIVE_TRAINER,
            expected_move_bps=None,
            expected_move_after_cost_bps=native_trainer_after_cost,
            cost_bps=cost_bps,
        )

    if (
        native_trainer_bps is not None
        and EXPECTED_MOVE_SOURCE_NATIVE_TRAINER in cfg.accepted_native_sources
    ):
        return _native_result(
            source=EXPECTED_MOVE_SOURCE_NATIVE_TRAINER,
            expected_move_bps=native_trainer_bps,
            expected_move_after_cost_bps=native_trainer_bps - cost_bps,
            cost_bps=cost_bps,
        )

    if (
        native_signal_bps is not None
        and EXPECTED_MOVE_SOURCE_NATIVE_SIGNAL in cfg.accepted_native_sources
    ):
        return _native_result(
            source=EXPECTED_MOVE_SOURCE_NATIVE_SIGNAL,
            expected_move_bps=native_signal_bps,
            expected_move_after_cost_bps=native_signal_bps - cost_bps,
            cost_bps=cost_bps,
        )

    if proxy_bps is not None:
        return _proxy_result(
            expected_move_bps=proxy_bps,
            cost_bps=cost_bps,
            proxy_validation_approved=proxy_validation_approved,
        )

    return _missing_result(cost_bps=cost_bps)
