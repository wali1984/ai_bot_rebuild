from __future__ import annotations

import copy

import pytest

from v2.backend.app.services.native_trainer.gen5_pit_regime_coverage_v1 import (
    Gen5RegimeCoverageError,
    build_pit_regime_coverage_v1,
)


def _row(
    *,
    row_id: str,
    split: str,
    ema_12: float,
    ema_26: float,
    true_range_pct: float,
) -> dict[str, object]:
    return {
        "row_id": row_id,
        "split": split,
        "decision_time": "2026-07-27T20:00:00.000000Z",
        "feature_cutoff": "2026-07-27T19:59:58.000000Z",
        "record_available_at": "2026-07-27T19:59:59.000000Z",
        "feature_values": [ema_12, ema_26, true_range_pct],
        "missing_mask": [False, False, False],
        "latest_unclosed_kline_excluded": True,
        "latest_closed_kline_close_time_ms": 1_785_182_399_000,
        "latest_unclosed_exclusion_decision_time_ms": 1_785_182_399_500,
    }


def _dataset() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    regimes = (
        (1.0, 0.0, 1.0),
        (1.0, 0.0, 3.0),
        (0.0, 1.0, 1.0),
        (0.0, 1.0, 3.0),
    )
    for split in ("train", "validation", "holdout"):
        for regime_index, values in enumerate(regimes):
            for member in range(5):
                rows.append(
                    _row(
                        row_id=f"{split}-{regime_index}-{member}",
                        split=split,
                        ema_12=values[0],
                        ema_26=values[1],
                        true_range_pct=values[2],
                    )
                )
    return {
        "dataset_id": "dataset-1",
        "dataset_sha256": "a" * 64,
        "feature_abi_sha256": "b" * 64,
        "ordered_feature_names": ["ema_12", "ema_26", "true_range_pct"],
        "rows": rows,
    }


def test_regime_coverage_is_train_fit_and_present_in_every_split() -> None:
    dataset = _dataset()

    report = build_pit_regime_coverage_v1(dataset)

    assert report["volatility_threshold"] == 2.0
    assert report["regime_coverage_proven"] is True
    assert report["all_four_regimes_present_in_every_split"] is True
    assert report["holdout_influences_threshold"] is False
    assert set(report["regime_counts_by_split"]["holdout"].values()) == {5}


def test_holdout_values_cannot_change_train_fitted_threshold() -> None:
    dataset = _dataset()
    mutated = copy.deepcopy(dataset)
    for row in mutated["rows"]:  # type: ignore[index]
        if row["split"] == "holdout":
            row["feature_values"][2] = 99_999.0

    original = build_pit_regime_coverage_v1(dataset)
    changed = build_pit_regime_coverage_v1(mutated)

    assert original["volatility_threshold"] == changed["volatility_threshold"] == 2.0
    assert original["threshold_fit_rows_sha256"] == changed["threshold_fit_rows_sha256"]


def test_regime_coverage_rejects_future_available_feature() -> None:
    dataset = _dataset()
    dataset["rows"][0]["record_available_at"] = "2026-07-27T20:00:01.000000Z"  # type: ignore[index]

    with pytest.raises(Gen5RegimeCoverageError, match="REGIME_POINT_IN_TIME_ORDER_INVALID"):
        build_pit_regime_coverage_v1(dataset)
