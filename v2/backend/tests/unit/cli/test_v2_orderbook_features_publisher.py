from __future__ import annotations

import ast
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.cli import v2_orderbook_features_publisher as supervisor
from v2.backend.app.services.orderbook_recorder.features import build_orderbook_payloads


def _clock(epoch_ms: int) -> str:
    return (
        datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _pair(*, server_ms: int, sequence_id: int = 10, available_age_ms: int = 50) -> tuple[bytes, bytes]:
    available_ms = server_ms - available_age_ms
    event_ms = available_ms - 25
    transaction_ms = event_ms - 5
    bids = [[100.0 - index * 0.1, 20.0 + index] for index in range(20)]
    asks = [[101.0 + index * 0.1, 20.0 + index] for index in range(20)]
    payloads = build_orderbook_payloads(
        exchange="binance",
        symbol="BTCUSDT",
        bids=bids,
        asks=asks,
        event_time_ms=event_ms,
        transaction_time_ms=transaction_ms,
        received_at=_clock(available_ms),
        available_at=_clock(available_ms),
        sequence_id=sequence_id,
        previous_sequence_id=sequence_id - 1,
        sequence_gap=False,
        update_type="partial_depth",
        depth_level=20,
        feed_speed_ms=250,
    )
    for payload in payloads.values():
        payload["generated_at"] = _clock(available_ms)
        payload["source_latency_ms"] = 25
        payload["update_age_ms"] = 0
    return tuple(
        json.dumps(payloads[role], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        for role in ("depth", "features")
    )  # type: ignore[return-value]


class _Redis:
    def __init__(
        self,
        *,
        server_ms: int,
        pair: tuple[bytes, bytes],
        pttls: tuple[int, int] = (29_900, 29_896),
    ) -> None:
        self.server_ms = server_ms
        self.depth_raw, self.features_raw = pair
        self.pttls = pttls
        self.eval_calls: list[tuple[str, int, str, str]] = []
        self.set_calls: list[tuple[str, str, int]] = []
        self.get_calls = 0

    def replace(
        self,
        *,
        server_ms: int,
        pair: tuple[bytes, bytes],
        pttls: tuple[int, int] = (29_900, 29_896),
    ) -> None:
        self.server_ms = server_ms
        self.depth_raw, self.features_raw = pair
        self.pttls = pttls

    def eval(self, script: str, key_count: int, depth_key: str, features_key: str) -> list[Any]:
        self.eval_calls.append((script, key_count, depth_key, features_key))
        seconds, milliseconds = divmod(self.server_ms, 1000)
        return [
            str(seconds).encode(),
            str(milliseconds * 1000).encode(),
            self.depth_raw,
            self.features_raw,
            self.pttls[0],
            self.pttls[1],
        ]

    def get(self, _key: str) -> None:
        self.get_calls += 1
        raise AssertionError("non-atomic GET is forbidden")

    def mget(self, *_keys: str) -> None:
        raise AssertionError("client-side MGET lacks Redis TIME/PTTL coherence")

    def set(self, key: str, value: str, *, ex: int) -> bool:
        self.set_calls.append((key, value, ex))
        return True


def _cycle(
    client: _Redis,
    tracker: supervisor.AdaptiveCadenceTracker | None = None,
) -> dict[str, Any]:
    return supervisor.run_cycle(
        client,
        symbols=["BTCUSDT"],
        ttl_seconds=60,
        cadence_tracker=tracker or supervisor.AdaptiveCadenceTracker(),
    )


def _mutate_json(raw: bytes, mutate) -> bytes:
    payload = json.loads(raw)
    mutate(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def test_cold_start_holds_then_observed_sequence_transition_becomes_healthy() -> None:
    first_ms = 1_784_674_800_000
    client = _Redis(server_ms=first_ms, pair=_pair(server_ms=first_ms))
    tracker = supervisor.AdaptiveCadenceTracker()

    cold = _cycle(client, tracker)
    assert cold["canonical_pair_integrity_valid"] == 1
    assert cold["canonical_pair_healthy"] == 0
    assert cold["canonical_pair_unknown"] == 1
    assert cold["canonical_pair_reasons"] == {"COLD_START_NO_OBSERVED_CADENCE": 1}

    next_ms = first_ms + 2_000
    client.replace(server_ms=next_ms, pair=_pair(server_ms=next_ms, sequence_id=11))
    healthy = _cycle(client, tracker)

    assert healthy["canonical_pair_healthy"] == 1
    assert healthy["canonical_pair_unknown"] == 0
    assert healthy["canonical_pair_reasons"] == {}
    assert healthy["features_written"] == 0
    assert healthy["trainer_admission_authorized"] is False
    assert healthy["paper_trading_authorized"] is False
    assert healthy["live_execution_authorized"] is False
    assert [row[0] for row in client.set_calls] == [supervisor.SUMMARY_KEY, supervisor.SUMMARY_KEY]


def test_receipt_binds_exact_bytes_hashes_counts_time_and_pttl() -> None:
    now = 1_784_674_800_123
    pair = _pair(server_ms=now)
    client = _Redis(server_ms=now, pair=pair, pttls=(29_111, 29_109))

    summary = _cycle(client)

    receipt = summary["pair_read_receipts"][0]
    assert receipt["depth_exact_bytes"] == len(pair[0])
    assert receipt["features_exact_bytes"] == len(pair[1])
    assert receipt["pair_exact_bytes"] == len(pair[0]) + len(pair[1])
    assert receipt["depth_sha256"] == hashlib.sha256(pair[0]).hexdigest()
    assert receipt["features_sha256"] == hashlib.sha256(pair[1]).hexdigest()
    assert receipt["redis_server_time_ms"] == now
    assert receipt["depth_pttl_ms"] == 29_111
    assert receipt["features_pttl_ms"] == 29_109
    assert receipt["atomic_read_lua_sha256"] == supervisor.ATOMIC_PAIR_READ_LUA_SHA256
    assert len(client.eval_calls) == 1
    assert client.get_calls == 0


def test_atomic_lua_boundary_cannot_observe_client_side_torn_pair() -> None:
    now = 1_784_674_800_000
    old_pair = _pair(server_ms=now)
    client = _Redis(server_ms=now, pair=old_pair)

    summary = _cycle(client)

    assert summary["canonical_pair_integrity_valid"] == 1
    assert client.get_calls == 0
    script, key_count, depth_key, features_key = client.eval_calls[0]
    assert key_count == 2
    assert "TIME" in script and "MGET" in script and script.count("PTTL") == 2
    assert depth_key == "v2:orderbook:depth:binance:BTCUSDT"
    assert features_key == "v2:orderbook:features:binance:BTCUSDT"


@pytest.mark.parametrize("invalid", [True, False, 0, -1, 1.5, math.nan, math.inf, -math.inf])
def test_invalid_ttl_is_rejected_before_any_redis_operation(invalid: Any) -> None:
    now = 1_784_674_800_000
    client = _Redis(server_ms=now, pair=_pair(server_ms=now))

    with pytest.raises(ValueError, match="ttl_seconds_must_be_positive_exact_int"):
        supervisor.run_cycle(
            client,
            symbols=["BTCUSDT"],
            ttl_seconds=invalid,
            cadence_tracker=supervisor.AdaptiveCadenceTracker(),
        )
    assert client.eval_calls == []
    assert client.set_calls == []


def test_summary_json_rejects_nonfinite_without_redis_write() -> None:
    now = 1_784_674_800_000
    client = _Redis(server_ms=now, pair=_pair(server_ms=now))

    assert supervisor._write_summary(client, {"forged": math.nan}, ttl_seconds=10) is False
    assert client.set_calls == []


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_exact_json_parser_rejects_nonfinite_constants(constant: str) -> None:
    now = 1_784_674_800_000
    depth, features = _pair(server_ms=now)
    forged = depth[:-1] + f',"forged":{constant}}}'.encode()

    summary = _cycle(_Redis(server_ms=now, pair=(forged, features)))

    assert summary["canonical_pair_reasons"] == {"JSON_NONFINITE_CONSTANT": 1}


def test_exact_json_parser_rejects_numeric_overflow_to_infinity() -> None:
    now = 1_784_674_800_000
    depth, features = _pair(server_ms=now)
    forged = depth[:-1] + b',"forged":1e999}'

    summary = _cycle(_Redis(server_ms=now, pair=(forged, features)))

    assert summary["canonical_pair_reasons"] == {"JSON_NONFINITE_NUMBER": 1}


def test_exact_json_parser_rejects_duplicate_keys_at_any_depth() -> None:
    now = 1_784_674_800_000
    depth, features = _pair(server_ms=now)
    text = depth.decode().replace('"quantity":20.0', '"quantity":20.0,"quantity":21.0', 1)

    summary = _cycle(_Redis(server_ms=now, pair=(text.encode(), features)))

    assert summary["canonical_pair_reasons"] == {"JSON_DUPLICATE_KEY": 1}


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda row: row.__setitem__("bids", "truthy"), "DEPTH_SHAPE_INVALID"),
        (lambda row: row.__setitem__("bids", [{"price": 100.0}]), "DEPTH_LEVEL_SHAPE_INVALID"),
        (lambda row: row.__setitem__("sequence_id", None), "SEQUENCE_ID_INVALID"),
        (lambda row: row.__setitem__("sequence_id", True), "SEQUENCE_ID_INVALID"),
        (
            lambda row: row.__setitem__("update_type", "rest_snapshot"),
            "TRANSPORT_NOT_DIRECT_PARTIAL_DEPTH_WSS",
        ),
    ],
)
def test_malformed_depth_sequence_and_rest_transport_fail_closed(mutate, reason: str) -> None:
    now = 1_784_674_800_000
    depth, features = _pair(server_ms=now)
    depth = _mutate_json(depth, mutate)

    summary = _cycle(_Redis(server_ms=now, pair=(depth, features)))

    assert summary["canonical_pair_reasons"] == {reason: 1}


def test_matching_rest_snapshot_pair_is_rejected_as_non_wss_transport() -> None:
    now = 1_784_674_800_000
    depth, features = _pair(server_ms=now)
    depth = _mutate_json(depth, lambda row: row.__setitem__("update_type", "rest_snapshot"))
    features = _mutate_json(features, lambda row: row.__setitem__("update_type", "rest_snapshot"))

    summary = _cycle(_Redis(server_ms=now, pair=(depth, features)))

    assert summary["canonical_pair_reasons"] == {"TRANSPORT_NOT_DIRECT_PARTIAL_DEPTH_WSS": 1}


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("spread_bps", 99.0),
        ("depth_5_bid_usd", 1.0),
        ("depth_imbalance", 0.99),
        ("depth_slope", 42.0),
        ("estimated_price_impact_bps", 999.0),
        ("orderbook_depth_usd", 1.0),
    ],
)
def test_every_forged_feature_family_is_recomputed(field: str, replacement: float) -> None:
    now = 1_784_674_800_000
    depth, features = _pair(server_ms=now)
    features = _mutate_json(features, lambda row: row.__setitem__(field, replacement))

    summary = _cycle(_Redis(server_ms=now, pair=(depth, features)))

    assert summary["canonical_pair_integrity_valid"] == 0
    assert list(summary["canonical_pair_reasons"].values()) == [1]
    assert "SUBSTITUTION" in next(iter(summary["canonical_pair_reasons"]))


def test_wrong_level_order_and_crossed_book_are_rejected() -> None:
    now = 1_784_674_800_000
    for mutation, reason in (
        (lambda row: row["bids"].reverse(), "BID_ORDER_INVALID"),
        (lambda row: row["asks"].reverse(), "ASK_ORDER_INVALID"),
        (lambda row: row["asks"][0].__setitem__("price", 99.0), "CROSSED_OR_ZERO_SPREAD"),
    ):
        depth, features = _pair(server_ms=now)
        depth = _mutate_json(depth, mutation)
        summary = _cycle(_Redis(server_ms=now, pair=(depth, features)))
        assert summary["canonical_pair_reasons"] == {reason: 1}


def test_one_day_stale_pair_with_fresh_ttl_is_never_called_healthy() -> None:
    now = 1_784_674_800_000
    one_day_ms = 24 * 60 * 60 * 1000
    stale_pair = _pair(server_ms=now - one_day_ms)
    client = _Redis(server_ms=now, pair=stale_pair, pttls=(29_900, 29_899))

    summary = _cycle(client)

    assert summary["canonical_pair_integrity_valid"] == 1
    assert summary["canonical_pair_healthy"] == 0
    assert summary["canonical_pair_unknown"] == 1
    assert summary["canonical_pair_reasons"] == {"COLD_START_NO_OBSERVED_CADENCE": 1}


def test_replayed_old_availability_cannot_seed_a_large_adaptive_budget() -> None:
    first_ms = 1_784_674_800_000
    client = _Redis(server_ms=first_ms, pair=_pair(server_ms=first_ms))
    tracker = supervisor.AdaptiveCadenceTracker()
    _cycle(client, tracker)

    next_server_ms = first_ms + 5_000
    # Availability advances by one millisecond, but still predates the prior
    # atomic Redis observation and therefore proves a replay rather than a new
    # source event.
    replay_clock = first_ms + 1
    client.replace(
        server_ms=next_server_ms,
        pair=_pair(server_ms=replay_clock, sequence_id=11),
    )
    summary = _cycle(client, tracker)

    assert summary["canonical_pair_reasons"] == {"REPLAYED_AVAILABILITY": 1}


def test_missing_expiry_or_large_pair_expiry_skew_is_held() -> None:
    now = 1_784_674_800_000
    for pttls, reason in (((-1, -1), "EXPIRY_EVIDENCE_INVALID"), ((29_900, 29_000), "PAIR_EXPIRY_MISMATCH")):
        summary = _cycle(_Redis(server_ms=now, pair=_pair(server_ms=now), pttls=pttls))
        assert summary["canonical_pair_reasons"] == {reason: 1}


def test_summary_write_boundary_has_no_key_parameter_or_write_alias() -> None:
    source_path = Path(supervisor.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    redis_write_names = {"set", "setex", "mset", "hset", "evalsha"}
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in redis_write_names
    ]
    assert len(calls) == 1
    call = calls[0]
    assert isinstance(call.func, ast.Attribute) and call.func.attr == "set"
    assert len(call.args) >= 1
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "SUMMARY_KEY"
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            continue
        value = node.value
        assert not (
            isinstance(value, ast.Attribute) and value.attr in redis_write_names
        ), "Redis write method must never be aliased"


def test_legacy_static_market_age_option_and_deriver_are_absent() -> None:
    source = Path(supervisor.__file__).read_text(encoding="utf-8")
    assert "max-book-age-seconds" not in source
    assert "DEFAULT_MAX_BOOK_AGE_SECONDS" not in source
    assert "derive_orderbook_features" not in source
    assert "v2:market:orderbook" not in source
