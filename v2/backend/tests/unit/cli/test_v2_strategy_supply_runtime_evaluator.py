from __future__ import annotations

import ast
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.cli import v2_strategy_supply_runtime_evaluator as evaluator
from v2.backend.app.services.strategy_supply.edge_hypothesis_generator import (
    LATEST_ERROR_SUMMARY_KEY,
    LATEST_POSITIVE_SUMMARY_KEY,
    STATUS_KEY,
    STRATEGY_FAMILIES,
)

NOW = datetime(2026, 7, 28, 14, 30, tzinfo=UTC)


def _utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _status(**overrides: Any) -> dict[str, Any]:
    status: dict[str, Any] = {
        "schema_version": "strategy_supply_publish_status_v1",
        "generated_utc": _utc(NOW - timedelta(seconds=10)),
        "status": "GREEN_PUBLISHING_GATE_CLEAN_POSITIVES",
        "status_reason": "gate_clean_positive_hypotheses_available",
        "symbol_count": 1,
        "timeframe_count": 1,
        "hypothesis_count": 3,
        "positive_hypothesis_count": 2,
        "gate_clean_positive_hypothesis_count": 1,
        "stage_rejected_positive_hypothesis_count": 1,
        "strategy_families": list(STRATEGY_FAMILIES),
        "redis_keys_written": [
            "v2:strategy_supply:hypotheses:BTCUSDT:1m",
            "v2:strategy_supply:positive_hypotheses:BTCUSDT:1m",
            "v2:strategy_supply:gate_clean_positive_hypotheses:BTCUSDT:1m",
            LATEST_POSITIVE_SUMMARY_KEY,
            LATEST_ERROR_SUMMARY_KEY,
        ],
        "ttl_seconds": 900,
        "publish_cadence_seconds": 60.0,
        "ttl_longer_than_three_publish_cadences": True,
        "approves_trade_alone": False,
        "routes_to_live": False,
        "places_real_order": False,
        "test_order_submitted": False,
        "cancel_or_modify_order": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "live_gate_required": "blocked_human_only",
        "exchange_action_taken": False,
    }
    status.update(overrides)
    return status


def _raw(status: dict[str, Any]) -> bytes:
    return json.dumps(
        status,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def test_valid_status_returns_content_bound_read_only_receipt() -> None:
    raw = _raw(_status())

    receipt = evaluator.evaluate_strategy_supply_status(
        raw,
        now_utc=NOW,
        max_age_seconds=180,
    )

    assert receipt["status"] == "PASS_CANONICAL_STRATEGY_SUPPLY_EVALUATED"
    assert receipt["learning_signal"] == (
        "GATE_CLEAN_ALTERNATIVE_STRATEGY_HYPOTHESES_PRESENT"
    )
    assert receipt["source_key"] == STATUS_KEY
    assert receipt["source_status_sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["source_age_seconds"] == 10.0
    assert receipt["symbol_count"] == 1
    assert receipt["timeframe_count"] == 1
    assert receipt["redis_keys_observed"] == 5
    assert receipt["approves_trade_alone"] is False
    assert receipt["execution_authority"] is False
    assert receipt["paper_only"] is True
    assert receipt["live_gate"] == "blocked_human_only"
    assert receipt["routes_to_live"] is False
    assert receipt["places_real_order"] is False
    assert receipt["exchange_action_taken"] is False


def test_duplicate_json_keys_fail_closed() -> None:
    raw = _raw(_status())
    duplicate = raw.replace(
        b'{"approves_trade_alone":false,',
        b'{"approves_trade_alone":false,"approves_trade_alone":false,',
        1,
    )

    with pytest.raises(ValueError, match="DUPLICATE_JSON_KEY"):
        evaluator.evaluate_strategy_supply_status(duplicate, now_utc=NOW)


def test_nonfinite_json_fails_closed() -> None:
    raw = _raw(_status()).replace(b'"ttl_seconds":900', b'"ttl_seconds":NaN')

    with pytest.raises(ValueError, match="NONFINITE_JSON"):
        evaluator.evaluate_strategy_supply_status(raw, now_utc=NOW)


@pytest.mark.parametrize(
    ("generated_utc", "expected"),
    [
        (_utc(NOW - timedelta(seconds=181)), "strategy_supply_status:STALE"),
        (_utc(NOW + timedelta(seconds=6)), "FUTURE_GENERATED_AT"),
    ],
)
def test_stale_or_future_status_fails_closed(
    generated_utc: str,
    expected: str,
) -> None:
    with pytest.raises(ValueError, match=expected):
        evaluator.evaluate_strategy_supply_status(
            _raw(_status(generated_utc=generated_utc)),
            now_utc=NOW,
            max_age_seconds=180,
        )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"positive_hypothesis_count": 4}, "HYPOTHESIS_COUNT_ORDER_INVALID"),
        (
            {"gate_clean_positive_hypothesis_count": 3},
            "HYPOTHESIS_COUNT_ORDER_INVALID",
        ),
        (
            {"stage_rejected_positive_hypothesis_count": 0},
            "STAGE_REJECTION_COUNT_MISMATCH",
        ),
        ({"symbol_count": 0}, "EMPTY_EVALUATION_UNIVERSE"),
        ({"timeframe_count": 0}, "EMPTY_EVALUATION_UNIVERSE"),
        ({"hypothesis_count": 0}, "HYPOTHESIS_COUNT_ORDER_INVALID"),
    ],
)
def test_invalid_counts_fail_closed(
    overrides: dict[str, Any],
    expected: str,
) -> None:
    with pytest.raises(ValueError, match=expected):
        evaluator.evaluate_strategy_supply_status(
            _raw(_status(**overrides)),
            now_utc=NOW,
        )


@pytest.mark.parametrize(
    "families",
    [
        list(STRATEGY_FAMILIES[:-1]),
        list(reversed(STRATEGY_FAMILIES)),
        [*STRATEGY_FAMILIES[:-1], STRATEGY_FAMILIES[0]],
    ],
)
def test_family_tampering_fails_closed(families: list[str]) -> None:
    with pytest.raises(ValueError, match="STRATEGY_FAMILY_SET_MISMATCH"):
        evaluator.evaluate_strategy_supply_status(
            _raw(_status(strategy_families=families)),
            now_utc=NOW,
        )


def test_duplicate_written_key_fails_closed() -> None:
    written = list(_status()["redis_keys_written"])
    written.append(written[0])

    with pytest.raises(ValueError, match="DUPLICATE_WRITTEN_KEY"):
        evaluator.evaluate_strategy_supply_status(
            _raw(_status(redis_keys_written=written)),
            now_utc=NOW,
        )


def test_unauthorized_written_key_fails_closed() -> None:
    written = [*_status()["redis_keys_written"], "v2:model_registry:paper:active"]

    with pytest.raises(ValueError, match="UNAUTHORIZED_WRITTEN_KEY"):
        evaluator.evaluate_strategy_supply_status(
            _raw(_status(redis_keys_written=written)),
            now_utc=NOW,
        )


def test_missing_expected_written_key_fails_closed() -> None:
    written = list(_status()["redis_keys_written"])
    written.remove("v2:strategy_supply:gate_clean_positive_hypotheses:BTCUSDT:1m")

    with pytest.raises(ValueError, match="WRITTEN_KEY_COUNT_MISMATCH"):
        evaluator.evaluate_strategy_supply_status(
            _raw(_status(redis_keys_written=written)),
            now_utc=NOW,
        )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"ttl_seconds": 180}, "TTL_CADENCE_COVERAGE_INVALID"),
        (
            {"ttl_longer_than_three_publish_cadences": False},
            "TTL_CADENCE_ATTESTATION_MISSING",
        ),
        ({"publish_cadence_seconds": 0}, "FINITE_POSITIVE_REQUIRED"),
    ],
)
def test_ttl_tampering_fails_closed(
    overrides: dict[str, Any],
    expected: str,
) -> None:
    with pytest.raises(ValueError, match=expected):
        evaluator.evaluate_strategy_supply_status(
            _raw(_status(**overrides)),
            now_utc=NOW,
        )


@pytest.mark.parametrize(
    ("field", "unsafe_value", "expected"),
    [
        ("paper_only", False, "PAPER_ONLY_REQUIRED"),
        ("exchange_action_taken", True, "EXCHANGE_ACTION_FORBIDDEN"),
        ("approves_trade_alone", True, "UNSAFE_AUTHORITY"),
        ("routes_to_live", True, "UNSAFE_AUTHORITY"),
        ("places_real_order", True, "UNSAFE_AUTHORITY"),
        ("test_order_submitted", True, "UNSAFE_AUTHORITY"),
        ("cancel_or_modify_order", True, "UNSAFE_AUTHORITY"),
        ("leverage_mutation", True, "UNSAFE_AUTHORITY"),
        ("margin_mode_mutation", True, "UNSAFE_AUTHORITY"),
        ("transfer_or_withdrawal", True, "UNSAFE_AUTHORITY"),
        ("live_gate", "open", "LIVE_GATE_BLOCK_REQUIRED"),
        ("live_gate_required", "open", "LIVE_GATE_BLOCK_REQUIRED"),
    ],
)
def test_authority_tampering_fails_closed(
    field: str,
    unsafe_value: Any,
    expected: str,
) -> None:
    with pytest.raises(ValueError, match=expected):
        evaluator.evaluate_strategy_supply_status(
            _raw(_status(**{field: unsafe_value})),
            now_utc=NOW,
        )


def test_evaluator_module_contains_no_redis_set_call() -> None:
    source_path = Path(evaluator.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    redis_set_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set"
    ]
    assert redis_set_calls == []


def test_main_reads_status_once_and_never_writes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class ReadOnlyRedis:
        def __init__(self) -> None:
            self.get_calls: list[str] = []

        def get(self, key: str) -> bytes:
            self.get_calls.append(key)
            return _raw(_status(generated_utc=_utc(datetime.now(UTC))))

        def set(self, *_args: Any, **_kwargs: Any) -> None:  # pragma: no cover
            raise AssertionError("read-only evaluator attempted Redis SET")

    client = ReadOnlyRedis()
    monkeypatch.setattr(evaluator, "_redis_client", lambda _url: client)
    monkeypatch.setenv("LIVE_GATE", "blocked_human_only")

    assert evaluator.main(["--max-age-seconds", "180"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert client.get_calls == [STATUS_KEY]
    assert receipt["status"] == "PASS_CANONICAL_STRATEGY_SUPPLY_EVALUATED"
    assert receipt["execution_authority"] is False
