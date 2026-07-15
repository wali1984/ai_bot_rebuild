# 12-Hour Continuous Adaptive Monitor — Active Execution Log
**Started:** 2026-07-14T21:55:00Z
**Mode:** CONTINUOUS ADAPTIVE (no static thresholds)
**Target:** A-grades passing + all gates open + all blockers resolved

---

## Live Metrics Dashboard

**Confidence Calibration**
- Max confidence (current): 0.7865 (target: 0.85+)
- Avg confidence (current): 0.5355 (target: 0.75+)
- Adaptive threshold (live): Computing...

**A-Grade Gate**
- Status: BLOCKED (0/100 trades for unlock)
- Target: 100+ historical trades with positive EV
- Progress: Awaiting B-grade evidence accumulation

**B-Grade Enablement**
- Status: EVALUATING (need 45%+ win rate on B trades)
- Med-confidence win rate: Computing...

**Paper Trading**
- Equity: $3,000.80
- Realized PnL: +$0.797
- Closed trades: 8
- Win rate: 62.5% (5W-3L)

**Market Regime**
- Volatility (BPS): Computing...
- Regime Type: Computing...

**Blockers Status**
- [ ] Forward edge tracked (checkpoint_id field)
- [ ] A-grade historical evidence (100+ trades)
- [ ] B-grade enablement (confidence > 45% accuracy)
- [ ] PPO activation (checkpoint promotion unblock)
- [ ] Feature pipeline (restore missing providers)
- [ ] Probation completion (5/5 closes)

---

## Adaptive Tuning Log

### Iteration 1 — T+0:00 (2026-07-14 21:55:00Z)
```
Outcome Analysis: NO_CONFIDENCE_DATA (trades present but no confidence field yet)
Market Regime: INSUFFICIENT_DATA
Action: Waiting for trades with confidence metadata
Threshold Adapt: Neutral (0.70)
B-Grade Enabled: FALSE
A-Grade Enabled: FALSE
```

### Iteration 2 — T+1:00 (TBD)
[Running continuously...]

---

## Continuous Actions (Every 60 seconds)

1. **Measure** — Analyze paper outcomes + market regime
2. **Learn** — Compute adaptive thresholds from data
3. **Apply** — Write tuning state to Redis (gates read it live)
4. **Report** — Log metrics to this file
5. **Check** — Are A-grades passing? All gates open?
6. **Iterate** — Loop until success

---

## Success Criteria (Exit Condition)

- [ ] Max confidence >= 0.85 (currently 0.7865)
- [ ] A-grade gate status == READY (100+ trades accumulated)
- [ ] B-grade entries flowing (positive EV trades entering)
- [ ] Checkpoint promotion unblocked (PPO activation)
- [ ] Feature pipeline >= 80% complete
- [ ] Probation at 5/5 closes
- [ ] Forward edge tracked (checkpoint_id in all fills)
- [ ] All hard failures resolved

**Exit:** When all criteria met, system achieves A-grade readiness.

---

## Status

🔴 STARTING UP — Adaptive monitoring loop initialization
⏱️ EXPECTED RESOLUTION: 2-4 hours (depends on paper trading pace and market regime)


### Iteration 1 — T+0:00 (2026-07-14T21:56:21Z)
```
Timestamp: Tue Jul 14 05:56:21 PM EDT 2026
Elapsed: 0h0m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T21:56:21.673197+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 2 — T+1:00 (2026-07-14T21:57:21Z)
```
Timestamp: Tue Jul 14 05:57:21 PM EDT 2026
Elapsed: 0h1m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T21:57:21.791282+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 3 — T+2:00 (2026-07-14T21:58:21Z)
```
Timestamp: Tue Jul 14 05:58:21 PM EDT 2026
Elapsed: 0h2m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T21:58:21.900768+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 4 — T+3:00 (2026-07-14T21:59:22Z)
```
Timestamp: Tue Jul 14 05:59:22 PM EDT 2026
Elapsed: 0h3m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T21:59:22.016745+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 5 — T+4:00 (2026-07-14T22:00:22Z)
```
Timestamp: Tue Jul 14 06:00:22 PM EDT 2026
Elapsed: 0h4m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:00:22.118987+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 6 — T+5:00 (2026-07-14T22:01:22Z)
```
Timestamp: Tue Jul 14 06:01:22 PM EDT 2026
Elapsed: 0h5m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:01:22.213509+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 7 — T+6:00 (2026-07-14T22:02:22Z)
```
Timestamp: Tue Jul 14 06:02:22 PM EDT 2026
Elapsed: 0h6m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:02:22.314598+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 8 — T+7:00 (2026-07-14T22:03:22Z)
```
Timestamp: Tue Jul 14 06:03:22 PM EDT 2026
Elapsed: 0h7m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:03:22.412962+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 9 — T+8:00 (2026-07-14T22:04:22Z)
```
Timestamp: Tue Jul 14 06:04:22 PM EDT 2026
Elapsed: 0h8m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:04:22.510878+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 10 — T+9:00 (2026-07-14T22:05:22Z)
```
Timestamp: Tue Jul 14 06:05:22 PM EDT 2026
Elapsed: 0h9m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:05:22.624582+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 11 — T+10:00 (2026-07-14T22:06:22Z)
```
Timestamp: Tue Jul 14 06:06:22 PM EDT 2026
Elapsed: 0h10m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:06:22.731628+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 12 — T+11:00 (2026-07-14T22:07:22Z)
```
Timestamp: Tue Jul 14 06:07:22 PM EDT 2026
Elapsed: 0h11m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:07:22.824377+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 13 — T+12:00 (2026-07-14T22:08:22Z)
```
Timestamp: Tue Jul 14 06:08:22 PM EDT 2026
Elapsed: 0h12m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:08:22.925757+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 14 — T+13:00 (2026-07-14T22:09:23Z)
```
Timestamp: Tue Jul 14 06:09:23 PM EDT 2026
Elapsed: 0h13m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:09:23.017268+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 15 — T+14:00 (2026-07-14T22:10:23Z)
```
Timestamp: Tue Jul 14 06:10:23 PM EDT 2026
Elapsed: 0h14m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:10:23.121412+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 16 — T+15:00 (2026-07-14T22:11:23Z)
```
Timestamp: Tue Jul 14 06:11:23 PM EDT 2026
Elapsed: 0h15m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:11:23.223995+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 17 — T+16:00 (2026-07-14T22:12:23Z)
```
Timestamp: Tue Jul 14 06:12:23 PM EDT 2026
Elapsed: 0h16m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:12:23.326241+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 18 — T+17:00 (2026-07-14T22:13:23Z)
```
Timestamp: Tue Jul 14 06:13:23 PM EDT 2026
Elapsed: 0h17m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:13:23.442927+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 19 — T+18:00 (2026-07-14T22:14:23Z)
```
Timestamp: Tue Jul 14 06:14:23 PM EDT 2026
Elapsed: 0h18m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:14:23.551989+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 20 — T+19:00 (2026-07-14T22:15:23Z)
```
Timestamp: Tue Jul 14 06:15:23 PM EDT 2026
Elapsed: 0h19m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:15:23.664582+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 21 — T+20:00 (2026-07-14T22:16:23Z)
```
Timestamp: Tue Jul 14 06:16:23 PM EDT 2026
Elapsed: 0h20m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:16:23.763625+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 22 — T+21:00 (2026-07-14T22:17:23Z)
```
Timestamp: Tue Jul 14 06:17:23 PM EDT 2026
Elapsed: 0h21m
A-Grade Ready: FALSE
Confidence Threshold: 0.7
B-Grade Enabled: FALSE

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.7, b_grade=False, a_grade=False
{
  "outcomes": {
    "status": "NO_CONFIDENCE_DATA",
    "sample_size": 0
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.7,
  "enable_b_grade": false,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:17:23.873485+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 23 — T+22:00 (2026-07-14T22:18:24Z)
```
Timestamp: Tue Jul 14 06:18:24 PM EDT 2026
Elapsed: 0h22m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:18:24.029424+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 24 — T+23:00 (2026-07-14T22:19:24Z)
```
Timestamp: Tue Jul 14 06:19:24 PM EDT 2026
Elapsed: 0h23m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:19:24.129353+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 1 — T+0:00 (2026-07-14T22:19:50Z)
```
Timestamp: Tue Jul 14 06:19:50 PM EDT 2026
Elapsed: 0h0m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:19:50.335976+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 2 — T+1:00 (2026-07-14T22:20:50Z)
```
Timestamp: Tue Jul 14 06:20:50 PM EDT 2026
Elapsed: 0h1m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:20:50.469098+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 3 — T+2:00 (2026-07-14T22:21:50Z)
```
Timestamp: Tue Jul 14 06:21:50 PM EDT 2026
Elapsed: 0h2m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:21:50.570666+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 4 — T+3:00 (2026-07-14T22:22:51Z)
```
Timestamp: Tue Jul 14 06:22:51 PM EDT 2026
Elapsed: 0h3m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:22:51.014095+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
{"error": "tuner timeout or error"}
```

### Iteration 5 — T+4:00 (2026-07-14T22:23:51Z)
```
Timestamp: Tue Jul 14 06:23:51 PM EDT 2026
Elapsed: 0h4m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:23:51.127032+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 6 — T+5:00 (2026-07-14T22:24:51Z)
```
Timestamp: Tue Jul 14 06:24:51 PM EDT 2026
Elapsed: 0h5m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:24:51.251220+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 7 — T+6:00 (2026-07-14T22:25:51Z)
```
Timestamp: Tue Jul 14 06:25:51 PM EDT 2026
Elapsed: 0h6m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:25:51.349597+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 8 — T+7:00 (2026-07-14T22:26:51Z)
```
Timestamp: Tue Jul 14 06:26:51 PM EDT 2026
Elapsed: 0h7m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:26:51.448578+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 9 — T+8:00 (2026-07-14T22:27:51Z)
```
Timestamp: Tue Jul 14 06:27:51 PM EDT 2026
Elapsed: 0h8m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:27:51.557140+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 10 — T+9:00 (2026-07-14T22:28:51Z)
```
Timestamp: Tue Jul 14 06:28:51 PM EDT 2026
Elapsed: 0h9m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:28:51.667911+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 11 — T+10:00 (2026-07-14T22:29:51Z)
```
Timestamp: Tue Jul 14 06:29:51 PM EDT 2026
Elapsed: 0h10m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:29:51.788310+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 1 — T+0:00 (2026-07-14T22:30:40Z)
```
Timestamp: Tue Jul 14 06:30:40 PM EDT 2026
Elapsed: 0h0m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:30:40.124147+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 12 — T+11:00 (2026-07-14T22:30:51Z)
```
Timestamp: Tue Jul 14 06:30:51 PM EDT 2026
Elapsed: 0h11m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:30:51.916994+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 2 — T+1:00 (2026-07-14T22:31:40Z)
```
Timestamp: Tue Jul 14 06:31:40 PM EDT 2026
Elapsed: 0h1m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:31:40.219297+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 13 — T+12:00 (2026-07-14T22:31:52Z)
```
Timestamp: Tue Jul 14 06:31:52 PM EDT 2026
Elapsed: 0h12m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:31:52.019241+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 3 — T+2:00 (2026-07-14T22:32:40Z)
```
Timestamp: Tue Jul 14 06:32:40 PM EDT 2026
Elapsed: 0h2m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:32:40.324190+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 14 — T+13:00 (2026-07-14T22:32:52Z)
```
Timestamp: Tue Jul 14 06:32:52 PM EDT 2026
Elapsed: 0h13m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:32:52.133386+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 4 — T+3:00 (2026-07-14T22:33:40Z)
```
Timestamp: Tue Jul 14 06:33:40 PM EDT 2026
Elapsed: 0h3m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:33:40.414196+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 15 — T+14:00 (2026-07-14T22:33:52Z)
```
Timestamp: Tue Jul 14 06:33:52 PM EDT 2026
Elapsed: 0h14m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:33:52.232390+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 5 — T+4:00 (2026-07-14T22:34:40Z)
```
Timestamp: Tue Jul 14 06:34:40 PM EDT 2026
Elapsed: 0h4m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:34:40.521296+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 16 — T+15:00 (2026-07-14T22:34:52Z)
```
Timestamp: Tue Jul 14 06:34:52 PM EDT 2026
Elapsed: 0h15m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:34:52.362050+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 6 — T+5:00 (2026-07-14T22:35:40Z)
```
Timestamp: Tue Jul 14 06:35:40 PM EDT 2026
Elapsed: 0h5m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:35:40.636837+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 17 — T+16:00 (2026-07-14T22:35:52Z)
```
Timestamp: Tue Jul 14 06:35:52 PM EDT 2026
Elapsed: 0h16m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:35:52.478927+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 7 — T+6:00 (2026-07-14T22:36:40Z)
```
Timestamp: Tue Jul 14 06:36:40 PM EDT 2026
Elapsed: 0h6m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:36:40.743558+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 18 — T+17:00 (2026-07-14T22:36:52Z)
```
Timestamp: Tue Jul 14 06:36:52 PM EDT 2026
Elapsed: 0h17m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:36:52.605025+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 8 — T+7:00 (2026-07-14T22:37:40Z)
```
Timestamp: Tue Jul 14 06:37:40 PM EDT 2026
Elapsed: 0h7m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:37:40.853633+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 19 — T+18:00 (2026-07-14T22:37:52Z)
```
Timestamp: Tue Jul 14 06:37:52 PM EDT 2026
Elapsed: 0h18m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:37:52.711552+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 9 — T+8:00 (2026-07-14T22:38:40Z)
```
Timestamp: Tue Jul 14 06:38:40 PM EDT 2026
Elapsed: 0h8m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:38:40.957332+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 20 — T+19:00 (2026-07-14T22:38:52Z)
```
Timestamp: Tue Jul 14 06:38:52 PM EDT 2026
Elapsed: 0h19m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:38:52.805496+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 10 — T+9:00 (2026-07-14T22:39:41Z)
```
Timestamp: Tue Jul 14 06:39:41 PM EDT 2026
Elapsed: 0h9m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:39:41.277089+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 21 — T+20:00 (2026-07-14T22:39:52Z)
```
Timestamp: Tue Jul 14 06:39:52 PM EDT 2026
Elapsed: 0h20m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:39:52.926479+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 11 — T+10:00 (2026-07-14T22:40:41Z)
```
Timestamp: Tue Jul 14 06:40:41 PM EDT 2026
Elapsed: 0h10m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:40:41.395860+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 22 — T+21:00 (2026-07-14T22:40:53Z)
```
Timestamp: Tue Jul 14 06:40:53 PM EDT 2026
Elapsed: 0h21m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:40:53.046656+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 12 — T+11:00 (2026-07-14T22:41:41Z)
```
Timestamp: Tue Jul 14 06:41:41 PM EDT 2026
Elapsed: 0h11m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:41:41.498046+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 23 — T+22:00 (2026-07-14T22:41:53Z)
```
Timestamp: Tue Jul 14 06:41:53 PM EDT 2026
Elapsed: 0h22m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:41:53.162054+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 13 — T+12:00 (2026-07-14T22:42:41Z)
```
Timestamp: Tue Jul 14 06:42:41 PM EDT 2026
Elapsed: 0h12m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:42:41.610895+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 24 — T+23:00 (2026-07-14T22:42:53Z)
```
Timestamp: Tue Jul 14 06:42:53 PM EDT 2026
Elapsed: 0h23m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:42:53.456455+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 14 — T+13:00 (2026-07-14T22:43:41Z)
```
Timestamp: Tue Jul 14 06:43:41 PM EDT 2026
Elapsed: 0h13m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:43:41.708917+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 25 — T+24:00 (2026-07-14T22:43:53Z)
```
Timestamp: Tue Jul 14 06:43:53 PM EDT 2026
Elapsed: 0h24m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:43:53.558892+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 15 — T+14:00 (2026-07-14T22:44:41Z)
```
Timestamp: Tue Jul 14 06:44:41 PM EDT 2026
Elapsed: 0h14m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:44:41.827428+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 26 — T+25:00 (2026-07-14T22:44:53Z)
```
Timestamp: Tue Jul 14 06:44:53 PM EDT 2026
Elapsed: 0h25m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:44:53.680374+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 16 — T+15:00 (2026-07-14T22:45:41Z)
```
Timestamp: Tue Jul 14 06:45:41 PM EDT 2026
Elapsed: 0h15m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:45:41.939831+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 27 — T+26:00 (2026-07-14T22:45:53Z)
```
Timestamp: Tue Jul 14 06:45:53 PM EDT 2026
Elapsed: 0h26m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:45:53.785186+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 17 — T+16:00 (2026-07-14T22:46:42Z)
```
Timestamp: Tue Jul 14 06:46:42 PM EDT 2026
Elapsed: 0h16m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:46:42.052317+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 28 — T+27:00 (2026-07-14T22:46:53Z)
```
Timestamp: Tue Jul 14 06:46:53 PM EDT 2026
Elapsed: 0h27m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:46:53.891075+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 18 — T+17:00 (2026-07-14T22:47:42Z)
```
Timestamp: Tue Jul 14 06:47:42 PM EDT 2026
Elapsed: 0h17m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:47:42.179484+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 29 — T+28:00 (2026-07-14T22:47:54Z)
```
Timestamp: Tue Jul 14 06:47:54 PM EDT 2026
Elapsed: 0h28m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:47:54.010648+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 19 — T+18:00 (2026-07-14T22:48:42Z)
```
Timestamp: Tue Jul 14 06:48:42 PM EDT 2026
Elapsed: 0h18m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:48:42.286440+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 30 — T+29:00 (2026-07-14T22:48:54Z)
```
Timestamp: Tue Jul 14 06:48:54 PM EDT 2026
Elapsed: 0h29m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:48:54.116731+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 20 — T+19:00 (2026-07-14T22:49:42Z)
```
Timestamp: Tue Jul 14 06:49:42 PM EDT 2026
Elapsed: 0h19m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:49:42.400331+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 31 — T+30:00 (2026-07-14T22:49:54Z)
```
Timestamp: Tue Jul 14 06:49:54 PM EDT 2026
Elapsed: 0h30m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:49:54.240829+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 21 — T+20:00 (2026-07-14T22:50:42Z)
```
Timestamp: Tue Jul 14 06:50:42 PM EDT 2026
Elapsed: 0h20m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:50:42.503332+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 32 — T+31:00 (2026-07-14T22:50:54Z)
```
Timestamp: Tue Jul 14 06:50:54 PM EDT 2026
Elapsed: 0h31m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:50:54.342164+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 22 — T+21:00 (2026-07-14T22:51:42Z)
```
Timestamp: Tue Jul 14 06:51:42 PM EDT 2026
Elapsed: 0h21m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:51:42.622317+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 33 — T+32:00 (2026-07-14T22:51:54Z)
```
Timestamp: Tue Jul 14 06:51:54 PM EDT 2026
Elapsed: 0h32m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:51:54.446299+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 23 — T+22:00 (2026-07-14T22:52:42Z)
```
Timestamp: Tue Jul 14 06:52:42 PM EDT 2026
Elapsed: 0h22m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:52:42.747953+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 34 — T+33:00 (2026-07-14T22:52:54Z)
```
Timestamp: Tue Jul 14 06:52:54 PM EDT 2026
Elapsed: 0h33m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:52:54.541164+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 24 — T+23:00 (2026-07-14T22:53:43Z)
```
Timestamp: Tue Jul 14 06:53:43 PM EDT 2026
Elapsed: 0h23m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:53:43.062826+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 35 — T+34:00 (2026-07-14T22:53:54Z)
```
Timestamp: Tue Jul 14 06:53:54 PM EDT 2026
Elapsed: 0h34m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:53:54.869544+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 25 — T+24:00 (2026-07-14T22:54:43Z)
```
Timestamp: Tue Jul 14 06:54:43 PM EDT 2026
Elapsed: 0h24m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:54:43.205292+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 36 — T+35:00 (2026-07-14T22:54:54Z)
```
Timestamp: Tue Jul 14 06:54:54 PM EDT 2026
Elapsed: 0h35m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:54:54.974645+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 26 — T+25:00 (2026-07-14T22:55:43Z)
```
Timestamp: Tue Jul 14 06:55:43 PM EDT 2026
Elapsed: 0h25m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:55:43.313408+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 37 — T+36:00 (2026-07-14T22:55:55Z)
```
Timestamp: Tue Jul 14 06:55:55 PM EDT 2026
Elapsed: 0h36m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:55:55.076134+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 27 — T+26:00 (2026-07-14T22:56:43Z)
```
Timestamp: Tue Jul 14 06:56:43 PM EDT 2026
Elapsed: 0h26m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:56:43.619366+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 38 — T+37:00 (2026-07-14T22:56:55Z)
```
Timestamp: Tue Jul 14 06:56:55 PM EDT 2026
Elapsed: 0h37m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:56:55.202633+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 28 — T+27:00 (2026-07-14T22:57:43Z)
```
Timestamp: Tue Jul 14 06:57:43 PM EDT 2026
Elapsed: 0h27m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:57:43.731905+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 39 — T+38:00 (2026-07-14T22:57:55Z)
```
Timestamp: Tue Jul 14 06:57:55 PM EDT 2026
Elapsed: 0h38m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:57:55.539165+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 29 — T+28:00 (2026-07-14T22:58:43Z)
```
Timestamp: Tue Jul 14 06:58:43 PM EDT 2026
Elapsed: 0h28m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:58:43.839450+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 40 — T+39:00 (2026-07-14T22:58:55Z)
```
Timestamp: Tue Jul 14 06:58:55 PM EDT 2026
Elapsed: 0h39m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:58:55.651587+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 30 — T+29:00 (2026-07-14T22:59:43Z)
```
Timestamp: Tue Jul 14 06:59:43 PM EDT 2026
Elapsed: 0h29m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:59:43.966359+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 41 — T+40:00 (2026-07-14T22:59:55Z)
```
Timestamp: Tue Jul 14 06:59:55 PM EDT 2026
Elapsed: 0h40m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T22:59:55.802883+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 31 — T+30:00 (2026-07-14T23:00:44Z)
```
Timestamp: Tue Jul 14 07:00:44 PM EDT 2026
Elapsed: 0h30m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:00:44.089967+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 42 — T+41:00 (2026-07-14T23:00:56Z)
```
Timestamp: Tue Jul 14 07:00:56 PM EDT 2026
Elapsed: 0h41m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:00:56.146995+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 32 — T+31:00 (2026-07-14T23:01:44Z)
```
Timestamp: Tue Jul 14 07:01:44 PM EDT 2026
Elapsed: 0h31m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:01:44.202524+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 43 — T+42:00 (2026-07-14T23:01:56Z)
```
Timestamp: Tue Jul 14 07:01:56 PM EDT 2026
Elapsed: 0h42m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:01:56.250925+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 33 — T+32:00 (2026-07-14T23:02:44Z)
```
Timestamp: Tue Jul 14 07:02:44 PM EDT 2026
Elapsed: 0h32m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:02:44.303688+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 44 — T+43:00 (2026-07-14T23:02:56Z)
```
Timestamp: Tue Jul 14 07:02:56 PM EDT 2026
Elapsed: 0h43m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:02:56.369559+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 34 — T+33:00 (2026-07-14T23:03:44Z)
```
Timestamp: Tue Jul 14 07:03:44 PM EDT 2026
Elapsed: 0h33m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:03:44.394992+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 45 — T+44:00 (2026-07-14T23:03:56Z)
```
Timestamp: Tue Jul 14 07:03:56 PM EDT 2026
Elapsed: 0h44m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:03:56.478795+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 35 — T+34:00 (2026-07-14T23:04:44Z)
```
Timestamp: Tue Jul 14 07:04:44 PM EDT 2026
Elapsed: 0h34m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:04:44.509726+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 46 — T+45:00 (2026-07-14T23:04:56Z)
```
Timestamp: Tue Jul 14 07:04:56 PM EDT 2026
Elapsed: 0h45m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:04:56.593583+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 36 — T+35:00 (2026-07-14T23:05:44Z)
```
Timestamp: Tue Jul 14 07:05:44 PM EDT 2026
Elapsed: 0h35m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:05:44.621338+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 47 — T+46:00 (2026-07-14T23:05:56Z)
```
Timestamp: Tue Jul 14 07:05:56 PM EDT 2026
Elapsed: 0h46m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:05:56.701896+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 37 — T+36:00 (2026-07-14T23:06:44Z)
```
Timestamp: Tue Jul 14 07:06:44 PM EDT 2026
Elapsed: 0h36m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:06:44.727228+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 48 — T+47:00 (2026-07-14T23:06:56Z)
```
Timestamp: Tue Jul 14 07:06:56 PM EDT 2026
Elapsed: 0h47m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:06:56.799599+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 38 — T+37:00 (2026-07-14T23:07:44Z)
```
Timestamp: Tue Jul 14 07:07:44 PM EDT 2026
Elapsed: 0h37m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:07:44.832293+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 49 — T+48:00 (2026-07-14T23:07:56Z)
```
Timestamp: Tue Jul 14 07:07:56 PM EDT 2026
Elapsed: 0h48m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:07:56.895319+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 39 — T+38:00 (2026-07-14T23:08:44Z)
```
Timestamp: Tue Jul 14 07:08:44 PM EDT 2026
Elapsed: 0h38m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:08:44.930978+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 50 — T+49:00 (2026-07-14T23:08:57Z)
```
Timestamp: Tue Jul 14 07:08:57 PM EDT 2026
Elapsed: 0h49m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:08:57.002556+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 40 — T+39:00 (2026-07-14T23:09:45Z)
```
Timestamp: Tue Jul 14 07:09:45 PM EDT 2026
Elapsed: 0h39m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:09:45.054909+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 51 — T+50:00 (2026-07-14T23:09:57Z)
```
Timestamp: Tue Jul 14 07:09:57 PM EDT 2026
Elapsed: 0h50m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:09:57.105934+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 41 — T+40:00 (2026-07-14T23:10:45Z)
```
Timestamp: Tue Jul 14 07:10:45 PM EDT 2026
Elapsed: 0h40m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:10:45.150503+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 52 — T+51:00 (2026-07-14T23:10:57Z)
```
Timestamp: Tue Jul 14 07:10:57 PM EDT 2026
Elapsed: 0h51m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:10:57.226124+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 42 — T+41:00 (2026-07-14T23:11:45Z)
```
Timestamp: Tue Jul 14 07:11:45 PM EDT 2026
Elapsed: 0h41m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:11:45.258864+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 53 — T+52:00 (2026-07-14T23:11:57Z)
```
Timestamp: Tue Jul 14 07:11:57 PM EDT 2026
Elapsed: 0h52m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:11:57.333411+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 43 — T+42:00 (2026-07-14T23:12:45Z)
```
Timestamp: Tue Jul 14 07:12:45 PM EDT 2026
Elapsed: 0h42m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:12:45.370055+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 54 — T+53:00 (2026-07-14T23:12:57Z)
```
Timestamp: Tue Jul 14 07:12:57 PM EDT 2026
Elapsed: 0h53m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:12:57.433325+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 44 — T+43:00 (2026-07-14T23:13:45Z)
```
Timestamp: Tue Jul 14 07:13:45 PM EDT 2026
Elapsed: 0h43m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:13:45.470166+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 55 — T+54:00 (2026-07-14T23:13:57Z)
```
Timestamp: Tue Jul 14 07:13:57 PM EDT 2026
Elapsed: 0h54m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:13:57.530965+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 45 — T+44:00 (2026-07-14T23:14:45Z)
```
Timestamp: Tue Jul 14 07:14:45 PM EDT 2026
Elapsed: 0h44m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:14:45.582809+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 56 — T+55:00 (2026-07-14T23:14:57Z)
```
Timestamp: Tue Jul 14 07:14:57 PM EDT 2026
Elapsed: 0h55m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:14:57.654301+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 46 — T+45:00 (2026-07-14T23:15:45Z)
```
Timestamp: Tue Jul 14 07:15:45 PM EDT 2026
Elapsed: 0h45m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:15:45.696215+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 57 — T+56:00 (2026-07-14T23:15:57Z)
```
Timestamp: Tue Jul 14 07:15:57 PM EDT 2026
Elapsed: 0h56m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:15:57.762820+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 47 — T+46:00 (2026-07-14T23:16:45Z)
```
Timestamp: Tue Jul 14 07:16:45 PM EDT 2026
Elapsed: 0h46m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:16:45.812933+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 58 — T+57:00 (2026-07-14T23:16:57Z)
```
Timestamp: Tue Jul 14 07:16:57 PM EDT 2026
Elapsed: 0h57m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:16:57.866084+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 48 — T+47:00 (2026-07-14T23:17:45Z)
```
Timestamp: Tue Jul 14 07:17:45 PM EDT 2026
Elapsed: 0h47m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:17:45.910370+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 59 — T+58:00 (2026-07-14T23:17:58Z)
```
Timestamp: Tue Jul 14 07:17:58 PM EDT 2026
Elapsed: 0h58m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:17:57.988463+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 49 — T+48:00 (2026-07-14T23:18:46Z)
```
Timestamp: Tue Jul 14 07:18:46 PM EDT 2026
Elapsed: 0h48m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:18:46.047900+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 60 — T+59:00 (2026-07-14T23:18:58Z)
```
Timestamp: Tue Jul 14 07:18:58 PM EDT 2026
Elapsed: 0h59m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:18:58.099163+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 50 — T+49:00 (2026-07-14T23:19:46Z)
```
Timestamp: Tue Jul 14 07:19:46 PM EDT 2026
Elapsed: 0h49m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:19:46.175249+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 61 — T+60:00 (2026-07-14T23:19:58Z)
```
Timestamp: Tue Jul 14 07:19:58 PM EDT 2026
Elapsed: 1h60m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:19:58.232077+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 51 — T+50:00 (2026-07-14T23:20:46Z)
```
Timestamp: Tue Jul 14 07:20:46 PM EDT 2026
Elapsed: 0h50m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:20:46.278108+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 62 — T+61:00 (2026-07-14T23:20:58Z)
```
Timestamp: Tue Jul 14 07:20:58 PM EDT 2026
Elapsed: 1h61m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:20:58.369822+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 52 — T+51:00 (2026-07-14T23:21:46Z)
```
Timestamp: Tue Jul 14 07:21:46 PM EDT 2026
Elapsed: 0h51m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:21:46.781998+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 63 — T+62:00 (2026-07-14T23:21:58Z)
```
Timestamp: Tue Jul 14 07:21:58 PM EDT 2026
Elapsed: 1h62m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:21:58.467366+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 53 — T+52:00 (2026-07-14T23:22:46Z)
```
Timestamp: Tue Jul 14 07:22:46 PM EDT 2026
Elapsed: 0h52m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:22:46.880285+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 64 — T+63:00 (2026-07-14T23:22:58Z)
```
Timestamp: Tue Jul 14 07:22:58 PM EDT 2026
Elapsed: 1h63m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:22:58.569147+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 54 — T+53:00 (2026-07-14T23:23:47Z)
```
Timestamp: Tue Jul 14 07:23:47 PM EDT 2026
Elapsed: 0h53m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:23:46.996814+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 65 — T+64:00 (2026-07-14T23:23:58Z)
```
Timestamp: Tue Jul 14 07:23:58 PM EDT 2026
Elapsed: 1h64m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:23:58.694050+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 55 — T+54:00 (2026-07-14T23:24:47Z)
```
Timestamp: Tue Jul 14 07:24:47 PM EDT 2026
Elapsed: 0h54m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:24:47.125933+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 66 — T+65:00 (2026-07-14T23:24:58Z)
```
Timestamp: Tue Jul 14 07:24:58 PM EDT 2026
Elapsed: 1h65m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:24:58.804101+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 56 — T+55:00 (2026-07-14T23:25:47Z)
```
Timestamp: Tue Jul 14 07:25:47 PM EDT 2026
Elapsed: 0h55m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:25:47.249142+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 67 — T+66:00 (2026-07-14T23:25:58Z)
```
Timestamp: Tue Jul 14 07:25:58 PM EDT 2026
Elapsed: 1h66m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:25:58.932870+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 57 — T+56:00 (2026-07-14T23:26:47Z)
```
Timestamp: Tue Jul 14 07:26:47 PM EDT 2026
Elapsed: 0h56m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:26:47.365225+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 68 — T+67:00 (2026-07-14T23:26:59Z)
```
Timestamp: Tue Jul 14 07:26:59 PM EDT 2026
Elapsed: 1h67m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:26:59.032589+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 58 — T+57:00 (2026-07-14T23:27:47Z)
```
Timestamp: Tue Jul 14 07:27:47 PM EDT 2026
Elapsed: 0h57m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:27:47.471602+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 69 — T+68:00 (2026-07-14T23:27:59Z)
```
Timestamp: Tue Jul 14 07:27:59 PM EDT 2026
Elapsed: 1h68m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:27:59.138428+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 59 — T+58:00 (2026-07-14T23:28:47Z)
```
Timestamp: Tue Jul 14 07:28:47 PM EDT 2026
Elapsed: 0h58m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:28:47.580686+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 70 — T+69:00 (2026-07-14T23:28:59Z)
```
Timestamp: Tue Jul 14 07:28:59 PM EDT 2026
Elapsed: 1h69m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:28:59.255514+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 60 — T+59:00 (2026-07-14T23:29:47Z)
```
Timestamp: Tue Jul 14 07:29:47 PM EDT 2026
Elapsed: 0h59m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:29:47.705349+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 71 — T+70:00 (2026-07-14T23:29:59Z)
```
Timestamp: Tue Jul 14 07:29:59 PM EDT 2026
Elapsed: 1h70m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:29:59.358694+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 61 — T+60:00 (2026-07-14T23:30:47Z)
```
Timestamp: Tue Jul 14 07:30:47 PM EDT 2026
Elapsed: 1h60m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:30:47.831481+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 72 — T+71:00 (2026-07-14T23:30:59Z)
```
Timestamp: Tue Jul 14 07:30:59 PM EDT 2026
Elapsed: 1h71m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:30:59.466427+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 62 — T+61:00 (2026-07-14T23:31:47Z)
```
Timestamp: Tue Jul 14 07:31:47 PM EDT 2026
Elapsed: 1h61m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:31:47.938265+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 73 — T+72:00 (2026-07-14T23:31:59Z)
```
Timestamp: Tue Jul 14 07:31:59 PM EDT 2026
Elapsed: 1h72m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:31:59.569301+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 63 — T+62:00 (2026-07-14T23:32:48Z)
```
Timestamp: Tue Jul 14 07:32:48 PM EDT 2026
Elapsed: 1h62m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:32:48.039702+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 74 — T+73:00 (2026-07-14T23:33:00Z)
```
Timestamp: Tue Jul 14 07:33:00 PM EDT 2026
Elapsed: 1h73m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:33:00.150828+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 64 — T+63:00 (2026-07-14T23:33:48Z)
```
Timestamp: Tue Jul 14 07:33:48 PM EDT 2026
Elapsed: 1h63m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:33:48.493057+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 75 — T+74:00 (2026-07-14T23:34:00Z)
```
Timestamp: Tue Jul 14 07:34:00 PM EDT 2026
Elapsed: 1h74m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:34:00.263982+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 65 — T+64:00 (2026-07-14T23:34:48Z)
```
Timestamp: Tue Jul 14 07:34:48 PM EDT 2026
Elapsed: 1h64m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:34:48.614140+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 76 — T+75:00 (2026-07-14T23:35:00Z)
```
Timestamp: Tue Jul 14 07:35:00 PM EDT 2026
Elapsed: 1h75m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:35:00.383296+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 66 — T+65:00 (2026-07-14T23:35:48Z)
```
Timestamp: Tue Jul 14 07:35:48 PM EDT 2026
Elapsed: 1h65m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:35:48.723947+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 77 — T+76:00 (2026-07-14T23:36:00Z)
```
Timestamp: Tue Jul 14 07:36:00 PM EDT 2026
Elapsed: 1h76m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:36:00.488362+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 67 — T+66:00 (2026-07-14T23:36:48Z)
```
Timestamp: Tue Jul 14 07:36:48 PM EDT 2026
Elapsed: 1h66m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:36:48.832471+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 78 — T+77:00 (2026-07-14T23:37:00Z)
```
Timestamp: Tue Jul 14 07:37:00 PM EDT 2026
Elapsed: 1h77m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:37:00.619403+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 68 — T+67:00 (2026-07-14T23:37:48Z)
```
Timestamp: Tue Jul 14 07:37:48 PM EDT 2026
Elapsed: 1h67m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:37:48.947034+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 79 — T+78:00 (2026-07-14T23:38:00Z)
```
Timestamp: Tue Jul 14 07:38:00 PM EDT 2026
Elapsed: 1h78m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:38:00.744319+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 69 — T+68:00 (2026-07-14T23:38:49Z)
```
Timestamp: Tue Jul 14 07:38:49 PM EDT 2026
Elapsed: 1h68m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:38:49.042393+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 80 — T+79:00 (2026-07-14T23:39:00Z)
```
Timestamp: Tue Jul 14 07:39:00 PM EDT 2026
Elapsed: 1h79m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:39:00.845600+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 70 — T+69:00 (2026-07-14T23:39:49Z)
```
Timestamp: Tue Jul 14 07:39:49 PM EDT 2026
Elapsed: 1h69m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:39:49.157682+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 81 — T+80:00 (2026-07-14T23:40:01Z)
```
Timestamp: Tue Jul 14 07:40:01 PM EDT 2026
Elapsed: 1h80m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:40:00.988870+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 71 — T+70:00 (2026-07-14T23:40:49Z)
```
Timestamp: Tue Jul 14 07:40:49 PM EDT 2026
Elapsed: 1h70m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:40:49.280887+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 82 — T+81:00 (2026-07-14T23:41:01Z)
```
Timestamp: Tue Jul 14 07:41:01 PM EDT 2026
Elapsed: 1h81m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:41:01.121535+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 72 — T+71:00 (2026-07-14T23:41:49Z)
```
Timestamp: Tue Jul 14 07:41:49 PM EDT 2026
Elapsed: 1h71m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:41:49.389995+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 83 — T+82:00 (2026-07-14T23:42:01Z)
```
Timestamp: Tue Jul 14 07:42:01 PM EDT 2026
Elapsed: 1h82m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:42:01.222334+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 73 — T+72:00 (2026-07-14T23:42:49Z)
```
Timestamp: Tue Jul 14 07:42:49 PM EDT 2026
Elapsed: 1h72m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:42:49.511291+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 84 — T+83:00 (2026-07-14T23:43:01Z)
```
Timestamp: Tue Jul 14 07:43:01 PM EDT 2026
Elapsed: 1h83m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:43:01.321143+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 74 — T+73:00 (2026-07-14T23:43:49Z)
```
Timestamp: Tue Jul 14 07:43:49 PM EDT 2026
Elapsed: 1h73m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:43:49.604465+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 85 — T+84:00 (2026-07-14T23:44:01Z)
```
Timestamp: Tue Jul 14 07:44:01 PM EDT 2026
Elapsed: 1h84m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:44:01.415193+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 75 — T+74:00 (2026-07-14T23:44:49Z)
```
Timestamp: Tue Jul 14 07:44:49 PM EDT 2026
Elapsed: 1h74m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:44:49.747898+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 86 — T+85:00 (2026-07-14T23:45:01Z)
```
Timestamp: Tue Jul 14 07:45:01 PM EDT 2026
Elapsed: 1h85m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:45:01.533169+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 76 — T+75:00 (2026-07-14T23:45:50Z)
```
Timestamp: Tue Jul 14 07:45:50 PM EDT 2026
Elapsed: 1h75m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:45:50.248796+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 87 — T+86:00 (2026-07-14T23:46:01Z)
```
Timestamp: Tue Jul 14 07:46:01 PM EDT 2026
Elapsed: 1h86m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:46:01.649089+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 77 — T+76:00 (2026-07-14T23:46:50Z)
```
Timestamp: Tue Jul 14 07:46:50 PM EDT 2026
Elapsed: 1h76m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:46:50.345224+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 88 — T+87:00 (2026-07-14T23:47:01Z)
```
Timestamp: Tue Jul 14 07:47:01 PM EDT 2026
Elapsed: 1h87m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:47:01.923742+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 78 — T+77:00 (2026-07-14T23:47:50Z)
```
Timestamp: Tue Jul 14 07:47:50 PM EDT 2026
Elapsed: 1h77m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:47:50.456616+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 89 — T+88:00 (2026-07-14T23:48:02Z)
```
Timestamp: Tue Jul 14 07:48:02 PM EDT 2026
Elapsed: 1h88m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:48:02.050105+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 79 — T+78:00 (2026-07-14T23:48:50Z)
```
Timestamp: Tue Jul 14 07:48:50 PM EDT 2026
Elapsed: 1h78m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:48:50.544368+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 90 — T+89:00 (2026-07-14T23:49:02Z)
```
Timestamp: Tue Jul 14 07:49:02 PM EDT 2026
Elapsed: 1h89m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:49:02.153937+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 80 — T+79:00 (2026-07-14T23:49:50Z)
```
Timestamp: Tue Jul 14 07:49:50 PM EDT 2026
Elapsed: 1h79m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:49:50.665742+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 91 — T+90:00 (2026-07-14T23:50:02Z)
```
Timestamp: Tue Jul 14 07:50:02 PM EDT 2026
Elapsed: 1h90m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:50:02.256848+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 81 — T+80:00 (2026-07-14T23:50:50Z)
```
Timestamp: Tue Jul 14 07:50:50 PM EDT 2026
Elapsed: 1h80m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:50:50.779830+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 92 — T+91:00 (2026-07-14T23:51:02Z)
```
Timestamp: Tue Jul 14 07:51:02 PM EDT 2026
Elapsed: 1h91m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:51:02.365238+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 82 — T+81:00 (2026-07-14T23:51:50Z)
```
Timestamp: Tue Jul 14 07:51:50 PM EDT 2026
Elapsed: 1h81m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:51:50.880239+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 93 — T+92:00 (2026-07-14T23:52:02Z)
```
Timestamp: Tue Jul 14 07:52:02 PM EDT 2026
Elapsed: 1h92m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:52:02.470677+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 83 — T+82:00 (2026-07-14T23:52:51Z)
```
Timestamp: Tue Jul 14 07:52:51 PM EDT 2026
Elapsed: 1h82m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:52:50.994193+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 94 — T+93:00 (2026-07-14T23:53:02Z)
```
Timestamp: Tue Jul 14 07:53:02 PM EDT 2026
Elapsed: 1h93m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:53:02.587575+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 84 — T+83:00 (2026-07-14T23:53:51Z)
```
Timestamp: Tue Jul 14 07:53:51 PM EDT 2026
Elapsed: 1h83m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:53:51.101397+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 95 — T+94:00 (2026-07-14T23:54:02Z)
```
Timestamp: Tue Jul 14 07:54:02 PM EDT 2026
Elapsed: 1h94m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:54:02.689669+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 85 — T+84:00 (2026-07-14T23:54:51Z)
```
Timestamp: Tue Jul 14 07:54:51 PM EDT 2026
Elapsed: 1h84m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:54:51.226726+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 96 — T+95:00 (2026-07-14T23:55:02Z)
```
Timestamp: Tue Jul 14 07:55:02 PM EDT 2026
Elapsed: 1h95m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:55:02.802164+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 86 — T+85:00 (2026-07-14T23:55:51Z)
```
Timestamp: Tue Jul 14 07:55:51 PM EDT 2026
Elapsed: 1h85m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:55:51.335630+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 97 — T+96:00 (2026-07-14T23:56:02Z)
```
Timestamp: Tue Jul 14 07:56:02 PM EDT 2026
Elapsed: 1h96m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:56:02.910378+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 87 — T+86:00 (2026-07-14T23:56:51Z)
```
Timestamp: Tue Jul 14 07:56:51 PM EDT 2026
Elapsed: 1h86m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:56:51.435300+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 98 — T+97:00 (2026-07-14T23:57:03Z)
```
Timestamp: Tue Jul 14 07:57:03 PM EDT 2026
Elapsed: 1h97m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:57:03.033649+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 88 — T+87:00 (2026-07-14T23:57:51Z)
```
Timestamp: Tue Jul 14 07:57:51 PM EDT 2026
Elapsed: 1h87m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:57:51.541983+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 99 — T+98:00 (2026-07-14T23:58:03Z)
```
Timestamp: Tue Jul 14 07:58:03 PM EDT 2026
Elapsed: 1h98m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:58:03.155256+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 89 — T+88:00 (2026-07-14T23:58:51Z)
```
Timestamp: Tue Jul 14 07:58:51 PM EDT 2026
Elapsed: 1h88m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:58:51.639435+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 100 — T+99:00 (2026-07-14T23:59:03Z)
```
Timestamp: Tue Jul 14 07:59:03 PM EDT 2026
Elapsed: 1h99m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:59:03.276697+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 90 — T+89:00 (2026-07-14T23:59:51Z)
```
Timestamp: Tue Jul 14 07:59:51 PM EDT 2026
Elapsed: 1h89m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-14T23:59:51.750235+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 101 — T+100:00 (2026-07-15T00:00:03Z)
```
Timestamp: Tue Jul 14 08:00:03 PM EDT 2026
Elapsed: 1h100m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:00:03.401031+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 91 — T+90:00 (2026-07-15T00:00:51Z)
```
Timestamp: Tue Jul 14 08:00:51 PM EDT 2026
Elapsed: 1h90m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:00:51.855767+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 102 — T+101:00 (2026-07-15T00:01:03Z)
```
Timestamp: Tue Jul 14 08:01:03 PM EDT 2026
Elapsed: 1h101m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:01:03.508623+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 92 — T+91:00 (2026-07-15T00:01:51Z)
```
Timestamp: Tue Jul 14 08:01:51 PM EDT 2026
Elapsed: 1h91m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:01:51.948298+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 103 — T+102:00 (2026-07-15T00:02:03Z)
```
Timestamp: Tue Jul 14 08:02:03 PM EDT 2026
Elapsed: 1h102m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:02:03.610395+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 93 — T+92:00 (2026-07-15T00:02:52Z)
```
Timestamp: Tue Jul 14 08:02:52 PM EDT 2026
Elapsed: 1h92m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:02:52.060850+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 104 — T+103:00 (2026-07-15T00:03:03Z)
```
Timestamp: Tue Jul 14 08:03:03 PM EDT 2026
Elapsed: 1h103m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:03:03.708440+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 94 — T+93:00 (2026-07-15T00:03:52Z)
```
Timestamp: Tue Jul 14 08:03:52 PM EDT 2026
Elapsed: 1h93m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:03:52.278393+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 105 — T+104:00 (2026-07-15T00:04:03Z)
```
Timestamp: Tue Jul 14 08:04:03 PM EDT 2026
Elapsed: 1h104m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:04:03.805923+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 95 — T+94:00 (2026-07-15T00:04:52Z)
```
Timestamp: Tue Jul 14 08:04:52 PM EDT 2026
Elapsed: 1h94m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:04:52.380196+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 106 — T+105:00 (2026-07-15T00:05:03Z)
```
Timestamp: Tue Jul 14 08:05:03 PM EDT 2026
Elapsed: 1h105m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:05:03.900133+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 96 — T+95:00 (2026-07-15T00:05:52Z)
```
Timestamp: Tue Jul 14 08:05:52 PM EDT 2026
Elapsed: 1h95m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:05:52.478770+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 107 — T+106:00 (2026-07-15T00:06:04Z)
```
Timestamp: Tue Jul 14 08:06:04 PM EDT 2026
Elapsed: 1h106m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:06:03.993186+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 97 — T+96:00 (2026-07-15T00:06:52Z)
```
Timestamp: Tue Jul 14 08:06:52 PM EDT 2026
Elapsed: 1h96m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:06:52.589773+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 108 — T+107:00 (2026-07-15T00:07:04Z)
```
Timestamp: Tue Jul 14 08:07:04 PM EDT 2026
Elapsed: 1h107m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:07:04.097968+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 98 — T+97:00 (2026-07-15T00:07:52Z)
```
Timestamp: Tue Jul 14 08:07:52 PM EDT 2026
Elapsed: 1h97m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:07:52.686019+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 109 — T+108:00 (2026-07-15T00:08:04Z)
```
Timestamp: Tue Jul 14 08:08:04 PM EDT 2026
Elapsed: 1h108m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:08:04.205377+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 99 — T+98:00 (2026-07-15T00:08:52Z)
```
Timestamp: Tue Jul 14 08:08:52 PM EDT 2026
Elapsed: 1h98m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:08:52.792022+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 110 — T+109:00 (2026-07-15T00:09:04Z)
```
Timestamp: Tue Jul 14 08:09:04 PM EDT 2026
Elapsed: 1h109m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:09:04.306983+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 100 — T+99:00 (2026-07-15T00:09:52Z)
```
Timestamp: Tue Jul 14 08:09:52 PM EDT 2026
Elapsed: 1h99m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:09:52.904080+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 111 — T+110:00 (2026-07-15T00:10:04Z)
```
Timestamp: Tue Jul 14 08:10:04 PM EDT 2026
Elapsed: 1h110m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:10:04.401316+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 101 — T+100:00 (2026-07-15T00:10:53Z)
```
Timestamp: Tue Jul 14 08:10:53 PM EDT 2026
Elapsed: 1h100m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:10:53.008880+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 112 — T+111:00 (2026-07-15T00:11:04Z)
```
Timestamp: Tue Jul 14 08:11:04 PM EDT 2026
Elapsed: 1h111m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:11:04.521576+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 102 — T+101:00 (2026-07-15T00:11:53Z)
```
Timestamp: Tue Jul 14 08:11:53 PM EDT 2026
Elapsed: 1h101m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:11:53.114108+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 113 — T+112:00 (2026-07-15T00:12:04Z)
```
Timestamp: Tue Jul 14 08:12:04 PM EDT 2026
Elapsed: 1h112m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:12:04.624822+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 103 — T+102:00 (2026-07-15T00:12:53Z)
```
Timestamp: Tue Jul 14 08:12:53 PM EDT 2026
Elapsed: 1h102m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:12:53.208855+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 114 — T+113:00 (2026-07-15T00:13:04Z)
```
Timestamp: Tue Jul 14 08:13:04 PM EDT 2026
Elapsed: 1h113m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:13:04.721300+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 104 — T+103:00 (2026-07-15T00:13:53Z)
```
Timestamp: Tue Jul 14 08:13:53 PM EDT 2026
Elapsed: 1h103m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:13:53.316072+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 115 — T+114:00 (2026-07-15T00:14:04Z)
```
Timestamp: Tue Jul 14 08:14:04 PM EDT 2026
Elapsed: 1h114m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:14:04.832054+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 105 — T+104:00 (2026-07-15T00:14:53Z)
```
Timestamp: Tue Jul 14 08:14:53 PM EDT 2026
Elapsed: 1h104m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:14:53.503845+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 116 — T+115:00 (2026-07-15T00:15:04Z)
```
Timestamp: Tue Jul 14 08:15:04 PM EDT 2026
Elapsed: 1h115m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:15:04.932979+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 106 — T+105:00 (2026-07-15T00:15:53Z)
```
Timestamp: Tue Jul 14 08:15:53 PM EDT 2026
Elapsed: 1h105m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:15:53.620802+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 117 — T+116:00 (2026-07-15T00:16:05Z)
```
Timestamp: Tue Jul 14 08:16:05 PM EDT 2026
Elapsed: 1h116m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:16:05.036780+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 107 — T+106:00 (2026-07-15T00:16:53Z)
```
Timestamp: Tue Jul 14 08:16:53 PM EDT 2026
Elapsed: 1h106m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:16:53.746378+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 118 — T+117:00 (2026-07-15T00:17:05Z)
```
Timestamp: Tue Jul 14 08:17:05 PM EDT 2026
Elapsed: 1h117m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:17:05.136392+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 108 — T+107:00 (2026-07-15T00:17:53Z)
```
Timestamp: Tue Jul 14 08:17:53 PM EDT 2026
Elapsed: 1h107m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:17:53.873986+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 119 — T+118:00 (2026-07-15T00:18:05Z)
```
Timestamp: Tue Jul 14 08:18:05 PM EDT 2026
Elapsed: 1h118m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:18:05.246859+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 109 — T+108:00 (2026-07-15T00:18:54Z)
```
Timestamp: Tue Jul 14 08:18:54 PM EDT 2026
Elapsed: 1h108m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:18:54.293702+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 120 — T+119:00 (2026-07-15T00:19:05Z)
```
Timestamp: Tue Jul 14 08:19:05 PM EDT 2026
Elapsed: 1h119m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:19:05.375825+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 110 — T+109:00 (2026-07-15T00:19:54Z)
```
Timestamp: Tue Jul 14 08:19:54 PM EDT 2026
Elapsed: 1h109m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:19:54.447046+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 121 — T+120:00 (2026-07-15T00:20:05Z)
```
Timestamp: Tue Jul 14 08:20:05 PM EDT 2026
Elapsed: 2h120m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:20:05.481613+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 111 — T+110:00 (2026-07-15T00:20:54Z)
```
Timestamp: Tue Jul 14 08:20:54 PM EDT 2026
Elapsed: 1h110m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:20:54.556438+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 122 — T+121:00 (2026-07-15T00:21:05Z)
```
Timestamp: Tue Jul 14 08:21:05 PM EDT 2026
Elapsed: 2h121m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:21:05.594955+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 112 — T+111:00 (2026-07-15T00:21:54Z)
```
Timestamp: Tue Jul 14 08:21:54 PM EDT 2026
Elapsed: 1h111m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:21:54.660139+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 123 — T+122:00 (2026-07-15T00:22:05Z)
```
Timestamp: Tue Jul 14 08:22:05 PM EDT 2026
Elapsed: 2h122m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:22:05.860423+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 113 — T+112:00 (2026-07-15T00:22:54Z)
```
Timestamp: Tue Jul 14 08:22:54 PM EDT 2026
Elapsed: 1h112m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:22:54.763797+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 124 — T+123:00 (2026-07-15T00:23:05Z)
```
Timestamp: Tue Jul 14 08:23:05 PM EDT 2026
Elapsed: 2h123m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:23:05.965779+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 114 — T+113:00 (2026-07-15T00:23:54Z)
```
Timestamp: Tue Jul 14 08:23:54 PM EDT 2026
Elapsed: 1h113m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:23:54.867824+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 125 — T+124:00 (2026-07-15T00:24:06Z)
```
Timestamp: Tue Jul 14 08:24:06 PM EDT 2026
Elapsed: 2h124m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:24:06.069730+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 115 — T+114:00 (2026-07-15T00:24:55Z)
```
Timestamp: Tue Jul 14 08:24:55 PM EDT 2026
Elapsed: 1h114m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:24:54.985066+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 126 — T+125:00 (2026-07-15T00:25:06Z)
```
Timestamp: Tue Jul 14 08:25:06 PM EDT 2026
Elapsed: 2h125m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:25:06.173024+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 116 — T+115:00 (2026-07-15T00:25:55Z)
```
Timestamp: Tue Jul 14 08:25:55 PM EDT 2026
Elapsed: 1h115m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:25:55.093502+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 127 — T+126:00 (2026-07-15T00:26:06Z)
```
Timestamp: Tue Jul 14 08:26:06 PM EDT 2026
Elapsed: 2h126m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:26:06.270869+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 117 — T+116:00 (2026-07-15T00:26:55Z)
```
Timestamp: Tue Jul 14 08:26:55 PM EDT 2026
Elapsed: 1h116m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:26:55.193724+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 128 — T+127:00 (2026-07-15T00:27:06Z)
```
Timestamp: Tue Jul 14 08:27:06 PM EDT 2026
Elapsed: 2h127m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:27:06.355736+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 118 — T+117:00 (2026-07-15T00:27:55Z)
```
Timestamp: Tue Jul 14 08:27:55 PM EDT 2026
Elapsed: 1h117m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:27:55.312924+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 129 — T+128:00 (2026-07-15T00:28:06Z)
```
Timestamp: Tue Jul 14 08:28:06 PM EDT 2026
Elapsed: 2h128m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:28:06.460593+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 119 — T+118:00 (2026-07-15T00:28:55Z)
```
Timestamp: Tue Jul 14 08:28:55 PM EDT 2026
Elapsed: 1h118m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:28:55.869617+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 130 — T+129:00 (2026-07-15T00:29:06Z)
```
Timestamp: Tue Jul 14 08:29:06 PM EDT 2026
Elapsed: 2h129m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:29:06.590774+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 120 — T+119:00 (2026-07-15T00:29:56Z)
```
Timestamp: Tue Jul 14 08:29:56 PM EDT 2026
Elapsed: 1h119m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:29:56.044230+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 131 — T+130:00 (2026-07-15T00:30:06Z)
```
Timestamp: Tue Jul 14 08:30:06 PM EDT 2026
Elapsed: 2h130m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:30:06.688833+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 121 — T+120:00 (2026-07-15T00:30:56Z)
```
Timestamp: Tue Jul 14 08:30:56 PM EDT 2026
Elapsed: 2h120m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:30:56.176078+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 132 — T+131:00 (2026-07-15T00:31:06Z)
```
Timestamp: Tue Jul 14 08:31:06 PM EDT 2026
Elapsed: 2h131m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:31:06.935133+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 122 — T+121:00 (2026-07-15T00:31:56Z)
```
Timestamp: Tue Jul 14 08:31:56 PM EDT 2026
Elapsed: 2h121m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:31:56.282203+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 133 — T+132:00 (2026-07-15T00:32:07Z)
```
Timestamp: Tue Jul 14 08:32:07 PM EDT 2026
Elapsed: 2h132m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:32:07.031253+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 123 — T+122:00 (2026-07-15T00:32:56Z)
```
Timestamp: Tue Jul 14 08:32:56 PM EDT 2026
Elapsed: 2h122m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:32:56.407283+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 134 — T+133:00 (2026-07-15T00:33:07Z)
```
Timestamp: Tue Jul 14 08:33:07 PM EDT 2026
Elapsed: 2h133m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:33:07.137705+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 124 — T+123:00 (2026-07-15T00:33:56Z)
```
Timestamp: Tue Jul 14 08:33:56 PM EDT 2026
Elapsed: 2h123m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:33:56.508271+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 135 — T+134:00 (2026-07-15T00:34:07Z)
```
Timestamp: Tue Jul 14 08:34:07 PM EDT 2026
Elapsed: 2h134m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:34:07.251564+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 125 — T+124:00 (2026-07-15T00:34:56Z)
```
Timestamp: Tue Jul 14 08:34:56 PM EDT 2026
Elapsed: 2h124m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:34:56.608016+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 136 — T+135:00 (2026-07-15T00:35:07Z)
```
Timestamp: Tue Jul 14 08:35:07 PM EDT 2026
Elapsed: 2h135m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:35:07.356076+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 126 — T+125:00 (2026-07-15T00:35:56Z)
```
Timestamp: Tue Jul 14 08:35:56 PM EDT 2026
Elapsed: 2h125m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:35:56.713431+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 137 — T+136:00 (2026-07-15T00:36:07Z)
```
Timestamp: Tue Jul 14 08:36:07 PM EDT 2026
Elapsed: 2h136m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:36:07.461149+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 127 — T+126:00 (2026-07-15T00:36:56Z)
```
Timestamp: Tue Jul 14 08:36:56 PM EDT 2026
Elapsed: 2h126m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:36:56.821674+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 138 — T+137:00 (2026-07-15T00:37:07Z)
```
Timestamp: Tue Jul 14 08:37:07 PM EDT 2026
Elapsed: 2h137m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:37:07.554804+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 128 — T+127:00 (2026-07-15T00:37:56Z)
```
Timestamp: Tue Jul 14 08:37:56 PM EDT 2026
Elapsed: 2h127m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:37:56.943663+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 139 — T+138:00 (2026-07-15T00:38:07Z)
```
Timestamp: Tue Jul 14 08:38:07 PM EDT 2026
Elapsed: 2h138m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:38:07.677414+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 129 — T+128:00 (2026-07-15T00:38:57Z)
```
Timestamp: Tue Jul 14 08:38:57 PM EDT 2026
Elapsed: 2h128m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:38:57.047000+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 140 — T+139:00 (2026-07-15T00:39:07Z)
```
Timestamp: Tue Jul 14 08:39:07 PM EDT 2026
Elapsed: 2h139m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:39:07.777939+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 130 — T+129:00 (2026-07-15T00:39:57Z)
```
Timestamp: Tue Jul 14 08:39:57 PM EDT 2026
Elapsed: 2h129m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:39:57.148931+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

### Iteration 141 — T+140:00 (2026-07-15T00:40:08Z)
```
Timestamp: Tue Jul 14 08:40:08 PM EDT 2026
Elapsed: 2h140m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:40:08.124426+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```

---

## ROOT CAUSE ANALYSIS — Gate Behavior Is Correct

**Current State (T+2h 5m):**
- Tuner: B-grade=true, loss_prob_threshold=0.85 ✅
- Decision gate: Reading adaptive threshold ✅
- Paper loop: Restarted with latest code ✅
- Candidates evaluated: 11 total, 0 accepted

**Block Analysis:**
- 9 candidates blocked for "LOSS_PROBABILITY_TOO_HIGH" (0.90)
- 2 candidates blocked for "ATR_STOP_CLUSTER"

**Candidates examined:**
- Loss probability: 0.90 (blocked even at 0.85 threshold)
- Primary block reason: "EXPECTED_EDGE_AFTER_COST_NON_POSITIVE"
- Secondary block reasons: Microstructure trust low, FVG misaligned, exit feasibility low

**Key Finding:**
The 0.90 loss probability is CORRECT — these candidates have NEGATIVE economic edge.
The gate is working perfectly by blocking them. The issue is NOT the gate — it's that
new candidates being generated have poor fundamental quality.

**Comparison to Successful Trades (8 trades, 62.5% win rate):**
- Confidence: 0.55-0.72 (moderate)
- Edge: null (not pre-computed/different flow)
- Outcome: Profitable

**Hypothesis:**
The successful 8 trades may have followed a different code path that didn't pre-compute
edge fields, OR they were generated in different market conditions with better features.
New candidates are properly computed but have negative edge in current market.

**Next Steps Needed:**
1. Restore missing Moralis features (15 features: aicoin, defillama, surf, etc.)
2. Check feature freshness/quality in current pipeline
3. Verify trainer model quality (gate is well-calibrated, model may need retraining)
4. Consider that market conditions have changed since the 8 winning trades were executed

**Adaptive System Status:**
✅ System is adaptive and self-correcting
✅ Gate correctly rejects poor-quality candidates
✅ Threshold tuning is working (0.85 when b_grade=true)
✅ Monitoring loop is capturing real outcomes
⚠️  Upstream issue: Candidate quality, not gate quality


### Iteration 131 — T+130:00 (2026-07-15T00:40:57Z)
```
Timestamp: Tue Jul 14 08:40:57 PM EDT 2026
Elapsed: 2h130m
A-Grade Ready: FALSE
Confidence Threshold: 0.8
B-Grade Enabled: TRUE ✅

Full Tuning State:
INFO:__main__:Adaptive tuning: confidence_threshold=0.8, loss_prob_threshold=0.85, b_grade=True, a_grade=False
{
  "outcomes": {
    "status": "OK",
    "sample_size": 8,
    "recent_sample": 8,
    "confidence_bins": {
      "high": {
        "count": 0,
        "win_rate": 0.0
      },
      "medium": {
        "count": 8,
        "win_rate": 0.625
      },
      "low": {
        "count": 0,
        "win_rate": 0.0
      }
    },
    "overall_win_rate": 0.625,
    "a_grade_count": 0,
    "b_grade_count": 0,
    "probation_count": 0,
    "total_pnl_usd": 0.8418772932059472,
    "average_pnl_per_trade": 0.1052346616507434
  },
  "market_regime": {
    "status": "INSUFFICIENT_DATA"
  },
  "adaptive_confidence_threshold": 0.8,
  "adaptive_loss_probability_threshold": 0.85,
  "enable_b_grade": true,
  "enable_a_grade": false,
  "a_grade_ready": false,
  "blockers_resolved": false,
  "generated_at": "2026-07-15T00:40:57.283541+00:00",
  "schema_version": "adaptive_gate_tuning_v1"
}
```
