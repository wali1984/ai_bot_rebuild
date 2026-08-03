from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from v2.backend.app.cli import v2_adaptive_gate_tuner as canonical_tuner
from v2.backend.app.services.adaptive_gate_tuning import runtime_tuner
from v2.backend.tests.unit.cli import test_v2_adaptive_gate_tuner as tuner_fixtures


class FakeRedis:
    def __init__(self, values: dict[str, object] | None = None):
        self.values = dict(values or {})
        self.write_calls: list[tuple[str, str, int | None]] = []

    def get(self, key: str) -> object | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        self.write_calls.append((key, value, ex))
        return True


def _canonical_state(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeRedis, dict[str, object]]:
    rows = [
        tuner_fixtures._clean_row(index, pnl=1.0 if index < 14 else -0.25) for index in range(20)
    ]
    redis_client = FakeRedis(tuner_fixtures._source_values(rows))
    tuner_fixtures._clock(monkeypatch)
    return redis_client, canonical_tuner.run_adaptive_tuning(redis_client)


def _runtime_results_for_sources(
    monkeypatch: pytest.MonkeyPatch,
    sources: dict[str, object],
) -> tuple[dict[str, object], dict[str, Any], float]:
    redis_client = FakeRedis(sources)
    tuner_fixtures._clock(monkeypatch)
    state = canonical_tuner.run_adaptive_tuning(redis_client)
    shadow = runtime_tuner.compute_adaptive_gate_tuning(
        redis_client,
        observed_at=tuner_fixtures.BASE.replace(second=3),
    )
    threshold = runtime_tuner.get_adaptive_threshold(
        redis_client,
        "adaptive_confidence_threshold",
        0.01,
        current_paper_session_id=tuner_fixtures.SESSION_ID,
        observed_at=tuner_fixtures.BASE.replace(second=3),
    )
    return state, shadow, threshold


def _set_path(root: dict[str, object], path: Sequence[str | int], value: object) -> None:
    current: object = root
    for part in path[:-1]:
        if isinstance(part, int):
            assert isinstance(current, list)
            current = current[part]
        else:
            assert isinstance(current, dict)
            current = current[part]
    final = path[-1]
    if isinstance(final, int):
        assert isinstance(current, list)
        current[final] = value
    else:
        assert isinstance(current, dict)
        current[final] = value


def _first_market_analysis(state: dict[str, object]) -> dict[str, object]:
    market_regime = state["market_regime"]
    assert isinstance(market_regime, dict)
    source_analyses = market_regime["source_analyses"]
    assert isinstance(source_analyses, list)
    analysis = source_analyses[0]
    assert isinstance(analysis, dict)
    return analysis


def test_runtime_tuner_publishes_only_non_authoritative_shadow() -> None:
    canonical_sentinel = "canonical-must-not-change"
    redis_client = FakeRedis({runtime_tuner.CANONICAL_GATE_TUNING_KEY: canonical_sentinel})

    runtime_tuner.publish_adaptive_gate_tuning(redis_client)

    assert len(redis_client.write_calls) == 1
    key, raw, ttl = redis_client.write_calls[0]
    assert key == runtime_tuner.SHADOW_GATE_TUNING_KEY
    assert key != runtime_tuner.CANONICAL_GATE_TUNING_KEY
    assert ttl == 60
    assert redis_client.values[runtime_tuner.CANONICAL_GATE_TUNING_KEY] == canonical_sentinel
    payload = json.loads(raw)
    assert payload["schema_version"] == runtime_tuner.SHADOW_SCHEMA_VERSION
    assert payload["producer"] == runtime_tuner.SHADOW_PRODUCER
    assert payload["authoritative"] is False
    assert payload["authority_status"] == "NON_AUTHORITATIVE_SHADOW_DIAGNOSTIC"
    assert payload["may_control_admission"] is False
    assert payload["canonical_authority_key"] == runtime_tuner.CANONICAL_GATE_TUNING_KEY
    assert payload["shadow_key"] == runtime_tuner.SHADOW_GATE_TUNING_KEY
    assert payload["emits_admission_thresholds"] is False
    assert payload["static_market_or_performance_thresholds"] is False
    assert payload["canonical_payload_valid"] is False
    assert payload["canonical_validation_scope"] == (
        "PUBLICATION_INTEGRITY_AND_FRESHNESS_ONLY_NO_SESSION_ADMISSION"
    )


def test_threshold_reader_ignores_shadow_payload() -> None:
    redis_client = FakeRedis(
        {
            runtime_tuner.SHADOW_GATE_TUNING_KEY: json.dumps(
                {
                    "adaptive_loss_probability_threshold": 0.99,
                    "authoritative": False,
                }
            )
        }
    )

    assert (
        runtime_tuner.get_adaptive_threshold(
            redis_client,
            "adaptive_loss_probability_threshold",
            0.80,
        )
        == canonical_tuner.FAIL_CLOSED_LOSS_PROBABILITY_CEILING
    )


def test_threshold_reader_accepts_only_fully_validated_current_session_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client, state = _canonical_state(monkeypatch)
    raw_expected = state["adaptive_loss_probability_threshold"]
    assert isinstance(raw_expected, int | float)
    expected = float(raw_expected)

    assert (
        runtime_tuner.get_adaptive_threshold(
            redis_client,
            "adaptive_loss_probability_threshold",
            0.80,
            current_paper_session_id=tuner_fixtures.SESSION_ID,
            observed_at=tuner_fixtures.BASE.replace(second=3),
        )
        == expected
    )
    assert expected > canonical_tuner.FAIL_CLOSED_LOSS_PROBABILITY_CEILING

    raw_state = redis_client.values[runtime_tuner.CANONICAL_GATE_TUNING_KEY]
    assert isinstance(raw_state, str | bytes | bytearray)
    forged = json.loads(raw_state)
    forged["producer"] = runtime_tuner.SHADOW_PRODUCER
    redis_client.values[runtime_tuner.CANONICAL_GATE_TUNING_KEY] = json.dumps(forged)
    assert (
        runtime_tuner.get_adaptive_threshold(
            redis_client,
            "adaptive_loss_probability_threshold",
            0.80,
            current_paper_session_id=tuner_fixtures.SESSION_ID,
            observed_at=tuner_fixtures.BASE.replace(second=3),
        )
        == canonical_tuner.FAIL_CLOSED_LOSS_PROBABILITY_CEILING
    )


def test_threshold_reader_returns_fail_closed_extrema_for_ambiguous_bound_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [tuner_fixtures._clean_row(index) for index in range(20)]
    for row in rows:
        row["paper_close_id"] = f"forged-{row['close_id']}"
        row["realized_pnl_usd"] = -1000.0
    redis_client = FakeRedis(tuner_fixtures._source_values(rows))
    tuner_fixtures._clock(monkeypatch)
    state = canonical_tuner.run_adaptive_tuning(redis_client)

    confidence = runtime_tuner.get_adaptive_threshold(
        redis_client,
        "adaptive_confidence_threshold",
        0.01,
        current_paper_session_id=tuner_fixtures.SESSION_ID,
        observed_at=tuner_fixtures.BASE.replace(second=3),
    )
    loss_probability = runtime_tuner.get_adaptive_threshold(
        redis_client,
        "adaptive_loss_probability_threshold",
        0.99,
        current_paper_session_id=tuner_fixtures.SESSION_ID,
        observed_at=tuner_fixtures.BASE.replace(second=3),
    )

    assert state["admitted_row_count"] == 0
    assert state["rejection_reason_counts"]["CLOSE_ID_ALIAS_CONFLICT"] == 20
    assert state["rejection_reason_counts"]["REALIZED_PNL_ALIAS_CONFLICT"] == 20
    assert confidence == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    assert loss_probability == canonical_tuner.FAIL_CLOSED_LOSS_PROBABILITY_CEILING


def test_runtime_rejects_duplicate_outer_keys_before_threshold_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client, _state = _canonical_state(monkeypatch)
    raw = redis_client.values[runtime_tuner.CANONICAL_GATE_TUNING_KEY]
    assert isinstance(raw, str)
    redis_client.values[runtime_tuner.CANONICAL_GATE_TUNING_KEY] = raw.replace(
        '"paper_only":true',
        '"paper_only":false,"paper_only":true',
        1,
    )

    shadow = runtime_tuner.compute_adaptive_gate_tuning(
        redis_client,
        observed_at=tuner_fixtures.BASE.replace(second=3),
    )
    threshold = runtime_tuner.get_adaptive_threshold(
        redis_client,
        "adaptive_confidence_threshold",
        0.01,
        current_paper_session_id=tuner_fixtures.SESSION_ID,
        observed_at=tuner_fixtures.BASE.replace(second=3),
    )

    assert shadow["canonical_payload_valid"] is False
    assert shadow["canonical_rejection_reasons"] == ["CANONICAL_PAYLOAD_DUPLICATE_JSON_KEY"]
    assert threshold == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR


def test_runtime_hashes_mutable_buffer_views_as_exact_immutable_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client, _state = _canonical_state(monkeypatch)
    raw = redis_client.values[runtime_tuner.CANONICAL_GATE_TUNING_KEY]
    assert isinstance(raw, str)
    raw_bytes = raw.encode("utf-8")
    strict_decode = canonical_tuner.decode_canonical_gate_tuning_redis_payload

    for wrapped in (bytearray(raw_bytes), memoryview(bytearray(raw_bytes))):

        def mutate_source_then_decode(
            captured: object,
            *,
            source: bytearray | memoryview = wrapped,
        ) -> tuple[dict[str, object] | None, list[str]]:
            assert type(captured) is bytes
            source[0] = ord("[")
            return strict_decode(captured)

        monkeypatch.setattr(
            runtime_tuner,
            "decode_canonical_gate_tuning_redis_payload",
            mutate_source_then_decode,
        )
        redis_client.values[runtime_tuner.CANONICAL_GATE_TUNING_KEY] = wrapped
        shadow = runtime_tuner.compute_adaptive_gate_tuning(
            redis_client,
            observed_at=tuner_fixtures.BASE.replace(second=3),
        )
        assert shadow["canonical_payload_valid"] is True
        assert shadow["canonical_payload_bytes_captured"] is True
        assert shadow["canonical_payload_sha256"] == hashlib.sha256(raw_bytes).hexdigest()
        assert bytes(wrapped) != raw_bytes


def test_runtime_totalizes_released_memoryview_and_reports_no_false_hash() -> None:
    released = memoryview(b"{}")
    released.release()
    redis_client = FakeRedis({runtime_tuner.CANONICAL_GATE_TUNING_KEY: released})

    shadow = runtime_tuner.compute_adaptive_gate_tuning(redis_client)
    threshold = runtime_tuner.get_adaptive_threshold(
        redis_client,
        "adaptive_confidence_threshold",
        0.01,
    )

    assert shadow["canonical_payload_present"] is True
    assert shadow["canonical_payload_bytes_captured"] is False
    assert shadow["canonical_payload_valid"] is False
    assert shadow["canonical_rejection_reasons"] == ["CANONICAL_PAYLOAD_BUFFER_INVALID"]
    assert shadow["canonical_payload_sha256"] is None
    assert threshold == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR


def test_threshold_reader_fails_closed_without_session_or_after_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client, state = _canonical_state(monkeypatch)
    raw_expires_at = state["expires_at"]
    assert isinstance(raw_expires_at, str)
    expires_at = datetime.fromisoformat(raw_expires_at.replace("Z", "+00:00"))

    assert (
        runtime_tuner.get_adaptive_threshold(
            redis_client,
            "adaptive_confidence_threshold",
            0.01,
            observed_at=tuner_fixtures.BASE.replace(second=3),
        )
        == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    )
    assert (
        runtime_tuner.get_adaptive_threshold(
            redis_client,
            "adaptive_loss_probability_threshold",
            0.99,
            current_paper_session_id=tuner_fixtures.SESSION_ID,
            observed_at=expires_at,
        )
        == canonical_tuner.FAIL_CLOSED_LOSS_PROBABILITY_CEILING
    )


def test_threshold_reader_rejects_unsafe_source_session_even_when_envelope_is_sealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = tuner_fixtures._source_values(
        [tuner_fixtures._clean_row(index) for index in range(20)]
    )
    sources[canonical_tuner.PAPER_SESSION_KEY] = json.dumps(
        {
            "paper_session_id": tuner_fixtures.SESSION_ID,
            "reset_session_id": tuner_fixtures.SESSION_ID,
            "paper_only": False,
            "routes_to_live": True,
            "places_real_order": True,
        },
        sort_keys=True,
    )
    redis_client = FakeRedis(sources)
    tuner_fixtures._clock(monkeypatch)
    state = canonical_tuner.run_adaptive_tuning(redis_client)

    assert canonical_tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    assert "CURRENT_PAPER_SESSION_SOURCE_UNSAFE" in (
        canonical_tuner.adaptive_gate_tuning_rejection_reasons(
            state,
            observed_at=tuner_fixtures.BASE.replace(second=3),
            current_paper_session_id=tuner_fixtures.SESSION_ID,
            require_current_session=True,
        )
    )
    assert (
        runtime_tuner.get_adaptive_threshold(
            redis_client,
            "adaptive_confidence_threshold",
            0.01,
            current_paper_session_id=tuner_fixtures.SESSION_ID,
            observed_at=tuner_fixtures.BASE.replace(second=3),
        )
        == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    )


def test_threshold_reader_rejects_unknown_threshold_name() -> None:
    with pytest.raises(ValueError, match="UNSUPPORTED_ADAPTIVE_THRESHOLD"):
        runtime_tuner.get_adaptive_threshold(FakeRedis(), "retired_static_gate", 0.5)


def test_threshold_reader_fails_closed_on_source_read_error() -> None:
    class FailingRedis:
        def get(self, key: str) -> object | None:
            raise RuntimeError(f"read failed for {key}")

    assert (
        runtime_tuner.get_adaptive_threshold(
            FailingRedis(),
            "adaptive_confidence_threshold",
            0.01,
            current_paper_session_id=tuner_fixtures.SESSION_ID,
            observed_at=tuner_fixtures.BASE.replace(second=3),
        )
        == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
    )


def test_runtime_shadow_reports_valid_canonical_without_republishing_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client, state = _canonical_state(monkeypatch)

    shadow = runtime_tuner.compute_adaptive_gate_tuning(
        redis_client,
        observed_at=tuner_fixtures.BASE.replace(second=3),
    )

    assert shadow["canonical_payload_valid"] is True
    assert shadow["canonical_policy_id"] == state["policy_id"]
    assert shadow["canonical_rejection_reasons"] == []
    assert shadow["emits_admission_thresholds"] is False
    assert not any(key.startswith("adaptive_") for key in shadow)


@pytest.mark.parametrize(
    "invalid_value",
    (
        int((tuner_fixtures.BASE.replace(minute=1)).timestamp() * 1000),
        None,
        "",
        {"epoch_ms": 0},
    ),
)
def test_runtime_keeps_sealed_invalid_market_close_alias_histories_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: object,
) -> None:
    rows = [tuner_fixtures._clean_row(index) for index in range(20)]
    sources = tuner_fixtures._source_values(rows)
    source_key = canonical_tuner.MARKET_CANDLE_KEYS[0]
    candles = json.loads(str(sources[source_key]))
    for candle in candles:
        candle["close_time"] = invalid_value
    sources[source_key] = json.dumps(candles, sort_keys=True)

    state, shadow, threshold = _runtime_results_for_sources(monkeypatch, sources)

    analysis = _first_market_analysis(state)
    assert analysis["source_row_count"] == 100
    assert analysis["admitted_row_count"] == 0
    assert analysis["rejected_row_count"] == 100
    assert state["permissive_authority"] is False
    assert canonical_tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    assert shadow["canonical_payload_valid"] is True
    assert threshold == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR


@pytest.mark.parametrize("removed_alias", ("candle_close_time", "close_time"))
def test_runtime_accepts_sealed_market_histories_with_one_valid_close_alias(
    monkeypatch: pytest.MonkeyPatch,
    removed_alias: str,
) -> None:
    rows = [tuner_fixtures._clean_row(index) for index in range(20)]
    sources = tuner_fixtures._source_values(rows)
    source_key = canonical_tuner.MARKET_CANDLE_KEYS[0]
    candles = json.loads(str(sources[source_key]))
    for candle in candles:
        candle.pop(removed_alias)
    sources[source_key] = json.dumps(candles, sort_keys=True)

    state, shadow, threshold = _runtime_results_for_sources(monkeypatch, sources)

    analysis = _first_market_analysis(state)
    assert analysis["admitted_row_count"] == 100
    assert analysis["rejected_row_count"] == 0
    assert canonical_tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    assert shadow["canonical_payload_valid"] is True
    assert threshold == state["adaptive_confidence_threshold"]


def test_runtime_keeps_submicrosecond_market_close_alias_collision_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [tuner_fixtures._clean_row(index) for index in range(20)]
    sources = tuner_fixtures._source_values(rows)
    source_key = canonical_tuner.MARKET_CANDLE_KEYS[0]
    candles = json.loads(str(sources[source_key]))
    for candle in candles:
        raw_close = candle["candle_close_time"]
        assert type(raw_close) is int
        seconds, milliseconds = divmod(raw_close, 1000)
        close = datetime.fromtimestamp(seconds, tz=UTC) + timedelta(milliseconds=milliseconds)
        stem = tuner_fixtures._canonical_utc(close).removesuffix("Z")
        candle["candle_close_time"] = f"{stem}1Z"
        candle["close_time"] = f"{stem}9Z"
    sources[source_key] = json.dumps(candles, sort_keys=True)

    state, shadow, threshold = _runtime_results_for_sources(monkeypatch, sources)

    analysis = _first_market_analysis(state)
    assert analysis["source_row_count"] == 100
    assert analysis["admitted_row_count"] == 0
    assert analysis["rejected_row_count"] == 100
    assert analysis["row_rejection_reason_counts"] == {"CLOSE_TIME_INVALID": 100}
    assert state["permissive_authority"] is False
    assert canonical_tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    assert shadow["canonical_payload_valid"] is True
    assert threshold == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR


def test_runtime_keeps_submicrosecond_outcome_clock_alias_collision_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [tuner_fixtures._clean_row(index) for index in range(20)]
    for row in rows:
        raw_close = row["exit_time"]
        assert type(raw_close) is str
        stem = raw_close.removesuffix("Z")
        row["exit_time"] = f"{stem}1Z"
        row["closed_at"] = f"{stem}9Z"
    sources = tuner_fixtures._source_values(rows)

    state, shadow, threshold = _runtime_results_for_sources(monkeypatch, sources)

    assert state["source_row_count"] == 20
    assert state["admitted_row_count"] == 0
    assert state["rejected_row_count"] == 20
    assert state["rejection_reason_counts"] == {"CLOSE_TIME_NOT_AWARE": 20}
    assert state["permissive_authority"] is False
    assert canonical_tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    assert shadow["canonical_payload_valid"] is True
    assert threshold == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR


@pytest.mark.parametrize(
    "sibling",
    (
        "NEGATIVE_ROWS",
        None,
        {"not": "a list"},
        [],
    ),
)
def test_runtime_keeps_sealed_invalid_outcome_collection_aliases_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    sibling: object,
) -> None:
    positive_rows = [tuner_fixtures._clean_row(index, pnl=1.0) for index in range(20)]
    negative_rows = [tuner_fixtures._clean_row(index, pnl=-1.0) for index in range(20)]
    sources = tuner_fixtures._source_values(positive_rows)
    closed_trades = negative_rows if sibling == "NEGATIVE_ROWS" else sibling
    sources[canonical_tuner.OUTCOMES_KEY] = json.dumps(
        {"trades": positive_rows, "closed_trades": closed_trades},
        sort_keys=True,
    )

    state, shadow, threshold = _runtime_results_for_sources(monkeypatch, sources)

    assert state["source_row_count"] == 0
    assert state["admitted_row_count"] == 0
    assert state["permissive_authority"] is False
    assert canonical_tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    assert shadow["canonical_payload_valid"] is True
    assert threshold == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR


@pytest.mark.parametrize(
    "aliases", (("trades",), ("closed_trades",), ("rows",), ("trades", "rows"))
)
def test_runtime_accepts_valid_single_or_equivalent_outcome_collection_aliases(
    monkeypatch: pytest.MonkeyPatch,
    aliases: tuple[str, ...],
) -> None:
    rows = [tuner_fixtures._clean_row(index) for index in range(20)]
    sources = tuner_fixtures._source_values(rows)
    sources[canonical_tuner.OUTCOMES_KEY] = json.dumps(
        {alias: copy.deepcopy(rows) for alias in aliases},
        sort_keys=True,
    )

    state, shadow, threshold = _runtime_results_for_sources(monkeypatch, sources)

    assert state["admitted_row_count"] == 20
    assert state["rejected_row_count"] == 0
    assert canonical_tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    assert shadow["canonical_payload_valid"] is True
    assert threshold == state["adaptive_confidence_threshold"]


@pytest.mark.parametrize(
    "field",
    (
        "dirty_flag",
        "dirty_reasons",
        "future_labels_used_as_features",
        "candidate_selected_after_outcome",
        "post_outcome_candidate_selection",
    ),
)
def test_runtime_keeps_missing_required_outcome_safety_fields_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    rows = [tuner_fixtures._clean_row(index) for index in range(20)]
    for row in rows:
        row.pop(field)
    sources = tuner_fixtures._source_values(rows)

    state, shadow, threshold = _runtime_results_for_sources(monkeypatch, sources)

    assert state["admitted_row_count"] == 0
    assert state["rejected_row_count"] == 20
    assert canonical_tuner.adaptive_gate_tuning_rejection_reasons(state) == []
    assert shadow["canonical_payload_valid"] is True
    assert threshold == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR


@pytest.mark.parametrize(
    ("path", "replacement", "expected_reason"),
    (
        (
            ("outcomes", "legacy_outcome_availability_at_cutoff_count"),
            False,
            "OUTCOMES_SOURCE_DERIVATION_MISMATCH",
        ),
        (
            ("outcomes", "grade_evidence", "A", "count"),
            False,
            "OUTCOMES_SOURCE_DERIVATION_MISMATCH",
        ),
        (
            ("market_regime", "source_analyses", 0, "rejected_row_count"),
            False,
            "MARKET_REGIME_SOURCE_DERIVATION_MISMATCH",
        ),
        (
            ("source_row_count",),
            20.0,
            "OUTCOME_SUMMARY_BINDING_INVALID:source_row_count",
        ),
        (
            ("immutable_bound_classification", "minimum_clean_outcomes", "value"),
            20.0,
            "IMMUTABLE_BOUND_CLASSIFICATION_INVALID",
        ),
        (
            ("ttl_seconds",),
            3600.0,
            "PUBLICATION_TTL_SECONDS_INVALID",
        ),
    ),
)
def test_validator_and_runtime_reject_resealed_json_type_confusion(
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[str | int, ...],
    replacement: object,
    expected_reason: str,
) -> None:
    redis_client, original = _canonical_state(monkeypatch)
    forged = copy.deepcopy(original)
    _set_path(forged, path, replacement)
    tuner_fixtures._reseal_state(forged)
    redis_client.values[runtime_tuner.CANONICAL_GATE_TUNING_KEY] = canonical_tuner._canonical_json(
        forged
    )

    validator_reasons = canonical_tuner.adaptive_gate_tuning_rejection_reasons(
        forged,
        observed_at=tuner_fixtures.BASE.replace(second=3),
        current_paper_session_id=tuner_fixtures.SESSION_ID,
        require_current_session=True,
    )
    shadow = runtime_tuner.compute_adaptive_gate_tuning(
        redis_client,
        observed_at=tuner_fixtures.BASE.replace(second=3),
    )
    threshold = runtime_tuner.get_adaptive_threshold(
        redis_client,
        "adaptive_confidence_threshold",
        0.01,
        current_paper_session_id=tuner_fixtures.SESSION_ID,
        observed_at=tuner_fixtures.BASE.replace(second=3),
    )

    assert expected_reason in validator_reasons
    assert "PUBLICATION_RECEIPT_HASH_INVALID" not in validator_reasons
    assert shadow["canonical_payload_valid"] is False
    assert expected_reason in shadow["canonical_rejection_reasons"]
    assert threshold == canonical_tuner.FAIL_CLOSED_CONFIDENCE_FLOOR
