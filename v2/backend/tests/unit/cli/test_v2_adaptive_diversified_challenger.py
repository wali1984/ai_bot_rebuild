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


def _with_hedge_labels(dataset: dict | None = None) -> dict:
    result = deepcopy(dataset or _dataset())
    for index, row in enumerate(result["rows"]):
        unhedged = float(row["long_net_bps"])
        decision_ms = int(
            datetime.fromisoformat(
                row["decision_time"].replace("Z", "+00:00")
            ).timestamp()
            * 1_000
        )
        unhedged_scenario = {
            "schema_version": "CounterfactualScenarioV2",
            "scenario_id": f"unhedged-{index:04d}",
            "action_sha256": "a" * 64,
            "gross_pnl_bps": unhedged + 2.1,
            "fees_bps": 1.0,
            "spread_bps": 0.5,
            "slippage_bps": 0.25,
            "funding_bps": 0.1,
            "market_impact_bps": 0.25,
            "after_cost_pnl_bps": unhedged,
            "source_event_time_ms": decision_ms + 1,
            "producer_generated_at_ms": decision_ms + 2,
            "record_available_at_ms": decision_ms + 3,
            "source_receipt_sha256s": ["c" * 64],
            "finality_proven": True,
            "counts_as_paper_profit": False,
            "actual_accounting_effect": False,
        }
        hedged = -4.0
        hedged_scenario = {
            **unhedged_scenario,
            "scenario_id": f"hedged-{index:04d}",
            "action_sha256": "b" * 64,
            "gross_pnl_bps": 0.0,
            "fees_bps": 2.0,
            "spread_bps": 1.0,
            "slippage_bps": 0.5,
            "funding_bps": 0.0,
            "market_impact_bps": 0.5,
            "after_cost_pnl_bps": hedged,
        }
        unhedged_sha = worker._sha256(  # noqa: SLF001
            worker._canonical_bytes(unhedged_scenario)  # noqa: SLF001
        )
        hedged_sha = worker._sha256(  # noqa: SLF001
            worker._canonical_bytes(hedged_scenario)  # noqa: SLF001
        )
        advantage = hedged - unhedged
        material = {
            "schema_version": "candidate_hedge_label_derivation_v2",
            "candidate_id": f"candidate-{index:04d}",
            "hedge_contract": worker.HEDGE_CONTRACT,
            "comparison_semantics": worker.HEDGE_COMPARISON,
            "proposed_action": "LONG",
            "unhedged_after_cost_pnl_bps": unhedged,
            "hedged_after_cost_pnl_bps": hedged,
            "hedge_advantage_bps": advantage,
            "target_hedge_vs_unhedged": advantage > 0.0,
            "hedged_after_cost_positive": hedged > 0.0,
            "cross_sectional_relative_value_label_present": False,
            "counterfactual_counts_as_realized_paper_profit": False,
            "actual_accounting_effect": False,
            "unhedged_scenario_sha256": unhedged_sha,
            "hedged_scenario_sha256": hedged_sha,
            "unhedged_scenario": unhedged_scenario,
            "hedged_scenario": hedged_scenario,
        }
        material["derivation_sha256"] = worker._sha256(  # noqa: SLF001
            worker._canonical_bytes(material)  # noqa: SLF001
        )
        row["directional_label_derivation"] = {
            "proposed_action": "LONG",
            "unhedged_scenario_sha256s": [unhedged_sha],
        }
        row["source_receipt_sha256s"] = ["c" * 64]
        row["hedge_label_derivation"] = material
    return result


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


def test_hedge_challenger_is_loss_avoidance_only_and_non_authoritative() -> None:
    result = _build("hedged_relative_value", _with_hedge_labels())

    assert result["status"] == "PASS_RESEARCH_CHALLENGERS_TRAINED"
    assert result["trained_candidate_count"] == 1
    assert result["hedge_contract"] == worker.HEDGE_CONTRACT
    assert result["hedge_comparison_semantics"] == worker.HEDGE_COMPARISON
    assert result["relative_value_supported"] is False
    assert result["relative_value_block_reason"] == (
        "NO_SYNCHRONIZED_PAIR_OR_BASKET_LABEL_BINDINGS"
    )
    candidate = result["candidates"][0]
    assert candidate["declaration"]["relative_value_supported"] is False
    assert candidate["fit_partition"] == "TRAIN_ONLY"
    assert candidate["holdout_used_for_selection"] is False
    assert set(candidate["train_target_hedge_counts"]) == {"0", "1"}
    assert sum(candidate["train_target_hedge_counts"].values()) == 60
    assert candidate["train_metrics"][
        "counterfactual_counts_as_realized_paper_profit"
    ] is False
    assert candidate["train_metrics"]["actual_accounting_effect"] is False
    assert result["statistical_superiority_proven"] is False
    assert result["activation_eligible"] is False
    assert result["registry_write_attempted"] is False


def test_hedge_holdout_changes_cannot_change_fit_or_validation_selection() -> None:
    dataset = _with_hedge_labels()
    mutated = deepcopy(dataset)
    for row in mutated["rows"]:
        if row["split"] != "holdout":
            continue
        hedge = row["hedge_label_derivation"]
        new_unhedged = -float(hedge["unhedged_after_cost_pnl_bps"])
        hedge["unhedged_after_cost_pnl_bps"] = new_unhedged
        hedge["unhedged_scenario"]["gross_pnl_bps"] = new_unhedged + 2.1
        hedge["unhedged_scenario"]["after_cost_pnl_bps"] = new_unhedged
        hedge["unhedged_scenario_sha256"] = worker._sha256(  # noqa: SLF001
            worker._canonical_bytes(hedge["unhedged_scenario"])  # noqa: SLF001
        )
        row["directional_label_derivation"]["unhedged_scenario_sha256s"] = [
            hedge["unhedged_scenario_sha256"]
        ]
        row["long_net_bps"] = new_unhedged
        row["target_action"] = worker.target_action_from_net_edges(
            long_net_bps=new_unhedged,
            short_net_bps=float(row["short_net_bps"]),
        )
        hedge["hedge_advantage_bps"] = (
            hedge["hedged_after_cost_pnl_bps"]
            - hedge["unhedged_after_cost_pnl_bps"]
        )
        hedge["target_hedge_vs_unhedged"] = hedge["hedge_advantage_bps"] > 0.0
        material = {
            key: value
            for key, value in hedge.items()
            if key != "derivation_sha256"
        }
        hedge["derivation_sha256"] = worker._sha256(  # noqa: SLF001
            worker._canonical_bytes(material)  # noqa: SLF001
        )

    baseline = _build("hedged_relative_value", dataset)["candidates"][0]
    changed = _build("hedged_relative_value", mutated)["candidates"][0]

    assert changed["model_parameter_fingerprint"] == baseline[
        "model_parameter_fingerprint"
    ]
    assert changed["validation_metrics"] == baseline["validation_metrics"]
    assert changed["holdout_used_for_selection"] is False


def test_legacy_dataset_without_hedge_labels_is_truthfully_ineligible() -> None:
    result = _build("hedged_relative_value")

    assert result["status"] == "PASS_NO_ELIGIBLE_SLICE"
    assert result["trained_candidate_count"] == 0
    assert result["rejected_slice_count"] == 1
    assert "TRAIN_HEDGE_ROWS_BELOW_20:0" in result["rejected_slices"][0][
        "exact_reasons"
    ]


@pytest.mark.parametrize(
    "mutation",
    ("advantage", "receipt_substitution", "predecision", "post_label"),
)
def test_coherently_rehashed_invalid_hedge_semantics_fail_closed(
    mutation: str,
) -> None:
    dataset = _with_hedge_labels()
    row = dataset["rows"][0]
    hedge = row["hedge_label_derivation"]
    nested_changed = False
    if mutation == "advantage":
        hedge["hedge_advantage_bps"] += 1.0
    elif mutation == "receipt_substitution":
        for scenario_name in ("unhedged_scenario", "hedged_scenario"):
            hedge[scenario_name]["source_receipt_sha256s"] = ["d" * 64]
        nested_changed = True
    else:
        boundary = datetime.fromisoformat(
            row[
                "decision_time" if mutation == "predecision" else "label_available_at"
            ].replace("Z", "+00:00")
        )
        base_ms = int(boundary.timestamp() * 1_000)
        offsets = (-3, -2, -1) if mutation == "predecision" else (1, 2, 3)
        for scenario_name in ("unhedged_scenario", "hedged_scenario"):
            scenario = hedge[scenario_name]
            scenario["source_event_time_ms"] = base_ms + offsets[0]
            scenario["producer_generated_at_ms"] = base_ms + offsets[1]
            scenario["record_available_at_ms"] = base_ms + offsets[2]
        nested_changed = True
    if nested_changed:
        hedge["unhedged_scenario_sha256"] = worker._sha256(  # noqa: SLF001
            worker._canonical_bytes(hedge["unhedged_scenario"])  # noqa: SLF001
        )
        hedge["hedged_scenario_sha256"] = worker._sha256(  # noqa: SLF001
            worker._canonical_bytes(hedge["hedged_scenario"])  # noqa: SLF001
        )
        row["directional_label_derivation"]["unhedged_scenario_sha256s"] = [
            hedge["unhedged_scenario_sha256"]
        ]
    material = {
        key: value for key, value in hedge.items() if key != "derivation_sha256"
    }
    hedge["derivation_sha256"] = worker._sha256(  # noqa: SLF001
        worker._canonical_bytes(material)  # noqa: SLF001
    )

    with pytest.raises(
        worker.AdaptiveDiversifiedChallengerError,
        match="hedge_label_derivation:SEMANTICS_INVALID",
    ):
        _build("hedged_relative_value", dataset)


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
        "TRAIN_HORIZON_SPECIFIC_CHALLENGERS": (
            "horizon",
            "horizon_challengers",
        ),
        "TRAIN_SYMBOL_OR_REGIME_SPECIFIC_CHALLENGERS": (
            "symbol_regime",
            "symbol_regime_challengers",
        ),
        "TRAIN_ALTERNATIVE_MODEL_ARCHITECTURES": (
            "architecture",
            "architecture_challengers",
        ),
        "TRAIN_HEDGED_AND_RELATIVE_VALUE_POLICIES": (
            "hedged_relative_value",
            "hedged_relative_value_challengers",
        ),
    }
    for step, (mode, output_name) in expected_modes.items():
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
            f"{{dispatch_run_root}}/{output_name}",
        ]
        assert descriptor["paper_only"] is True
        assert descriptor["routes_to_live"] is False
        assert descriptor["exchange_action_taken"] is False
