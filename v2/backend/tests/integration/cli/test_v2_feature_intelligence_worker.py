from __future__ import annotations

import datetime as dt

import pytest

from v2.backend.app.services.feature_intelligence.service import (
    FeatureIntelligenceService,
    FeatureSnapshotIn,
    RegimeLabel,
    classify_regime,
    compute_microstructure,
    feature_freshness_flag,
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def test_microstructure_returns_missing_when_bid_ask_absent() -> None:
    snap = FeatureSnapshotIn(symbol="BTCUSDT", timeframe="1m", generated_utc=_now_iso())
    micro = compute_microstructure(snap)
    assert micro.bid_ask_spread_bps is None
    assert "bid_ask" in micro.missing_inputs
    assert micro.micro_price is None


def test_microstructure_computes_spread_and_micro_price() -> None:
    snap = FeatureSnapshotIn(
        symbol="BTCUSDT",
        timeframe="1m",
        generated_utc=_now_iso(),
        bid_price=99.0,
        ask_price=101.0,
        bid_size=2.0,
        ask_size=1.0,
    )
    micro = compute_microstructure(snap)
    assert micro.bid_ask_spread_bps is not None and 195 < micro.bid_ask_spread_bps < 205
    # imbalance positive because bid_size > ask_size
    assert micro.depth_imbalance is not None and micro.depth_imbalance > 0
    # micro price tilts toward ask because bid_size higher
    assert micro.micro_price is not None and micro.micro_price > 100.0


def test_microstructure_realized_volatility_from_recent_closes() -> None:
    snap = FeatureSnapshotIn(
        symbol="BTCUSDT",
        timeframe="1m",
        generated_utc=_now_iso(),
        recent_close_prices=(100.0, 100.5, 99.5, 101.0, 100.0),
    )
    micro = compute_microstructure(snap)
    assert micro.realized_volatility_pct is not None and micro.realized_volatility_pct > 0.0


def test_microstructure_toxicity_proxy_in_unit_interval() -> None:
    snap = FeatureSnapshotIn(
        symbol="BTCUSDT",
        timeframe="1m",
        generated_utc=_now_iso(),
        bid_price=99.5,
        ask_price=100.5,
        bid_size=10.0,
        ask_size=2.0,
    )
    micro = compute_microstructure(snap)
    assert micro.toxicity_proxy is not None
    assert 0.0 <= micro.toxicity_proxy <= 1.0


def test_feature_freshness_fresh_when_recent() -> None:
    assert feature_freshness_flag(_now_iso(), max_age_seconds=120) == "FRESH"


def test_feature_freshness_stale_when_old() -> None:
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=600)).isoformat(timespec="seconds")
    assert feature_freshness_flag(old, max_age_seconds=120) == "STALE"


def test_feature_freshness_missing_when_none_or_invalid() -> None:
    assert feature_freshness_flag(None) == "MISSING"
    assert feature_freshness_flag("not-a-timestamp") == "MISSING"


@pytest.mark.parametrize(
    "rv,ts,di,expected",
    [
        (2.0, 0.0, 0.0, RegimeLabel.VOLATILE),
        (0.5, 1.0, 0.1, RegimeLabel.TRENDING_UP),
        (0.5, -1.0, 0.1, RegimeLabel.TRENDING_DOWN),
        (0.5, 0.0, 0.1, RegimeLabel.RANGING),
        (None, 0.0, 0.0, RegimeLabel.UNCERTAIN),
        (0.5, None, 0.0, RegimeLabel.UNCERTAIN),
    ],
)
def test_classify_regime_basic(rv: float | None, ts: float | None, di: float | None, expected: RegimeLabel) -> None:
    out = classify_regime(realized_volatility_pct=rv, trend_strength_pct=ts, depth_imbalance=di)
    assert out is expected


def test_service_compute_returns_complete_schema() -> None:
    svc = FeatureIntelligenceService()
    snap = FeatureSnapshotIn(
        symbol="BTCUSDT",
        timeframe="1m",
        generated_utc=_now_iso(),
        bid_price=99.95,
        ask_price=100.05,
        bid_size=5.0,
        ask_size=5.0,
        recent_close_prices=(99.0, 99.5, 100.0, 100.5, 101.0),
    )
    out = svc.compute(snap)
    assert out["schema_version"] == "1.0.0"
    assert out["symbol"] == "BTCUSDT"
    assert out["regime"] in {r.value for r in RegimeLabel}
    assert out["freshness"] == "FRESH"
    assert "missing_inputs" in out


def test_service_status_payload_holds_safety_invariants() -> None:
    svc = FeatureIntelligenceService()
    status = svc.current_paper_only_status()
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
    assert status["approves_live"] is False
    assert status["approves_canary"] is False
    assert status["approves_legacy_shutdown"] is False
    assert status["approves_redis_trim"] is False
    assert status["scope"] == "PAPER_ONLY"
    assert status["migration_classification"] == "PARTIALLY_MIGRATED"
    assert isinstance(status["components_ported"], list) and len(status["components_ported"]) >= 5
    assert isinstance(status["components_missing"], list) and len(status["components_missing"]) >= 1


def test_service_status_payload_cites_legacy_sha256() -> None:
    svc = FeatureIntelligenceService()
    status = svc.current_paper_only_status()
    citations = status["legacy_sha256_citations"]
    assert "rl/microstructure_proactive.py" in citations
    assert len(citations["rl/microstructure_proactive.py"]["sha256"]) == 64
