from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_adaptive_feature_representation_challenger as worker


FEATURES = (
    "expected_funding_bps",
    "expected_slippage_bps",
    "fee_bps",
    "spread_bps",
    "bb_width_pct",
    "body_pct",
    "close",
    "ema_12",
    "ema_26",
    "high",
    "log_return",
    "low",
    "macd",
    "macd_hist",
    "macd_signal",
    "num_trades",
    "open",
    "quote_volume",
    "range_pct",
    "ret_pct",
    "rsi_14",
    "taker_buy_base_vol",
    "taker_buy_quote_vol",
    "taker_buy_ratio",
    "taker_sell_base_vol",
    "taker_sell_quote_vol",
    "taker_sell_ratio",
    "true_range_pct",
    "volume",
)


def _dataset() -> dict:
    rows = []
    for index in range(72):
        if index < 48:
            split = "train"
        elif index < 60:
            split = "validation"
        else:
            split = "holdout"
        values = [
            (((index + 3) * (position + 5)) % (31 + position)) / (31 + position)
            + position * 0.001
            for position in range(len(FEATURES))
        ]
        long_net = values[6] * 20.0 - values[20] * 5.0 - 5.0
        short_net = values[12] * 18.0 - values[23] * 4.0 - 5.0
        if long_net > short_net and long_net > 0.0:
            action = "long"
        elif short_net > 0.0:
            action = "short"
        else:
            action = "hold"
        rows.append(
            {
                "split": split,
                "feature_values": values,
                "missing_mask": [0] * len(FEATURES),
                "long_net_bps": long_net,
                "short_net_bps": short_net,
                "target_action": action,
            }
        )
    return {
        "dataset_sha256": "d" * 64,
        "feature_abi_sha256": "a" * 64,
        "feature_builder_sha256": "b" * 64,
        "ordered_feature_names": list(FEATURES),
        "rows": rows,
    }


def _build(dataset: dict | None = None) -> dict:
    return worker.build_representation_candidate(
        dataset=dataset or _dataset(),
        release_projection={"dataset_sha256": "d" * 64, "root": "/release"},
        release_source={
            "matured_revision_count": 72,
            "terminal_chain_sha256": "c" * 64,
        },
    )


def test_train_only_compact_selection_preserves_cost_identity_and_safety() -> None:
    result = _build()

    assert result["selection_partition"] == "TRAIN_ONLY"
    assert result["validation_used_for_selection"] is False
    assert result["holdout_used_for_selection"] is False
    assert len(result["selected_feature_names"]) <= worker.MAX_SELECTED_FEATURES
    assert len(result["selected_feature_names"]) >= worker.MIN_SELECTED_FEATURES
    assert set(worker.REQUIRED_COST_FEATURES) <= set(result["selected_feature_names"])
    assert result["serving_abi_changed"] is False
    assert result["activation_eligible"] is False
    assert result["checkpoint_promotable"] is False
    assert result["live_eligible"] is False
    assert result["paper_only"] is True
    assert result["live_gate"] == "blocked_human_only"
    assert result["routes_to_live"] is False
    assert result["places_real_order"] is False
    assert result["exchange_action_taken"] is False


def test_validation_and_holdout_labels_cannot_change_selected_representation() -> None:
    baseline_dataset = _dataset()
    mutated = deepcopy(baseline_dataset)
    for row in mutated["rows"]:
        if row["split"] != "train":
            row["long_net_bps"] *= -1000.0
            row["short_net_bps"] = 100000.0 - row["short_net_bps"]
            row["target_action"] = "short"

    baseline = _build(baseline_dataset)
    changed_future_partitions = _build(mutated)

    assert changed_future_partitions["selected_positions"] == baseline[
        "selected_positions"
    ]
    assert changed_future_partitions["selected_feature_names"] == baseline[
        "selected_feature_names"
    ]
    assert changed_future_partitions["feature_evidence"] == baseline[
        "feature_evidence"
    ]


@pytest.mark.parametrize("mutation", ["missing", "nonfinite", "release_mismatch"])
def test_invalid_feature_or_release_evidence_fails_closed(mutation: str) -> None:
    dataset = _dataset()
    projection = {"dataset_sha256": "d" * 64, "root": "/release"}
    if mutation == "missing":
        dataset["rows"][0]["missing_mask"][4] = 1
    elif mutation == "nonfinite":
        dataset["rows"][0]["feature_values"][4] = float("nan")
    else:
        projection["dataset_sha256"] = "e" * 64

    with pytest.raises(worker.AdaptiveFeatureRepresentationError):
        worker.build_representation_candidate(
            dataset=dataset,
            release_projection=projection,
            release_source={
                "matured_revision_count": 72,
                "terminal_chain_sha256": "c" * 64,
            },
        )


def test_immutable_output_is_idempotent_and_rejects_collision(tmp_path: Path) -> None:
    payload = _build()
    output = tmp_path / worker.OUTPUT_NAME
    first = worker._write_immutable(output, payload)  # noqa: SLF001
    second = worker._write_immutable(output, payload)  # noqa: SLF001
    assert first == second

    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        worker.AdaptiveFeatureRepresentationError,
        match="IMMUTABLE_COLLISION",
    ):
        worker._write_immutable(output, payload)  # noqa: SLF001
