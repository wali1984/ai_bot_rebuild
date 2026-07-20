from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from v2.backend.app.cli import v2_adaptive_gate_tuner as tuner

BASE = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
SESSION_ID = "paper-session-2026-07-17"


def _canonical_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class FakeRedis:
    def __init__(self, values: dict[str, object]):
        self.values = dict(values)
        self.read_keys: list[str] = []
        self.write_calls: list[tuple[str, str, int | None]] = []

    def get(self, key: str) -> object | None:
        self.read_keys.append(key)
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.write_calls.append((key, value, ex))
        self.values[key] = value
        return True


def _clean_row(
    index: int,
    *,
    pnl: float = 1.0,
    confidence: float = 0.60,
    session_id: str = SESSION_ID,
) -> dict[str, object]:
    close_time = BASE - timedelta(minutes=60 - index)
    feature_cutoff = close_time - timedelta(minutes=2)
    feature_available_at = feature_cutoff + timedelta(milliseconds=100)
    decision_time = feature_available_at + timedelta(milliseconds=100)
    entry_execution_time = decision_time + timedelta(milliseconds=100)
    return {
        "close_id": f"close-{index}",
        "position_id": f"position-{index}",
        "prediction_id": f"prediction-{index}",
        "entry_prediction_id": f"prediction-{index}",
        "paper_session_id": session_id,
        "session_id": session_id,
        "reset_session_id": session_id,
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "dirty_flag": False,
        "dirty_reasons": [],
        "future_labels_used_as_features": False,
        "candidate_selected_after_outcome": False,
        "post_outcome_candidate_selection": False,
        "source_hashes": {
            "prediction_hash": f"{index + 1:064x}",
            "source_lineage_hash": f"{index + 10_001:064x}",
        },
        "realized_net_pnl_usd": pnl,
        "confidence_calibrated": confidence,
        "feature_cutoff": _canonical_utc(feature_cutoff),
        "entry_feature_cutoff": _canonical_utc(feature_cutoff),
        "feature_available_at": _canonical_utc(feature_available_at),
        "entry_feature_available_at": _canonical_utc(feature_available_at),
        "available_at": _canonical_utc(feature_available_at),
        "decision_time": _canonical_utc(decision_time),
        "entry_execution_time": _canonical_utc(entry_execution_time),
        "entry_time": _canonical_utc(entry_execution_time),
        "closed_quantity": 0.1,
        "entry_price": 100.0,
        "exit_price": 101.0 if pnl > 0 else 99.0,
        "close_reason": "TIER_1_PROFIT_TARGET" if pnl > 0 else "TIER_1_STOP",
        "exit_time": _canonical_utc(close_time),
        "outcome_available_at": _canonical_utc(close_time + timedelta(seconds=1)),
        "grade": "B",
    }


def _source_values(rows: Sequence[object]) -> dict[str, object]:
    values: dict[str, object] = {
        tuner.OUTCOMES_KEY: json.dumps(rows, sort_keys=True),
        tuner.PAPER_SESSION_KEY: json.dumps(
            {
                "paper_session_id": SESSION_ID,
                "reset_session_id": SESSION_ID,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            },
            sort_keys=True,
        ),
        tuner.TRAINER_METRICS_KEY: json.dumps(
            {"win_rate_percent": 60.0, "profit_factor": 1.5},
            sort_keys=True,
        ),
    }
    for symbol, key in zip(
        tuner.MARKET_CANDLE_SYMBOLS,
        tuner.MARKET_CANDLE_KEYS,
        strict=True,
    ):
        candles: list[dict[str, object]] = []
        for index in range(100):
            close_time = BASE - timedelta(minutes=100 - index, milliseconds=1)
            event_time = close_time + timedelta(milliseconds=100)
            available_at = event_time + timedelta(milliseconds=100)
            range_bps = 10.0 + float(index % 20)
            half_range = (range_bps / 10_000.0) * 100.0 / 2.0
            candles.append(
                {
                    "symbol": symbol,
                    "timeframe": tuner.MARKET_CANDLE_TIMEFRAME,
                    "open_time": int((close_time - timedelta(minutes=1)).timestamp() * 1000),
                    "event_time": int(event_time.timestamp() * 1000),
                    "candle_close_time": int(close_time.timestamp() * 1000),
                    "close_time": int(close_time.timestamp() * 1000),
                    "available_at": int(available_at.timestamp() * 1000),
                    "is_closed": True,
                    "closed_candle": True,
                    "candle_closed_confirmed": True,
                    "feature_eligible": True,
                    "open": 100.0,
                    "high": 100.0 + half_range,
                    "low": 100.0 - half_range,
                    "close": 100.0,
                    "volume": 10.0,
                }
            )
        values[key] = json.dumps(candles, sort_keys=True)
    return values


def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    values = iter(
        (
            BASE,
            BASE + timedelta(seconds=1),
            BASE + timedelta(seconds=2),
        )
    )
    monkeypatch.setattr(tuner, "_utc_now", lambda: next(values))


def _reseal_state(state: dict[str, object]) -> None:
    material = state["canonical_policy_material"]
    assert isinstance(material, dict)
    material_hash = tuner._sha256_canonical(material)
    policy_id = f"adaptive_gate_policy_{material_hash[:24]}"
    state["canonical_policy_material_hash_sha256"] = material_hash
    state["policy_id"] = policy_id
    receipt = state["publication_receipt"]
    assert isinstance(receipt, dict)
    for field in (
        "policy_id",
        "canonical_policy_material_hash_sha256",
        "canonical_source_snapshot_hash_sha256",
        "outcomes_source_key",
        "outcomes_source_hash_sha256",
        "outcomes_cutoff",
        "generated_at",
        "available_at",
        "expires_at",
    ):
        receipt[field] = state[field]
    unsigned = copy.deepcopy(state)
    unsigned.pop("publication_receipt")
    unsigned.pop("receipt_hash_sha256")
    receipt_hash = tuner._receipt_hash(unsigned)
    state["receipt_hash_sha256"] = receipt_hash
    receipt["receipt_hash_sha256"] = receipt_hash


def _replace_source_rows(
    sources: dict[str, object],
    source_key: str,
    rows: object,
) -> None:
    sources[source_key] = json.dumps(rows, sort_keys=True)


def test_canonical_cli_is_deterministic_sealed_single_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index, pnl=1.0 if index < 14 else -0.25) for index in range(20)]
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert redis_client.read_keys == list(tuner.CANONICAL_SOURCE_KEYS)
    assert len(redis_client.write_calls) == 1
    write_key, serialized, ttl = redis_client.write_calls[0]
    assert write_key == tuner.GATE_TUNING_KEY
    assert ttl == tuner.GATE_TUNING_TTL_SECONDS
    assert serialized == tuner._canonical_json(state)
    assert state["schema_version"] == tuner.GATE_TUNING_SCHEMA_VERSION
    assert state["policy_version"] == tuner.GATE_TUNING_POLICY_VERSION
    assert state["producer"] == tuner.CANONICAL_PRODUCER
    assert state["authoritative"] is True
    assert state["paper_only"] is True
    assert state["routes_to_live"] is False
    assert state["places_real_order"] is False
    assert state["outcomes_cutoff"] == "2026-07-17T12:00:00.000000Z"
    assert state["generated_at"] == "2026-07-17T12:00:01.000000Z"
    assert state["available_at"] == "2026-07-17T12:00:02.000000Z"
    assert state["expires_at"] == "2026-07-17T13:00:02.000000Z"
    assert state["current_paper_session_id"] == SESSION_ID
    assert state["source_key"] == tuner.OUTCOMES_KEY
    assert state["source_hash"] == tuner._raw_sha256(redis_client.values[tuner.OUTCOMES_KEY])
    assert state["canonical_source_snapshot_hash_sha256"] == tuner._sha256_canonical(
        state["canonical_source_snapshot"]
    )
    rebound, normalized_snapshot, snapshot_reasons = tuner._decode_bound_source_snapshot(
        state["canonical_source_snapshot"]
    )
    assert snapshot_reasons == []
    assert normalized_snapshot == state["canonical_source_snapshot"]
    assert rebound == {
        key: str(redis_client.values[key]).encode("utf-8") for key in tuner.CANONICAL_SOURCE_KEYS
    }
    assert state["admitted_row_count"] == 20
    assert state["rejected_row_count"] == 0
    assert state["evidence_sufficient"] is True
    assert state["enable_b_grade"] is True
    assert state["policy_id"].startswith("adaptive_gate_policy_")
    assert state["canonical_policy_material_hash_sha256"] == tuner._sha256_canonical(
        state["canonical_policy_material"]
    )
    unsigned = copy.deepcopy(state)
    unsigned.pop("publication_receipt")
    unsigned.pop("receipt_hash_sha256")
    assert state["receipt_hash_sha256"] == tuner._receipt_hash(unsigned)
    assert state["publication_receipt"]["receipt_hash_sha256"] == state["receipt_hash_sha256"]


def test_same_sources_and_clocks_produce_byte_identical_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _source_values([_clean_row(index) for index in range(20)])
    first = FakeRedis(sources)
    _clock(monkeypatch)
    first_state = tuner.run_adaptive_tuning(first)

    second = FakeRedis(sources)
    _clock(monkeypatch)
    second_state = tuner.run_adaptive_tuning(second)

    assert second_state == first_state
    assert second.write_calls[0][1] == first.write_calls[0][1]


@pytest.mark.parametrize("retained_alias", ("candle_close_time", "close_time"))
def test_sealed_market_source_accepts_each_valid_single_close_clock_alias(
    monkeypatch: pytest.MonkeyPatch,
    retained_alias: str,
) -> None:
    sources = _source_values([_clean_row(index) for index in range(20)])
    source_key = tuner.MARKET_CANDLE_KEYS[0]
    candles = json.loads(str(sources[source_key]))
    removed_alias = "close_time" if retained_alias == "candle_close_time" else "candle_close_time"
    for candle in candles:
        candle.pop(removed_alias)
    _replace_source_rows(sources, source_key, candles)
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    analysis = state["market_regime"]["source_analyses"][0]
    assert analysis["source_row_count"] == 100
    assert analysis["admitted_row_count"] == 100
    assert analysis["rejected_row_count"] == 0
    assert analysis["row_rejection_reason_counts"] == {}
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


@pytest.mark.parametrize(
    ("invalid_case", "expected_reason"),
    (
        ("VALID_AND_FUTURE_CONFLICT", "CLOSE_TIME_ALIAS_CONFLICT"),
        ("NULL_SIBLING", "CLOSE_TIME_INVALID"),
        ("EMPTY_SIBLING", "CLOSE_TIME_INVALID"),
        ("WRONG_TYPE_SIBLING", "CLOSE_TIME_INVALID"),
    ),
)
def test_sealed_market_source_rejects_every_invalid_present_close_clock_alias(
    monkeypatch: pytest.MonkeyPatch,
    invalid_case: str,
    expected_reason: str,
) -> None:
    sources = _source_values([_clean_row(index) for index in range(20)])
    source_key = tuner.MARKET_CANDLE_KEYS[0]
    candles = json.loads(str(sources[source_key]))
    invalid_value: object
    if invalid_case == "VALID_AND_FUTURE_CONFLICT":
        invalid_value = int((BASE + timedelta(minutes=1)).timestamp() * 1000)
    elif invalid_case == "NULL_SIBLING":
        invalid_value = None
    elif invalid_case == "EMPTY_SIBLING":
        invalid_value = ""
    else:
        invalid_value = {"epoch_ms": int(BASE.timestamp() * 1000)}
    for candle in candles:
        candle["close_time"] = invalid_value
    _replace_source_rows(sources, source_key, candles)
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    analysis = state["market_regime"]["source_analyses"][0]
    assert analysis["source_row_count"] == 100
    assert analysis["admitted_row_count"] == 0
    assert analysis["rejected_row_count"] == 100
    assert analysis["row_rejection_reason_counts"][expected_reason] == 100
    assert state["market_evidence_sufficient"] is False
    assert state["permissive_authority"] is False
    assert state["adaptive_confidence_threshold"] == tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_sealed_market_source_rejects_submicrosecond_close_alias_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _source_values([_clean_row(index) for index in range(20)])
    source_key = tuner.MARKET_CANDLE_KEYS[0]
    candles = json.loads(str(sources[source_key]))
    for candle in candles:
        raw_close = candle["candle_close_time"]
        assert type(raw_close) is int
        close = datetime.fromtimestamp(raw_close // 1000, tz=UTC) + timedelta(
            milliseconds=raw_close % 1000
        )
        stem = _canonical_utc(close).removesuffix("Z")
        candle["candle_close_time"] = f"{stem}1Z"
        candle["close_time"] = f"{stem}9Z"
    _replace_source_rows(sources, source_key, candles)
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    analysis = state["market_regime"]["source_analyses"][0]
    assert analysis["source_row_count"] == 100
    assert analysis["admitted_row_count"] == 0
    assert analysis["rejected_row_count"] == 100
    assert analysis["row_rejection_reason_counts"]["CLOSE_TIME_INVALID"] == 100
    assert state["market_evidence_sufficient"] is False
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


@pytest.mark.parametrize("collection_alias", ("trades", "closed_trades", "rows"))
def test_sealed_outcome_envelope_accepts_each_valid_single_collection_alias(
    monkeypatch: pytest.MonkeyPatch,
    collection_alias: str,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    sources = _source_values(rows)
    _replace_source_rows(sources, tuner.OUTCOMES_KEY, {collection_alias: rows})
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["source_row_count"] == 20
    assert state["admitted_row_count"] == 20
    assert state["rejected_row_count"] == 0
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_sealed_outcome_envelope_accepts_type_exact_equivalent_collection_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    sources = _source_values(rows)
    _replace_source_rows(
        sources,
        tuner.OUTCOMES_KEY,
        {
            "trades": rows,
            "closed_trades": copy.deepcopy(rows),
            "rows": copy.deepcopy(rows),
        },
    )
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 20
    assert state["rejected_row_count"] == 0
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


@pytest.mark.parametrize(
    ("invalid_case", "expected_reason"),
    (
        ("CONFLICTING_CONTENT", "SOURCE_PAYLOAD_ROWS_ALIAS_CONFLICT"),
        ("NULL_SIBLING", "SOURCE_PAYLOAD_ROWS_INVALID"),
        ("WRONG_TYPE_SIBLING", "SOURCE_PAYLOAD_ROWS_INVALID"),
        ("EMPTY_AND_POPULATED", "SOURCE_PAYLOAD_ROWS_ALIAS_CONFLICT"),
    ),
)
def test_sealed_outcome_envelope_rejects_every_invalid_present_collection_alias(
    monkeypatch: pytest.MonkeyPatch,
    invalid_case: str,
    expected_reason: str,
) -> None:
    positive_rows = [_clean_row(index, pnl=1.0) for index in range(20)]
    negative_rows = [_clean_row(index, pnl=-1.0) for index in range(20)]
    sibling: object
    if invalid_case == "CONFLICTING_CONTENT":
        sibling = negative_rows
    elif invalid_case == "NULL_SIBLING":
        sibling = None
    elif invalid_case == "WRONG_TYPE_SIBLING":
        sibling = {"rows": negative_rows}
    else:
        sibling = []
    sources = _source_values(positive_rows)
    _replace_source_rows(
        sources,
        tuner.OUTCOMES_KEY,
        {"trades": positive_rows, "closed_trades": sibling},
    )
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["source_row_count"] == 0
    assert state["admitted_row_count"] == 0
    assert state["source_rejection_reason_counts"][expected_reason] == 1
    assert state["permissive_authority"] is False
    assert state["adaptive_confidence_threshold"] == tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_source_capture_freezes_mutable_bytes_before_later_reads_can_mutate_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _source_values([_clean_row(index) for index in range(20)])
    original_outcomes = str(sources[tuner.OUTCOMES_KEY]).encode("utf-8")
    mutable_outcomes = bytearray(original_outcomes)
    sources[tuner.OUTCOMES_KEY] = mutable_outcomes

    class MutatingRedis(FakeRedis):
        def get(self, key: str) -> object | None:
            if key != tuner.OUTCOMES_KEY and mutable_outcomes != b"[]":
                mutable_outcomes[:] = b"[]"
            return super().get(key)

    redis_client = MutatingRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert mutable_outcomes == b"[]"
    assert state["admitted_row_count"] == 20
    assert state["source_hash"] == tuner._raw_sha256(original_outcomes)
    rebound, _snapshot, reasons = tuner._decode_bound_source_snapshot(
        state["canonical_source_snapshot"]
    )
    assert reasons == []
    assert rebound is not None
    assert rebound[tuner.OUTCOMES_KEY] == original_outcomes


def test_dirty_future_wrong_session_and_missing_lineage_rows_are_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clean = _clean_row(0)
    dirty = _clean_row(1)
    dirty["dirty_flag"] = True
    future = _clean_row(2)
    future["outcome_available_at"] = _canonical_utc(BASE + timedelta(seconds=30))
    wrong_session = _clean_row(3, session_id="prior-session")
    missing_lineage = _clean_row(4)
    missing_lineage.pop("source_hashes")
    nonfinite = _clean_row(5)
    nonfinite["realized_net_pnl_usd"] = float("nan")
    redis_client = FakeRedis(
        _source_values([clean, dirty, future, wrong_session, missing_lineage, nonfinite])
    )
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 1
    assert state["rejected_row_count"] == 5
    reasons = state["rejection_reason_counts"]
    assert reasons["ROW_DIRTY"] == 1
    assert reasons["OUTCOME_AVAILABLE_AT_AFTER_OUTCOMES_CUTOFF"] == 1
    assert reasons["ROW_SESSION_MISMATCH"] == 1
    assert reasons["SOURCE_HASH_LINEAGE_MISSING"] == 1
    assert reasons["REALIZED_PNL_MISSING_OR_NONFINITE"] == 1
    assert state["policy_status"] == "FAIL_CLOSED_INSUFFICIENT_OR_UNTRUSTED_EVIDENCE"
    assert state["permissive_authority"] is False
    assert state["enable_b_grade"] is False
    assert state["enable_a_grade"] is False
    assert state["adaptive_confidence_threshold"] == tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    assert state["adaptive_loss_probability_threshold"] == (
        tuner.FAIL_CLOSED_LOSS_PROBABILITY_CEILING
    )
    assert state["adaptive_long_confidence_floor"] == tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    assert state["adaptive_short_confidence_floor"] == tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    assert state["adaptive_expectancy_floor"] == 0.0
    assert state["adaptive_entry_freeze_allowance"] == 0.0


def test_explicit_exact_safe_outcome_fields_are_admitted_by_the_sealed_producer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert all(
        row["dirty_flag"] is False
        and type(row["dirty_reasons"]) is list
        and row["dirty_reasons"] == []
        and row["future_labels_used_as_features"] is False
        and row["candidate_selected_after_outcome"] is False
        and row["post_outcome_candidate_selection"] is False
        for row in rows
    )
    assert state["admitted_row_count"] == 20
    assert state["rejected_row_count"] == 0
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


@pytest.mark.parametrize(
    ("field", "expected_reason"),
    (
        ("dirty_flag", "ROW_DIRTY"),
        ("dirty_reasons", "ROW_DIRTY"),
        ("future_labels_used_as_features", "ROW_FUTURE_LABEL_LEAKAGE_FLAGGED"),
        ("candidate_selected_after_outcome", "ROW_POST_OUTCOME_SELECTION_FLAGGED"),
        ("post_outcome_candidate_selection", "ROW_POST_OUTCOME_SELECTION_FLAGGED"),
    ),
)
def test_each_required_outcome_safety_field_rejects_all_ambiguous_values_in_sealed_source(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    expected_reason: str,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    invalid_values: tuple[object, ...]
    if field == "dirty_reasons":
        invalid_values = (None, False, 0, 1, "", {}, ["DIRTY"])
    else:
        invalid_values = (None, 0, 1, "false", {}, [], True)
    for index, row in enumerate(rows):
        if index % (len(invalid_values) + 1) == 0:
            row.pop(field)
        else:
            row[field] = invalid_values[(index - 1) % len(invalid_values)]
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["source_row_count"] == 20
    assert state["admitted_row_count"] == 0
    assert state["rejected_row_count"] == 20
    assert state["rejection_reason_counts"][expected_reason] == 20
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_conflicting_independent_repro_rows_cannot_create_permissive_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row["paper_close_id"] = f"forged-{row['close_id']}"
        row["realized_pnl_usd"] = -1000.0
        row["pnl_usd"] = -2000.0
        row["close_available_at"] = _canonical_utc(BASE + timedelta(seconds=30))
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 0
    assert state["rejected_row_count"] == 20
    reasons = state["rejection_reason_counts"]
    assert reasons["CLOSE_ID_ALIAS_CONFLICT"] == 20
    assert reasons["REALIZED_PNL_ALIAS_CONFLICT"] == 20
    assert reasons["OUTCOME_AVAILABLE_AT_ALIAS_CONFLICT"] == 20
    assert state["permissive_authority"] is False
    assert state["enable_b_grade"] is False
    material = state["canonical_policy_material"]
    assert isinstance(material, dict)
    evidence = material["outcomes_evidence"]
    assert isinstance(evidence, dict)
    assert evidence["rejection_reason_counts"] == reasons
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []

    forged = copy.deepcopy(state)
    forged_outcomes = forged["outcomes"]
    assert isinstance(forged_outcomes, dict)
    forged_counts = forged_outcomes["rejection_reason_counts"]
    assert isinstance(forged_counts, dict)
    forged_counts["REALIZED_PNL_ALIAS_CONFLICT"] = 19
    _reseal_state(forged)

    validator_reasons = tuner.adaptive_gate_tuning_rejection_reasons(forged)

    assert "OUTCOMES_SOURCE_DERIVATION_MISMATCH" in validator_reasons
    assert "PUBLICATION_RECEIPT_HASH_INVALID" not in validator_reasons


@pytest.mark.parametrize(
    ("alias_field", "conflicting_value", "expected_reason"),
    (
        ("paper_close_id", "forged-close", "CLOSE_ID_ALIAS_CONFLICT"),
        ("realized_pnl_usd", -1000.0, "REALIZED_PNL_ALIAS_CONFLICT"),
        ("entry_confidence", 0.95, "CONFIDENCE_ALIAS_CONFLICT"),
        ("close_quantity", 0.2, "CLOSED_QUANTITY_ALIAS_CONFLICT"),
        ("exit_fill_price", 999.0, "EXIT_PRICE_ALIAS_CONFLICT"),
        ("exit_reason", "CONFLICTING_REASON", "CLOSE_REASON_ALIAS_CONFLICT"),
        ("closed_at", _canonical_utc(BASE), "CLOSE_TIME_ALIAS_CONFLICT"),
        (
            "close_available_at",
            _canonical_utc(BASE + timedelta(seconds=30)),
            "OUTCOME_AVAILABLE_AT_ALIAS_CONFLICT",
        ),
    ),
)
def test_each_material_alias_family_fails_closed_on_conflict(
    monkeypatch: pytest.MonkeyPatch,
    alias_field: str,
    conflicting_value: object,
    expected_reason: str,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row[alias_field] = conflicting_value
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 0
    assert state["rejected_row_count"] == 20
    assert state["rejection_reason_counts"][expected_reason] == 20
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_invalid_bool_and_nonfinite_numeric_aliases_all_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row["realized_pnl_usd"] = True
        row["entry_confidence"] = float("inf")
        row["quantity"] = False
        row["exit_fill_price"] = float("nan")
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    reasons = state["rejection_reason_counts"]
    assert state["admitted_row_count"] == 0
    assert reasons["REALIZED_PNL_MISSING_OR_NONFINITE"] == 20
    assert reasons["CONFIDENCE_MISSING_NONFINITE_OR_OUT_OF_RANGE"] == 20
    assert reasons["CLOSED_QUANTITY_MISSING_NONFINITE_OR_NONPOSITIVE"] == 20
    assert reasons["EXIT_PRICE_MISSING_NONFINITE_OR_NONPOSITIVE"] == 20
    assert state["permissive_authority"] is False


@pytest.mark.parametrize(
    ("alias_field", "invalid_value", "expected_reason"),
    (
        ("paper_close_id", "", "CLOSE_ID_TYPE_INVALID"),
        ("realized_pnl_usd", None, "REALIZED_PNL_MISSING_OR_NONFINITE"),
        ("entry_confidence", "", "CONFIDENCE_MISSING_NONFINITE_OR_OUT_OF_RANGE"),
        ("close_quantity", None, "CLOSED_QUANTITY_MISSING_NONFINITE_OR_NONPOSITIVE"),
        ("exit_fill_price", "", "EXIT_PRICE_MISSING_NONFINITE_OR_NONPOSITIVE"),
        ("exit_reason", None, "CLOSE_REASON_TYPE_INVALID"),
        ("closed_at", "", "CLOSE_TIME_NOT_AWARE"),
        ("close_available_at", None, "OUTCOME_AVAILABLE_AT_NOT_AWARE"),
    ),
)
def test_every_present_material_alias_must_itself_be_valid(
    monkeypatch: pytest.MonkeyPatch,
    alias_field: str,
    invalid_value: object,
    expected_reason: str,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row[alias_field] = invalid_value
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 0
    assert state["rejection_reason_counts"][expected_reason] == 20
    assert state["permissive_authority"] is False


def test_numeric_aliases_never_use_approximate_market_tolerance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row["entry_confidence"] = 0.6000000000000001
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 0
    assert state["rejection_reason_counts"]["CONFIDENCE_ALIAS_CONFLICT"] == 20
    assert state["permissive_authority"] is False


def test_alias_parsers_reject_overbound_text_without_coercion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row["paper_close_id"] = "x" * (tuner.MAX_OUTCOME_ALIAS_TEXT_CHARS + 1)
        row["realized_pnl_usd"] = "1" * (tuner.MAX_OUTCOME_NUMERIC_ALIAS_TEXT_CHARS + 1)
        row["closed_at"] = "0" * (tuner.MAX_OUTCOME_ALIAS_TEXT_CHARS + 1)
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    reasons = state["rejection_reason_counts"]
    assert state["admitted_row_count"] == 0
    assert reasons["CLOSE_ID_TYPE_INVALID"] == 20
    assert reasons["REALIZED_PNL_MISSING_OR_NONFINITE"] == 20
    assert reasons["CLOSE_TIME_NOT_AWARE"] == 20
    assert state["permissive_authority"] is False


@pytest.mark.parametrize(
    ("alias_field", "expected_reason"),
    (
        ("closed_at", "CLOSE_TIME_NOT_AWARE"),
        ("close_available_at", "OUTCOME_AVAILABLE_AT_NOT_AWARE"),
    ),
)
def test_every_supplied_close_clock_alias_must_be_aware(
    monkeypatch: pytest.MonkeyPatch,
    alias_field: str,
    expected_reason: str,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row[alias_field] = "2026-07-17T11:00:00"
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 0
    assert state["rejection_reason_counts"][expected_reason] == 20
    assert state["permissive_authority"] is False


@pytest.mark.parametrize(
    ("aliases", "expected_reason"),
    (
        (("feature_cutoff", "entry_feature_cutoff"), "FEATURE_CUTOFF_NOT_AWARE"),
        (
            ("feature_available_at", "entry_feature_available_at", "available_at"),
            "FEATURE_AVAILABLE_AT_NOT_AWARE",
        ),
        (("decision_time", "entry_decision_time"), "DECISION_TIME_NOT_AWARE"),
        (("entry_execution_time", "entry_time"), "ENTRY_EXECUTION_TIME_NOT_AWARE"),
        (("exit_time", "closed_at"), "CLOSE_TIME_NOT_AWARE"),
        (
            ("outcome_available_at", "close_available_at"),
            "OUTCOME_AVAILABLE_AT_NOT_AWARE",
        ),
    ),
)
def test_every_outcome_clock_alias_family_rejects_submicrosecond_collision(
    monkeypatch: pytest.MonkeyPatch,
    aliases: tuple[str, ...],
    expected_reason: str,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        raw_clock = row[aliases[0]]
        assert type(raw_clock) is str
        stem = raw_clock.removesuffix("Z")
        for alias_index, alias in enumerate(aliases):
            row[alias] = f"{stem}{1 + alias_index}Z"
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["source_row_count"] == 20
    assert state["admitted_row_count"] == 0
    assert state["rejected_row_count"] == 20
    assert state["rejection_reason_counts"][expected_reason] == 20
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


@pytest.mark.parametrize(
    "invalid_clock",
    (
        "2026-07-17T11:00:00.000000+00:00",
        "2026-07-17T11:00:00Z",
        "2026-07-17T11:00:00.00000Z",
        "2026-07-17T11:00:00.0000000Z",
        " 2026-07-17T11:00:00.000000Z",
        "2026-07-17 11:00:00.000000Z",
    ),
)
def test_present_outcome_clock_alias_rejects_every_noncanonical_utc_form(
    monkeypatch: pytest.MonkeyPatch,
    invalid_clock: str,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row["closed_at"] = invalid_clock
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 0
    assert state["rejected_row_count"] == 20
    assert state["rejection_reason_counts"]["CLOSE_TIME_NOT_AWARE"] == 20
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_equivalent_material_aliases_are_admitted_without_approximate_tolerance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row["paper_close_id"] = f"  {row['close_id']}  "
        row["realized_pnl_usd"] = "1.000"
        row["pnl"] = 1
        row["entry_confidence"] = "0.6000"
        row["close_quantity"] = "0.100"
        row["quantity"] = 0.1
        row["exit_fill_price"] = str(row["exit_price"])
        row["exit_reason"] = f"  {row['close_reason']}  "
        row["closed_at"] = row["exit_time"]
        row["close_available_at"] = row["outcome_available_at"]
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 20
    assert state["rejected_row_count"] == 0
    assert state["rejection_reason_counts"] == {}
    assert state["permissive_authority"] is True
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_valid_legacy_single_alias_rows_remain_admissible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row["paper_close_id"] = row.pop("close_id")
        row["pnl_usd"] = row.pop("realized_net_pnl_usd")
        row["entry_confidence"] = row.pop("confidence_calibrated")
        row["quantity"] = row.pop("closed_quantity")
        row["exit_fill_price"] = row.pop("exit_price")
        row["exit_reason"] = row.pop("close_reason")
        row["closed_at"] = row.pop("exit_time")
        row["closed_available_at"] = row.pop("outcome_available_at")
        row.pop("feature_available_at")
        row.pop("entry_feature_available_at")
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 20
    assert state["rejected_row_count"] == 0
    assert state["permissive_authority"] is True
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


@pytest.mark.parametrize(
    ("alias_field", "alias_value", "expected_reason"),
    (
        ("session_id", None, "CURRENT_PAPER_SESSION_ID_TYPE_INVALID"),
        ("session_id", "", "CURRENT_PAPER_SESSION_ID_TYPE_INVALID"),
        ("session_id", "conflicting-session", "CURRENT_PAPER_SESSION_IDENTITY_CONFLICT"),
    ),
)
def test_every_present_current_session_identity_alias_is_strict(
    monkeypatch: pytest.MonkeyPatch,
    alias_field: str,
    alias_value: object,
    expected_reason: str,
) -> None:
    sources = _source_values([_clean_row(index) for index in range(20)])
    session = json.loads(str(sources[tuner.PAPER_SESSION_KEY]))
    session[alias_field] = alias_value
    sources[tuner.PAPER_SESSION_KEY] = json.dumps(session, sort_keys=True)
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["current_paper_session_id"] is None
    assert expected_reason in state["session_identity_errors"]
    assert state["admitted_row_count"] == 0
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


@pytest.mark.parametrize(
    ("alias_field", "alias_value", "expected_reason"),
    (
        ("session_id", None, "ROW_SESSION_ID_TYPE_INVALID"),
        ("reset_session_id", "", "ROW_SESSION_ID_TYPE_INVALID"),
        ("session_id", "conflicting-session", "ROW_SESSION_IDENTITY_CONFLICT"),
    ),
)
def test_every_present_row_session_identity_alias_is_strict(
    monkeypatch: pytest.MonkeyPatch,
    alias_field: str,
    alias_value: object,
    expected_reason: str,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row[alias_field] = alias_value
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 0
    assert state["rejection_reason_counts"][expected_reason] == 20
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


@pytest.mark.parametrize(
    ("alias_field", "alias_value", "expected_reason"),
    (
        ("source_prediction_id", None, "PREDICTION_LINEAGE_TYPE_INVALID"),
        ("entry_prediction_id", "", "PREDICTION_LINEAGE_TYPE_INVALID"),
        ("source_prediction_id", "conflicting-prediction", "PREDICTION_LINEAGE_CONFLICT"),
    ),
)
def test_every_present_prediction_lineage_alias_is_strict(
    monkeypatch: pytest.MonkeyPatch,
    alias_field: str,
    alias_value: object,
    expected_reason: str,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row[alias_field] = alias_value
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 0
    assert state["rejection_reason_counts"][expected_reason] == 20
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_reason"),
    (
        ("position_id", 123, "POSITION_ID_TYPE_INVALID"),
        ("position_id", True, "POSITION_ID_TYPE_INVALID"),
        ("grade", 7, "GRADE_TYPE_INVALID"),
        ("grade", False, "GRADE_TYPE_INVALID"),
    ),
)
def test_position_and_grade_never_use_string_coercion(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid_value: object,
    expected_reason: str,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row[field] = invalid_value
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 0
    assert state["rejection_reason_counts"][expected_reason] == 20
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_mixed_valid_and_invalid_source_hashes_reject_the_complete_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        source_hashes = row["source_hashes"]
        assert isinstance(source_hashes, dict)
        source_hashes["invalid_extra"] = "not-a-canonical-lowercase-sha256"
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 0
    assert state["rejection_reason_counts"]["SOURCE_HASH_LINEAGE_VALUE_INVALID"] == 20
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_source_hash_lineage_is_bounded_total_and_fully_bound() -> None:
    row = _clean_row(0)
    source_hashes = row["source_hashes"]
    assert isinstance(source_hashes, dict)
    original_hashes = copy.deepcopy(source_hashes)
    reasons, normalized = tuner._outcome_row_rejection_reasons(
        row,
        outcomes_cutoff=BASE,
        current_paper_session_id=SESSION_ID,
    )

    assert reasons == []
    assert normalized is not None
    assert normalized["source_hashes"] == original_hashes
    assert normalized["valid_source_hash_count"] == len(original_hashes)
    assert normalized["source_hashes_hash_sha256"] == tuner._sha256_canonical(original_hashes)

    class HostileMapping(Mapping[str, str]):
        def __getitem__(self, key: str) -> str:
            raise AssertionError(f"hostile mapping was accessed: {key}")

        def __iter__(self) -> Iterator[str]:
            raise AssertionError("hostile mapping was iterated")

        def __len__(self) -> int:
            raise AssertionError("hostile mapping length was read")

    validated, hostile_reasons = tuner._validated_source_hash_lineage(
        {"source_hashes": HostileMapping()}
    )

    assert validated is None
    assert hostile_reasons == ["SOURCE_HASH_LINEAGE_CONTAINER_INVALID"]


def test_absent_optional_identity_aliases_and_string_grade_remain_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row.pop("session_id")
        row.pop("reset_session_id")
        row.pop("entry_prediction_id")
        row["grade"] = " b "
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 20
    assert state["rejected_row_count"] == 0
    assert state["outcomes"]["b_grade_count"] == 20
    assert state["permissive_authority"] is True
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_one_profitable_outcome_cannot_manufacture_permissive_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis(_source_values([_clean_row(0, pnl=100.0)]))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["outcomes"]["status"] == "INSUFFICIENT_CLEAN_EVIDENCE"
    assert state["outcomes"]["clean_outcome_shortfall"] == 19
    assert state["permissive_authority"] is False
    assert state["enable_b_grade"] is False
    assert state["adaptive_loss_probability_threshold"] == (
        tuner.FAIL_CLOSED_LOSS_PROBABILITY_CEILING
    )


def test_missing_current_session_and_naive_clocks_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _clean_row(0)
    row["exit_time"] = "2026-07-17T11:00:00"
    sources = _source_values([row])
    sources.pop(tuner.PAPER_SESSION_KEY)
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["current_paper_session_id"] is None
    assert state["admitted_row_count"] == 0
    assert state["rejected_row_count"] == 1
    assert state["rejection_reason_counts"]["CURRENT_PAPER_SESSION_ID_UNAVAILABLE"] == 1
    assert state["rejection_reason_counts"]["CLOSE_TIME_NOT_AWARE"] == 1
    assert state["authority_status"] == "CANONICAL_FAIL_CLOSED"


def test_nonpaper_or_live_routing_session_is_fail_closed_and_runtime_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _source_values([_clean_row(index) for index in range(20)])
    sources[tuner.PAPER_SESSION_KEY] = json.dumps(
        {
            "paper_session_id": SESSION_ID,
            "reset_session_id": SESSION_ID,
            "paper_only": False,
            "routes_to_live": True,
            "places_real_order": True,
        },
        sort_keys=True,
    )
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["current_paper_session_id"] is None
    assert state["permissive_authority"] is False
    assert state["policy_status"] == ("FAIL_CLOSED_INSUFFICIENT_OR_UNTRUSTED_EVIDENCE")
    assert state["session_identity_errors"] == [
        "CURRENT_PAPER_SESSION_LIVE_ROUTE_STATUS_NOT_FALSE",
        "CURRENT_PAPER_SESSION_NOT_EXPLICITLY_PAPER_ONLY",
        "CURRENT_PAPER_SESSION_REAL_ORDER_STATUS_NOT_FALSE",
    ]
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    admission_reasons = tuner.adaptive_gate_tuning_rejection_reasons(
        state,
        observed_at=BASE + timedelta(seconds=3),
        current_paper_session_id=SESSION_ID,
        require_current_session=True,
    )
    assert "CURRENT_PAPER_SESSION_SOURCE_UNSAFE" in admission_reasons
    assert "PAPER_SESSION_ID_MISMATCH" in admission_reasons


def test_finite_numeric_extremes_reject_rows_without_crashing_or_nonfinite_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    rows[0]["closed_quantity"] = 5e-324
    rows[0]["entry_price"] = 5e-324
    rows[1]["closed_quantity"] = 1e308
    rows[1]["entry_price"] = 1e308
    rows[1]["exit_price"] = 1e308
    sources = _source_values(rows)
    first_market_key = tuner.MARKET_CANDLE_KEYS[0]
    candles = json.loads(str(sources[first_market_key]))
    candles[0].update(
        {
            "open": 5e-324,
            "high": 1e308,
            "low": 5e-324,
            "close": 5e-324,
        }
    )
    sources[first_market_key] = json.dumps(candles, sort_keys=True)
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["rejection_reason_counts"]["ENTRY_NOTIONAL_NONFINITE_OR_NONPOSITIVE"] == 2
    first_market = state["market_regime"]["source_analyses"][0]
    assert first_market["row_rejection_reason_counts"]["RANGE_BPS_NONFINITE"] == 1
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    tuner._canonical_json(state)


def test_finite_aggregate_overflow_becomes_fail_closed_source_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index, pnl=1e308) for index in range(20)]
    for row in rows:
        row["closed_quantity"] = 1.0
        row["entry_price"] = 1e308
        row["exit_price"] = 1e308
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    source_reasons = state["source_rejection_reason_counts"]
    assert source_reasons["OUTCOME_AGGREGATE_NONFINITE"] == 1
    assert source_reasons["RECENT_OUTCOME_AGGREGATE_NONFINITE"] == 1
    assert state["outcome_evidence_sufficient"] is False
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    tuner._canonical_json(state)


def test_declared_outcome_row_cap_is_enforced_before_row_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(tuner.MAX_OUTCOME_SOURCE_ROWS + 1)]
    redis_client = FakeRedis(_source_values(rows))

    def unexpected_row_iteration(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"row cap failed before iteration: {args!r} {kwargs!r}")

    monkeypatch.setattr(
        tuner,
        "_outcome_row_rejection_reasons",
        unexpected_row_iteration,
    )
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["source_row_count"] == tuner.MAX_OUTCOME_SOURCE_ROWS + 1
    assert state["admitted_row_count"] == 0
    assert state["rejected_row_count"] == tuner.MAX_OUTCOME_SOURCE_ROWS + 1
    assert state["source_rejection_reason_counts"]["SOURCE_ROW_LIMIT_EXCEEDED"] == 1
    assert state["permissive_authority"] is False


def test_source_byte_cap_is_enforced_before_json_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _source_values([])
    sources[tuner.OUTCOMES_KEY] = b"x" * (tuner.MAX_CANONICAL_SOURCE_PAYLOAD_BYTES + 1)
    redis_client = FakeRedis(sources)
    original_decode = tuner._decode_json

    def guarded_decode(value: Any) -> tuple[Any, str | None]:
        if isinstance(value, bytes) and len(value) > tuner.MAX_CANONICAL_SOURCE_PAYLOAD_BYTES:
            raise AssertionError("oversized source reached JSON decoder")
        return original_decode(value)

    monkeypatch.setattr(tuner, "_decode_json", guarded_decode)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    expected_error = f"SOURCE_PAYLOAD_SIZE_LIMIT_EXCEEDED:{tuner.OUTCOMES_KEY}"
    assert state["source_read_errors"] == [expected_error]
    outcomes_snapshot = state["canonical_source_snapshot"][0]
    assert outcomes_snapshot["present"] is True
    assert outcomes_snapshot["payload_included"] is False
    assert outcomes_snapshot["payload_base64"] is None
    assert outcomes_snapshot["payload_byte_count"] == (tuner.MAX_CANONICAL_SOURCE_PAYLOAD_BYTES + 1)
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_publish_rejects_tampered_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_client = FakeRedis(_source_values([_clean_row(index) for index in range(20)]))
    _clock(monkeypatch)
    state = tuner.run_adaptive_tuning(redis_client)
    redis_client.write_calls.clear()
    forged = copy.deepcopy(state)
    forged["receipt_hash_sha256"] = "0" * 64
    forged["publication_receipt"]["receipt_hash_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="RECEIPT_HASH_INVALID"):
        tuner.publish_gate_tuning(redis_client, forged)

    assert redis_client.write_calls == []


def test_consumer_contract_accepts_only_current_unexpired_session_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis(_source_values([_clean_row(index) for index in range(20)]))
    _clock(monkeypatch)
    state = tuner.run_adaptive_tuning(redis_client)

    assert (
        tuner.adaptive_gate_tuning_rejection_reasons(
            state,
            observed_at=BASE + timedelta(seconds=3),
            current_paper_session_id=SESSION_ID,
            require_current_session=True,
        )
        == []
    )
    assert "PAPER_SESSION_ID_MISMATCH" in (
        tuner.adaptive_gate_tuning_rejection_reasons(
            state,
            observed_at=BASE + timedelta(seconds=3),
            current_paper_session_id="different-session",
            require_current_session=True,
        )
    )
    assert "PUBLICATION_NOT_AVAILABLE_OR_EXPIRED_AT_CONSUMER" in (
        tuner.adaptive_gate_tuning_rejection_reasons(
            state,
            observed_at=state["expires_at"],
            current_paper_session_id=SESSION_ID,
            require_current_session=True,
        )
    )


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    (
        (
            lambda state: state.__setitem__("producer", "forged.writer"),
            "CANONICAL_ENVELOPE_PRODUCER_INVALID",
        ),
        (
            lambda state: state.__setitem__("schema_version", "legacy_v2"),
            "CANONICAL_ENVELOPE_SCHEMA_INVALID",
        ),
        (
            lambda state: state["canonical_policy_material"].__setitem__("policy_values", {}),
            "POLICY_MATERIAL_BINDING_INVALID",
        ),
        (
            lambda state: state["publication_receipt"].__setitem__("canonical_key", "wrong:key"),
            "PUBLICATION_RECEIPT_BINDING_INVALID",
        ),
        (
            lambda state: state.__setitem__("routes_to_live", True),
            "CANONICAL_ENVELOPE_PAPER_SAFETY_FLAGS_INVALID",
        ),
    ),
)
def test_consumer_contract_rejects_forged_or_inconsistent_authority(
    monkeypatch: pytest.MonkeyPatch,
    mutation: Callable[[dict[str, Any]], None],
    expected_reason: str,
) -> None:
    redis_client = FakeRedis(_source_values([_clean_row(index) for index in range(20)]))
    _clock(monkeypatch)
    state = copy.deepcopy(tuner.run_adaptive_tuning(redis_client))
    mutation(state)

    reasons = tuner.adaptive_gate_tuning_rejection_reasons(
        state,
        observed_at=BASE + timedelta(seconds=3),
        current_paper_session_id=SESSION_ID,
        require_current_session=True,
    )

    assert expected_reason in reasons
    if expected_reason != "PUBLICATION_RECEIPT_BINDING_INVALID":
        assert "PUBLICATION_RECEIPT_HASH_INVALID" in reasons


def test_market_regime_uses_canonical_finalized_histories_and_empirical_factor() -> None:
    redis_client = FakeRedis(_source_values([]))

    regime = tuner.learn_market_regime(redis_client, observed_at=BASE)

    assert regime["status"] == "OK"
    assert regime["symbols_analyzed"] == len(tuner.MARKET_CANDLE_SYMBOLS)
    assert regime["regime"] in {"LOW", "NORMAL", "HIGH"}
    assert tuner.MIN_VOLATILITY_FACTOR <= regime["volatility_factor"] <= tuner.MAX_VOLATILITY_FACTOR
    assert [row["source_key"] for row in regime["source_analyses"]] == list(
        tuner.MARKET_CANDLE_KEYS
    )
    assert all(
        row["admitted_row_count"] == 100
        and row["rejected_row_count"] == 0
        and row["evidence_sufficient"] is True
        for row in regime["source_analyses"]
    )


def test_declared_market_row_cap_is_enforced_before_row_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _source_values([])
    source_key = tuner.MARKET_CANDLE_KEYS[0]
    rows = json.loads(str(sources[source_key]))
    rows.append(copy.deepcopy(rows[-1]))

    def unexpected_row_iteration(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"row cap failed before iteration: {args!r} {kwargs!r}")

    monkeypatch.setattr(tuner, "_market_candle_row", unexpected_row_iteration)
    analysis = tuner._market_source_analysis(
        json.dumps(rows, sort_keys=True),
        source_key=source_key,
        symbol=tuner.MARKET_CANDLE_SYMBOLS[0],
        cutoff=BASE,
    )

    assert analysis["source_row_count"] == tuner.MAX_MARKET_CANDLE_ROWS_PER_SYMBOL + 1
    assert analysis["admitted_row_count"] == 0
    assert analysis["source_rejection_reason_counts"]["SOURCE_ROW_LIMIT_EXCEEDED"] == 1


def test_market_factor_changes_continuously_with_empirical_current_volatility() -> None:
    normal_sources = _source_values([])
    elevated_sources = copy.deepcopy(normal_sources)
    for key in tuner.MARKET_CANDLE_KEYS:
        rows = json.loads(str(elevated_sources[key]))
        for row in rows[-10:]:
            row["high"] = 101.5
            row["low"] = 98.5
        elevated_sources[key] = json.dumps(rows, sort_keys=True)

    normal = tuner.learn_market_regime(FakeRedis(normal_sources), observed_at=BASE)
    elevated = tuner.learn_market_regime(
        FakeRedis(elevated_sources),
        observed_at=BASE,
    )

    assert normal["status"] == "OK"
    assert elevated["status"] == "OK"
    assert elevated["regime"] == "HIGH"
    assert elevated["empirical_percentile"] > normal["empirical_percentile"]
    assert elevated["volatility_factor"] > normal["volatility_factor"]


def test_unfinished_or_future_available_candle_cannot_create_permissive_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _source_values([_clean_row(index) for index in range(20)])
    key = tuner.MARKET_CANDLE_KEYS[0]
    candles = json.loads(str(sources[key]))
    for candle in candles:
        candle["candle_close_time"] = int((BASE + timedelta(minutes=1)).timestamp() * 1000)
        candle["close_time"] = candle["candle_close_time"]
        candle["event_time"] = int((BASE + timedelta(minutes=1, seconds=1)).timestamp() * 1000)
        candle["available_at"] = int((BASE + timedelta(minutes=1, seconds=2)).timestamp() * 1000)
    sources[key] = json.dumps(candles, sort_keys=True)
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["outcome_evidence_sufficient"] is True
    assert state["market_evidence_sufficient"] is False
    assert state["evidence_sufficient"] is False
    assert state["permissive_authority"] is False
    assert state["enable_b_grade"] is False
    assert state["volatility_factor"] == tuner.MAX_VOLATILITY_FACTOR
    first_analysis = state["market_regime"]["source_analyses"][0]
    assert first_analysis["row_rejection_reason_counts"]["UNFINISHED_AT_TUNING_CUTOFF"] == 100
    assert first_analysis["row_rejection_reason_counts"]["AVAILABLE_AFTER_TUNING_CUTOFF"] == 100


def test_consumer_rejects_forged_market_evidence_sufficiency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis(_source_values([_clean_row(index) for index in range(20)]))
    _clock(monkeypatch)
    forged = copy.deepcopy(tuner.run_adaptive_tuning(redis_client))
    forged["market_evidence_sufficient"] = False

    reasons = tuner.adaptive_gate_tuning_rejection_reasons(
        forged,
        observed_at=BASE + timedelta(seconds=3),
        current_paper_session_id=SESSION_ID,
        require_current_session=True,
    )

    assert "MARKET_EVIDENCE_SUFFICIENCY_DERIVATION_INVALID" in reasons
    assert "PUBLICATION_RECEIPT_HASH_INVALID" in reasons


def test_legacy_close_availability_is_conservatively_observed_at_snapshot_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row.pop("outcome_available_at")
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 20
    assert state["rejected_row_count"] == 0
    assert state["outcomes"]["legacy_outcome_availability_at_cutoff_count"] == 20
    assert state["outcome_evidence_sufficient"] is True


def test_dedicated_and_legacy_feature_availability_conflict_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    for row in rows:
        row["available_at"] = _canonical_utc(BASE - timedelta(days=1))
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 0
    assert state["rejection_reason_counts"]["FEATURE_AVAILABLE_AT_ALIAS_CONFLICT"] == 20
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_negative_realized_edge_keeps_valid_authority_restrictive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis(_source_values([_clean_row(index, pnl=-1.0) for index in range(20)]))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["evidence_sufficient"] is True
    assert state["economic_edge_positive"] is False
    assert state["authority_status"] == "CANONICAL_EVIDENCE_BACKED_RESTRICTIVE"
    assert state["policy_status"] == "EVIDENCE_BACKED_RESTRICTIVE_NONPOSITIVE_EDGE"
    assert state["permissive_authority"] is False
    assert state["enable_b_grade"] is False
    assert state["enable_a_grade"] is False
    assert state["adaptive_long_confidence_floor"] == tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    assert state["adaptive_short_confidence_floor"] == tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    assert state["adaptive_expectancy_floor"] > 0.0
    assert state["adaptive_entry_freeze_allowance"] == 0.0


def test_policy_declares_empirical_derivation_and_classifies_immutable_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis(_source_values([_clean_row(index) for index in range(20)]))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["static_market_or_performance_thresholds"] is False
    assert state["canonical_policy_material"]["static_market_or_performance_thresholds"] is False
    assert state["threshold_derivation"] == tuner.THRESHOLD_DERIVATION_METHOD
    classifications = state["immutable_bound_classification"]
    assert classifications["minimum_clean_outcomes"]["class"] == ("EVIDENCE_INTEGRITY_SAMPLE_FLOOR")
    assert classifications["outcome_required_point_in_time_clocks"]["class"] == (
        "POINT_IN_TIME_LINEAGE_INTEGRITY_CONTRACT"
    )
    assert classifications["recent_outcome_window_cap"]["class"] == (
        "BOUNDED_COMPUTE_AND_RECENCY_WINDOW"
    )
    assert classifications["publication_ttl_seconds"]["class"] == (
        "RESOURCE_AND_REVOCABILITY_BOUND"
    )


def test_untrusted_raw_trainer_metrics_cannot_change_canonical_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    first_sources = _source_values(rows)
    second_sources = copy.deepcopy(first_sources)
    second_sources[tuner.TRAINER_METRICS_KEY] = json.dumps(
        {"win_rate_percent": 0.0, "profit_factor": -999.0},
        sort_keys=True,
    )
    first = FakeRedis(first_sources)
    _clock(monkeypatch)
    first_state = tuner.run_adaptive_tuning(first)
    second = FakeRedis(second_sources)
    _clock(monkeypatch)
    second_state = tuner.run_adaptive_tuning(second)

    assert tuner.TRAINER_METRICS_KEY not in tuner.CANONICAL_SOURCE_KEYS
    assert tuner.TRAINER_METRICS_KEY not in first.read_keys
    assert tuner.TRAINER_METRICS_KEY not in second.read_keys
    assert second_state == first_state


def test_confidence_and_loss_thresholds_move_with_pit_empirical_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lower_confidence_rows = [
        _clean_row(index, confidence=0.30 + (index / 100.0)) for index in range(20)
    ]
    higher_confidence_rows = [
        _clean_row(index, confidence=0.50 + (index / 100.0)) for index in range(20)
    ]
    lower_confidence_redis = FakeRedis(_source_values(lower_confidence_rows))
    _clock(monkeypatch)
    lower_confidence_state = tuner.run_adaptive_tuning(lower_confidence_redis)
    higher_confidence_redis = FakeRedis(_source_values(higher_confidence_rows))
    _clock(monkeypatch)
    higher_confidence_state = tuner.run_adaptive_tuning(higher_confidence_redis)

    assert (
        higher_confidence_state["adaptive_confidence_threshold"]
        > (lower_confidence_state["adaptive_confidence_threshold"])
    )

    fourteen_wins = [_clean_row(index, pnl=1.0 if index < 14 else -0.25) for index in range(20)]
    fifteen_wins = [_clean_row(index, pnl=1.0 if index < 15 else -0.25) for index in range(20)]
    fourteen_redis = FakeRedis(_source_values(fourteen_wins))
    _clock(monkeypatch)
    fourteen_state = tuner.run_adaptive_tuning(fourteen_redis)
    fifteen_redis = FakeRedis(_source_values(fifteen_wins))
    _clock(monkeypatch)
    fifteen_state = tuner.run_adaptive_tuning(fifteen_redis)

    assert (
        fifteen_state["adaptive_loss_probability_threshold"]
        > (fourteen_state["adaptive_loss_probability_threshold"])
    )
    assert (
        fourteen_state["adaptive_loss_probability_threshold"]
        == (fourteen_state["outcomes"]["win_rate_lower_bound"])
    )


def test_grade_admission_uses_grade_specific_evidence_floor_not_fixed_100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twenty_a_rows = [_clean_row(index) for index in range(20)]
    for row in twenty_a_rows:
        row["grade"] = "A"
    twenty_redis = FakeRedis(_source_values(twenty_a_rows))
    _clock(monkeypatch)
    twenty_state = tuner.run_adaptive_tuning(twenty_redis)

    nineteen_a_rows = copy.deepcopy(twenty_a_rows)
    nineteen_a_rows[-1]["grade"] = "B"
    nineteen_redis = FakeRedis(_source_values(nineteen_a_rows))
    _clock(monkeypatch)
    nineteen_state = tuner.run_adaptive_tuning(nineteen_redis)

    assert twenty_state["admitted_row_count"] == 20
    assert twenty_state["enable_a_grade"] is True
    assert nineteen_state["outcomes"]["grade_evidence"]["A"]["count"] == 19
    assert nineteen_state["enable_a_grade"] is False


def test_duplicate_close_and_noncanonical_lineage_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    rows[-1]["close_id"] = rows[0]["close_id"]
    rows[-2]["source_hashes"] = {"opaque_identifier": "not-a-content-hash"}
    rows[-3]["prediction_hash"] = "f" * 64
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["admitted_row_count"] == 17
    assert state["rejection_reason_counts"]["DUPLICATE_CLOSE_ID"] == 1
    assert state["rejection_reason_counts"]["SOURCE_HASH_LINEAGE_HAS_NO_CANONICAL_SHA256"] == 1
    assert state["rejection_reason_counts"]["SOURCE_HASH_LINEAGE_CONFLICT:prediction_hash"] == 1
    assert state["evidence_sufficient"] is False
    assert state["adaptive_confidence_threshold"] == tuner.FAIL_CLOSED_CONFIDENCE_FLOOR


def test_point_in_time_clock_violations_are_rejected_before_adaptation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    decision_time = datetime.fromisoformat(str(rows[0]["decision_time"]))
    later_than_decision = _canonical_utc(decision_time + timedelta(seconds=1))
    rows[0]["feature_cutoff"] = later_than_decision
    rows[0]["entry_feature_cutoff"] = later_than_decision
    second_decision_time = datetime.fromisoformat(str(rows[1]["decision_time"]))
    second_later_than_decision = _canonical_utc(second_decision_time + timedelta(seconds=1))
    rows[1]["feature_available_at"] = second_later_than_decision
    rows[1]["entry_feature_available_at"] = second_later_than_decision
    rows[1]["available_at"] = second_later_than_decision
    entry_execution_time = datetime.fromisoformat(str(rows[2]["entry_execution_time"]))
    rows[2]["decision_time"] = _canonical_utc(entry_execution_time + timedelta(seconds=1))
    rows[3].pop("entry_execution_time")
    rows[3].pop("entry_time")
    close_time = datetime.fromisoformat(str(rows[4]["exit_time"]))
    after_close = _canonical_utc(close_time + timedelta(seconds=1))
    rows[4]["entry_execution_time"] = after_close
    rows[4]["entry_time"] = after_close
    fifth_close_time = datetime.fromisoformat(str(rows[5]["exit_time"]))
    rows[5]["outcome_available_at"] = _canonical_utc(fifth_close_time - timedelta(seconds=1))
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    reasons = state["rejection_reason_counts"]
    assert reasons["FEATURE_CUTOFF_AFTER_FEATURE_AVAILABLE_AT"] == 1
    assert reasons["FEATURE_CUTOFF_AFTER_DECISION_TIME"] == 1
    assert reasons["FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME"] == 1
    assert reasons["DECISION_TIME_AFTER_ENTRY_EXECUTION_TIME"] == 1
    assert reasons["ENTRY_EXECUTION_TIME_MISSING"] == 1
    assert reasons["ENTRY_EXECUTION_TIME_AFTER_CLOSE_TIME"] == 1
    assert reasons["OUTCOME_AVAILABLE_AT_BEFORE_CLOSE_TIME"] == 1
    assert state["admitted_row_count"] == 14
    assert state["permissive_authority"] is False


def test_resealed_policy_value_tamper_is_rejected_by_empirical_recomputation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis(_source_values([_clean_row(index) for index in range(20)]))
    _clock(monkeypatch)
    forged = copy.deepcopy(tuner.run_adaptive_tuning(redis_client))
    forged_value = 0.01
    forged["adaptive_confidence_threshold"] = forged_value
    forged["adaptive_long_confidence_floor"] = forged_value
    forged["adaptive_short_confidence_floor"] = forged_value
    policy_values = forged["canonical_policy_material"]["policy_values"]
    policy_values["adaptive_confidence_threshold"] = forged_value
    policy_values["adaptive_long_confidence_floor"] = forged_value
    policy_values["adaptive_short_confidence_floor"] = forged_value
    material_hash = tuner._sha256_canonical(forged["canonical_policy_material"])
    policy_id = f"adaptive_gate_policy_{material_hash[:24]}"
    forged["canonical_policy_material_hash_sha256"] = material_hash
    forged["policy_id"] = policy_id
    forged["publication_receipt"]["canonical_policy_material_hash_sha256"] = material_hash
    forged["publication_receipt"]["policy_id"] = policy_id
    unsigned = copy.deepcopy(forged)
    unsigned.pop("publication_receipt")
    unsigned.pop("receipt_hash_sha256")
    receipt_hash = tuner._receipt_hash(unsigned)
    forged["receipt_hash_sha256"] = receipt_hash
    forged["publication_receipt"]["receipt_hash_sha256"] = receipt_hash

    reasons = tuner.adaptive_gate_tuning_rejection_reasons(
        forged,
        observed_at=BASE + timedelta(seconds=3),
        current_paper_session_id=SESSION_ID,
        require_current_session=True,
    )

    assert "POLICY_VALUE_DERIVATION_INVALID:adaptive_confidence_threshold" in reasons
    assert "POLICY_VALUE_DERIVATION_INVALID:adaptive_long_confidence_floor" in reasons
    assert "POLICY_VALUE_DERIVATION_INVALID:adaptive_short_confidence_floor" in reasons
    assert "PUBLICATION_RECEIPT_HASH_INVALID" not in reasons


def test_resealed_positive_outcomes_cannot_substitute_for_bound_negative_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    negative_redis = FakeRedis(_source_values([_clean_row(index, pnl=-1.0) for index in range(20)]))
    _clock(monkeypatch)
    negative_state = tuner.run_adaptive_tuning(negative_redis)
    positive_redis = FakeRedis(_source_values([_clean_row(index, pnl=1.0) for index in range(20)]))
    _clock(monkeypatch)
    forged = copy.deepcopy(tuner.run_adaptive_tuning(positive_redis))

    for field in (
        "source_hash",
        "outcomes_source_hash_sha256",
        "paper_session_source_hash_sha256",
        "source_manifest",
        "source_manifest_hash_sha256",
        "canonical_source_snapshot",
        "canonical_source_snapshot_hash_sha256",
    ):
        forged[field] = copy.deepcopy(negative_state[field])
    material = forged["canonical_policy_material"]
    assert isinstance(material, dict)
    material["source_manifest_hash_sha256"] = forged["source_manifest_hash_sha256"]
    material["canonical_source_snapshot_hash_sha256"] = forged[
        "canonical_source_snapshot_hash_sha256"
    ]
    _reseal_state(forged)

    reasons = tuner.adaptive_gate_tuning_rejection_reasons(
        forged,
        observed_at=BASE + timedelta(seconds=3),
        current_paper_session_id=SESSION_ID,
        require_current_session=True,
    )

    assert "OUTCOMES_SOURCE_DERIVATION_MISMATCH" in reasons
    assert "PUBLICATION_RECEIPT_HASH_INVALID" not in reasons
    assert "POLICY_MATERIAL_BINDING_INVALID" not in reasons


def test_duplicate_json_keys_are_untrusted_source_not_ambiguous_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _source_values([_clean_row(index) for index in range(20)])
    sources[tuner.PAPER_SESSION_KEY] = (
        '{"paper_session_id":"paper-session-2026-07-17",'
        '"paper_session_id":"forged-session","reset_session_id":'
        '"paper-session-2026-07-17","paper_only":true,'
        '"routes_to_live":false,"places_real_order":false}'
    )
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["current_paper_session_id"] is None
    assert state["source_rejection_reason_counts"]["SOURCE_PAYLOAD_DUPLICATE_JSON_KEY"] == 1
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []


def test_outer_canonical_decoder_rejects_duplicate_keys_before_mapping_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis(_source_values([_clean_row(index) for index in range(20)]))
    _clock(monkeypatch)
    state = tuner.run_adaptive_tuning(redis_client)
    raw = tuner._canonical_json(state)
    ambiguous = raw.replace(
        '"paper_only":true',
        '"paper_only":false,"paper_only":true',
        1,
    )

    decoded, reasons = tuner.decode_canonical_gate_tuning_redis_payload(ambiguous)

    assert decoded is None
    assert reasons == ["CANONICAL_PAYLOAD_DUPLICATE_JSON_KEY"]


@pytest.mark.parametrize(
    ("limit_name", "limit_value", "raw", "expected_reason"),
    (
        (
            "MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES",
            2,
            b'{"x":0}',
            "CANONICAL_PAYLOAD_BYTE_LIMIT_EXCEEDED",
        ),
        (
            "MAX_CANONICAL_GATE_TUNING_JSON_DEPTH",
            1,
            b'{"x":[[0]]}',
            "CANONICAL_PAYLOAD_JSON_DEPTH_LIMIT_EXCEEDED",
        ),
        (
            "MAX_CANONICAL_GATE_TUNING_JSON_NODES",
            2,
            b'{"x":0}',
            "CANONICAL_PAYLOAD_JSON_NODE_LIMIT_EXCEEDED",
        ),
        (
            "MAX_CANONICAL_GATE_TUNING_JSON_TEXT_BYTES",
            2,
            b'{"long":0}',
            "CANONICAL_PAYLOAD_JSON_TEXT_LIMIT_EXCEEDED",
        ),
    ),
)
def test_outer_canonical_decoder_enforces_resource_limits(
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit_value: int,
    raw: bytes,
    expected_reason: str,
) -> None:
    monkeypatch.setattr(tuner, limit_name, limit_value)

    def forbidden_json_loads(*args: object, **kwargs: object) -> object:
        raise AssertionError("json.loads must not run for a lexically overbound payload")

    monkeypatch.setattr(json, "loads", forbidden_json_loads)

    decoded, reasons = tuner.decode_canonical_gate_tuning_redis_payload(raw)

    assert decoded is None
    assert reasons == [expected_reason]


def test_outer_canonical_decoder_ignores_quoted_and_escaped_delimiters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "text": '[[[{{{"quoted":"}]}}}]]]',
        "escaped": '\\"}][{',
    }
    raw = tuner._canonical_json(expected).encode("utf-8")
    monkeypatch.setattr(tuner, "MAX_CANONICAL_GATE_TUNING_JSON_DEPTH", 1)

    decoded, reasons = tuner.decode_canonical_gate_tuning_redis_payload(raw)

    assert reasons == []
    assert decoded == expected


def test_outer_canonical_decoder_rejects_scalar_depth_before_json_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tuner, "MAX_CANONICAL_GATE_TUNING_JSON_DEPTH", 1)

    def forbidden_json_loads(*args: object, **kwargs: object) -> object:
        raise AssertionError("json.loads must not run for an over-depth scalar")

    monkeypatch.setattr(json, "loads", forbidden_json_loads)

    decoded, reasons = tuner.decode_canonical_gate_tuning_redis_payload(b'{"x":[0]}')

    assert decoded is None
    assert reasons == ["CANONICAL_PAYLOAD_JSON_DEPTH_LIMIT_EXCEEDED"]


def test_outer_canonical_decoder_totalizes_released_memoryview() -> None:
    released = memoryview(b'{"x":0}')
    released.release()

    decoded, reasons = tuner.decode_canonical_gate_tuning_redis_payload(released)

    assert decoded is None
    assert reasons == ["CANONICAL_PAYLOAD_BUFFER_INVALID"]


def test_string_byte_cap_is_checked_without_allocating_multibyte_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tuner, "MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES", 3)

    def forbidden_encode(value: str) -> bytes:
        raise AssertionError(f"over-cap string must not be encoded: {value!r}")

    monkeypatch.setattr(tuner, "_encode_utf8_exact", forbidden_encode)

    decoded, reasons = tuner.decode_canonical_gate_tuning_redis_payload("éé")

    assert decoded is None
    assert reasons == ["CANONICAL_PAYLOAD_BYTE_LIMIT_EXCEEDED"]


def test_mutable_buffer_capture_is_an_immutable_exact_snapshot() -> None:
    expected = b'{"x":0}'
    sources: tuple[bytearray | memoryview, ...] = (
        bytearray(expected),
        memoryview(bytearray(expected)),
    )

    for source in sources:
        captured, reasons = tuner.capture_canonical_gate_tuning_redis_bytes(source)
        source[0] = ord("[")

        assert reasons == []
        assert captured == expected
        assert bytes(source) != captured


@pytest.mark.parametrize(
    "source",
    (bytearray(b"{}"), memoryview(bytearray(b"{}"))),
)
def test_mutable_buffer_capture_rechecks_cap_after_copy_race(
    monkeypatch: pytest.MonkeyPatch,
    source: bytearray | memoryview,
) -> None:
    monkeypatch.setattr(tuner, "MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES", 4)
    monkeypatch.setattr(tuner, "_copy_buffer_exact", lambda _value: b"12345")

    captured, reasons = tuner.capture_canonical_gate_tuning_redis_bytes(source)

    assert captured is None
    assert reasons == ["CANONICAL_PAYLOAD_BYTE_LIMIT_EXCEEDED"]


@pytest.mark.parametrize("raw", (b'{"x":1e10000}', b'{"x":Infinity}'))
def test_outer_canonical_decoder_rejects_nonfinite_numeric_forms(raw: bytes) -> None:
    decoded, reasons = tuner.decode_canonical_gate_tuning_redis_payload(raw)

    assert decoded is None
    assert reasons == ["CANONICAL_PAYLOAD_NUMERIC_INVALID"]


def test_huge_finite_json_integer_fails_closed_without_crashing_producer_or_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_clean_row(index) for index in range(20)]
    rows[0]["realized_net_pnl_usd"] = 10**309
    redis_client = FakeRedis(_source_values(rows))
    _clock(monkeypatch)

    state = tuner.run_adaptive_tuning(redis_client)

    assert state["rejection_reason_counts"]["REALIZED_PNL_MISSING_OR_NONFINITE"] == 1
    assert state["permissive_authority"] is False
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    state["adaptive_confidence_threshold"] = 10**309
    assert tuner.adaptive_gate_tuning_rejection_reasons(state) == [
        "CANONICAL_PAYLOAD_NUMERIC_INVALID"
    ]


def test_canonical_builder_cannot_be_given_permissive_values_for_negative_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _source_values([_clean_row(index, pnl=-1.0) for index in range(20)])
    redis_client = FakeRedis(sources)
    _clock(monkeypatch)
    evidence_state = tuner.run_adaptive_tuning(redis_client)
    positive_redis = FakeRedis(_source_values([_clean_row(index, pnl=1.0) for index in range(20)]))
    _clock(monkeypatch)
    positive_state = tuner.run_adaptive_tuning(positive_redis)
    _clock(monkeypatch)

    rebuilt = tuner._build_canonical_state(
        outcomes=positive_state["outcomes"],
        regime=positive_state["market_regime"],
        source_values=sources,
        source_manifest=tuner._source_manifest(sources),
        source_read_errors=[],
        current_paper_session_id=SESSION_ID,
        session_identity_errors=[],
        outcomes_cutoff=BASE,
        adaptive_confidence_threshold=0.01,
        loss_probability_threshold=0.99,
        enable_b_grade=True,
        enable_a_grade=True,
        volatility_factor=tuner.MIN_VOLATILITY_FACTOR,
        trainer_performance_factor=tuner.MAX_PERFORMANCE_FACTOR,
        portfolio_performance_factor=tuner.MAX_PERFORMANCE_FACTOR,
        long_confidence_floor=0.01,
        short_confidence_floor=0.01,
        expectancy_floor=0.0,
        entry_freeze_allowance=1.0,
        a_plus_strictness=tuner.MIN_A_PLUS_STRICTNESS,
    )

    assert rebuilt["adaptive_confidence_threshold"] == tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    assert rebuilt["adaptive_loss_probability_threshold"] == (
        tuner.FAIL_CLOSED_LOSS_PROBABILITY_CEILING
    )
    assert rebuilt["enable_b_grade"] is False
    assert rebuilt["enable_a_grade"] is False
    assert rebuilt["adaptive_entry_freeze_allowance"] == 0.0
    assert rebuilt["outcomes"] == evidence_state["outcomes"]
    assert rebuilt["outcomes"] != positive_state["outcomes"]
    assert (
        tuner.adaptive_gate_tuning_rejection_reasons(
            rebuilt,
            observed_at=BASE + timedelta(seconds=3),
            current_paper_session_id=SESSION_ID,
            require_current_session=True,
        )
        == []
    )
