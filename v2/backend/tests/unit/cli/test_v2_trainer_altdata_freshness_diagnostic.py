"""Unit tests for the WI-5 alt-data freshness diagnostic (mask semantics)."""
from __future__ import annotations

from types import SimpleNamespace

from app.cli.v2_trainer_altdata_freshness_diagnostic import analyze_freshness, _category


def _ex(values, missing, stale, source, names):
    return SimpleNamespace(tensor=SimpleNamespace(
        values=values, missing_mask=missing, stale_mask=stale,
        source_availability=source, feature_names=names,
    ))


def test_category_classifies_external_altdata_and_derivatives() -> None:
    assert _category("santiment_sentiment_score") == "external_altdata"
    # nansen/lunarcrush are free-tier/disabled -> classified separately, not "dead".
    assert _category("nansen_score") == "disabled_altdata"
    assert _category("lunarcrush_score") == "disabled_altdata"
    assert _category("funding_rate") == "derivatives_microstructure"
    assert _category("liquidation_strength") == "derivatives_microstructure"
    assert _category("last_price") == "core"


def test_dead_feature_detected_when_always_missing() -> None:
    names = ["santiment_sentiment_score", "last_price"]
    # feature 0 always missing; feature 1 always present + fresh.
    rows = [_ex([0.0, 1.5], [1, 0], [0, 0], [0, 1], names) for _ in range(10)]
    r = analyze_freshness(rows)
    ext = r["summary_by_category"]["external_altdata"]
    assert ext["dead_count"] == 1
    assert ext["mean_present_and_fresh_rate"] == 0.0
    core = r["summary_by_category"]["core"]
    assert core["healthy_count"] == 1


def test_healthy_feature_when_present_and_fresh() -> None:
    names = ["santiment_sentiment_score"]
    rows = [_ex([0.4], [0], [0], [1], names) for _ in range(10)]
    r = analyze_freshness(rows)
    ext = r["summary_by_category"]["external_altdata"]
    assert ext["healthy_count"] == 1
    assert ext["dead_count"] == 0


def test_read_only_posture() -> None:
    r = analyze_freshness([_ex([1.0], [0], [0], [1], ["last_price"])])
    assert r["read_only"] is True
    assert r["changes_no_decision"] is True
    assert r["live_gate"] == "blocked_human_only"
