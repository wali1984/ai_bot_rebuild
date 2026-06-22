"""Tests for V2 native trainer bridge-exit prediction publisher."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2.backend.app.services.trainer_bridge_exit.native_prediction_publisher import (
    ALLOWED_TRAINER_SOURCE_VALUES,
    FORBIDDEN_TRAINER_SOURCE_VALUES,
    KNOWN_UNIVERSE,
    LIVE_GATE_BLOCKED,
    REQUIRED_PREDICTION_FIELDS,
    SHADOW_PREDICTION_KEY_TEMPLATE,
    TIMEFRAMES,
    TRAINER_SOURCE_BASELINE_PAPER_SHADOW,
    TRAINER_SOURCE_CONTRACT_ONLY,
    PredictionInputs,
    V2OnlyPublisher,
    build_prediction_payload,
    default_paths,
    is_publishable,
    publish_predictions_for_universe,
    run_publisher_packet,
    should_preserve_existing,
)


# ---------------------------------------------------------------------------
# In-memory v2:* client
# ---------------------------------------------------------------------------


class _InMemoryClient:
    """Duck-typed client with get/set, used for hermetic tests."""

    def __init__(self):
        self._store: dict[str, str] = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value):
        self._store[key] = value
        return True


def _seed_features_and_ta(client, *, symbols, timeframes, fresh=True):
    """Seed every (symbol, timeframe) with a feature + TA payload."""
    for sym in symbols:
        for tf in timeframes:
            client.set(
                f"v2:features:latest:{sym}:{tf}",
                json.dumps({
                    "feature_snapshot_id": f"{sym}:{tf}:test",
                    "freshness_state": "FRESH" if fresh else "STALE",
                }),
            )
            client.set(
                f"v2:features:ta:{sym}:{tf}",
                json.dumps({
                    "indicators": {
                        "ema_9": 100.5,
                        "ema_21": 99.8,
                        "rsi_14": 52.0,
                    },
                }),
            )


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def test_prediction_payload_contains_all_required_fields():
    payload = build_prediction_payload(PredictionInputs(
        symbol="BTCUSDT", timeframe="1m",
        features={"feature_snapshot_id": "x", "freshness_state": "FRESH"},
        ta={"indicators": {"ema_9": 100.5, "ema_21": 99.8}},
    ))
    for f in REQUIRED_PREDICTION_FIELDS:
        assert f in payload, f


def test_prediction_with_features_and_ta_uses_baseline_label():
    payload = build_prediction_payload(PredictionInputs(
        symbol="BTCUSDT", timeframe="1m",
        features={"feature_snapshot_id": "x", "freshness_state": "FRESH"},
        ta={"indicators": {"ema_9": 100.5, "ema_21": 99.8}},
    ))
    assert payload["trainer_source"] == TRAINER_SOURCE_BASELINE_PAPER_SHADOW
    assert payload["trainer_source"] in ALLOWED_TRAINER_SOURCE_VALUES
    for forbidden in FORBIDDEN_TRAINER_SOURCE_VALUES:
        assert payload["trainer_source"] != forbidden


def test_prediction_without_inputs_falls_back_to_contract_only():
    payload = build_prediction_payload(PredictionInputs(
        symbol="BTCUSDT", timeframe="1m", features=None, ta=None,
    ))
    assert payload["trainer_source"] == TRAINER_SOURCE_CONTRACT_ONLY
    assert payload["expected_move_bps"] is None
    assert payload["confidence_calibrated"] is None
    assert "v2_features_latest_missing" in payload["missing_feature_flags"]
    assert "v2_features_ta_missing" in payload["missing_feature_flags"]


def test_paper_fill_gate_stays_blocked_for_every_prediction():
    payload = build_prediction_payload(PredictionInputs(
        symbol="BTCUSDT", timeframe="1m",
        features={"feature_snapshot_id": "x", "freshness_state": "FRESH"},
        ta={"indicators": {"ema_9": 100.5, "ema_21": 99.8}},
    ))
    assert payload["paper_fill_allowed"] is False
    assert payload["paper_fill_gate_status"] == "BLOCKED_BASELINE_OR_CONTRACT_ONLY"
    assert len(payload["paper_fill_gate_block_reasons"]) >= 1


def test_safety_pins_present_on_every_payload():
    payload = build_prediction_payload(PredictionInputs(
        symbol="BTCUSDT", timeframe="1m", features=None, ta=None,
    ))
    assert payload["live_gate"] == LIVE_GATE_BLOCKED
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False


def test_is_publishable_rejects_missing_field():
    payload = build_prediction_payload(PredictionInputs(
        symbol="BTCUSDT", timeframe="1m", features=None, ta=None,
    ))
    del payload["confidence_calibrated"]
    assert is_publishable(payload) is False


def test_is_publishable_rejects_paper_fill_allowed_true():
    payload = build_prediction_payload(PredictionInputs(
        symbol="BTCUSDT", timeframe="1m", features=None, ta=None,
    ))
    payload["paper_fill_allowed"] = True
    assert is_publishable(payload) is False


def test_is_publishable_rejects_forbidden_trainer_source():
    payload = build_prediction_payload(PredictionInputs(
        symbol="BTCUSDT", timeframe="1m", features=None, ta=None,
    ))
    payload["trainer_source"] = "V2_NATIVE_TRAINER_READY"
    assert is_publishable(payload) is False


def test_should_preserve_existing_when_source_is_stronger():
    existing = {
        "trainer_source": "V2_NATIVE_TRAINER_v1_real_model",
        "paper_fill_allowed": True,
    }
    assert should_preserve_existing(existing) is True


def test_should_not_preserve_when_existing_is_baseline_or_contract_only():
    for src in ALLOWED_TRAINER_SOURCE_VALUES:
        assert should_preserve_existing({"trainer_source": src}) is False


# ---------------------------------------------------------------------------
# Publisher (write-side safety)
# ---------------------------------------------------------------------------


def test_publisher_rejects_non_v2_keys():
    pub = V2OnlyPublisher(client=_InMemoryClient())
    ok = pub.set_json("legacy:foo:bar", {"x": 1})
    assert ok is False
    assert pub.audit.old_redis_write_attempts == 1
    assert any("blocked_non_v2_key" in e for e in pub.audit.errors)


def test_publisher_writes_v2_keys_when_client_present():
    client = _InMemoryClient()
    pub = V2OnlyPublisher(client=client)
    ok = pub.set_json("v2:prediction:BTCUSDT:1m", {"x": 1})
    assert ok is True
    assert pub.audit.writes_succeeded == 1
    assert pub.audit.old_redis_write_attempts == 0
    assert json.loads(client.get("v2:prediction:BTCUSDT:1m")) == {"x": 1}


def test_publisher_get_rejects_non_v2_keys_at_read_time():
    pub = V2OnlyPublisher(client=_InMemoryClient())
    with pytest.raises(ValueError):
        pub.get_json("legacy:foo")


# ---------------------------------------------------------------------------
# Universe orchestration
# ---------------------------------------------------------------------------


def test_publisher_publishes_per_symbol_timeframe_with_shadow_only_keys():
    client = _InMemoryClient()
    pub = V2OnlyPublisher(client=client)
    _seed_features_and_ta(client, symbols=KNOWN_UNIVERSE, timeframes=TIMEFRAMES)
    result = publish_predictions_for_universe(publisher=pub)
    s = result["status"]
    expected = len(KNOWN_UNIVERSE) * len(TIMEFRAMES)
    assert s["published_count"] == expected
    assert s["preserved_count"] == 0
    assert s["rejected_count"] == 0
    assert s["canonical_prediction_writes_blocked"] is True
    assert s["trainer_native_readiness_claimed"] is False
    assert s["v2_native_trainer_ready"] is False
    assert pub.audit.old_redis_write_attempts == 0
    # Every published payload satisfies the publisher contract while the
    # canonical prediction namespace remains untouched.
    for sym in KNOWN_UNIVERSE:
        for tf in TIMEFRAMES:
            raw = client.get(f"v2:prediction:{sym}:{tf}")
            assert raw is None
            raw = client.get(
                SHADOW_PREDICTION_KEY_TEMPLATE.format(symbol=sym, timeframe=tf)
            )
            assert raw is not None
            payload = json.loads(raw)
            assert is_publishable(payload)
            assert payload["trainer_source"] in ALLOWED_TRAINER_SOURCE_VALUES


def test_publisher_preserves_stronger_existing_prediction():
    client = _InMemoryClient()
    pub = V2OnlyPublisher(client=client)
    _seed_features_and_ta(
        client, symbols=("BTCUSDT",), timeframes=("1m",),
    )
    # Plant an existing prediction with a stronger source.
    client.set(
        "v2:prediction:BTCUSDT:1m",
        json.dumps({"trainer_source": "V2_NATIVE_TRAINER_v1_existing_runtime"}),
    )
    result = publish_predictions_for_universe(
        publisher=pub, universe=("BTCUSDT",), timeframes=("1m",),
    )
    s = result["status"]
    assert s["preserved_count"] == 1
    assert s["published_count"] == 0
    # Existing key is untouched.
    raw = client.get("v2:prediction:BTCUSDT:1m")
    payload = json.loads(raw)
    assert payload["trainer_source"] == "V2_NATIVE_TRAINER_v1_existing_runtime"


# ---------------------------------------------------------------------------
# End-to-end packet
# ---------------------------------------------------------------------------


def test_run_publisher_packet_emits_all_required_artifacts(tmp_path: Path):
    client = _InMemoryClient()
    _seed_features_and_ta(client, symbols=KNOWN_UNIVERSE, timeframes=TIMEFRAMES)
    paths = default_paths(tmp_path)
    publisher = V2OnlyPublisher(client=client)
    result = run_publisher_packet(paths, publisher=publisher)
    assert result.go_no_go == (
        "V2_NATIVE_TRAINER_BRIDGE_EXIT_PREDICTION_PUBLISHER_READY"
    )
    for required in [
        "GO_NO_GO.md",
        "V2_NATIVE_TRAINER_BRIDGE_EXIT_PREDICTION_PUBLISHER_REPORT.md",
        "publisher_status.json",
        "per_symbol_rows.json",
        "publisher_audit.json",
        "operator_dashboard_payload.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    for public_required in [
        "operator_dashboard_payload.json",
        "publisher_status.json",
    ]:
        assert (paths.public_dir / public_required).exists(), public_required


def test_emitted_packet_has_no_truthy_approvals_or_native_trainer_claims(tmp_path: Path):
    client = _InMemoryClient()
    _seed_features_and_ta(client, symbols=KNOWN_UNIVERSE, timeframes=TIMEFRAMES)
    paths = default_paths(tmp_path)
    publisher = V2OnlyPublisher(client=client)
    run_publisher_packet(paths, publisher=publisher)
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"trainer_native_readiness_claimed": true',
        '"v2_native_trainer_ready": true',
        '"full_migration_claimed": true',
        '"bridge_data_labeled_as_v2_native": true',
        '"paper_fill_allowed": true',
        '"did_not_weaken_paper_fill_gate": false',
        '"did_not_overwrite_stronger_existing_prediction": false',
        '"trainer_source": "V2_NATIVE_TRAINER_READY"',
        '"trainer_source": "V2_NATIVE_TRAINER_ACTIVE"',
    ]
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
