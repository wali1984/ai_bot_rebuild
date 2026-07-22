from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_base_publisher_cycle_status_v1 as status_module,
)

STATUS_PATH_NAME = "profiled_base_publisher_status_v1.json"


def _status() -> dict[str, Any]:
    status: dict[str, Any] = {name: None for name in status_module._STATUS_FIELDS}
    status.update(
        {
            "schema_version": (
                status_module.PROFILED_BASE_FEATURE_PUBLISHER_STATUS_V1_SCHEMA_VERSION
            ),
            "publisher_schema_version": (
                status_module.PROFILED_BASE_FEATURE_PUBLISHER_V1_SCHEMA_VERSION
            ),
            "classification": "CYCLE_COMPLETE_ALL_SELECTED_AUTHENTICATED_OR_UNCHANGED",
            "cycle_started_at": "2026-07-22T14:19:00.000000Z",
            "discovery_completed_at": "2026-07-22T14:19:01.000000Z",
            "selection_at": "2026-07-22T14:19:02.000000Z",
            "cycle_completed_at": "2026-07-22T14:19:12.360713Z",
            "cycle_elapsed_seconds": 12.360713,
            "cycle_period_seconds": 300.0,
            "resource_sustainability_horizon_seconds": 7_776_000.0,
            "dynamic_selection_universe": {
                "trainer_evidence_or_authority_conferred": False,
            },
            "resource_decision": {},
            "disk_resource_safety": {},
            "cycle_evidence_accounted_bytes": 0,
            "cycle_materialized_artifact_bytes": 0,
            "cycle_materialized_publication_count": 0,
            "cycle_disk_consumption_high_water_bytes": 0,
            "cycle_owned_durable_growth_bytes": 0,
            "evidence_accounting_method": "UNIT_TEST",
            "coverage": {},
            "rotation_last_attempted_at": {},
            "publications": [],
            "masked_cost_observations": [],
            "skips": [],
            "failures": [],
            "rejected_discovery_key_sha256s": [],
            "authority": {
                "trainer_admission_authorized": False,
                "prediction_authorized": False,
                "paper_trading_authorized": False,
                "live_execution_authorized": False,
                "runtime_wired": False,
            },
            "authority_semantics": {
                "publisher_runtime_authority_granted": False,
                "published_child_trainer_admission_authorized": False,
                "masked_parent_trainer_admission_authorized": False,
                "prediction_paper_live_authority_granted": False,
                "automatic_trainer_transition_authorized": False,
            },
            "commission_cost_mode": "MASKED_COST_OBSERVATION",
            "commission_credentials_available": False,
            "commission_broker_reader_available": False,
            "exchange_credentials_loaded_by_publisher": False,
            "legacy_feature_redis_write_performed": False,
            "market_performance_thresholds_applied": False,
            "singleton_writer_lock": {},
            "state_sha256": "1" * 64,
        }
    )
    for count_name, list_name in status_module._SYMBOL_COUNT_LIST_PAIRS:
        status[count_name] = 0
        status[list_name] = []
    status["status_sha256"] = status_module.stable_sha256(
        {name: value for name, value in status.items() if name != "status_sha256"}
    )
    return status


def _write_status(
    tmp_path: Path,
    status: dict[str, Any],
    *,
    recalculate_hash: bool = True,
    canonical: bool = True,
) -> Path:
    material = dict(status)
    if recalculate_hash:
        material["status_sha256"] = status_module.stable_sha256(
            {name: value for name, value in material.items() if name != "status_sha256"}
        )
    payload = (
        json.dumps(
            material,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":") if canonical else None,
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )
    path = (tmp_path / STATUS_PATH_NAME).absolute()
    path.write_bytes(payload)
    path.chmod(0o600)
    return path


def test_reads_exact_canonical_cycle_status_as_local_integrity_only(
    tmp_path: Path,
) -> None:
    status = _status()
    path = _write_status(tmp_path, status)
    result = status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)

    assert result.status_path == path
    assert result.status_sha256 == status["status_sha256"]
    assert result.cycle_completed_at == status["cycle_completed_at"]
    assert result.local_status_integrity_verified is True
    assert result.independent_status_authentication_verified is False
    assert result.external_monotonic_manifest_head_verified is False
    assert result.full_consumption_external_ack_verified is False
    assert result.optimizer_admission_authorized is False
    assert result.checkpoint_write_authorized is False
    assert result.model_write_authorized is False
    assert result.prediction_authorized is False
    assert result.paper_trading_authorized is False
    assert result.live_execution_authorized is False
    assert result.order_submission_authorized is False
    assert result.execution_authorized is False
    assert result.runtime_wired is False


def test_changed_payload_with_stale_status_hash_is_rejected(tmp_path: Path) -> None:
    status = _status()
    status["classification"] = "TAMPERED_AFTER_HASH"
    path = _write_status(tmp_path, status, recalculate_hash=False)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_IDENTITY_INVALID",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_exact_57_field_contract_rejects_missing_or_extra_field(
    tmp_path: Path,
    mutation: str,
) -> None:
    status = _status()
    if mutation == "missing":
        del status["coverage"]
    else:
        status["unexpected_field"] = False
    path = _write_status(tmp_path, status)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_FIELDS_INVALID",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("trainer_admission_authorized", True),
        ("runtime_wired", 0),
    ],
)
def test_publisher_authority_must_be_exact_false(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    status = _status()
    status["authority"] = {**status["authority"], field: value}
    path = _write_status(tmp_path, status)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_AUTHORITY_INVALID",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)


def test_automatic_trainer_transition_must_remain_false(tmp_path: Path) -> None:
    status = _status()
    status["authority_semantics"] = {
        **status["authority_semantics"],
        "automatic_trainer_transition_authorized": True,
    }
    path = _write_status(tmp_path, status)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_AUTHORITY_SEMANTICS_INVALID",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)


@pytest.mark.parametrize(
    "count,values",
    [
        (2, ["BTCUSDT"]),
        (2, ["BTCUSDT", "BTCUSDT"]),
        (1, ["btc-usdt"]),
        (1, [{"symbol": "BTCUSDT"}]),
    ],
)
def test_symbol_count_inventory_must_be_exact_unique_and_canonical(
    tmp_path: Path,
    count: int,
    values: list[Any],
) -> None:
    status = _status()
    status["selected_symbol_count"] = count
    status["selected_symbols"] = values
    path = _write_status(tmp_path, status)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_SYMBOL_INVENTORY_INVALID",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)


@pytest.mark.parametrize(
    "mutation",
    [
        "eligible_not_discovered",
        "selected_not_eligible",
        "deferred_selected_overlap",
        "published_not_selected",
        "outcome_overlap",
        "selected_without_outcome_or_failure",
        "failed_not_discovered",
        "successful_and_failed",
        "eligible_unselected_failure",
    ],
)
def test_symbol_inventory_writer_relations_are_enforced(
    tmp_path: Path,
    mutation: str,
) -> None:
    status = _status()
    status.update(
        {
            "discovered_symbol_count": 2,
            "discovered_symbols": ["BTCUSDT", "ETHUSDT"],
            "eligible_symbol_count": 1,
            "eligible_symbols": ["BTCUSDT"],
            "selected_symbol_count": 1,
            "selected_symbols": ["BTCUSDT"],
            "published_symbol_count": 1,
            "published_symbols": ["BTCUSDT"],
        }
    )
    status["authority_semantics"] = {
        **status["authority_semantics"],
        "published_child_trainer_admission_authorized": True,
    }
    if mutation == "eligible_not_discovered":
        status["eligible_symbols"] = ["SOLUSDT"]
    elif mutation == "selected_not_eligible":
        status["selected_symbols"] = ["ETHUSDT"]
    elif mutation == "deferred_selected_overlap":
        status["resource_deferred_symbol_count"] = 1
        status["resource_deferred_symbols"] = ["BTCUSDT"]
    elif mutation == "published_not_selected":
        status["published_symbols"] = ["ETHUSDT"]
    elif mutation == "outcome_overlap":
        status["unchanged_symbol_count"] = 1
        status["unchanged_symbols"] = ["BTCUSDT"]
    elif mutation == "selected_without_outcome_or_failure":
        status["published_symbol_count"] = 0
        status["published_symbols"] = []
        status["authority_semantics"][
            "published_child_trainer_admission_authorized"
        ] = False
    elif mutation == "failed_not_discovered":
        status["failed_symbol_count"] = 1
        status["failed_symbols"] = ["SOLUSDT"]
    elif mutation == "successful_and_failed":
        status["failed_symbol_count"] = 1
        status["failed_symbols"] = ["BTCUSDT"]
    elif mutation == "eligible_unselected_failure":
        status.update(
            {
                "eligible_symbol_count": 2,
                "eligible_symbols": ["BTCUSDT", "ETHUSDT"],
                "failed_symbol_count": 1,
                "failed_symbols": ["ETHUSDT"],
            }
        )
    path = _write_status(tmp_path, status)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_SYMBOL_INVENTORY_RELATION_INVALID",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)


@pytest.mark.parametrize(
    "published,replayed,claimed",
    [
        (["BTCUSDT"], [], False),
        ([], ["BTCUSDT"], False),
        ([], [], True),
    ],
)
def test_published_child_admission_semantic_matches_writer_formula(
    tmp_path: Path,
    published: list[str],
    replayed: list[str],
    claimed: bool,
) -> None:
    status = _status()
    selected = published or replayed
    if selected:
        status.update(
            {
                "discovered_symbol_count": 1,
                "discovered_symbols": ["BTCUSDT"],
                "eligible_symbol_count": 1,
                "eligible_symbols": ["BTCUSDT"],
                "selected_symbol_count": 1,
                "selected_symbols": ["BTCUSDT"],
                "published_symbol_count": len(published),
                "published_symbols": published,
                "exact_replay_symbol_count": len(replayed),
                "exact_replay_symbols": replayed,
            }
        )
    status["authority_semantics"] = {
        **status["authority_semantics"],
        "published_child_trainer_admission_authorized": claimed,
    }
    path = _write_status(tmp_path, status)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_AUTHORITY_SEMANTICS_INVALID",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)


def test_cycle_clock_rollback_is_rejected(tmp_path: Path) -> None:
    status = _status()
    status["selection_at"] = "2026-07-22T14:18:59.000000Z"
    path = _write_status(tmp_path, status)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_CLOCK_ORDER_INVALID",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)


def test_noncanonical_json_is_rejected_even_with_valid_semantics(tmp_path: Path) -> None:
    path = _write_status(tmp_path, _status(), canonical=False)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_NOT_CANONICAL",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)


def test_duplicate_json_key_is_rejected(tmp_path: Path) -> None:
    status = _status()
    canonical = json.dumps(
        status,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload = canonical[:-1] + ',"status_sha256":"' + status["status_sha256"] + '"}\n'
    path = (tmp_path / STATUS_PATH_NAME).absolute()
    path.write_text(payload, encoding="ascii")
    path.chmod(0o600)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_DUPLICATE_OR_INVALID_KEY",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)


def test_symlink_status_path_is_rejected(tmp_path: Path) -> None:
    target = _write_status(tmp_path, _status())
    link = (tmp_path / "status-link.json").absolute()
    link.symlink_to(target)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_OPEN_FAILED",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=link)


def test_symlinked_parent_directory_is_rejected(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    target = _write_status(real_parent, _status())
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    linked_status = (linked_parent / target.name).absolute()

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_PARENT_CHAIN_INVALID",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(
            status_path=linked_status
        )


def test_group_writable_status_file_is_rejected(tmp_path: Path) -> None:
    path = _write_status(tmp_path, _status())
    os.chmod(path, 0o660)

    with pytest.raises(
        status_module.ProfiledBasePublisherCycleStatusV1Error,
        match="PROFILED_BASE_STATUS_FILE_INVALID",
    ):
        status_module.read_verified_profiled_base_publisher_cycle_status_v1(status_path=path)
