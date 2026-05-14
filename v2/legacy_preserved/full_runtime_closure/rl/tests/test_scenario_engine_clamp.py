from rl.scenario_engine import ScenarioEngine


def test_scenario_logit_delta_is_clamped_positive():
    engine = ScenarioEngine(alpha=1.0, clamp=0.12)
    features = {
        "liquidation_short_strength": 15.0,
        "liquidation_long_strength": 0.0,
        "liquidation_volume": 8000.0,
        "basis_pct": 2.0,
        "funding_rate": 1.0,
        "depth_spoof_score": 0.0,
    }

    out = engine.evaluate("BTCUSDT", "15m", features, base_logit=0.2)
    assert out["logit_delta"] <= 0.12
    assert out["logit_delta"] >= -0.12


def test_scenario_logit_delta_is_clamped_negative():
    engine = ScenarioEngine(alpha=1.0, clamp=0.10)
    features = {
        "liquidation_short_strength": 0.0,
        "liquidation_long_strength": 15.0,
        "liquidation_volume": 10000.0,
        "basis_pct": -2.0,
        "funding_rate": -1.0,
        "depth_spoof_score": 5.0,
        "depth_spread": 1.0,
    }

    out = engine.evaluate("BTCUSDT", "15m", features, base_logit=-0.2)
    assert out["logit_delta"] >= -0.10
    assert out["logit_delta"] <= 0.10
