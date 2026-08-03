from __future__ import annotations

import asyncio
import json
import math
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[5]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from v2.backend.app.cli import v2_coinapi_wsds_loop as wsds  # noqa: E402

COINAPI_SYMBOL_ID = "BINANCEFTS_PERP_BTC_USDT"


class StatefulRedis:
    def __init__(self, *, set_ack: object = True) -> None:
        self.set_ack = set_ack
        self.values: dict[str, str] = {}
        self.fences: dict[str, dict[str, str]] = {}
        self.cadence_records: dict[str, dict[str, str]] = {}
        self.auth_records: dict[str, dict[str, str]] = {}
        self.conflicts: dict[str, str] = {}
        self.payload_ttls_ms: dict[str, int] = {}
        self.expiry_refreshes: dict[str, int] = {}
        self.lock = threading.Lock()

    def set(self, key: str, value: str, ex: int | None = None) -> object:
        assert ex is None or ex > 0
        if self.set_ack is True:
            self.values[key] = value
            self.payload_ttls_ms[key] = -1 if ex is None else ex * 1000
        return self.set_ack

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def hmget(self, key: str, *fields: str) -> list[str | None]:
        record = self.cadence_records.get(key) or self.auth_records.get(key) or {}
        return [record.get(field) for field in fields]

    def pttl(self, key: str) -> int:
        if key in self.auth_records:
            return -1
        return self.payload_ttls_ms.get(key, -2)

    def exists(self, key: str) -> int:
        return int(
            key in self.values
            or key in self.fences
            or key in self.cadence_records
            or key in self.auth_records
        )

    def delete(self, key: str) -> int:
        removed = key in self.cadence_records or key in self.auth_records
        self.cadence_records.pop(key, None)
        self.auth_records.pop(key, None)
        self.payload_ttls_ms.pop(key, None)
        return int(removed)

    def eval(self, script: str, numkeys: int, *args: object) -> list[object]:
        if "COINAPI_BOUNDED_PERSISTENT_HASH_READ_V1" in script:
            assert numkeys == 1
            key, identity_field, payload_field, identity_limit, payload_limit = args
            record = self.cadence_records.get(str(key)) or self.auth_records.get(str(key))
            if record is None:
                return [wsds._STATE_READ_MISSING, "", ""]
            if self.pttl(str(key)) != -1:
                return [wsds._STATE_READ_INVALID, "", ""]
            identity = record.get(str(identity_field))
            payload = record.get(str(payload_field))
            if identity is None or payload is None:
                return [wsds._STATE_READ_INVALID, "", ""]
            identity_length = len(identity.encode("utf-8"))
            payload_length = len(payload.encode("utf-8"))
            if identity_length > int(str(identity_limit)) or payload_length > int(
                str(payload_limit)
            ):
                return [wsds._STATE_READ_OVERSIZED, identity_length, payload_length]
            return [wsds._STATE_READ_OK, identity, payload]
        assert "decimal_compare" in script
        if "AUTH_STATE_COMMITTED_NEWER" in script:
            assert numkeys == 1
            key, revision, payload, identity_limit, payload_limit = args
            assert identity_limit == wsds.MAX_STATE_IDENTITY_BYTES
            assert payload_limit == wsds.MAX_STATE_JSON_BYTES
            current = self.auth_records.get(str(key))
            if current is not None:
                incoming = int(str(revision))
                previous = int(current["revision_ns"])
                if incoming < previous:
                    return [wsds._AUTH_STATE_OLDER, 0]
                if incoming == previous:
                    if str(payload) == current["payload"]:
                        return [wsds._AUTH_STATE_CURRENT, 0]
                    return [wsds._AUTH_STATE_CONFLICT, 0]
            self.auth_records[str(key)] = {
                "revision_ns": str(revision),
                "payload": str(payload),
            }
            self.payload_ttls_ms[str(key)] = -1
            return [wsds._AUTH_STATE_COMMITTED, 1]
        if "CADENCE_COMMITTED_NEWER" in script:
            assert numkeys == 1
            key, event, payload, identity_limit, payload_limit = args
            assert identity_limit == wsds.MAX_STATE_IDENTITY_BYTES
            assert payload_limit == wsds.MAX_STATE_JSON_BYTES
            with self.lock:
                current = self.cadence_records.get(str(key))
                if current is not None:
                    incoming = int(str(event))
                    previous = int(current["last_event_ns"])
                    if incoming < previous:
                        return [wsds._CADENCE_OLDER, 0]
                    if incoming == previous:
                        if str(payload) == current["payload"]:
                            return [wsds._CADENCE_CURRENT, 0]
                        return [wsds._CADENCE_CONFLICT, 0]
                self.cadence_records[str(key)] = {
                    "last_event_ns": str(event),
                    "payload": str(payload),
                }
                self.payload_ttls_ms[str(key)] = -1
                return [wsds._CADENCE_COMMITTED, 1]
        assert "PERSIST" in script
        assert numkeys == 3
        (
            fence_key,
            data_key,
            conflict_key,
            event,
            digest,
            payload,
            ttl,
            identity_limit,
            payload_limit,
        ) = args
        assert identity_limit == wsds.MAX_STATE_IDENTITY_BYTES
        assert payload_limit == wsds.MAX_REDIS_QUARANTINE_JSON_BYTES
        assert type(ttl) is int and ttl > 0
        with self.lock:
            current = self.fences.get(str(fence_key))
            current_ttl = self.payload_ttls_ms.get(str(data_key), -2)
            if current is not None:
                incoming = int(str(event))
                previous = int(current["event"])
                if incoming < previous:
                    return [wsds._FENCE_OLDER, 0, current_ttl]
                if incoming == previous:
                    if str(digest) == current["digest"]:
                        return [wsds._FENCE_DUPLICATE, 0, current_ttl]
                    if str(conflict_key) in self.conflicts:
                        return [wsds._FENCE_CONFLICT_DUPLICATE, 0, current_ttl]
                    self.conflicts[str(conflict_key)] = str(payload)
                    return [wsds._FENCE_CONFLICT, 1, current_ttl]
            self.fences[str(fence_key)] = {
                "event": str(event),
                "digest": str(digest),
            }
            self.values[str(data_key)] = str(payload)
            self.payload_ttls_ms[str(data_key)] = ttl * 1000
            self.expiry_refreshes[str(data_key)] = self.expiry_refreshes.get(str(data_key), 0) + 1
            return [wsds._FENCE_COMMITTED, 1, ttl * 1000]


class NeverEvalRedis:
    def __init__(self) -> None:
        self.eval_calls = 0

    def eval(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.eval_calls += 1
        raise AssertionError("invalid raw payload reached Redis EVAL")


class MessageSocket:
    def __init__(
        self,
        messages: list[Any],
        final_error: Exception | None = None,
    ) -> None:
        self.messages = list(messages)
        self.final_error = final_error or RuntimeError("socket exhausted")
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        if self.messages:
            message = self.messages.pop(0)
            if callable(message):
                message = message()
            return json.dumps(message)
        raise self.final_error


class FakeConnection:
    def __init__(self, socket: MessageSocket) -> None:
        self.socket = socket

    async def __aenter__(self) -> MessageSocket:
        return self.socket

    async def __aexit__(self, *args: object) -> bool:
        del args
        return False


def _quote(
    event: str,
    received: str,
    *,
    symbol_id: str = "BINANCEFTS_PERP_BTC_USDT",
    bid: object = 100,
    ask: object = 101,
    bid_size: object = 2,
    ask_size: object = 3,
) -> dict[str, object]:
    return {
        "type": "quote",
        "symbol_id": symbol_id,
        "time_exchange": event,
        "time_coinapi": received,
        "bid_price": bid,
        "ask_price": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
    }


def _quote_ns(
    event_ns: int,
    *,
    received_lag_ns: int = 100_000,
    bid: object = 100,
) -> dict[str, object]:
    return _quote(
        wsds.iso_utc_ns(event_ns),
        wsds.iso_utc_ns(event_ns + received_lag_ns),
        bid=bid,
    )


def _basis_ending_at(
    last_event_ns: int,
    *,
    api_key: str = "configured-key",
    coinapi_symbol_id: str = COINAPI_SYMBOL_ID,
) -> dict[str, Any]:
    cadence_ns = 1_000_000_000
    samples = [
        (
            last_event_ns - offset,
            last_event_ns - offset + 100_000,
            last_event_ns - offset + 200_000,
        )
        for offset in (2 * cadence_ns, cadence_ns, 0)
    ]
    basis = wsds._build_authenticated_cadence_basis(
        samples,
        symbol="BTCUSDT",
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
    )
    assert basis is not None
    return basis


def _raw_ws_payload(
    event_ns: int,
    *,
    bid: float = 100.0,
    symbol: str = "BTCUSDT",
    coinapi_symbol_id: str = COINAPI_SYMBOL_ID,
) -> dict[str, object]:
    identity = wsds.parse_coinapi_symbol_id(coinapi_symbol_id)
    assert identity is not None
    observed_ns = ((event_ns // 1_000) + 1) * 1_000
    normalized = wsds.normalize_wsds_snapshot(
        symbol=symbol,
        snapshot={
            "coinapi_symbol_id": coinapi_symbol_id,
            "coinapi_exchange_id": identity[0],
            "coinapi_market_type": identity[1],
            "source_event_time": wsds.iso_utc_ns(event_ns),
            "source_event_ts_ms": event_ns // 1_000_000,
            "source_event_ts_ns": event_ns,
            "provider_received_time": wsds.iso_utc_ns(event_ns),
            "observed_at": wsds.iso_utc_ns(observed_ns),
            "ingested_at": wsds.iso_utc_ns(observed_ns + 1_000),
            "generated_at": wsds.iso_utc_ns(observed_ns + 2_000),
            "available_at": None,
            "best_bid_px": bid,
            "best_ask_px": bid + 1.0,
            "best_bid_sz": 1.0,
            "best_ask_sz": 1.0,
            "mid_px": bid + 0.5,
            "spread_bps": 10_000.0 / (bid + 0.5),
            "microprice": bid + 0.5,
            "book_bid_sum_5": 1.0,
            "book_ask_sum_5": 1.0,
            "imbalance_5": 0.0,
        },
        timeframes=("1m",),
    )
    payload = normalized["quarantine_payload"]
    assert isinstance(payload, dict)
    return payload


def _cadence_key(
    *,
    provisional: bool = False,
    api_key: str = "configured-key",
    coinapi_symbol_id: str = COINAPI_SYMBOL_ID,
) -> str:
    key = wsds._cadence_state_key(
        symbol="BTCUSDT",
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
        provisional=provisional,
    )
    assert key is not None
    return key


def _data_key(
    *,
    symbol: str = "BTCUSDT",
    coinapi_symbol_id: str = COINAPI_SYMBOL_ID,
) -> str:
    return wsds.WS_DATA_KEY_TEMPLATE.format(
        coinapi_symbol_id=coinapi_symbol_id,
        symbol=symbol,
    )


def _fence_key(
    *,
    symbol: str = "BTCUSDT",
    coinapi_symbol_id: str = COINAPI_SYMBOL_ID,
) -> str:
    return wsds.WS_FENCE_KEY_TEMPLATE.format(
        coinapi_symbol_id=coinapi_symbol_id,
        symbol=symbol,
    )


def _conflict_key(
    event_ns: int,
    digest: str,
    *,
    symbol: str = "BTCUSDT",
    coinapi_symbol_id: str = COINAPI_SYMBOL_ID,
) -> str:
    return wsds.WS_CONFLICT_KEY_TEMPLATE.format(
        coinapi_symbol_id=coinapi_symbol_id,
        symbol=symbol,
        event_ns=event_ns,
        digest=digest,
    )


def _run_fake_session(
    tmp_path: Path,
    messages: list[Any],
    *,
    symbols: tuple[str, ...] = ("BTCUSDT",),
    redis_client: Any | None = None,
    final_error: Exception | None = None,
    api_key: str = "configured-key",
) -> tuple[dict[str, Any], tuple[Path, ...], StatefulRedis | Any]:
    socket = MessageSocket(messages, final_error)
    connection = FakeConnection(socket)
    status_paths = (
        tmp_path / "status.json",
        tmp_path / "public.json",
        tmp_path / "worklog.json",
    )
    client = redis_client or StatefulRedis()
    stats = asyncio.run(
        wsds._run_session(
            symbols=symbols,
            api_key=api_key,
            redis_client=client,
            ttl_seconds=60,
            ws_url=wsds.DEFAULT_WS_URL,
            data_types=["quote"],
            max_symbols=len(symbols),
            max_seconds_per_session=10.0,
            max_messages_per_session=len(messages),
            heartbeat_interval_seconds=0.01,
            status_paths=status_paths,
            connect_factory=lambda *args, **kwargs: connection,
        )
    )
    return stats, status_paths, client


def _connected_args(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "out": tmp_path / "status.json",
        "out_public": tmp_path / "public.json",
        "out_worklog": tmp_path / "worklog.json",
        "total_seconds": 0.01,
        "ttl_seconds": 60,
        "max_symbols": 1,
        "max_seconds_per_session": 10.0,
        "max_messages_per_session": 10,
        "heartbeat_interval_seconds": 1.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_coinapi_wsds_once_emits_blocked_status_with_no_subscription_or_live_input(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("V2_COINAPI_WSDS_OPT_IN", raising=False)
    monkeypatch.delenv("COINAPI_API_KEY", raising=False)
    monkeypatch.delenv("COINAPI_KEY", raising=False)
    monkeypatch.delenv("COINAPI_WSDS_URL", raising=False)
    monkeypatch.setattr(wsds, "DEFAULT_SECRET_PATHS", (tmp_path / "missing.env",))
    monkeypatch.setattr(wsds, "_connect_redis", StatefulRedis)
    out = tmp_path / "status.json"
    rc = wsds.main(
        [
            "--once",
            "--smoke-test",
            "--out",
            str(out),
            "--out-public",
            str(tmp_path / "public.json"),
            "--out-worklog",
            str(tmp_path / "worklog.json"),
        ]
    )
    payload = json.loads(out.read_text())
    assert rc == 0
    assert payload["classification"] == "V2_COINAPI_WSDS_OPTIONAL_DORMANT_NOT_OPTED_IN"
    assert payload["provider_health"]["state"] == "OPTIONAL_DORMANT_NOT_OPTED_IN"
    assert payload["subscribed_symbols"] == []
    assert payload["stream_connected"] is False
    assert payload["live_data_enabled"] is False
    assert payload["live_decision_input_enabled"] is False
    assert payload["trainer_consumable"] is False
    assert payload["redis_ok"] is True  # exact heartbeat SET acknowledgement
    assert payload["service_healthy"] is True
    assert payload["status_publication_healthy"] is True
    assert payload["current_data_commit_acked"] is False
    assert payload["publication_healthy"] is False


def test_ws_endpoint_is_exact_and_redirect_processing_is_disabled() -> None:
    for rejected in (
        "ws://ws.coinapi.io:443/v1/",
        "wss://ws.coinapi.io/v1/",
        "wss://user@ws.coinapi.io:443/v1/",
        "wss://ws.coinapi.io:443/v1",
        "wss://ws.coinapi.io:443/v1/?apikey=secret",
        "wss://evil.invalid:443/v1/",
    ):
        with pytest.raises(ValueError, match="allowlisted"):
            wsds._validate_ws_url(rejected)

    class Connector:
        def process_redirect(self, exc: Exception) -> str:
            del exc
            return "wss://evil.invalid/"

    connector = Connector()
    captured: dict[str, object] = {}

    def factory(url: str, **kwargs: object) -> Connector:
        captured["url"] = url
        captured.update(kwargs)
        return connector

    returned = wsds._open_ws_without_redirects(
        wsds.DEFAULT_WS_URL,
        connect_factory=factory,
    )
    marker = RuntimeError("redirect")
    assert returned is connector
    assert connector.process_redirect(marker) is marker
    assert captured["url"] == "wss://ws.coinapi.io:443/v1/"
    assert captured["max_size"] == 1_048_576


@pytest.mark.parametrize(
    "raw",
    (
        "NaN",
        "Infinity",
        "-Infinity",
        "1e999",
        '{"nested":[NaN]}',
        '{"nested":[-1e999]}',
    ),
)
def test_ws_bounded_json_rejects_nonfinite_numbers_at_every_depth(raw: str) -> None:
    assert (
        wsds._loads_bounded_json(
            raw,
            max_bytes=wsds.MAX_WS_MESSAGE_BYTES,
            max_depth=wsds.MAX_WS_JSON_DEPTH,
            max_items=wsds.MAX_WS_JSON_ITEMS,
        )
        is None
    )


def test_ws_direct_string_utf8_count_is_incremental_and_bounded() -> None:
    multibyte = '"' + ("é" * (wsds.UTF8_COUNT_CHUNK_CHARACTERS + 1)) + '"'
    exact_bytes = 2 + (2 * (wsds.UTF8_COUNT_CHUNK_CHARACTERS + 1))

    assert wsds._utf8_length_within_limit(multibyte, max_bytes=exact_bytes)
    assert not wsds._utf8_length_within_limit(multibyte, max_bytes=exact_bytes - 1)
    assert wsds._loads_bounded_json(
        multibyte,
        max_bytes=exact_bytes,
        max_depth=wsds.MAX_WS_JSON_DEPTH,
        max_items=wsds.MAX_WS_JSON_ITEMS,
    ) == "é" * (wsds.UTF8_COUNT_CHUNK_CHARACTERS + 1)
    assert (
        wsds._loads_bounded_json(
            "x" * (wsds.MAX_STATE_JSON_BYTES + 1),
            max_bytes=wsds.MAX_STATE_JSON_BYTES,
            max_depth=16,
            max_items=64,
        )
        is None
    )


def test_ws_provider_quota_message_without_http_status_is_terminal_and_sanitized(
    tmp_path: Path,
) -> None:
    stats, paths, _client = _run_fake_session(
        tmp_path,
        [{"type": "error", "message": "subscription quota exhausted"}],
    )
    provider_health = stats["provider_health"]
    assert isinstance(provider_health, dict)
    assert provider_health["provider_http_status"] is None
    assert provider_health["provider_error_class"] == "QUOTA_OR_SUBSCRIPTION_EXHAUSTED"
    assert provider_health["raw_provider_reason_recorded"] is False
    assert provider_health["raw_provider_body_recorded"] is False
    assert stats["committed_messages"] == 0
    status = json.loads(paths[0].read_text())
    assert status["classification"] == "V2_COINAPI_WSDS_OPTIONAL_AUTH_UNAVAILABLE"
    assert "subscription quota exhausted" not in json.dumps(status, sort_keys=True)


def test_ws_set_and_fence_ack_types_are_exact() -> None:
    for ack in (False, 1, "OK", b"OK", None):
        assert not wsds._safe_set_json(StatefulRedis(set_ack=ack), "v2:test", {}, ex=60)
    assert wsds._safe_set_json(StatefulRedis(), "v2:test", {}, ex=60)

    class AckRedis:
        def __init__(self, result: object) -> None:
            self.result = result

        def eval(self, *args: object) -> object:
            del args
            return self.result

    payload = _raw_ws_payload(1)
    payload_digest = wsds._provider_content_digest(payload)
    assert payload_digest is not None
    exact_conflict_key = _conflict_key(1, payload_digest)
    assert wsds._atomic_fenced_quarantine_write(
        StatefulRedis(),
        fence_key=_fence_key(),
        data_key=_data_key(),
        conflict_key="v2:quarantine:coinapi:wsds:conflict:unicode",
        event_identity_ns="١",
        payload=payload,
        ex=60,
    ) == (wsds._FENCE_ERROR, -2)
    for malformed in (
        [wsds._FENCE_COMMITTED, True, 60_000],
        [wsds._FENCE_COMMITTED, 1, True],
        [wsds._FENCE_COMMITTED, "1", 60_000],
        ["UNKNOWN", 1, 60_000],
        [wsds._FENCE_COMMITTED, 0, 60_000],
        [wsds._FENCE_COMMITTED, 1, 0],
        [wsds._FENCE_COMMITTED],
        (wsds._FENCE_COMMITTED, 1, 60_000),
        RuntimeError("not returned"),
    ):
        client: Any
        if isinstance(malformed, Exception):

            class RaisingRedis:
                def __init__(self, error: Exception) -> None:
                    self.error = error

                def eval(self, *args: object) -> object:
                    del args
                    raise self.error

            client = RaisingRedis(malformed)
        else:
            client = AckRedis(malformed)
        assert wsds._atomic_fenced_quarantine_write(
            client,
            fence_key=_fence_key(),
            data_key=_data_key(),
            conflict_key=exact_conflict_key,
            event_identity_ns="1",
            payload=payload,
            ex=60,
        ) == (wsds._FENCE_ERROR, -2)

    now_ns = wsds.datetime_epoch_ns(datetime.now(UTC))
    basis = _basis_ending_at(now_ns - 1_000_000)
    cadence_key = _cadence_key()
    for malformed in (
        [wsds._CADENCE_COMMITTED, True],
        [wsds._CADENCE_COMMITTED, 0],
        ["UNKNOWN", 1],
        [wsds._CADENCE_COMMITTED],
        (wsds._CADENCE_COMMITTED, 1),
    ):
        assert (
            wsds._atomic_persist_authenticated_cadence_basis(
                AckRedis(malformed),
                key=cadence_key,
                symbol="BTCUSDT",
                coinapi_symbol_id=COINAPI_SYMBOL_ID,
                api_key="configured-key",
                basis=basis,
            )
            == wsds._CADENCE_ERROR
        )
    assert (
        wsds._atomic_persist_authenticated_cadence_basis(
            StatefulRedis(),
            key=cadence_key,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
            basis=basis,
        )
        == wsds._CADENCE_COMMITTED
    )


def test_authenticated_cadence_cas_is_monotonic_and_equal_event_conflicts_fail_closed() -> None:
    client = StatefulRedis()
    now_ns = wsds.datetime_epoch_ns(datetime.now(UTC))
    newer = _basis_ending_at(now_ns - 1_000_000)
    older = _basis_ending_at(now_ns - 2_000_000)
    conflicting = dict(newer)
    conflicting["max_arrival_lag_ns"] += 1
    unsigned = {key: value for key, value in conflicting.items() if key != "signature"}
    signature = wsds._cadence_signature("configured-key", unsigned)
    assert signature is not None
    conflicting["signature"] = signature
    cadence_key = _cadence_key()

    def persist(basis: dict[str, Any]) -> str:
        return wsds._atomic_persist_authenticated_cadence_basis(
            client,
            key=cadence_key,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
            basis=basis,
        )

    assert persist(newer) == wsds._CADENCE_COMMITTED
    assert persist(newer) == wsds._CADENCE_CURRENT
    assert persist(older) == wsds._CADENCE_OLDER
    assert persist(conflicting) == wsds._CADENCE_CONFLICT
    assert (
        wsds._load_authenticated_cadence_basis(
            client,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
        )
        == newer
    )


def test_ws_quote_requires_symbol_received_clock_and_rejects_boolean_nonfinite() -> None:
    observed = datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC)
    valid = _quote(
        "2026-07-20T12:00:00.000000100Z",
        "2026-07-20T12:00:00.000000200Z",
    )
    invalid = (
        {**valid, "symbol_id": ""},
        {**valid, "symbol_id": "OTHER"},
        {**valid, "time_coinapi": None},
        {**valid, "bid_size": True},
        {**valid, "ask_price": math.inf},
        {**valid, "ask_price": 10**400},
        {**valid, "time_coinapi": "2026-07-20T11:59:59Z"},
    )
    for message in invalid:
        assert (
            wsds._snapshot_from_message(
                message,
                observed_at=observed,
                expected_symbol_id="BINANCEFTS_PERP_BTC_USDT",
            )
            is None
        )


@pytest.mark.parametrize(
    "extreme_timestamp",
    (
        "0001-01-01T00:00:00+23:59",
        "9999-12-31T23:59:59-23:59",
    ),
)
def test_ws_quote_rejects_timestamp_utc_normalization_overflow(
    extreme_timestamp: str,
) -> None:
    assert (
        wsds._snapshot_from_message(
            _quote(extreme_timestamp, extreme_timestamp),
            observed_at=datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC),
            expected_symbol_id=COINAPI_SYMBOL_ID,
        )
        is None
    )


def test_ws_accepts_only_canonical_coinapi_symbol_id_field() -> None:
    observed = datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC)
    canonical = _quote(
        "2026-07-20T12:00:00Z",
        "2026-07-20T12:00:00.1Z",
    )
    legacy_alias = dict(canonical)
    legacy_alias["symbol_id_exchange"] = legacy_alias.pop("symbol_id")
    canonical_with_legacy_alias = {
        **canonical,
        "symbol_id_exchange": COINAPI_SYMBOL_ID,
    }

    snapshot = wsds._snapshot_from_message(
        canonical,
        observed_at=observed,
        expected_symbol_id=COINAPI_SYMBOL_ID,
    )
    assert snapshot is not None
    assert snapshot["coinapi_symbol_id"] == COINAPI_SYMBOL_ID
    assert snapshot["coinapi_exchange_id"] == "BINANCEFTS"
    assert snapshot["coinapi_market_type"] == "PERP"
    for rejected in (legacy_alias, canonical_with_legacy_alias):
        assert wsds._message_symbol_id(rejected) == ""
        assert (
            wsds._snapshot_from_message(
                rejected,
                observed_at=observed,
                expected_symbol_id=COINAPI_SYMBOL_ID,
            )
            is None
        )


def test_ws_snapshot_preserves_submillisecond_event_and_uses_spread_bps() -> None:
    snapshot = wsds._snapshot_from_message(
        _quote(
            "2026-07-20T12:00:00.000000100Z",
            "2026-07-20T12:00:00.000000200Z",
            bid_size=0,
            ask_size=0,
        ),
        observed_at=datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC),
        expected_symbol_id="BINANCEFTS_PERP_BTC_USDT",
    )
    assert snapshot is not None
    assert snapshot["source_event_ts_ns"] == 1_784_548_800_000_000_100
    assert snapshot["microprice"] is None
    assert snapshot["imbalance_5"] is None
    assert snapshot["spread_bps"] > 0
    assert "spread" not in snapshot
    event = wsds.parse_provider_timestamp(snapshot["source_event_time"])
    received = wsds.parse_provider_timestamp(snapshot["provider_received_time"])
    observed = wsds.parse_provider_timestamp(snapshot["observed_at"])
    ingested = wsds.parse_provider_timestamp(snapshot["ingested_at"])
    generated = wsds.parse_provider_timestamp(snapshot["generated_at"])
    assert event and received and observed and ingested and generated
    assert event[1] <= received[1] <= observed[1] < ingested[1] < generated[1]


def test_ws_book_requires_level_ordering() -> None:
    base: dict[str, object] = {
        "type": "book5",
        "symbol_id": "BINANCEFTS_PERP_BTC_USDT",
        "time_exchange": "2026-07-20T12:00:00Z",
        "time_coinapi": "2026-07-20T12:00:00.1Z",
        "bids": [{"price": 100, "size": 1}, {"price": 99, "size": 1}],
        "asks": [{"price": 101, "size": 1}, {"price": 102, "size": 1}],
    }
    observed = datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC)
    assert (
        wsds._snapshot_from_message(
            base,
            observed_at=observed,
            expected_symbol_id="BINANCEFTS_PERP_BTC_USDT",
        )
        is not None
    )
    for message in (
        {**base, "bids": [{"price": 99, "size": 1}, {"price": 100, "size": 1}]},
        {**base, "asks": [{"price": 102, "size": 1}, {"price": 101, "size": 1}]},
    ):
        assert (
            wsds._snapshot_from_message(
                message,
                observed_at=observed,
                expected_symbol_id="BINANCEFTS_PERP_BTC_USDT",
            )
            is None
        )


def test_two_session_commits_cannot_self_authorize_cadence_or_current_health(
    tmp_path: Path,
) -> None:
    event_one = _quote(
        "2026-07-19T00:00:00.000000100Z",
        "2026-07-19T00:00:00.000000200Z",
    )
    older = _quote(
        "2026-07-19T00:00:00.000000050Z",
        "2026-07-19T00:00:00.000000060Z",
    )
    event_two = _quote(
        "2026-07-19T00:00:00.000000900Z",
        "2026-07-19T00:00:00.000001000Z",
    )
    clockless = {**event_one, "time_coinapi": None}
    stats, paths, client = _run_fake_session(
        tmp_path,
        [clockless, event_one, event_one, older, event_two],
    )
    status = json.loads(paths[0].read_text())

    assert stats["selected_messages_observed"] == 5
    assert stats["schema_rejected_messages"] == 1
    assert stats["schema_valid_messages"] == 4
    assert stats["committed_messages"] == 2
    assert stats["duplicate_messages_rejected"] == 1
    assert stats["older_messages_rejected"] == 1
    assert stats["receipt_accepted_messages"] == 0
    assert stats["symbol_health"]["BTCUSDT"]["committed_count"] == 2
    assert stats["symbol_health"]["BTCUSDT"]["cadence_ready"] is False
    assert stats["symbol_health"]["BTCUSDT"]["fresh"] is False
    assert stats["current_data_redis_ack"] is False
    assert stats["last_snapshot_utc"] is not None
    assert status["stream_admission_ready"] is False
    assert status["trainer_consumable"] is False
    assert status["live_decision_input_enabled"] is False
    all_keys = (
        list(client.values)
        + list(client.fences)
        + list(client.cadence_records)
        + list(client.conflicts)
    )
    assert all(key.startswith("v2:quarantine:coinapi:") for key in all_keys)
    assert not any("v2:features:" in key or "v2:market:" in key for key in all_keys)
    assert _cadence_key() not in client.cadence_records


def test_authenticated_cadence_is_learned_cold_and_only_used_by_later_session(
    tmp_path: Path,
) -> None:
    client = StatefulRedis()

    def live_quote() -> dict[str, object]:
        event_ns = wsds.datetime_epoch_ns(datetime.now(UTC))
        return _quote_ns(event_ns, received_lag_ns=0)

    def training_quote() -> dict[str, object]:
        message = live_quote()
        time.sleep(0.005)
        return message

    first, first_paths, _ = _run_fake_session(
        tmp_path / "first",
        [training_quote, training_quote, training_quote],
        redis_client=client,
    )
    first_status = json.loads(first_paths[0].read_text())
    cadence_key = _cadence_key()

    assert first["committed_messages"] == 3
    assert first["cadence_bases_persisted"] == 1
    assert first["cadence_bootstrap_session_rotation_requested"] is True
    assert first["authenticated_cadence_bases_loaded"] == 0
    assert first["symbol_health"]["BTCUSDT"]["cadence_ready"] is False
    assert first_status["stream_admission_ready"] is False
    stored_basis = json.loads(client.cadence_records[cadence_key]["payload"])
    assert (
        wsds._validated_cadence_basis(
            stored_basis,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
        )
        is not None
    )

    second, second_paths, _ = _run_fake_session(
        tmp_path / "second",
        [live_quote],
        redis_client=client,
    )
    second_status = json.loads(second_paths[0].read_text())

    assert second["authenticated_cadence_bases_loaded"] == 1
    assert second["fresh_messages"] == 1
    assert second["current_data_redis_ack"] is True
    assert second["symbol_health"]["BTCUSDT"]["cadence_basis_authenticated"] is True
    assert second_status["stream_admission_ready"] is True
    assert second_status["current_data_commit_acked"] is True


def test_stale_replay_cannot_bootstrap_authenticated_cadence(tmp_path: Path) -> None:
    now_ns = wsds.datetime_epoch_ns(datetime.now(UTC))
    stale_events = (now_ns - 30_000_000, now_ns - 20_000_000, now_ns - 10_000_000)
    stats, _paths, client = _run_fake_session(
        tmp_path,
        [_quote_ns(event_ns) for event_ns in stale_events],
    )

    assert stats["committed_messages"] == 3
    assert stats["cadence_bases_persisted"] == 0
    assert stats["current_data_redis_ack"] is False
    assert _cadence_key() not in client.cadence_records


def test_cadence_basis_hmac_and_redis_read_types_fail_closed() -> None:
    now_ns = wsds.datetime_epoch_ns(datetime.now(UTC))
    basis = _basis_ending_at(now_ns - 20_000_000)
    cadence_key = _cadence_key()
    client = StatefulRedis()
    assert (
        wsds._atomic_persist_authenticated_cadence_basis(
            client,
            key=cadence_key,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
            basis=basis,
        )
        == wsds._CADENCE_COMMITTED
    )
    assert (
        wsds._load_authenticated_cadence_basis(
            client,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
        )
        == basis
    )

    tampered = dict(basis)
    tampered["event_cadence_ns"] += 1
    client.cadence_records[cadence_key]["payload"] = json.dumps(tampered)
    assert (
        wsds._load_authenticated_cadence_basis(
            client,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
        )
        is None
    )
    assert (
        wsds._validated_cadence_basis(
            basis,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="wrong-key",
        )
        is None
    )

    class InexactRedis:
        def eval(self, script: str, numkeys: int, *args: object) -> object:
            del script, numkeys, args
            return (wsds._STATE_READ_OK, "1", "{}")

        def pttl(self, key: str) -> object:
            del key
            return True

    assert wsds._read_persistent_cadence_payload(InexactRedis(), cadence_key) is None
    assert (
        wsds._safe_pttl_ms(
            InexactRedis(),
            _data_key(),
        )
        is None
    )


def test_one_committed_sample_remains_cold_and_last_snapshot_needs_commit(
    tmp_path: Path,
) -> None:
    invalid = _quote(
        "2026-07-19T00:00:00Z",
        "2026-07-19T00:00:00.1Z",
        bid_size=True,
    )
    valid = _quote(
        "2026-07-19T00:00:00.000000100Z",
        "2026-07-19T00:00:00.000000200Z",
    )
    stats, paths, _client = _run_fake_session(
        tmp_path,
        [invalid, valid],
    )
    status = json.loads(paths[0].read_text())
    assert stats["committed_messages"] == 1
    assert stats["last_snapshot_utc"] is not None
    assert stats["symbol_health"]["BTCUSDT"]["cadence_ready"] is False
    assert status["stream_admission_ready"] is False
    assert status["service_healthy"] is True
    assert status["publication_healthy"] is False

    class FailingRedis(StatefulRedis):
        def eval(self, *args: object) -> object:
            del args
            raise RuntimeError("redis unavailable")

    failed, _paths, _client = _run_fake_session(
        tmp_path / "failed",
        [valid],
        redis_client=FailingRedis(),
    )
    assert failed["schema_valid_messages"] == 1
    assert failed["committed_messages"] == 0
    assert failed["last_snapshot_utc"] is None
    assert failed["redis_write_failures"] >= 1


def test_one_symbol_cannot_make_multisymbol_stream_globally_usable(tmp_path: Path) -> None:
    first = _quote(
        "2026-07-19T00:00:00.000000100Z",
        "2026-07-19T00:00:00.000000200Z",
    )
    second = _quote(
        "2026-07-19T00:00:00.000000900Z",
        "2026-07-19T00:00:00.000001000Z",
    )
    stats, paths, _client = _run_fake_session(
        tmp_path,
        [first, second],
        symbols=("BTCUSDT", "ETHUSDT"),
    )
    status = json.loads(paths[0].read_text())
    assert stats["symbol_health"]["BTCUSDT"]["cadence_ready"] is False
    assert stats["symbol_health"]["ETHUSDT"]["observed"] is False
    assert status["stream_admission_ready"] is False
    assert status["all_subscribed_symbols_covered"] is False
    assert status["provider_data_usable"] is False


def test_conflict_is_quarantined_without_baseline_or_ttl_refresh(tmp_path: Path) -> None:
    first = _quote(
        "2026-07-19T00:00:00.000000100Z",
        "2026-07-19T00:00:00.000000200Z",
    )
    conflict = {**first, "bid_price": 99}
    stats, _paths, client = _run_fake_session(
        tmp_path,
        [first, conflict],
    )
    key = _data_key()
    assert stats["committed_messages"] == 1
    assert stats["conflicting_messages_quarantined"] == 1
    assert stats["symbol_health"]["BTCUSDT"]["committed_count"] == 1
    assert stats["symbol_health"]["BTCUSDT"]["fresh"] is False
    assert stats["current_data_redis_ack"] is False
    assert client.expiry_refreshes[key] == 1
    assert len(client.conflicts) == 1


@pytest.mark.parametrize("rejection", ("duplicate", "older", "conflict"))
def test_duplicate_older_or_conflict_clears_current_ack_and_freshness(
    tmp_path: Path,
    rejection: str,
) -> None:
    client = StatefulRedis()
    now_ns = wsds.datetime_epoch_ns(datetime.now(UTC))
    basis = _basis_ending_at(now_ns - 30_000_000)
    cadence_key = _cadence_key()
    assert (
        wsds._atomic_persist_authenticated_cadence_basis(
            client,
            key=cadence_key,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
            basis=basis,
        )
        == wsds._CADENCE_COMMITTED
    )
    current: dict[str, Any] = {}

    def first() -> dict[str, object]:
        event_ns = wsds.datetime_epoch_ns(datetime.now(UTC))
        message = _quote_ns(event_ns, received_lag_ns=0)
        current["event_ns"] = event_ns
        current["message"] = message
        return message

    def rejected() -> dict[str, object]:
        event_ns = int(current["event_ns"])
        message = current["message"]
        assert isinstance(message, dict)
        if rejection == "duplicate":
            return dict(message)
        if rejection == "older":
            return _quote_ns(event_ns - 1, received_lag_ns=0)
        return _quote_ns(event_ns, received_lag_ns=0, bid=99)

    stats, paths, _ = _run_fake_session(
        tmp_path,
        [first, rejected],
        redis_client=client,
    )
    status = json.loads(paths[0].read_text())

    assert stats["committed_messages"] == 1
    assert stats["fresh_messages"] == 1
    assert stats["current_data_redis_ack"] is False
    assert stats["symbol_health"]["BTCUSDT"]["fresh"] is False
    assert stats["symbol_health"]["BTCUSDT"]["committed"] is False
    assert status["stream_admission_ready"] is False
    if rejection == "duplicate":
        assert stats["duplicate_messages_rejected"] == 1
    elif rejection == "older":
        assert stats["older_messages_rejected"] == 1
    else:
        assert stats["conflicting_messages_quarantined"] == 1


def test_expired_payload_clears_current_health_while_persistent_fence_blocks_rollback() -> None:
    client = StatefulRedis()
    data_key = _data_key()
    fence_key = _fence_key()
    payload = _raw_ws_payload(200)
    digest = wsds._provider_content_digest(payload)
    assert digest is not None
    first = wsds._atomic_fenced_quarantine_write(
        client,
        fence_key=fence_key,
        data_key=data_key,
        conflict_key=_conflict_key(200, digest),
        event_identity_ns="200",
        payload=payload,
        ex=60,
    )
    assert first == (wsds._FENCE_COMMITTED, 60_000)
    client.payload_ttls_ms[data_key] = -2
    older_payload = _raw_ws_payload(199, bid=99.0)
    older_digest = wsds._provider_content_digest(older_payload)
    assert older_digest is not None
    older = wsds._atomic_fenced_quarantine_write(
        client,
        fence_key=fence_key,
        data_key=data_key,
        conflict_key=_conflict_key(199, older_digest),
        event_identity_ns="199",
        payload=older_payload,
        ex=60,
    )
    assert older == (wsds._FENCE_OLDER, -2)
    assert client.fences[fence_key]["event"] == "200"

    now_ns = wsds.datetime_epoch_ns(datetime.now(UTC))
    basis = _basis_ending_at(now_ns - 30_000_000)
    health = wsds._initial_symbol_health(("BTCUSDT",), {"BTCUSDT": basis})
    state = health["BTCUSDT"]
    event_ns = now_ns - 2_000_000
    assert wsds._record_committed_event(
        state,
        cadence_basis=basis,
        session_anchor_ns=event_ns - 1,
        event_ns=event_ns,
        provider_received_ns=event_ns + 100_000,
        observed_ns=now_ns,
        data_key=data_key,
        payload_ttl_ms=60_000,
    )
    assert (
        wsds._refresh_current_health(
            ("BTCUSDT",),
            health,
            client,
            now_ns=now_ns,
        )
        is False
    )
    assert state["fresh"] is False
    assert state["current_health_reason"] == "CURRENT_PAYLOAD_TTL_NOT_POSITIVE"


def test_ws_atomic_fence_recovers_on_newer_event_after_payload_ttl_expiry() -> None:
    client = StatefulRedis()
    data_key = _data_key()
    fence_key = _fence_key()

    def write(event: int) -> tuple[str, int]:
        payload = _raw_ws_payload(event, bid=float(event))
        digest = wsds._provider_content_digest(payload)
        assert digest is not None
        return wsds._atomic_fenced_quarantine_write(
            client,
            fence_key=fence_key,
            data_key=data_key,
            conflict_key=_conflict_key(event, digest),
            event_identity_ns=str(event),
            payload=payload,
            ex=60,
        )

    assert write(100) == (wsds._FENCE_COMMITTED, 60_000)
    client.values.pop(data_key)
    client.payload_ttls_ms.pop(data_key)

    assert fence_key in client.fences
    assert write(101) == (wsds._FENCE_COMMITTED, 60_000)
    assert data_key in client.values
    assert client.expiry_refreshes[data_key] == 2


def test_receive_timeout_tracks_adaptive_age_and_payload_ttl_deadlines() -> None:
    health = wsds._initial_symbol_health(("BTCUSDT",))
    state = health["BTCUSDT"]
    now_ns = wsds.datetime_epoch_ns(datetime.now(UTC))
    state.update(
        {
            "current_candidate_fresh": True,
            "current_event_ns": now_ns - 90_000_000,
            "freshness_budget_ns": 100_000_000,
            "current_payload_ttl_ms": 5,
        }
    )

    timeout = wsds._adaptive_receive_timeout_seconds(
        ("BTCUSDT",),
        health,
        heartbeat_interval_seconds=10.0,
        now_ns=now_ns,
    )
    assert 0 < timeout <= 0.005
    wsds._clear_current_health(state, "TEST")
    assert (
        wsds._adaptive_receive_timeout_seconds(
            ("BTCUSDT",),
            health,
            heartbeat_interval_seconds=10.0,
            now_ns=now_ns,
        )
        == 10.0
    )


def test_current_health_recovers_despite_cumulative_write_failures() -> None:
    symbol_health = {
        "BTCUSDT": {
            "observed": True,
            "schema_valid": True,
            "coverage": True,
            "fresh": True,
            "committed": True,
            "receipt_present": False,
            "cadence_ready": True,
        }
    }
    payload = wsds._base_status(
        symbols=("BTCUSDT",),
        subscribed_symbols=("BTCUSDT",),
        opt_in=True,
        credential_present=True,
        redis_ok=True,
        stream_connected=True,
        classification="READY",
        blocker=None,
        stats={"redis_write_failures": 999},
        data_types=["quote"],
        ws_url=wsds.DEFAULT_WS_URL,
        symbol_health=symbol_health,
    )
    assert payload["publication_healthy"] is True
    assert payload["service_healthy"] is True
    assert payload["stream_admission_ready"] is True


def test_redis_availability_cannot_claim_current_data_without_stream_admission() -> None:
    payload = wsds._base_status(
        symbols=("BTCUSDT",),
        subscribed_symbols=(),
        opt_in=True,
        credential_present=True,
        redis_ok=True,
        stream_connected=False,
        classification="OPTIONAL_BACKOFF",
        blocker="AWAITING_DURABLE_OPTIONAL_REPROBE_WINDOW",
        stats={},
        data_types=["quote"],
        ws_url=wsds.DEFAULT_WS_URL,
        symbol_health=wsds._initial_symbol_health(("BTCUSDT",)),
    )
    assert payload["service_healthy"] is True
    assert payload["stream_admission_ready"] is False
    assert payload["current_data_commit_acked"] is False
    assert payload["publication_healthy"] is False


def test_terminal_403_persists_sparse_retry_state_and_has_no_subscription(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    async def fake_run_session(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        del kwargs
        calls += 1
        return {
            "sessions": 1,
            "messages_received": 0,
            "schema_valid_messages": 0,
            "committed_messages": 0,
            "redis_write_failures": 0,
            "current_data_redis_ack": False,
            "provider_health": {
                "provider_http_status": 403,
                "provider_error_class": "ENTITLEMENT_REJECTED",
                "last_close_code": 1008,
                "last_close_reason_class": "ENTITLEMENT_REJECTED",
                "quota_metadata": {},
            },
        }

    monkeypatch.delenv("COINAPI_WSDS_URL", raising=False)
    monkeypatch.setattr(wsds, "_run_session", fake_run_session)
    args = SimpleNamespace(
        out=tmp_path / "status.json",
        out_public=tmp_path / "public.json",
        out_worklog=tmp_path / "worklog.json",
        total_seconds=0.01,
        ttl_seconds=60,
        max_symbols=1,
        max_seconds_per_session=10.0,
        max_messages_per_session=10,
        heartbeat_interval_seconds=1.0,
    )
    redis_client = StatefulRedis()
    asyncio.run(wsds._run_connected_loop(args, ("BTCUSDT",), "key", redis_client))
    payload = json.loads(args.out.read_text())
    assert calls == 1
    assert payload["classification"] == "V2_COINAPI_WSDS_OPTIONAL_AUTH_UNAVAILABLE"
    assert payload["subscribed_symbols"] == []
    assert payload["live_data_enabled"] is False
    assert payload["live_decision_input_enabled"] is False
    assert wsds._load_auth_state(redis_client, api_key="key") is not None
    asyncio.run(wsds._run_connected_loop(args, ("BTCUSDT",), "key", redis_client))
    assert calls == 1


def test_terminal_quota_without_http_status_survives_restart_and_recovers_on_reprobe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    recovered = False

    async def fake_run_session(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        del kwargs
        calls += 1
        await asyncio.sleep(0.002)
        if not recovered:
            return {
                "sessions": 1,
                "messages_received": 0,
                "real_messages_received": 0,
                "schema_valid_messages": 0,
                "committed_messages": 0,
                "redis_write_failures": 0,
                "current_data_redis_ack": False,
                "transport_connected": True,
                "authenticated_transport_succeeded": False,
                "provider_health": {
                    "provider_http_status": None,
                    "provider_error_class": "QUOTA_OR_SUBSCRIPTION_EXHAUSTED",
                    "last_close_code": 1008,
                    "last_close_reason_class": "QUOTA_OR_SUBSCRIPTION_EXHAUSTED",
                    "quota_metadata": {},
                },
            }
        return {
            "sessions": 1,
            "messages_received": 1,
            "real_messages_received": 1,
            "schema_valid_messages": 1,
            "committed_messages": 1,
            "redis_write_failures": 0,
            "current_data_redis_ack": True,
            "stream_admission_ready": True,
            "transport_connected": True,
            "authenticated_transport_succeeded": True,
            "provider_health": {},
        }

    monkeypatch.delenv("COINAPI_SUBSCRIBE_DATA_TYPES", raising=False)
    monkeypatch.delenv("COINAPI_WSDS_URL", raising=False)
    monkeypatch.delenv("COINAPI_PRIMARY_EXCHANGE_ID", raising=False)
    monkeypatch.setattr(wsds, "_run_session", fake_run_session)
    args = _connected_args(tmp_path, total_seconds=0.001)
    first_process = StatefulRedis()

    asyncio.run(wsds._run_connected_loop(args, ("BTCUSDT",), "key", first_process))
    first_status = json.loads(args.out.read_text())
    state = wsds._load_auth_state(first_process, api_key="key")

    assert calls == 1
    assert first_status["classification"] == "V2_COINAPI_WSDS_OPTIONAL_AUTH_UNAVAILABLE"
    assert state is not None
    assert state["last_http_status"] is None
    assert state["last_error_class"] == "QUOTA_OR_SUBSCRIPTION_EXHAUSTED"
    assert state["next_probe_at_ns"] > state["revision_ns"]
    assert "key" not in json.dumps(state, sort_keys=True)

    auth_key = wsds._auth_latch_key("key")
    assert auth_key is not None
    restarted_process = StatefulRedis()
    restarted_process.auth_records[auth_key] = dict(first_process.auth_records[auth_key])
    restarted_process.payload_ttls_ms[auth_key] = -1
    asyncio.run(wsds._run_connected_loop(args, ("BTCUSDT",), "key", restarted_process))
    assert calls == 1

    expired = wsds._build_auth_state(
        api_key="key",
        http_status=None,
        error_class="QUOTA_OR_SUBSCRIPTION_EXHAUSTED",
        prior_state=None,
        quota_metadata=None,
        now_ns=0,
    )
    assert expired is not None
    expired_payload = wsds._canonical_json(expired)
    assert expired_payload is not None
    restarted_process.auth_records[auth_key] = {
        "revision_ns": "0",
        "payload": expired_payload,
    }
    restarted_process.payload_ttls_ms[auth_key] = -1
    recovered = True

    asyncio.run(wsds._run_connected_loop(args, ("BTCUSDT",), "key", restarted_process))

    assert calls == 2
    assert wsds._load_auth_state(restarted_process, api_key="key") is None
    assert auth_key not in restarted_process.auth_records


def test_connected_zero_data_uses_durable_sparse_reprobe_across_restarts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    async def fake_run_session(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        del kwargs
        calls += 1
        return {
            "sessions": 1,
            "messages_received": 0,
            "real_messages_received": 0,
            "schema_valid_messages": 0,
            "committed_messages": 0,
            "redis_write_failures": 0,
            "current_data_redis_ack": False,
            "transport_connected": True,
            "authenticated_transport_succeeded": False,
            "provider_health": {},
        }

    monkeypatch.delenv("COINAPI_WSDS_URL", raising=False)
    monkeypatch.setattr(wsds, "_run_session", fake_run_session)
    args = SimpleNamespace(
        out=tmp_path / "status.json",
        out_public=tmp_path / "public.json",
        out_worklog=tmp_path / "worklog.json",
        total_seconds=0.01,
        ttl_seconds=60,
        max_symbols=1,
        max_seconds_per_session=10.0,
        max_messages_per_session=10,
        heartbeat_interval_seconds=1.0,
    )
    client = StatefulRedis()
    asyncio.run(wsds._run_connected_loop(args, ("BTCUSDT",), "key", client))
    first_payload = json.loads(args.out.read_text())
    assert calls == 1
    assert first_payload["classification"] == "V2_COINAPI_WSDS_OPTIONAL_CONNECTED_NO_DATA"
    state = wsds._load_auth_state(client, api_key="key")
    assert state is not None
    assert state["last_error_class"] == "CONNECTED_NO_DATA"

    asyncio.run(wsds._run_connected_loop(args, ("BTCUSDT",), "key", client))
    assert calls == 1


@pytest.mark.parametrize("fault", ("exists", "read"))
def test_indeterminate_durable_auth_state_blocks_before_ws_session(
    tmp_path: Path,
    monkeypatch,
    fault: str,
) -> None:
    calls = 0

    class IndeterminateRedis(StatefulRedis):
        def exists(self, key: str) -> int:
            if fault == "exists":
                del key
                raise RuntimeError("durable state read unavailable")
            return 1

        def eval(self, script: str, numkeys: int, *args: object) -> list[object]:
            if fault == "read" and "COINAPI_BOUNDED_PERSISTENT_HASH_READ_V1" in script:
                raise RuntimeError("durable state read unavailable")
            return super().eval(script, numkeys, *args)

    async def forbidden_session(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        del kwargs
        calls += 1
        raise AssertionError("WS session must not open")

    monkeypatch.delenv("COINAPI_WSDS_URL", raising=False)
    monkeypatch.delenv("COINAPI_PRIMARY_EXCHANGE_ID", raising=False)
    monkeypatch.setattr(wsds, "_run_session", forbidden_session)
    args = SimpleNamespace(
        out=tmp_path / "status.json",
        out_public=tmp_path / "public.json",
        out_worklog=tmp_path / "worklog.json",
        total_seconds=0.01,
        ttl_seconds=60,
        max_symbols=1,
        max_seconds_per_session=10.0,
        max_messages_per_session=10,
        heartbeat_interval_seconds=1.0,
    )

    aggregate = asyncio.run(
        wsds._run_connected_loop(args, ("BTCUSDT",), "key", IndeterminateRedis())
    )
    payload = json.loads(args.out.read_text())

    assert calls == 0
    assert aggregate["durable_auth_retry_state_healthy"] is False
    assert payload["classification"] == "V2_COINAPI_WSDS_OPTIONAL_RETRY_STATE_UNAVAILABLE"
    assert payload["blocked_reason"] == (
        "DURABLE_RETRY_STATE_UNAVAILABLE" if fault == "exists" else "DURABLE_RETRY_STATE_INVALID"
    )
    assert payload["provider_health"]["typed_missing"] is True
    assert payload["trainer_consumable"] is False
    assert payload["live_decision_input_enabled"] is False


def test_dormant_loop_reresolves_prerequisites_and_transitions_without_busy_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = False
    credential = ""
    sleeps: list[float] = []
    redis_calls = 0
    secret_reads = 0
    endpoint_reads = 0
    exchange_reads = 0
    connected: list[tuple[str, Any, str | None, str | None]] = []
    redis_clients = [StatefulRedis(), StatefulRedis()]
    original_getenv = wsds.os.getenv

    def fake_opt_in(name: str, default: bool = False) -> bool:
        return ready if name == wsds.OPT_IN_ENV_VAR else default

    def fake_secret(name: str) -> str:
        nonlocal secret_reads
        assert name in {"COINAPI_API_KEY", "COINAPI_KEY"}
        secret_reads += 1
        return credential if ready and name == "COINAPI_API_KEY" else ""

    def fake_connect_redis() -> StatefulRedis | None:
        nonlocal redis_calls
        redis_calls += 1
        if not ready:
            return None
        return redis_clients[min(redis_calls - 2, len(redis_clients) - 1)]

    def tracked_getenv(name: str, default: str | None = None) -> str | None:
        nonlocal endpoint_reads, exchange_reads
        if name == "COINAPI_WSDS_URL":
            endpoint_reads += 1
        elif name == "COINAPI_PRIMARY_EXCHANGE_ID":
            exchange_reads += 1
        value = original_getenv(name, default)
        return value if type(value) is str else default

    def fake_sleep(seconds: float) -> None:
        nonlocal credential, ready
        sleeps.append(seconds)
        ready = True
        credential = "first-key" if len(sleeps) == 1 else "renewed-key"
        wsds.os.environ["COINAPI_PRIMARY_EXCHANGE_ID"] = (
            "BINANCEFTS" if len(sleeps) == 1 else "COINBASE"
        )

    async def fake_connected_loop(
        args: SimpleNamespace,
        symbols: tuple[str, ...],
        api_key: str,
        connected_redis: Any,
    ) -> dict[str, Any]:
        assert symbols == ("BTCUSDT",)
        connected.append(
            (
                api_key,
                connected_redis,
                wsds.os.environ.get("COINAPI_WSDS_URL"),
                wsds.os.environ.get("COINAPI_PRIMARY_EXCHANGE_ID"),
            )
        )
        if len(connected) == 2:
            args.loop = False
        return {"sessions": len(connected)}

    monkeypatch.setenv("COINAPI_WSDS_URL", wsds.DEFAULT_WS_URL)
    monkeypatch.setenv("COINAPI_PRIMARY_EXCHANGE_ID", "BINANCEFTS")
    monkeypatch.setattr(wsds, "websockets", object())
    monkeypatch.setattr(wsds, "_env_bool", fake_opt_in)
    monkeypatch.setattr(wsds, "_read_secret_value", fake_secret)
    monkeypatch.setattr(wsds, "_connect_redis", fake_connect_redis)
    monkeypatch.setattr(wsds.os, "getenv", tracked_getenv)
    monkeypatch.setattr(wsds.time, "sleep", fake_sleep)
    monkeypatch.setattr(wsds, "_run_connected_loop", fake_connected_loop)
    args = SimpleNamespace(
        out=tmp_path / "status.json",
        out_public=tmp_path / "public.json",
        out_worklog=tmp_path / "worklog.json",
        loop=True,
        interval_seconds=1,
        ttl_seconds=60,
    )

    aggregate = wsds._run_blocked_loop(args, ("BTCUSDT",))

    assert aggregate == {"sessions": 2}
    assert sleeps == [30, 30]
    assert redis_calls == 3
    assert secret_reads >= 4
    assert endpoint_reads == 3
    assert exchange_reads == 3
    assert connected == [
        ("first-key", redis_clients[0], wsds.DEFAULT_WS_URL, "BINANCEFTS"),
        ("renewed-key", redis_clients[1], wsds.DEFAULT_WS_URL, "COINBASE"),
    ]


def test_ws_subscription_types_use_an_exact_feature_gated_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "COINAPI_SUBSCRIBE_DATA_TYPES",
        "COINAPI_ALLOW_TRADE",
        "COINAPI_ALLOW_FULL_BOOK",
    ):
        monkeypatch.delenv(name, raising=False)
    assert wsds._subscribe_data_types() == ["quote", "book5"]

    for rejected in (
        "Quote,book5",
        "quote,BOOK5",
        "quote,orderbook",
        "quote,book20",
        "quote,trade",
        "quote,book",
    ):
        monkeypatch.setenv("COINAPI_SUBSCRIBE_DATA_TYPES", rejected)
        assert wsds._subscribe_data_types() is None

    monkeypatch.setenv("COINAPI_ALLOW_TRADE", "true")
    monkeypatch.setenv("COINAPI_ALLOW_FULL_BOOK", "true")
    monkeypatch.setenv("COINAPI_SUBSCRIBE_DATA_TYPES", "trade,book,quote,trade")
    assert wsds._subscribe_data_types() == ["trade", "book", "quote"]


def test_invalid_ws_subscription_type_is_typed_before_session_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def forbidden_session(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        del kwargs
        calls += 1
        raise AssertionError("WS session must not open")

    monkeypatch.setenv("COINAPI_SUBSCRIBE_DATA_TYPES", "quote,orderbook")
    monkeypatch.delenv("COINAPI_WSDS_URL", raising=False)
    monkeypatch.delenv("COINAPI_PRIMARY_EXCHANGE_ID", raising=False)
    monkeypatch.setattr(wsds, "_run_session", forbidden_session)
    args = _connected_args(tmp_path)

    aggregate = asyncio.run(wsds._run_connected_loop(args, ("BTCUSDT",), "key", StatefulRedis()))
    payload = json.loads(args.out.read_text())

    assert calls == 0
    assert aggregate["configuration_valid"] is False
    assert payload["classification"] == "V2_COINAPI_WSDS_OPTIONAL_CONFIGURATION_INVALID"
    assert payload["provider_health"]["provider_error_class"] == ("INVALID_SUBSCRIPTION_DATA_TYPES")
    assert payload["trainer_consumable"] is False


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    (
        ("heartbeat_interval_seconds", math.nan, "INVALID_HEARTBEAT_INTERVAL_SECONDS"),
        ("heartbeat_interval_seconds", 0.0, "INVALID_HEARTBEAT_INTERVAL_SECONDS"),
        (
            "heartbeat_interval_seconds",
            wsds.MAX_WS_HEARTBEAT_SECONDS + 1.0,
            "INVALID_HEARTBEAT_INTERVAL_SECONDS",
        ),
        (
            "heartbeat_interval_seconds",
            31.0,
            "HEARTBEAT_INTERVAL_EXCEEDS_HALF_TTL",
        ),
        ("max_seconds_per_session", math.inf, "INVALID_MAX_SECONDS_PER_SESSION"),
        ("max_seconds_per_session", 0.0, "INVALID_MAX_SECONDS_PER_SESSION"),
        (
            "max_seconds_per_session",
            wsds.MAX_WS_RUNTIME_SECONDS + 1.0,
            "INVALID_MAX_SECONDS_PER_SESSION",
        ),
        ("total_seconds", -math.inf, "INVALID_TOTAL_SECONDS"),
        ("total_seconds", 0.0, "INVALID_TOTAL_SECONDS"),
        ("total_seconds", wsds.MAX_WS_RUNTIME_SECONDS + 1.0, "INVALID_TOTAL_SECONDS"),
    ),
)
def test_invalid_ws_timeout_config_is_typed_before_session_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: float,
    expected_error: str,
) -> None:
    calls = 0

    async def forbidden_session(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        del kwargs
        calls += 1
        raise AssertionError("WS session must not open")

    monkeypatch.delenv("COINAPI_SUBSCRIBE_DATA_TYPES", raising=False)
    monkeypatch.delenv("COINAPI_ALLOW_TRADE", raising=False)
    monkeypatch.delenv("COINAPI_ALLOW_FULL_BOOK", raising=False)
    monkeypatch.delenv("COINAPI_WSDS_URL", raising=False)
    monkeypatch.delenv("COINAPI_PRIMARY_EXCHANGE_ID", raising=False)
    monkeypatch.setattr(wsds, "_run_session", forbidden_session)
    args = _connected_args(tmp_path, **{field: value})

    aggregate = asyncio.run(wsds._run_connected_loop(args, ("BTCUSDT",), "key", StatefulRedis()))
    payload = json.loads(args.out.read_text())

    assert calls == 0
    assert aggregate["configuration_valid"] is False
    assert payload["classification"] == "V2_COINAPI_WSDS_OPTIONAL_CONFIGURATION_INVALID"
    assert payload["provider_health"]["provider_error_class"] == expected_error
    assert payload["trainer_consumable"] is False


def test_malformed_optional_exchange_config_is_typed_and_never_opens_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    async def forbidden_session(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        del kwargs
        calls += 1
        raise AssertionError("WS session must not open")

    monkeypatch.setenv("COINAPI_PRIMARY_EXCHANGE_ID", "binancefts:evil")
    monkeypatch.delenv("COINAPI_WSDS_URL", raising=False)
    monkeypatch.setattr(wsds, "_run_session", forbidden_session)
    args = SimpleNamespace(
        out=tmp_path / "status.json",
        out_public=tmp_path / "public.json",
        out_worklog=tmp_path / "worklog.json",
        total_seconds=0.01,
        ttl_seconds=60,
        max_symbols=1,
        max_seconds_per_session=10.0,
        max_messages_per_session=10,
        heartbeat_interval_seconds=1.0,
    )

    aggregate = asyncio.run(wsds._run_connected_loop(args, ("BTCUSDT",), "key", StatefulRedis()))
    payload = json.loads(args.out.read_text())

    assert calls == 0
    assert aggregate["configuration_valid"] is False
    assert payload["classification"] == "V2_COINAPI_WSDS_OPTIONAL_CONFIGURATION_INVALID"
    assert payload["provider_health"]["provider_error_class"] == "INVALID_PRIMARY_EXCHANGE_ID"
    assert payload["provider_health"]["typed_missing"] is True
    assert payload["trainer_consumable"] is False


def test_ws_quota_reset_and_committed_only_backoff_semantics() -> None:
    assert (
        wsds._provider_retry_delay_seconds(
            {"rate_limit_reset": 1_699_999_999}, now_epoch=1_700_000_000
        )
        == 0.0
    )
    assert (
        wsds._provider_retry_delay_seconds(
            {"rate_limit_reset": 1_700_000_100}, now_epoch=1_700_000_000
        )
        == 100.0
    )
    assert (
        wsds._provider_retry_delay_seconds(
            {"retry_after_seconds": wsds.AUTH_BACKOFF_MAX_SECONDS * 1000}
        )
        == wsds.AUTH_BACKOFF_MAX_SECONDS
    )
    failures, first = wsds._next_backoff(0, committed_messages=0, random_unit=0.5)
    failures, second = wsds._next_backoff(failures, committed_messages=0, random_unit=0.5)
    reset, delay = wsds._next_backoff(failures, committed_messages=1, random_unit=0.5)
    assert (failures, first, second) == (2, 1.0, 2.0)
    assert (reset, delay) == (0, None)


def test_status_mkdir_failure_is_typed_sanitized_and_nonfatal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_error = "secret mkdir failure marker"

    def fail_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        del self, args, kwargs
        raise PermissionError(raw_error)

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)
    payload: dict[str, Any] = {"classification": "TEST", "stats": {}}
    assert wsds._write_status(payload, (tmp_path / "nested" / "status.json",)) is False
    assert payload["status_file_write_healthy"] is False
    assert payload["status_file_write_error_classes"] == ["PermissionError"]
    assert payload["raw_status_file_error_recorded"] is False
    assert raw_error not in json.dumps(payload, sort_keys=True)


def test_coinapi_wsds_registry_remains_operator_gated_when_key_name_exists(monkeypatch) -> None:
    from v2.backend.app.services.native_ingestors import registry as reg_mod

    monkeypatch.setattr(
        "v2.backend.app.services.native_ingestors.secret_decision.key_name_available",
        lambda name, **kwargs: True,
    )
    cls = reg_mod._classify("live_coinapi_wsds")
    assert cls.classification == "OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN"


def test_ws_deep_json_and_persistent_state_are_bounded_without_recursion_escape() -> None:
    deeply_nested = "[" * 2_000 + "0" + "]" * 2_000
    assert (
        wsds._loads_bounded_json(
            deeply_nested,
            max_bytes=wsds.MAX_WS_MESSAGE_BYTES,
            max_depth=wsds.MAX_WS_JSON_DEPTH,
            max_items=wsds.MAX_WS_JSON_ITEMS,
        )
        is None
    )
    client = StatefulRedis()
    cadence_key = _cadence_key()
    client.cadence_records[cadence_key] = {
        "last_event_ns": "1",
        "payload": deeply_nested,
    }
    client.payload_ttls_ms[cadence_key] = -1
    assert wsds._read_persistent_cadence_payload(client, cadence_key) is None


def test_provisional_cadence_survives_short_sessions_and_never_self_authorizes(
    tmp_path: Path,
) -> None:
    client = StatefulRedis()

    def live_quote() -> dict[str, object]:
        return _quote_ns(wsds.datetime_epoch_ns(datetime.now(UTC)), received_lag_ns=0)

    first, _paths, _ = _run_fake_session(
        tmp_path / "first",
        [live_quote],
        redis_client=client,
    )
    provisional_key = _cadence_key(provisional=True)
    assert first["authenticated_cadence_bases_loaded"] == 0
    assert first["current_data_redis_ack"] is False
    assert first["provisional_cadence_records_persisted"] == 1
    assert provisional_key in client.cadence_records

    second, _paths, _ = _run_fake_session(
        tmp_path / "second",
        [live_quote],
        redis_client=client,
    )
    assert second["authenticated_cadence_bases_loaded"] == 0
    assert second["provisional_cadence_records_loaded"] == 1
    assert second["current_data_redis_ack"] is False

    third, _paths, _ = _run_fake_session(
        tmp_path / "third",
        [live_quote],
        redis_client=client,
    )
    final_key = _cadence_key()
    assert third["authenticated_cadence_bases_loaded"] == 0
    assert third["cadence_bases_persisted"] == 1
    assert third["current_data_redis_ack"] is False
    assert final_key in client.cadence_records
    assert provisional_key not in client.cadence_records

    fourth, _paths, _ = _run_fake_session(
        tmp_path / "fourth",
        [live_quote],
        redis_client=client,
    )
    assert fourth["authenticated_cadence_bases_loaded"] == 1
    assert fourth["symbol_health"]["BTCUSDT"]["cadence_ready"] is True


def test_cadence_estimator_uses_robust_upper_median_not_minimum_delta() -> None:
    samples = [
        (1_000, 1_100, 1_200),
        (2_000, 2_100, 2_200),
        (102_000, 102_100, 102_200),
    ]
    basis = wsds._build_authenticated_cadence_basis(
        samples,
        symbol="BTCUSDT",
        coinapi_symbol_id=COINAPI_SYMBOL_ID,
        api_key="configured-key",
    )
    assert basis is not None
    assert basis["event_cadence_ns"] == 100_000
    assert basis["provider_cadence_ns"] == 100_000
    assert basis["arrival_cadence_ns"] == 100_000


def test_ws_symbol_and_payload_key_injection_fail_closed() -> None:
    with pytest.raises(ValueError, match="uppercase"):
        wsds._coinapi_symbol_id("BTC:EVILUSDT", exchange_id="BINANCEFTS")
    payload = _raw_ws_payload(1)
    digest = wsds._provider_content_digest(payload)
    assert digest is not None
    with pytest.raises(ValueError, match="exactly bind"):
        wsds._atomic_fenced_quarantine_write(
            StatefulRedis(),
            fence_key=_fence_key(
                symbol="ETHUSDT",
                coinapi_symbol_id="BINANCEFTS_PERP_ETH_USDT",
            ),
            data_key=_data_key(
                symbol="ETHUSDT",
                coinapi_symbol_id="BINANCEFTS_PERP_ETH_USDT",
            ),
            conflict_key=_conflict_key(
                1,
                digest,
                symbol="ETHUSDT",
                coinapi_symbol_id="BINANCEFTS_PERP_ETH_USDT",
            ),
            event_identity_ns="1",
            payload=payload,
            ex=60,
        )

    hostile_fields: tuple[tuple[str, object], ...] = (
        ("quarantine_only", False),
        ("canonical_receipt_resolver_present", True),
        ("available_at", "2026-07-20T12:00:00Z"),
        ("feature_cutoff", "2026-07-20T12:00:00Z"),
        ("postcommit_receipt_present", True),
        ("feature_eligible", True),
        ("trainer_consumable", True),
        ("prediction_eligible", True),
        ("live_gate", "approved"),
        ("live_symbols", ["BTCUSDT"]),
        ("market_key", "v2:features:microfeat:BTCUSDT:1m"),
        ("microfeat_payloads", {"v2:features:microfeat:BTCUSDT:1m": {}}),
        ("authority_grant", "trainer"),
        ("execution_authority", True),
        ("grant_id", "provider-grant"),
        ("approves_live", True),
        ("live_execution_enabled", True),
        ("writes_exchange_orders", True),
        ("places_real_order", True),
        ("order_submission_enabled", True),
        ("order_id", "provider-order"),
        ("trader_execution_enabled", True),
        ("exchange_action_taken", True),
    )
    for field, value in hostile_fields:
        authority_injected = {**payload, field: value}
        injected_digest = wsds._provider_content_digest(authority_injected)
        assert injected_digest is not None
        client = StatefulRedis()
        result = wsds._atomic_fenced_quarantine_write(
            client,
            fence_key=_fence_key(),
            data_key=_data_key(),
            conflict_key=_conflict_key(1, injected_digest),
            event_identity_ns="1",
            payload=authority_injected,
            ex=60,
        )
        assert result == (wsds._FENCE_ERROR, -2)
        assert client.values == {}
        assert client.fences == {}

    for field, value in hostile_fields:
        nested_authority = dict(payload)
        nested_authority["mid_px"] = {field: value}
        nested_digest = wsds._provider_content_digest(nested_authority)
        assert nested_digest is not None
        assert wsds._atomic_fenced_quarantine_write(
            StatefulRedis(),
            fence_key=_fence_key(),
            data_key=_data_key(),
            conflict_key=_conflict_key(1, nested_digest),
            event_identity_ns="1",
            payload=nested_authority,
            ex=60,
        ) == (wsds._FENCE_ERROR, -2)


def test_ws_atomic_commit_revalidates_post_normalization_payload_before_eval() -> None:
    payload = _raw_ws_payload(1)

    def assert_rejected(mutated: dict[str, Any]) -> None:
        event_ns = mutated.get("source_event_ts_ns")
        assert type(event_ns) is int
        digest = wsds._provider_content_digest(mutated) or ("0" * 64)
        client = NeverEvalRedis()
        result = wsds._atomic_fenced_quarantine_write(
            client,
            fence_key=_fence_key(),
            data_key=_data_key(),
            conflict_key=_conflict_key(event_ns, digest),
            event_identity_ns=str(event_ns),
            payload=mutated,
            ex=60,
        )
        assert result == (wsds._FENCE_ERROR, -2)
        assert client.eval_calls == 0

    mutations: tuple[tuple[str, object], ...] = (
        ("best_bid_px", "100.0"),
        ("best_bid_px", 10**400),
        ("best_bid_sz", -1.0),
        ("spread_bps", math.inf),
        ("source_event_ts_ms", int(payload["source_event_ts_ms"]) + 1),
        ("updated_ts_ms", int(payload["updated_ts_ms"]) + 1),
        ("producer_version", "tampered-producer"),
        ("coinapi_exchange_id", "COINBASE"),
        ("best_ask_px", 99.0),
        ("mid_px", 999.0),
        ("book_bid_sum_5", 0.5),
    )
    for field, value in mutations:
        assert_rejected({**payload, field: value})

    inverted_clock = dict(payload)
    inverted_clock["generated_at"] = payload["ingested_at"]
    assert_rejected(inverted_clock)


def test_ws_persistent_state_reads_are_atomic_and_length_gated() -> None:
    class OversizedStateRedis:
        def __init__(self) -> None:
            self.identity_fields: list[str] = []
            self.direct_fetch_calls = 0

        def hmget(self, *args: object) -> object:
            del args
            self.direct_fetch_calls += 1
            raise AssertionError("persistent state must not use HMGET")

        def hget(self, *args: object) -> object:
            del args
            self.direct_fetch_calls += 1
            raise AssertionError("persistent state must not use direct HGET")

        def eval(self, script: str, numkeys: int, *args: object) -> list[object]:
            assert numkeys == 1
            assert "COINAPI_BOUNDED_PERSISTENT_HASH_READ_V1" in script
            assert "HMGET" not in script
            assert script.index("redis.call('TYPE'") < script.index("redis.call('PTTL'")
            assert script.index("redis.call('PTTL'") < script.index("redis.call('HSTRLEN'")
            assert script.index("redis.call('HSTRLEN'") < script.index("redis.call('HGET'")
            _key, identity_field, _payload_field, _identity_limit, payload_limit = args
            self.identity_fields.append(str(identity_field))
            return [wsds._STATE_READ_OVERSIZED, 1, int(str(payload_limit)) + 1]

    client = OversizedStateRedis()
    auth_key = wsds._auth_latch_key("configured-key")
    cadence_key = _cadence_key()
    provisional_key = _cadence_key(provisional=True)
    assert auth_key is not None

    assert wsds._bounded_persistent_hash_read(
        client,
        key=auth_key,
        identity_field="revision_ns",
    ) == (wsds._STATE_READ_OVERSIZED, None, None)
    assert wsds._load_auth_state(client, api_key="configured-key") is None
    assert wsds._read_persistent_cadence_payload(client, cadence_key) is None
    assert (
        wsds._load_authenticated_cadence_basis(
            client,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
        )
        is None
    )
    assert (
        wsds._read_provisional_cadence_payload(
            client,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
        )
        is None
    )
    assert provisional_key != cadence_key
    assert client.identity_fields == [
        "revision_ns",
        "revision_ns",
        "last_event_ns",
        "last_event_ns",
        "last_event_ns",
    ]
    assert client.direct_fetch_calls == 0

    class ReplyRedis:
        def __init__(self, reply: object) -> None:
            self.reply = reply

        def eval(self, script: str, numkeys: int, *args: object) -> object:
            del script, numkeys, args
            return self.reply

    assert wsds._bounded_persistent_hash_read(
        ReplyRedis([wsds._STATE_READ_INVALID, "", ""]),
        key=auth_key,
        identity_field="revision_ns",
    ) == (wsds._STATE_READ_INVALID, None, None)
    assert wsds._bounded_persistent_hash_read(
        ReplyRedis([wsds._STATE_READ_OK, b"1", b"x" * (wsds.MAX_STATE_JSON_BYTES + 1)]),
        key=auth_key,
        identity_field="revision_ns",
    ) == (wsds._STATE_READ_ERROR, None, None)


def test_ws_provider_identity_is_bound_into_all_namespaces_with_cold_bootstrap() -> None:
    coinbase_symbol_id = "COINBASE_SPOT_BTC_USDT"
    binance_payload = _raw_ws_payload(1)
    coinbase_payload = _raw_ws_payload(
        1,
        coinapi_symbol_id=coinbase_symbol_id,
    )
    binance_keys = wsds._expected_ws_quarantine_keys(binance_payload)
    coinbase_keys = wsds._expected_ws_quarantine_keys(coinbase_payload)

    assert binance_keys is not None
    assert coinbase_keys is not None
    assert binance_keys[:3] != coinbase_keys[:3]
    assert COINAPI_SYMBOL_ID in binance_keys[0]
    assert coinbase_symbol_id in coinbase_keys[0]
    assert _cadence_key() != _cadence_key(coinapi_symbol_id=coinbase_symbol_id)
    assert _data_key() != _data_key(coinapi_symbol_id=coinbase_symbol_id)
    assert wsds._coinapi_symbol_id("BTCUSDT", exchange_id="COINBASE") == coinbase_symbol_id

    legacy_payload = dict(binance_payload)
    legacy_payload["schema_version"] = "v2_coinapi_wsds_raw_quarantine_v2"
    assert wsds._expected_ws_quarantine_keys(legacy_payload) is None

    status = wsds._base_status(
        symbols=("BTCUSDT",),
        subscribed_symbols=(),
        opt_in=True,
        credential_present=True,
        redis_ok=False,
        stream_connected=False,
        classification="TEST",
        blocker="TEST",
        stats={},
        data_types=["quote"],
        ws_url=wsds.DEFAULT_WS_URL,
    )
    assert status["provider_identity_schema_version"] == wsds.PROVIDER_IDENTITY_SCHEMA_VERSION
    assert status["quarantine_namespace_version"] == "v4"
    assert status["cadence_namespace_version"] == "v4"
    assert status["provisional_cadence_namespace_version"] == "v3"
    assert status["legacy_namespace_reads_enabled"] is False
    assert status["legacy_namespace_migration_mode"] == "COLD_BOOTSTRAP_REQUIRED"
    assert status["trainer_consumable"] is False


def test_ws_retry_after_and_credential_rotation_are_bounded_and_nonsecret() -> None:
    state = wsds._build_auth_state(
        api_key="first-secret",
        http_status=403,
        error_class="ENTITLEMENT_REJECTED",
        prior_state=None,
        quota_metadata={"retry_after_seconds": 17},
        now_ns=1_000_000_000,
    )
    assert state is not None
    assert state["next_probe_at_ns"] == 31_000_000_000
    assert state["retry_after_honored"] is True
    assert "first-secret" not in json.dumps(state, sort_keys=True)
    short_window = {
        **state,
        "next_probe_at_ns": state["revision_ns"] + 29_000_000_000,
    }
    short_unsigned = {key: value for key, value in short_window.items() if key != "signature"}
    short_window["signature"] = wsds._auth_state_signature("first-secret", short_unsigned)
    assert wsds._validated_auth_state(short_window, api_key="first-secret") is None
    assert wsds._validated_auth_state(state, api_key="second-secret") is None
    assert wsds._auth_latch_key("first-secret") != wsds._auth_latch_key("second-secret")


def test_connected_ws_durable_reprobe_refreshes_optional_heartbeat_without_reconnect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    args = _connected_args(tmp_path, total_seconds=120.0)
    client = StatefulRedis()
    session_calls = 0
    sleep_delays: list[float] = []
    published_payloads: list[dict[str, Any]] = []
    original_publish_status = wsds._publish_status

    async def provider_rejection(**kwargs: object) -> dict[str, Any]:
        nonlocal session_calls
        del kwargs
        session_calls += 1
        return {
            "committed_messages": 0,
            "real_messages_received": 0,
            "transport_connected": False,
            "authenticated_transport_succeeded": False,
            "current_data_redis_ack": False,
            "provider_health": {
                "state": "PROVIDER_BLOCKED",
                "provider_http_status": 403,
                "provider_error_class": "ENTITLEMENT_REJECTED",
                "quota_metadata": {"retry_after_seconds": 17},
            },
        }

    def capture_status(payload: dict[str, Any], *args: object, **kwargs: object) -> bool:
        published_payloads.append(json.loads(json.dumps(payload)))
        return original_publish_status(payload, *args, **kwargs)  # type: ignore[arg-type]

    async def stop_after_two_heartbeats(delay: float) -> None:
        sleep_delays.append(delay)
        if len(sleep_delays) == 2:
            args.total_seconds = 0.0

    monkeypatch.delenv(wsds.AUTH_LATCH_RESET_ENV, raising=False)
    monkeypatch.delenv("COINAPI_WSDS_URL", raising=False)
    monkeypatch.delenv("COINAPI_PRIMARY_EXCHANGE_ID", raising=False)
    monkeypatch.delenv("COINAPI_SUBSCRIBE_DATA_TYPES", raising=False)
    monkeypatch.setattr(wsds, "_run_session", provider_rejection)
    monkeypatch.setattr(wsds, "_publish_status", capture_status)
    monkeypatch.setattr(wsds.asyncio, "sleep", stop_after_two_heartbeats)

    asyncio.run(
        wsds._run_connected_loop(
            args,
            ("BTCUSDT",),
            "configured-key",
            client,
        )
    )

    assert session_calls == 1
    assert len(sleep_delays) == 2
    assert all(
        0.0 < delay <= args.heartbeat_interval_seconds
        for delay in sleep_delays
    )
    assert len(published_payloads) == 2
    assert all(payload["trainer_consumable"] is False for payload in published_payloads)
    assert all(payload["provider_data_usable"] is False for payload in published_payloads)
    assert all(payload["typed_missing"] is True for payload in published_payloads)
    assert published_payloads[-1]["blocked_reason"] == (
        "AWAITING_DURABLE_OPTIONAL_REPROBE_WINDOW"
    )
    assert len(client.auth_records) == 1
    stored = json.loads(next(iter(client.auth_records.values()))["payload"])
    assert stored["next_probe_at_ns"] - stored["revision_ns"] == 30_000_000_000
    assert published_payloads[-1]["provider_health"]["next_probe_at_ns"] == stored[
        "next_probe_at_ns"
    ]


def test_cadence_namespace_rotation_does_not_require_deleting_old_evidence() -> None:
    client = StatefulRedis()
    now_ns = wsds.datetime_epoch_ns(datetime.now(UTC))
    old_basis = _basis_ending_at(now_ns - 2_000_000, api_key="old-secret")
    new_basis = _basis_ending_at(now_ns - 1_000_000, api_key="new-secret")
    old_key = _cadence_key(api_key="old-secret")
    new_key = _cadence_key(api_key="new-secret")
    old_provisional_key = _cadence_key(api_key="old-secret", provisional=True)
    new_provisional_key = _cadence_key(api_key="new-secret", provisional=True)

    assert old_key != new_key
    assert old_provisional_key != new_provisional_key
    assert "old-secret" not in old_key
    assert "new-secret" not in new_key
    assert (
        wsds._atomic_persist_authenticated_cadence_basis(
            client,
            key=old_key,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="old-secret",
            basis=old_basis,
        )
        == wsds._CADENCE_COMMITTED
    )
    assert (
        wsds._load_authenticated_cadence_basis(
            client,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="new-secret",
        )
        is None
    )
    assert (
        wsds._atomic_persist_authenticated_cadence_basis(
            client,
            key=new_key,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="new-secret",
            basis=new_basis,
        )
        == wsds._CADENCE_COMMITTED
    )
    assert old_key in client.cadence_records
    assert new_key in client.cadence_records
    assert (
        wsds._load_authenticated_cadence_basis(
            client,
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="new-secret",
        )
        == new_basis
    )


def test_ws_atomic_lua_reads_are_length_gated_and_existing_state_is_consistent() -> None:
    for marker, script in (
        ("COINAPI_ATOMIC_FENCE_BOUNDED_V2", wsds._ATOMIC_FENCE_LUA),
        ("COINAPI_ATOMIC_CADENCE_BOUNDED_V2", wsds._ATOMIC_CADENCE_LUA),
        ("COINAPI_ATOMIC_AUTH_STATE_BOUNDED_V2", wsds._ATOMIC_AUTH_STATE_LUA),
    ):
        assert marker in script
        assert script.count("redis.call('HGET'") == 1
        assert script.index("redis.call('HSTRLEN'") < script.index("redis.call('HGET'")
        assert "identity_limit = tonumber" in script
        assert "payload_limit = tonumber" in script
        assert "identity_limit > 64" in script
    assert wsds._ATOMIC_FENCE_LUA.count("redis.call('GET'") == 1
    assert wsds._ATOMIC_FENCE_LUA.index("redis.call('STRLEN'") < wsds._ATOMIC_FENCE_LUA.index(
        "redis.call('GET'"
    )
    assert "payload_limit > 1048576" in wsds._ATOMIC_FENCE_LUA
    assert "payload_limit > 32768" in wsds._ATOMIC_CADENCE_LUA
    assert "payload_limit > 32768" in wsds._ATOMIC_AUTH_STATE_LUA
    assert "fence_type == 'hash'" in wsds._ATOMIC_FENCE_LUA
    assert (
        "current_event and baseline_payload and baseline_payload ~= current_payload"
        in wsds._ATOMIC_FENCE_LUA
    )
    assert "redis.sha1hex(current_payload) ~= current_payload_sha1" in wsds._ATOMIC_FENCE_LUA
    assert "key_type == 'hash'" in wsds._ATOMIC_CADENCE_LUA
    assert "existing_conflict == incoming_payload" in wsds._ATOMIC_FENCE_LUA


def test_ws_atomic_writes_reject_oversized_input_and_preflight_races(monkeypatch) -> None:
    payload = _raw_ws_payload(1_000_000)
    expected = wsds._expected_ws_quarantine_keys(payload)
    assert expected is not None
    fence_key, data_key, conflict_key, event_identity_ns = expected
    never_eval = NeverEvalRedis()
    monkeypatch.setattr(wsds, "MAX_REDIS_QUARANTINE_JSON_BYTES", 1)
    assert wsds._atomic_fenced_quarantine_write(
        never_eval,
        fence_key=fence_key,
        data_key=data_key,
        conflict_key=conflict_key,
        event_identity_ns=event_identity_ns,
        payload=payload,
        ex=60,
    ) == (wsds._FENCE_ERROR, -2)
    assert never_eval.eval_calls == 0
    monkeypatch.setattr(
        wsds,
        "MAX_REDIS_QUARANTINE_JSON_BYTES",
        wsds.MAX_WS_MESSAGE_BYTES,
    )

    class OversizedFenceStateRedis:
        def eval(self, script: str, numkeys: int, *args: object) -> list[object]:
            assert numkeys == 3
            assert "COINAPI_ATOMIC_FENCE_BOUNDED_V2" in script
            assert args[-2:] == (
                wsds.MAX_STATE_IDENTITY_BYTES,
                wsds.MAX_REDIS_QUARANTINE_JSON_BYTES,
            )
            oversized_existing_payload = "x" * (int(args[-1]) + 1)
            assert len(oversized_existing_payload) > int(args[-1])
            return [wsds._FENCE_ERROR, 0, -2]

    assert wsds._atomic_fenced_quarantine_write(
        OversizedFenceStateRedis(),
        fence_key=fence_key,
        data_key=data_key,
        conflict_key=conflict_key,
        event_identity_ns=event_identity_ns,
        payload=payload,
        ex=60,
    ) == (wsds._FENCE_ERROR, -2)

    prior_auth = wsds._build_auth_state(
        api_key="configured-key",
        http_status=403,
        error_class="ENTITLEMENT_REJECTED",
        prior_state=None,
        quota_metadata=None,
        now_ns=1,
    )
    replacement_auth = wsds._build_auth_state(
        api_key="configured-key",
        http_status=403,
        error_class="ENTITLEMENT_REJECTED",
        prior_state=prior_auth,
        quota_metadata=None,
        now_ns=2,
    )
    assert prior_auth is not None and replacement_auth is not None
    prior_auth_serialized = wsds._canonical_json(prior_auth)
    assert prior_auth_serialized is not None

    class AuthPreflightRaceRedis:
        def __init__(self) -> None:
            self.current_payload = prior_auth_serialized
            self.atomic_calls = 0

        def exists(self, key: str) -> int:
            del key
            return 1

        def eval(self, script: str, numkeys: int, *args: object) -> list[object]:
            assert numkeys == 1
            if "COINAPI_BOUNDED_PERSISTENT_HASH_READ_V1" in script:
                before_race = self.current_payload
                self.current_payload = "x" * (wsds.MAX_STATE_JSON_BYTES + 1)
                return [wsds._STATE_READ_OK, str(prior_auth["revision_ns"]), before_race]
            assert "COINAPI_ATOMIC_AUTH_STATE_BOUNDED_V2" in script
            self.atomic_calls += 1
            assert args[-2:] == (
                wsds.MAX_STATE_IDENTITY_BYTES,
                wsds.MAX_STATE_JSON_BYTES,
            )
            assert len(self.current_payload) > int(args[-1])
            return [wsds._AUTH_STATE_ERROR, 0]

    auth_race_client = AuthPreflightRaceRedis()
    assert (
        wsds._persist_auth_state(
            auth_race_client,
            api_key="configured-key",
            state=replacement_auth,
        )
        == wsds._AUTH_STATE_ERROR
    )
    assert auth_race_client.atomic_calls == 1

    now_ns = wsds.datetime_epoch_ns(datetime.now(UTC))
    prior_basis = _basis_ending_at(now_ns - 2_000_000_000)
    replacement_basis = _basis_ending_at(now_ns - 1_000_000_000)
    prior_basis_serialized = wsds._canonical_json(prior_basis)
    assert prior_basis_serialized is not None

    class CadencePreflightRaceRedis:
        def __init__(self) -> None:
            self.current_payload = prior_basis_serialized
            self.atomic_calls = 0

        def exists(self, key: str) -> int:
            del key
            return 1

        def eval(self, script: str, numkeys: int, *args: object) -> list[object]:
            assert numkeys == 1
            if "COINAPI_BOUNDED_PERSISTENT_HASH_READ_V1" in script:
                before_race = self.current_payload
                self.current_payload = "x" * (wsds.MAX_STATE_JSON_BYTES + 1)
                return [wsds._STATE_READ_OK, str(prior_basis["last_event_ns"]), before_race]
            assert "COINAPI_ATOMIC_CADENCE_BOUNDED_V2" in script
            self.atomic_calls += 1
            assert args[-2:] == (
                wsds.MAX_STATE_IDENTITY_BYTES,
                wsds.MAX_STATE_JSON_BYTES,
            )
            assert len(self.current_payload) > int(args[-1])
            return [wsds._CADENCE_ERROR, 0]

    cadence_race_client = CadencePreflightRaceRedis()
    assert (
        wsds._atomic_persist_authenticated_cadence_basis(
            cadence_race_client,
            key=_cadence_key(),
            symbol="BTCUSDT",
            coinapi_symbol_id=COINAPI_SYMBOL_ID,
            api_key="configured-key",
            basis=replacement_basis,
        )
        == wsds._CADENCE_ERROR
    )
    assert cadence_race_client.atomic_calls == 1


def test_ws_redis_connection_uses_bounded_connect_and_read_timeouts(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class RedisClient:
        def ping(self) -> bool:
            return True

    client = RedisClient()

    def redis_factory(**kwargs: object) -> RedisClient:
        captured.update(kwargs)
        return client

    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=redis_factory))

    assert wsds._connect_redis() is client
    assert captured == {
        "host": "127.0.0.1",
        "port": 6379,
        "db": 0,
        "decode_responses": True,
        "socket_connect_timeout": 2,
        "socket_timeout": 3,
    }
