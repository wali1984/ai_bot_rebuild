from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    CanonicalCandle,
)
from v2.backend.app.services.native_trainer import (
    durable_feature_snapshot_ledger as feature_ledger_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_manifest_v1 as manifest_module,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_MODEL_FEATURE_COUNT,
    LOGICAL_MODEL_INPUT_COUNT,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    PROFILED_OBSERVATION_RUNTIME_STATUS,
    PROFILED_OBSERVATION_TRAINING_EXAMPLE_ADAPTER_CONTRACT_VERSION,
    ProfiledTrainingObservationManifestV1Error,
    authenticate_profiled_training_observation_inventory_page_v1,
    authenticate_profiled_training_observation_manifest_v1,
    build_profiled_training_observation_manifest_v1,
    read_profiled_training_observation_page_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_model_feature_snapshot_record_v1 as base_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_ledger_loader_v1 as loader_support,
)

AUTH_KEY = b"profiled-observation-manifest-test-key-v1"
AUTH_KEY_ID = "unit/profiled-observation-v1"


@pytest.fixture(autouse=True)
def trusted_factory_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    trusted_now = max(
        datetime.now(tz=UTC) + timedelta(days=1),
        datetime(2026, 7, 23, tzinfo=UTC),
    )
    monkeypatch.setattr(
        manifest_module,
        "_factory_wall_clock_now",
        lambda: trusted_now,
    )


@pytest.fixture(scope="module")
def authenticated_base_evidence(
    tmp_path_factory: pytest.TempPathFactory,
) -> Any:
    return base_support._build_evidence(
        tmp_path_factory.mktemp("observation-manifest-authenticated-base")
    )


def _label_candles(
    *,
    decision_time: str,
    entry_price: float,
    rows: int = 49,
) -> list[dict[str, Any]]:
    decision = datetime.fromisoformat(decision_time.replace("Z", "+00:00")).astimezone(UTC)
    slot_start = decision.replace(
        minute=(decision.minute // 5) * 5,
        second=0,
        microsecond=0,
    )
    candles: list[dict[str, Any]] = []
    for ordinal in range(rows):
        open_time = slot_start + timedelta(minutes=5 * ordinal)
        close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
        available_at = close_time + timedelta(milliseconds=1)
        close = entry_price * (1.0 + 0.0002 * ordinal)
        raw_hash = hashlib.sha256(
            f"BTCUSDT:{open_time.isoformat()}:{close}".encode("ascii")
        ).hexdigest()
        candles.append(
            CanonicalCandle(
                symbol="BTCUSDT",
                exchange="binance",
                timeframe="5m",
                candle_open_time=int(open_time.timestamp() * 1000),
                candle_close_time=int(close_time.timestamp() * 1000),
                event_time=int(close_time.timestamp() * 1000),
                ingested_at=int(available_at.timestamp() * 1000),
                available_at=int(available_at.timestamp() * 1000),
                is_closed=True,
                source="binance_wss",
                source_sequence_id=f"manifest-test:{ordinal}",
                raw_payload_hash=raw_hash,
                ohlcv={
                    "open": entry_price,
                    "high": max(entry_price, close) * 1.001,
                    "low": min(entry_price, close) * 0.999,
                    "close": close,
                    "volume": 1_000.0 + ordinal,
                    "quote_volume": (1_000.0 + ordinal) * close,
                    "num_trades": 100 + ordinal,
                },
                is_backfilled=False,
                feature_eligible=True,
            ).to_dict()
        )
    return candles


def _setup_sources(
    tmp_path: Path,
    authenticated_base_evidence: Any,
    *,
    label_rows: int = 49,
) -> tuple[Any, DurableCanonical5mLabelArchive, str, Path]:
    parent = authenticated_base_evidence.record
    ledger, _, _ = loader_support._ledger_with_pair(tmp_path, parent)
    envelope = parent["frozen_envelope"]
    feature_values = dict(
        zip(
            envelope["ordered_feature_names"],
            envelope["feature_values"],
            strict=True,
        )
    )
    entry_price = float(feature_values["close"])
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    archive.append_candles(
        _label_candles(
            decision_time=envelope["tensor_decision_time"],
            entry_price=entry_price,
            rows=label_rows,
        )
    )
    observation = loader_support._observation()
    return ledger, archive, observation, (tmp_path / "cost-cas").absolute()


def test_builds_authenticated_manifest_and_reopens_exact_446_1784_example(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    manifest_root = (tmp_path / "manifests").absolute()

    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=manifest_root,
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )
    page = read_profiled_training_observation_page_v1(
        manifest_path=built.manifest_path,
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        hmac_key=AUTH_KEY,
        expected_auth_key_id=AUTH_KEY_ID,
        expected_manifest_id=built.manifest_id,
        expected_observation_time=built.observation_time,
        limit=1,
    )

    assert built.total_profiled_samples == 1
    assert built.admitted_examples == 1
    assert built.label_unavailable_samples == 0
    assert built.checkpoint_write_authorized is False
    assert built.runtime_wired is False
    assert built.manifest_path.name == (
        f"profiled_training_observation_{built.manifest_id}.sqlite3"
    )
    assert len(page.examples) == 1
    assert page.has_more_manifest_entries is False
    example = page.examples[0]
    assert len(example.training_example.tensor.values) == LOGICAL_MODEL_FEATURE_COUNT
    assert len(example.training_example.tensor.model_vector) == LOGICAL_MODEL_INPUT_COUNT
    assert sum(example.training_example.tensor.source_availability) == 35
    assert example.training_example.label_timing_valid is True
    assert example.training_example.row_classification == "TRAINABLE"
    assert example.training_example.behavior_action_index is None
    assert example.optimizer_admission_authorized is False
    assert example.checkpoint_write_authorized is False
    assert example.prediction_authorized is False
    assert example.paper_trading_authorized is False
    assert example.live_execution_authorized is False
    assert example.runtime_wired is False
    assert page.checkpoint_write_authorized is False
    assert page.external_monotonic_manifest_head_verified is False


def test_prepared_factory_clock_makes_crash_replay_deterministic(
    tmp_path: Path,
    authenticated_base_evidence: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    prepared_factory_clock = (
        datetime.fromisoformat(observation.replace("Z", "+00:00"))
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    calls = 0

    def forbidden_wall_clock() -> datetime:
        nonlocal calls
        calls += 1
        raise AssertionError("prepared replay must not resample the wall clock")

    monkeypatch.setattr(manifest_module, "_factory_wall_clock_now", forbidden_wall_clock)
    arguments = {
        "ledger": ledger,
        "trusted_immutable_cost_store_root": cost_root,
        "label_archive": archive,
        "manifest_root": (tmp_path / "prepared-manifests").absolute(),
        "training_observed_at": observation,
        "auth_key_id": AUTH_KEY_ID,
        "hmac_key": AUTH_KEY,
        "prepared_factory_wall_clock_observed_at": prepared_factory_clock,
    }
    first = build_profiled_training_observation_manifest_v1(**arguments)
    second = build_profiled_training_observation_manifest_v1(**arguments)

    assert calls == 0
    assert first.factory_wall_clock_observed_at == prepared_factory_clock
    assert second.manifest_path == first.manifest_path
    assert second.manifest_id == first.manifest_id


def test_prepared_factory_clock_rejects_noncanonical_value(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    prepared = datetime.fromisoformat(observation.replace("Z", "+00:00")).astimezone(UTC)
    noncanonical = prepared.isoformat(timespec="seconds").replace("+00:00", "Z")

    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_PREPARED_FACTORY_WALL_CLOCK_INVALID",
    ):
        build_profiled_training_observation_manifest_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            label_archive=archive,
            manifest_root=(tmp_path / "invalid-prepared-manifests").absolute(),
            training_observed_at=observation,
            auth_key_id=AUTH_KEY_ID,
            hmac_key=AUTH_KEY,
            prepared_factory_wall_clock_observed_at=noncanonical,
        )


def test_prepared_factory_clock_rejects_value_before_observation(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    before = datetime.fromisoformat(observation.replace("Z", "+00:00")) - timedelta(microseconds=1)
    before_text = before.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_RETROSPECTIVE_CUTOFF_AFTER_FACTORY_WALL_CLOCK",
    ):
        build_profiled_training_observation_manifest_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            label_archive=archive,
            manifest_root=(tmp_path / "invalid-prepared-manifests").absolute(),
            training_observed_at=observation,
            auth_key_id=AUTH_KEY_ID,
            hmac_key=AUTH_KEY,
            prepared_factory_wall_clock_observed_at=before_text,
        )


def test_label_path_missing_at_observation_is_typed_exclusion_not_bad_label(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
        label_rows=3,
    )

    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )
    page = read_profiled_training_observation_page_v1(
        manifest_path=built.manifest_path,
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        hmac_key=AUTH_KEY,
        expected_auth_key_id=AUTH_KEY_ID,
        expected_manifest_id=built.manifest_id,
        expected_observation_time=built.observation_time,
    )

    assert built.total_profiled_samples == 1
    assert built.admitted_examples == 0
    assert built.label_unavailable_samples == 1
    assert page.examples == ()
    assert page.next_after_ordinal == 1
    assert page.label_unavailable_scanned == 1


def test_wrong_hmac_key_fails_before_any_training_example_is_returned(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )

    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_METADATA_AUTHENTICATION_INVALID",
    ):
        read_profiled_training_observation_page_v1(
            manifest_path=built.manifest_path,
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            hmac_key=b"wrong-profiled-observation-manifest-key",
            expected_auth_key_id=AUTH_KEY_ID,
            expected_manifest_id=built.manifest_id,
            expected_observation_time=built.observation_time,
        )


def test_later_valid_ledger_suffix_does_not_move_fixed_observation_page(
    tmp_path: Path,
    authenticated_base_evidence: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )
    observed = datetime.fromisoformat(observation.replace("Z", "+00:00")).astimezone(UTC)
    monkeypatch.setattr(
        feature_ledger_module,
        "utc_now",
        lambda: (observed + timedelta(seconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    )
    ledger.append_snapshot(loader_support._generic_same_width_record(suffix="post-observation"))

    page = read_profiled_training_observation_page_v1(
        manifest_path=built.manifest_path,
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        hmac_key=AUTH_KEY,
        expected_auth_key_id=AUTH_KEY_ID,
        expected_manifest_id=built.manifest_id,
        expected_observation_time=built.observation_time,
    )

    assert len(page.examples) == 1
    assert page.manifest_id == built.manifest_id
    assert page.observation_time == observation
    assert page.examples[0].runtime_wired is False
    assert PROFILED_OBSERVATION_RUNTIME_STATUS.endswith("NO_OPTIMIZER_OR_SERVING_AUTHORITY")


def test_factory_reads_every_page_under_one_high_water_when_rows_exceed_page_size(
    tmp_path: Path,
    authenticated_base_evidence: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    generic = loader_support._generic_same_width_record(suffix="manifest-page-two")
    observed = datetime.fromisoformat(observation.replace("Z", "+00:00"))
    commit_clock = (
        (observed - timedelta(seconds=1)).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
    monkeypatch.setattr(feature_ledger_module, "utc_now", lambda: commit_clock)
    append = ledger.append_snapshot(generic)
    assert append.inserted_rows == 1
    attest_calls = 0
    real_attest = ledger._attest_query_snapshot

    def counted_attest(*args: Any, **kwargs: Any) -> None:
        nonlocal attest_calls
        attest_calls += 1
        real_attest(*args, **kwargs)

    monkeypatch.setattr(ledger, "_attest_query_snapshot", counted_attest)

    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
        scan_limit=1,
    )
    page = read_profiled_training_observation_page_v1(
        manifest_path=built.manifest_path,
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        hmac_key=AUTH_KEY,
        expected_auth_key_id=AUTH_KEY_ID,
        expected_manifest_id=built.manifest_id,
        expected_observation_time=built.observation_time,
    )

    assert built.total_profiled_samples == 1
    assert built.ledger_exclusions == 1
    assert len(page.examples) == 1
    assert page.has_more_manifest_entries is False
    connection = sqlite3.connect(built.manifest_path)
    try:
        row = connection.execute(
            "SELECT metadata_json FROM observation_manifest_metadata WHERE singleton = 1"
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    metadata = json.loads(str(row[0]))
    assert metadata["source_page_size"] == 1
    assert metadata["maximum_resident_source_page_rows"] <= 1
    assert metadata["maximum_resident_entry_rows"] <= 1
    assert attest_calls == 1
    assert metadata["factory_memory_semantics"] == (
        "KEYSET_SOURCE_PAGE_PLUS_ONE_ENTRY_NO_FULL_SAMPLE_OR_ENTRY_INVENTORY"
    )


def test_existing_content_address_reauthenticates_every_entry_before_reuse(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    manifest_root = (tmp_path / "manifests").absolute()
    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=manifest_root,
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )
    connection = sqlite3.connect(built.manifest_path)
    try:
        connection.execute("DROP TRIGGER observation_manifest_entries_no_update")
        row = connection.execute(
            "SELECT entry_json FROM observation_manifest_entries WHERE ordinal = 1"
        ).fetchone()
        assert row is not None
        entry = json.loads(str(row[0]))
        entry["runtime_wired"] = True
        tampered = json.dumps(
            entry,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        connection.execute(
            "UPDATE observation_manifest_entries SET entry_json = ? WHERE ordinal = 1",
            (tampered,),
        )
        connection.execute(
            "CREATE TRIGGER observation_manifest_entries_no_update "
            "BEFORE UPDATE ON observation_manifest_entries "
            "BEGIN SELECT RAISE(ABORT, 'observation_manifest_entries_immutable'); END"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_ENTRY_AUTHENTICATION_INVALID",
    ):
        build_profiled_training_observation_manifest_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            label_archive=archive,
            manifest_root=manifest_root,
            training_observed_at=observation,
            auth_key_id=AUTH_KEY_ID,
            hmac_key=AUTH_KEY,
        )


def test_label_entry_uses_authenticated_decision_orderbook_mid_not_prior_close(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )
    connection = sqlite3.connect(built.manifest_path)
    try:
        row = connection.execute(
            "SELECT entry_json FROM observation_manifest_entries WHERE ordinal = 1"
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    entry = json.loads(str(row[0]))
    sample = entry["sample_binding"]
    label_binding = entry["label_binding"]
    directional = label_binding["directional_cost_evidence"]
    parent_envelope = authenticated_base_evidence.record["frozen_envelope"]
    parent_values = dict(
        zip(
            parent_envelope["ordered_feature_names"],
            parent_envelope["feature_values"],
            strict=True,
        )
    )
    prior_finalized_close = float(parent_values["close"])
    reference_mid = float(sample["decision_reference_price"])
    final_close = prior_finalized_close * (
        1.0 + 0.0002 * (entry["label_binding"]["label_path_candle_count"] - 1)
    )

    assert prior_finalized_close != reference_mid
    assert reference_mid == 100.0
    assert directional["decision_reference_price"] == reference_mid
    assert directional["decision_reference_price_source"] == (
        "AUTHENTICATED_CAUSAL_COST_ORDERBOOK_DEPTH_CAS_MID"
    )
    assert (
        directional["decision_reference_price_payload_sha256"]
        == sample["decision_reference_price_payload_sha256"]
    )
    assert (
        directional["decision_reference_price_receipt_sha256"]
        == sample["decision_reference_price_receipt_sha256"]
    )
    assert directional["raw_return_bps"] == pytest.approx(
        ((final_close - reference_mid) / reference_mid) * 10_000.0
    )
    assert directional["chosen_direction"] == "long"
    assert directional["chosen_directional_round_trip_cost_bps"] == pytest.approx(
        directional["long_round_trip_cost_bps"]
    )
    assert label_binding["label_horizon_seconds"] == 900
    assert label_binding["label_horizon_seconds"] == sample["expected_holding_horizon_seconds"]
    target_us = label_binding["label_horizon_target_time_epoch_us"]
    final_close_us = label_binding["label_final_candle_close_time_ms"] * 1_000
    assert target_us <= final_close_us < target_us + 300_000_000


def test_manifest_distinguishes_generated_decision_postcommit_and_observation_clocks(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )
    page = read_profiled_training_observation_page_v1(
        manifest_path=built.manifest_path,
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        hmac_key=AUTH_KEY,
        expected_auth_key_id=AUTH_KEY_ID,
        expected_manifest_id=built.manifest_id,
        expected_observation_time=built.observation_time,
    )
    trust = page.examples[0].training_example.trust_row
    assert trust is not None
    with sqlite3.connect(built.manifest_path) as connection:
        metadata_row = connection.execute(
            "SELECT metadata_json FROM observation_manifest_metadata WHERE singleton = 1"
        ).fetchone()
    assert metadata_row is not None
    metadata = json.loads(str(metadata_row[0]))
    context = metadata["observation_context"]
    adapter_contract = context["training_example_adapter_contract"]
    record_generated = datetime.fromisoformat(
        str(trust["record_generated_at"]).replace("Z", "+00:00")
    )
    decision = datetime.fromisoformat(str(trust["decision_time"]).replace("Z", "+00:00"))
    trainer_sample_available = datetime.fromisoformat(
        str(trust["trainer_sample_available_at"]).replace("Z", "+00:00")
    )
    observed = datetime.fromisoformat(observation.replace("Z", "+00:00"))

    assert record_generated < decision < trainer_sample_available < observed
    assert PROFILED_OBSERVATION_TRAINING_EXAMPLE_ADAPTER_CONTRACT_VERSION == (
        "profiled_training_example_adapter_postcommit_availability_v1"
    )
    assert adapter_contract["schema_version"] == (
        PROFILED_OBSERVATION_TRAINING_EXAMPLE_ADAPTER_CONTRACT_VERSION
    )
    assert adapter_contract["trust_row_available_at_source_field"] == ("postcommit_readback_at")
    assert adapter_contract["record_generated_at_must_not_exceed_decision_time"] is True
    assert adapter_contract["postcommit_readback_at_must_exceed_decision_time"] is True
    assert adapter_contract["postcommit_readback_at_must_exceed_record_generated_at"] is True
    assert context["training_example_adapter_contract_sha256"] == (
        manifest_module.stable_sha256(adapter_contract)
    )
    assert trust["training_example_adapter_contract_version"] == (
        PROFILED_OBSERVATION_TRAINING_EXAMPLE_ADAPTER_CONTRACT_VERSION
    )
    assert (
        trust["training_example_adapter_contract_sha256"]
        == (context["training_example_adapter_contract_sha256"])
    )
    assert trust["available_at"] == trust["postcommit_readback_at"]
    assert trust["available_at"] == trust["trainer_sample_available_at"]
    assert trust["available_at"] != trust["record_generated_at"]
    assert trainer_sample_available > record_generated
    assert trust["available_at_semantics"] == (
        "TRAINER_SAMPLE_DURABLY_AVAILABLE_AT_LEDGER_POSTCOMMIT_READBACK"
    )
    assert trust["trainer_sample_available_at_source"] == ("LEDGER_POSTCOMMIT_READBACK_RECEIPT")
    assert trust["trainer_sample_available_at"] == trust["postcommit_readback_at"]
    assert (
        datetime.fromisoformat(
            str(trust["decision_reference_price_available_at"]).replace("Z", "+00:00")
        )
        <= decision
    )

    revised_contract = {
        **adapter_contract,
        "schema_version": "profiled_training_example_adapter_postcommit_availability_v2",
    }
    revised_context = {
        **context,
        "training_example_adapter_contract": revised_contract,
        "training_example_adapter_contract_sha256": manifest_module.stable_sha256(revised_contract),
    }
    revised_metadata_without_id = {
        **{name: value for name, value in metadata.items() if name != "manifest_id"},
        "observation_context": revised_context,
        "observation_context_sha256": manifest_module.stable_sha256(revised_context),
    }
    assert manifest_module.stable_sha256(revised_metadata_without_id) != built.manifest_id


def test_future_retrospective_cutoff_is_rejected_by_factory_wall_clock(
    tmp_path: Path,
    authenticated_base_evidence: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, archive, _observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    trusted_wall_clock = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(
        manifest_module,
        "_factory_wall_clock_now",
        lambda: trusted_wall_clock,
    )
    future_cutoff = (
        (trusted_wall_clock + timedelta(microseconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )

    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_RETROSPECTIVE_CUTOFF_AFTER_FACTORY_WALL_CLOCK",
    ):
        build_profiled_training_observation_manifest_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            label_archive=archive,
            manifest_root=(tmp_path / "manifests").absolute(),
            training_observed_at=future_cutoff,
            auth_key_id=AUTH_KEY_ID,
            hmac_key=AUTH_KEY,
        )


def test_runtime_page_skips_full_database_check_after_factory_readback(
    tmp_path: Path,
    authenticated_base_evidence: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    full_checks = 0
    real_check = manifest_module._run_full_sqlite_check

    def counted_check(connection: sqlite3.Connection) -> None:
        nonlocal full_checks
        full_checks += 1
        real_check(connection)

    monkeypatch.setattr(manifest_module, "_run_full_sqlite_check", counted_check)
    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )
    factory_full_checks = full_checks
    assert factory_full_checks == 1

    page = read_profiled_training_observation_page_v1(
        manifest_path=built.manifest_path,
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        hmac_key=AUTH_KEY,
        expected_auth_key_id=AUTH_KEY_ID,
        expected_manifest_id=built.manifest_id,
        expected_observation_time=built.observation_time,
    )

    assert len(page.examples) == 1
    assert full_checks == factory_full_checks


def test_random_access_anchor_hmac_binds_chain_columns(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )
    connection = sqlite3.connect(built.manifest_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("DROP TRIGGER observation_manifest_entries_no_update")
        row = connection.execute(
            "SELECT * FROM observation_manifest_entries WHERE ordinal = 1"
        ).fetchone()
        assert row is not None
        altered_previous = "f" * 64
        altered_chain = manifest_module._entry_chain(
            altered_previous,
            str(row["entry_sha256"]),
        )
        connection.execute(
            "UPDATE observation_manifest_entries "
            "SET previous_entry_chain_sha256 = ?, entry_chain_sha256 = ? "
            "WHERE ordinal = 1",
            (altered_previous, altered_chain),
        )
        altered = connection.execute(
            "SELECT * FROM observation_manifest_entries WHERE ordinal = 1"
        ).fetchone()
        metadata_row = connection.execute(
            "SELECT metadata_json FROM observation_manifest_metadata WHERE singleton = 1"
        ).fetchone()
        assert altered is not None and metadata_row is not None
        metadata = json.loads(str(metadata_row[0]))
    finally:
        connection.close()

    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_ENTRY_AUTHENTICATION_INVALID",
    ):
        manifest_module._verify_entry_row(
            altered,
            key=AUTH_KEY,
            observation_context_sha256=metadata["observation_context_sha256"],
            expected_previous_chain=None,
        )


def test_actual_trigger_definition_is_authenticated(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )
    connection = sqlite3.connect(built.manifest_path)
    try:
        connection.execute("DROP TRIGGER observation_manifest_entries_no_update")
        connection.execute(
            "CREATE TRIGGER observation_manifest_entries_no_update "
            "BEFORE UPDATE ON observation_manifest_entries BEGIN SELECT 1; END"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_MANIFEST_SCHEMA_INVALID",
    ):
        read_profiled_training_observation_page_v1(
            manifest_path=built.manifest_path,
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            hmac_key=AUTH_KEY,
            expected_auth_key_id=AUTH_KEY_ID,
            expected_manifest_id=built.manifest_id,
            expected_observation_time=built.observation_time,
        )


@pytest.mark.parametrize("wrong_field", ["manifest_id", "observation_time"])
def test_page_requires_exact_external_manifest_pin(
    tmp_path: Path,
    authenticated_base_evidence: Any,
    wrong_field: str,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )
    expected_manifest_id = "0" * 64 if wrong_field == "manifest_id" else built.manifest_id
    expected_observation_time = built.observation_time
    if wrong_field == "observation_time":
        expected_observation_time = (
            (
                datetime.fromisoformat(built.observation_time.replace("Z", "+00:00"))
                + timedelta(microseconds=1)
            )
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_EXPECTED_MANIFEST_BINDING_MISMATCH",
    ):
        read_profiled_training_observation_page_v1(
            manifest_path=built.manifest_path,
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            hmac_key=AUTH_KEY,
            expected_auth_key_id=AUTH_KEY_ID,
            expected_manifest_id=expected_manifest_id,
            expected_observation_time=expected_observation_time,
        )


def test_full_manifest_authentication_returns_only_non_authoritative_scalar_summary(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )

    authenticated = authenticate_profiled_training_observation_manifest_v1(
        manifest_path=built.manifest_path,
        hmac_key=AUTH_KEY,
        expected_auth_key_id=AUTH_KEY_ID,
        expected_manifest_id=built.manifest_id,
        expected_observation_time=built.observation_time,
    )
    page = authenticate_profiled_training_observation_inventory_page_v1(
        authenticated_manifest=authenticated,
        hmac_key=AUTH_KEY,
        limit=1,
    )

    assert authenticated.manifest_id == built.manifest_id
    assert authenticated.feature_ledger_verified_records == 2
    assert authenticated.feature_ledger_prefix_head_sequence == 1
    assert authenticated.label_archive_verified_rows == 49
    assert authenticated.label_archive_prefix_head_sequence == 49
    assert authenticated.full_manifest_authentication_verified is True
    assert authenticated.full_entry_inventory_verified is True
    assert authenticated.external_monotonic_manifest_head_verified is False
    assert authenticated.full_consumption_external_ack_verified is False
    assert authenticated.optimizer_admission_authorized is False
    assert authenticated.checkpoint_write_authorized is False
    assert authenticated.model_write_authorized is False
    assert authenticated.prediction_authorized is False
    assert authenticated.paper_trading_authorized is False
    assert authenticated.live_execution_authorized is False
    assert authenticated.execution_authorized is False
    assert authenticated.runtime_wired is False
    assert page.scanned_entry_count == 1
    assert page.admitted_entry_count == 1
    assert page.label_unavailable_count == 0
    assert page.page_start_previous_entry_chain_sha256 == (
        manifest_module.PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS
    )
    assert page.page_end_entry_chain_sha256 == authenticated.entry_chain_head_sha256
    assert page.has_more_manifest_entries is False
    assert page.external_monotonic_manifest_head_verified is False
    assert page.runtime_wired is False


def test_full_authentication_rejects_key_key_id_tamper_and_unsafe_path_bindings(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, archive, observation, cost_root = _setup_sources(
        tmp_path,
        authenticated_base_evidence,
    )
    built = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )
    call = {
        "manifest_path": built.manifest_path,
        "hmac_key": AUTH_KEY,
        "expected_auth_key_id": AUTH_KEY_ID,
        "expected_manifest_id": built.manifest_id,
        "expected_observation_time": built.observation_time,
    }

    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_METADATA_AUTHENTICATION_INVALID",
    ):
        authenticate_profiled_training_observation_manifest_v1(**{**call, "hmac_key": b"x" * 32})
    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_METADATA_AUTHENTICATION_INVALID",
    ):
        authenticate_profiled_training_observation_manifest_v1(
            **{**call, "expected_auth_key_id": "unit/wrong-manifest-key"}
        )

    os.chmod(built.manifest_path, 0o640)
    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_PROMOTION_PATH_PROTECTION_INVALID",
    ):
        authenticate_profiled_training_observation_manifest_v1(**call)
    os.chmod(built.manifest_path, 0o600)

    hardlink = tmp_path / "manifest-hardlink.sqlite3"
    os.link(built.manifest_path, hardlink)
    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_PROMOTION_PATH_PROTECTION_INVALID",
    ):
        authenticate_profiled_training_observation_manifest_v1(**call)
    hardlink.unlink()

    symlink_root = tmp_path / "symlink-manifest"
    symlink_root.mkdir()
    symlink = symlink_root / built.manifest_path.name
    symlink.symlink_to(built.manifest_path)
    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_PROMOTION_PATH_OPEN_FAILED",
    ):
        authenticate_profiled_training_observation_manifest_v1(**{**call, "manifest_path": symlink})

    tamper_root = tmp_path / "tampered-manifest"
    tamper_root.mkdir()
    tampered = tamper_root / built.manifest_path.name
    shutil.copyfile(built.manifest_path, tampered)
    os.chmod(tampered, 0o600)
    connection = sqlite3.connect(tampered)
    try:
        connection.execute("DROP TRIGGER observation_manifest_metadata_no_update")
        connection.execute(
            "UPDATE observation_manifest_metadata SET metadata_sha256 = ?",
            ("f" * 64,),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="PROFILED_OBSERVATION_MANIFEST_SCHEMA_INVALID|"
        "PROFILED_OBSERVATION_METADATA_AUTHENTICATION_INVALID",
    ):
        authenticate_profiled_training_observation_manifest_v1(
            **{**call, "manifest_path": tampered}
        )
