from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from v2.backend.app.cli import (
    v2_adaptive_feature_representation_challenger as worker,
)

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


def test_target_action_must_match_net_edge_identity() -> None:
    dataset = _dataset()
    dataset["rows"][0]["target_action"] = (
        "short" if dataset["rows"][0]["target_action"] != "short" else "long"
    )

    with pytest.raises(
        worker.AdaptiveFeatureRepresentationError,
        match="NET_EDGE_MISMATCH",
    ):
        _build(dataset)


def test_constant_non_cost_features_cannot_create_false_superiority() -> None:
    dataset = _dataset()
    for row in dataset["rows"]:
        row["feature_values"] = [0.0] * len(FEATURES)

    result = _build(dataset)

    assert result["selected_feature_names"] == list(worker.REQUIRED_COST_FEATURES)
    assert result["sufficient_admissible_features"] is False
    assert result["representation_superior"] is False
    assert result["status"] == "PASS_EVALUATED_INSUFFICIENT_ADMISSIBLE_FEATURES"
    non_cost = [
        evidence
        for evidence in result["feature_evidence"]
        if evidence["name"] not in worker.REQUIRED_COST_FEATURES
    ]
    assert all(evidence["selected"] is False for evidence in non_cost)
    assert all(
        evidence["exact_reason"] == "LOW_VARIANCE_TRAIN_ONLY"
        for evidence in non_cost
    )


def test_run_once_consumes_authenticated_in_memory_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticated = _dataset()
    release_projection = {
        "dataset_sha256": "d" * 64,
        "root": str(tmp_path / "release"),
        "paths": {"dataset": str(tmp_path / "release" / "dataset.json")},
    }
    release_source = {
        "matured_revision_count": 72,
        "terminal_chain_sha256": "c" * 64,
    }

    def authenticated_snapshot(_root: Path) -> tuple[dict, dict, dict]:
        # A path consumer would fail or consume substituted bytes; the worker
        # must use only the exact object returned by signed authentication.
        release_path = Path(release_projection["paths"]["dataset"])
        release_path.parent.mkdir(parents=True)
        release_path.write_text('{"substituted":true}\n', encoding="utf-8")
        return release_projection, release_source, authenticated

    monkeypatch.setattr(
        worker.supervisor,
        "_authenticated_dataset_release_snapshot",
        authenticated_snapshot,
    )

    result = worker.run_once(
        dataset_release_root=tmp_path / "release",
        output_dir=tmp_path / "output",
    )

    assert result["dataset_release"]["dataset_sha256"] == "d" * 64
    assert result["selected_feature_names"]


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
