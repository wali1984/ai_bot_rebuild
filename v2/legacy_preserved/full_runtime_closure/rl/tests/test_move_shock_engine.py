import unittest

from rl.move_shock_engine import MoveShockEngine


class TestMoveShockEngine(unittest.TestCase):
    def test_stable_zscore_computation(self):
        eng = MoveShockEngine(window=40, z_cap=6.0)
        symbol = "BTCUSDT"
        tf = "5m"

        base = {
            "depth_spread": 10.0,
            "depth_imbalance_5": 0.0,
            "depth_microprice": 100.0,
            "depth_mid_price": 100.0,
            "ob_ob_imbalance": 0.0,
            "depth_fast_move_score": 0.1,
            "liquidation_long_strength": 1.0,
            "liquidation_short_strength": 1.0,
            "funding_rate": 0.01,
            "basis_pct": 0.02,
            "mark_price": 100.0,
            "index_price": 100.0,
        }

        # Warm up rolling stats on a near-stationary sequence
        for _ in range(60):
            out = eng.evaluate(symbol, tf, dict(base))

        self.assertIn("move_intensity", out)
        self.assertGreaterEqual(out["move_intensity"], 0.0)
        self.assertLessEqual(out["move_intensity"], 10.0)

        # A moderate perturbation should remain bounded and stable (non-exploding z)
        shock = dict(base)
        shock["depth_spread"] = 12.0
        out2 = eng.evaluate(symbol, tf, shock)
        self.assertLessEqual(out2["move_intensity"], 10.0)
        self.assertTrue(isinstance(out2.get("top_contributors", []), list))

    def test_clamp_safety(self):
        eng = MoveShockEngine(window=30, z_cap=3.0)
        symbol = "ETHUSDT"
        tf = "1m"

        # Build baseline
        for _ in range(35):
            eng.evaluate(symbol, tf, {
                "depth_spread": 1.0,
                "depth_imbalance_5": 0.0,
                "depth_spoof_score": 0.0,
                "depth_microprice": 2000.0,
                "depth_mid_price": 2000.0,
            })

        out = eng.evaluate(symbol, tf, {
            "depth_spread": 1e9,
            "depth_imbalance_5": 1e6,
            "depth_spoof_score": 1.0,
            "depth_microprice": 3000.0,
            "depth_mid_price": 2000.0,
            "p_false_move": 1.0,
        })

        self.assertGreaterEqual(out["move_intensity"], 0.0)
        self.assertLessEqual(out["move_intensity"], 10.0)
        self.assertGreaterEqual(out["spoof_probability"], 0.0)
        self.assertLessEqual(out["spoof_probability"], 1.0)

        for c in out.get("top_contributors", []):
            self.assertLessEqual(abs(float(c.get("z", 0.0))), 3.0 + 1e-9)

    def test_deterministic_type_classification(self):
        eng = MoveShockEngine(window=25, z_cap=6.0)
        symbol = "SOLUSDT"
        tf = "5m"

        baseline = {
            "depth_spread": 2.0,
            "depth_imbalance_5": 0.0,
            "depth_spoof_score": 0.1,
            "p_false_move": 0.1,
            "depth_microprice": 150.0,
            "depth_mid_price": 150.0,
            "liquidation_long_strength": 2.0,
            "liquidation_short_strength": 2.0,
            "liquidation_volume": 10.0,
            "depth_fast_move_score": 0.2,
        }

        for _ in range(30):
            eng.evaluate(symbol, tf, baseline)

        # Force spoof-dominated imbalance shock => SPOOF_FALSE_MOVE (deterministic rule)
        spoof_case = dict(baseline)
        spoof_case.update({
            "depth_imbalance_5": 2.5,
            "ob_ob_imbalance": 2.0,
            "depth_spoof_score": 0.95,
            "p_false_move": 0.95,
            "depth_churn_score": 0.9,
        })
        out = eng.evaluate(symbol, tf, spoof_case)
        self.assertEqual(out["move_type"], "SPOOF_FALSE_MOVE")


if __name__ == "__main__":
    unittest.main()
