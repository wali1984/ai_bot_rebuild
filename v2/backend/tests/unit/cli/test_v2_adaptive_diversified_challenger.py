from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_adaptive_diversified_challenger as worker
from v2.backend.app.services.adaptive_system import escalation_supervisor_v2 as supervisor

FEATURES = (
    "expected_funding_bps",
    "expected_slippage_bps",
    "fee_bps",
    "spread_bps",
    "true_range_pct",
    "rsi_14",
    "macd_hist",
    "volume",
)


def _dataset() -> dict:
    rows = []
    start = datetime(2026, 7, 20, tzinfo=timezone.utc)
    for index in range(180):
        split = "train" if index < 60 else "validation" if index < 120 else "holdout"
        group_phase = (index // 3) % 3
        if group_phase == 0:
            long_net, short_net, action = 8.0 + index % 5, -6.0, "long"
        elif group_phase == 1:
            long_net, short_net, action = -6.0, 7.0 + index % 5, "short"
        else:
            long_net, short_net, action = -2.0, -3.0, "hold"
        decision = start + timedelta(minutes=5 * index)
        rows.append(
            {
                "split": split,
                "symbol": ("AAAUSDT", "BBBUSDT", "CCCUSDT")[index % 3],
                "timeframe": ("5m", "15m", "1h")[index % 3],
                "feature_values": [
                    float(group_phase),
                    float((group_phase + 1) % 3),
                    4.0,
                    1.0 + (index % 4) * 0.1,
                    0.1 + (index % 9) * 0.01,
                    30.0 + group_phase * 20.0,
                    -1.0 + group_phase,
                    1000.0 + index,
                ],
                "missing_mask": [0] * len(FEATURES),
                "long_net_bps": long_net,
                "short_net_bps": short_net,
                "target_action": action,
                "decision_time": decision.isoformat().replace("+00:00", "Z"),
                "label_available_at": (decision + timedelta(minutes=15))
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
    return {
        "dataset_sha256": "d" * 64,
        "feature_abi_sha256": "a" * 64,
        "feature_builder_sha256": "b" * 64,
        "ordered_feature_names": list(FEATURES),
        "rows": rows,
    }


def _build(mode: str, dataset: dict | None = None) -> dict:
    return worker.build_challenger_evidence(
        mode=mode,
        dataset=dataset or _dataset(),
        release_projection={"dataset_sha256": "d" * 64, "root": "/release"},
        release_source={
            "matured_revision_count": 180,
            "terminal_chain_sha256": "c" * 64,
        },
    )


def test_horizon_challengers_are_train_only_and_non_authoritative() -> None:
    result = _build("horizon")

    assert result["status"] == "PASS_RESEARCH_CHALLENGERS_TRAINED"
    assert result["trained_candidate_count"] == 3
    assert result["fit_partition"] == "TRAIN_ONLY"
    assert result["holdout_used_for_selection"] is False
    assert result["counterfactual_counts_as_realized_paper_profit"] is False
    assert result["statistical_superiority_proven"] is False
    assert result["serving_abi_changed"] is False
    assert result["registry_write_attempted"] is False
    assert result["activation_eligible"] is False
    assert result["checkpoint_promotable"] is False
    assert result["paper_only"] is True
    assert result["live_gate"] == "blocked_human_only"
    assert result["routes_to_live"] is False
    assert result["places_real_order"] is False
    assert result["exchange_action_taken"] is False
    assert all(
        candidate["fit_partition"] == "TRAIN_ONLY"
        and candidate["holdout_used_for_selection"] is False
        and len(candidate["model_parameter_fingerprint"]) == 64
        for candidate in result["candidates"]
    )


def test_repeated_training_is_deterministic() -> None:
    assert _build("horizon") == _build("horizon")


def test_architecture_selection_never_uses_holdout() -> None:
    dataset = _dataset()
    mutated = deepcopy(dataset)
    for row in mutated["rows"]:
        if row["split"] != "holdout":
            continue
        row["long_net_bps"] = -1000.0
        row["short_net_bps"] = 1000.0
        row["target_action"] = "short"

    baseline = _build("architecture", dataset)
    changed = _build("architecture", mutated)

    assert changed["selected_candidate_id"] == baseline["selected_candidate_id"]
    assert [candidate["validation_metrics"] for candidate in changed["candidates"]] == [
        candidate["validation_metrics"] for candidate in baseline["candidates"]
    ]
    assert changed["holdout_used_for_selection"] is False
    assert changed["selection_scope"] == "COMPARABLE_FULL_UNIVERSE_VALIDATION_BRIER"
    assert sum(candidate["selected_by_validation"] for candidate in changed["candidates"]) == 1


def test_symbol_and_train_frozen_regime_slices_are_evaluated() -> None:
    result = _build("symbol_regime")

    kinds = {
        candidate["group_kind"]
        for candidate in result["candidates"] + result["rejected_slices"]
    }
    assert "symbol" in kinds
    assert "train_frozen_volatility_regime" in kinds
    assert set(result["regime_thresholds_fit_on_train_only"]) == {
        "train_q33",
        "train_q67",
    }


@pytest.mark.parametrize("mutation", ["action", "bool", "future_label", "release"])
def test_invalid_authenticated_rows_fail_closed(mutation: str) -> None:
    dataset = _dataset()
    projection = {"dataset_sha256": "d" * 64, "root": "/release"}
    if mutation == "action":
        dataset["rows"][0]["target_action"] = "short"
    elif mutation == "bool":
        dataset["rows"][0]["feature_values"][0] = True
    elif mutation == "future_label":
        dataset["rows"][0]["label_available_at"] = dataset["rows"][0][
            "decision_time"
        ]
    else:
        projection["dataset_sha256"] = "e" * 64

    with pytest.raises(worker.AdaptiveDiversifiedChallengerError):
        worker.build_challenger_evidence(
            mode="horizon",
            dataset=dataset,
            release_projection=projection,
            release_source={
                "matured_revision_count": 180,
                "terminal_chain_sha256": "c" * 64,
            },
        )


def test_run_once_consumes_authenticated_snapshot_without_path_reread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticated = _dataset()
    projection = {
        "dataset_sha256": "d" * 64,
        "root": str(tmp_path / "release"),
        "paths": {"dataset": str(tmp_path / "release" / "dataset.json")},
    }
    source = {
        "matured_revision_count": 180,
        "terminal_chain_sha256": "c" * 64,
    }

    def snapshot(_root: Path) -> tuple[dict, dict, dict]:
        path = Path(projection["paths"]["dataset"])
        path.parent.mkdir(parents=True)
        path.write_text('{"forged":true}\n', encoding="utf-8")
        return projection, source, authenticated

    monkeypatch.setattr(
        worker.supervisor,
        "_authenticated_dataset_release_snapshot",
        snapshot,
    )

    result = worker.run_once(
        mode="horizon",
        dataset_release_root=tmp_path / "release",
        output_dir=tmp_path / "output",
    )

    assert result["trained_candidate_count"] == 3
    assert result["dataset_release"]["dataset_sha256"] == "d" * 64


def test_supervisor_descriptors_bind_all_diversified_rungs_to_signed_release() -> None:
    expected_modes = {
        "TRAIN_HORIZON_SPECIFIC_CHALLENGERS": "horizon",
        "TRAIN_SYMBOL_OR_REGIME_SPECIFIC_CHALLENGERS": "symbol_regime",
        "TRAIN_ALTERNATIVE_MODEL_ARCHITECTURES": "architecture",
    }
    for step, mode in expected_modes.items():
        descriptor = supervisor.WORKER_COMMANDS[step]
        argv = descriptor["argv"]
        assert descriptor["entrypoint"] == (
            "v2.backend.app.cli.v2_adaptive_diversified_challenger"
        )
        assert argv == [
            ".venv/bin/python",
            "-m",
            "v2.backend.app.cli.v2_adaptive_diversified_challenger",
            "--mode",
            mode,
            "--dataset-release-root",
            "{dataset_release_root}",
            "--output-dir",
            f"{{dispatch_run_root}}/{'horizon_challengers' if mode == 'horizon' else 'symbol_regime_challengers' if mode == 'symbol_regime' else 'architecture_challengers'}",
        ]
        assert descriptor["paper_only"] is True
        assert descriptor["routes_to_live"] is False
        assert descriptor["exchange_action_taken"] is False
