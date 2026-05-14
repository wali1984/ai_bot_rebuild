from rl.tf_aggregator import aggregate_tf_votes


def test_tf_aggregator_detects_conflict_for_entry_block():
    tf_preds = {
        "4h": {"action": "LONG", "confidence": 0.92},
        "1h": {"action": "LONG", "confidence": 0.88},
        "15m": {"action": "SHORT", "confidence": 0.93},
        "5m": {"action": "SHORT", "confidence": 0.91},
        "1m": {"action": "SHORT", "confidence": 0.89},
    }

    out = aggregate_tf_votes(tf_preds, current_conf=0.9)

    assert out["bias_dir"] == 1
    assert out["timing_dir"] == -1
    assert out["conflict_score"] > 0.65
    assert out["tf_votes"]["4h"] == 1
    assert out["tf_votes"]["5m"] == -1


def test_tf_aggregator_low_conflict_when_aligned():
    tf_preds = {
        "4h": {"action": "LONG", "confidence": 0.91},
        "1h": {"action": "LONG", "confidence": 0.90},
        "15m": {"action": "LONG", "confidence": 0.86},
        "5m": {"action": "LONG", "confidence": 0.84},
    }

    out = aggregate_tf_votes(tf_preds, current_conf=0.85)

    assert out["bias_dir"] == 1
    assert out["timing_dir"] == 1
    assert out["conflict_score"] < 0.2
