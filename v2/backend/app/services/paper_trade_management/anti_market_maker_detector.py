"""Phase 9: Anti-market-maker detection — 6 independent detectors.

Each detector is a pure function that accepts a feature/orderbook snapshot
and returns a standardized detection result.

Detectors:
    1. sweep_up_down         — large rapid price sweep against retail direction
    2. spoof_wall_pull       — large order appears then vanishes (spoofing)
    3. liquidity_hunt        — price manipulation to trigger retail stops
    4. depth_tape_divergence — orderbook depth/shape doesn't match actual tape
    5. toxic_flow            — adverse-selection indicators in trade flow
    6. stop_run_risk         — price proximity to known stop-cluster zones

Wiring:
    - ENTRY_BLOCK: block new entries when detected
    - EXIT_ACCELERATE: accelerate exit on open positions when detected
    - SIZE_REDUCE: reduce position size (paper mode only) when detected

All detectors fail-safe: when data is missing, `detected=False`.
None place exchange orders. None mutate Redis. Live gate: blocked_human_only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SCHEMA_VERSION = "v2_anti_mm_detector_v1"

# Wiring actions
ACTION_ENTRY_BLOCK = "ENTRY_BLOCK"
ACTION_EXIT_ACCELERATE = "EXIT_ACCELERATE"
ACTION_SIZE_REDUCE = "SIZE_REDUCE"
ACTION_NONE = "NONE"


@dataclass(frozen=True)
class DetectionResult:
    detector: str
    detected: bool
    confidence: float  # 0–1
    reason: str
    actions: tuple[str, ...]  # ENTRY_BLOCK | EXIT_ACCELERATE | SIZE_REDUCE | NONE
    evidence: dict  # raw inputs used for the decision


def _coerce(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ── Detector 1: Sweep Up / Down ───────────────────────────────────────────────

def detect_sweep(
    *,
    price_change_bps: float | None,
    volume_spike_ratio: float | None = None,
    sweep_up_detected: bool | None = None,
    sweep_down_detected: bool | None = None,
    sweep_threshold_bps: float = 50.0,
    volume_spike_threshold: float = 3.0,
) -> DetectionResult:
    """Detect rapid price sweeps suggesting market-maker aggressive liquidity takeout.

    Fires when price moves >= sweep_threshold_bps in a single period AND
    volume spike is high (suggesting sweep, not organic trend).
    Also honours raw feature flags if present.
    """
    evidence = {
        "price_change_bps": price_change_bps,
        "volume_spike_ratio": volume_spike_ratio,
        "sweep_up_detected": sweep_up_detected,
        "sweep_down_detected": sweep_down_detected,
    }
    # Honour pre-computed flags from feature pipeline
    if sweep_up_detected or sweep_down_detected:
        return DetectionResult(
            detector="SWEEP_UP_DOWN",
            detected=True,
            confidence=0.85,
            reason="SWEEP_FLAG_FROM_FEATURE_PIPELINE",
            actions=(ACTION_ENTRY_BLOCK, ACTION_EXIT_ACCELERATE),
            evidence=evidence,
        )
    pc = _coerce(price_change_bps)
    vs = _coerce(volume_spike_ratio)
    if pc is None:
        return DetectionResult(
            detector="SWEEP_UP_DOWN",
            detected=False,
            confidence=0.0,
            reason="INSUFFICIENT_DATA",
            actions=(ACTION_NONE,),
            evidence=evidence,
        )
    sweep = abs(pc) >= sweep_threshold_bps
    vol_confirm = vs is not None and vs >= volume_spike_threshold
    detected = sweep and vol_confirm if vs is not None else sweep
    confidence = min(0.9, abs(pc) / sweep_threshold_bps * 0.5 + (0.3 if vol_confirm else 0.0))
    return DetectionResult(
        detector="SWEEP_UP_DOWN",
        detected=detected,
        confidence=round(min(1.0, confidence), 3) if detected else 0.0,
        reason=f"SWEEP:price={pc:.0f}bps,vol_spike={vs}" if detected else "NO_SWEEP",
        actions=(ACTION_ENTRY_BLOCK, ACTION_EXIT_ACCELERATE) if detected else (ACTION_NONE,),
        evidence=evidence,
    )


# ── Detector 2: Spoof / Wall Pull ────────────────────────────────────────────

def detect_spoof_wall_pull(
    *,
    spoof_detected: bool | None = None,
    spoof_score: float | None = None,
    wall_pull_detected: bool | None = None,
    ob_imbalance: float | None = None,
    spoof_score_threshold: float = 0.65,
    ob_imbalance_reversal_threshold: float = 0.70,
) -> DetectionResult:
    """Detect spoofing (large order appears then pulled before fill)."""
    evidence = {
        "spoof_detected": spoof_detected,
        "spoof_score": spoof_score,
        "wall_pull_detected": wall_pull_detected,
        "ob_imbalance": ob_imbalance,
    }
    if spoof_detected or wall_pull_detected:
        return DetectionResult(
            detector="SPOOF_WALL_PULL",
            detected=True,
            confidence=0.80,
            reason="SPOOF_FLAG_FROM_FEATURE_PIPELINE",
            actions=(ACTION_ENTRY_BLOCK, ACTION_SIZE_REDUCE),
            evidence=evidence,
        )
    ss = _coerce(spoof_score)
    if ss is not None and ss >= spoof_score_threshold:
        return DetectionResult(
            detector="SPOOF_WALL_PULL",
            detected=True,
            confidence=round(min(1.0, ss), 3),
            reason=f"HIGH_SPOOF_SCORE:{ss:.3f}",
            actions=(ACTION_ENTRY_BLOCK, ACTION_SIZE_REDUCE),
            evidence=evidence,
        )
    return DetectionResult(
        detector="SPOOF_WALL_PULL",
        detected=False,
        confidence=0.0,
        reason="NO_SPOOF_EVIDENCE",
        actions=(ACTION_NONE,),
        evidence=evidence,
    )


# ── Detector 3: Liquidity Hunt ────────────────────────────────────────────────

def detect_liquidity_hunt(
    *,
    liquidity_hunt_detected: bool | None = None,
    price_touched_stop_zone: bool | None = None,
    liquidation_count_5m: int | None = None,
    nearest_liquidation_level_above: float | None = None,
    nearest_liquidation_level_below: float | None = None,
    mark_price: float | None = None,
    liquidity_hunt_liq_count_threshold: int = 5,
    liquidation_proximity_pct: float = 0.005,  # 0.5% from mark
) -> DetectionResult:
    """Detect patterns consistent with hunting retail stop/liquidation clusters."""
    evidence = {
        "liquidity_hunt_detected": liquidity_hunt_detected,
        "liquidation_count_5m": liquidation_count_5m,
        "price_touched_stop_zone": price_touched_stop_zone,
    }
    if liquidity_hunt_detected or price_touched_stop_zone:
        return DetectionResult(
            detector="LIQUIDITY_HUNT",
            detected=True,
            confidence=0.80,
            reason="LIQUIDITY_HUNT_FLAG_FROM_PIPELINE",
            actions=(ACTION_ENTRY_BLOCK, ACTION_EXIT_ACCELERATE),
            evidence=evidence,
        )
    lc = liquidation_count_5m
    if lc is not None and lc >= liquidity_hunt_liq_count_threshold:
        return DetectionResult(
            detector="LIQUIDITY_HUNT",
            detected=True,
            confidence=round(min(1.0, lc / (liquidity_hunt_liq_count_threshold * 2)), 3),
            reason=f"HIGH_LIQUIDATION_COUNT_5M:{lc}",
            actions=(ACTION_ENTRY_BLOCK, ACTION_EXIT_ACCELERATE),
            evidence=evidence,
        )
    # Check proximity to known liquidation levels
    if mark_price and mark_price > 0:
        for level, label in [
            (nearest_liquidation_level_above, "above"),
            (nearest_liquidation_level_below, "below"),
        ]:
            if level and level > 0:
                proximity = abs(mark_price - level) / mark_price
                if proximity <= liquidation_proximity_pct:
                    return DetectionResult(
                        detector="LIQUIDITY_HUNT",
                        detected=True,
                        confidence=round(1.0 - proximity / liquidation_proximity_pct, 3),
                        reason=f"PRICE_NEAR_LIQUIDATION_CLUSTER_{label.upper()}",
                        actions=(ACTION_ENTRY_BLOCK, ACTION_EXIT_ACCELERATE),
                        evidence=evidence,
                    )
    return DetectionResult(
        detector="LIQUIDITY_HUNT",
        detected=False,
        confidence=0.0,
        reason="NO_LIQUIDITY_HUNT_EVIDENCE",
        actions=(ACTION_NONE,),
        evidence=evidence,
    )


# ── Detector 4: Depth vs Tape Divergence ─────────────────────────────────────

def detect_depth_tape_divergence(
    *,
    depth_vs_tape_divergence: float | None = None,
    ob_imbalance: float | None = None,
    taker_buy_ratio: float | None = None,
    divergence_threshold: float = 0.40,
) -> DetectionResult:
    """Detect when orderbook depth (imbalance) diverges from actual tape (taker flow).

    High ob_imbalance (bids >> asks) with low taker_buy_ratio means
    the visible bid wall is not absorbing actual sell flow — suspicious.
    """
    evidence = {
        "depth_vs_tape_divergence": depth_vs_tape_divergence,
        "ob_imbalance": ob_imbalance,
        "taker_buy_ratio": taker_buy_ratio,
    }
    dtd = _coerce(depth_vs_tape_divergence)
    if dtd is not None:
        detected = abs(dtd) >= divergence_threshold
        return DetectionResult(
            detector="DEPTH_TAPE_DIVERGENCE",
            detected=detected,
            confidence=round(min(1.0, abs(dtd) / divergence_threshold * 0.7), 3) if detected else 0.0,
            reason=f"DEPTH_TAPE_DIVERGENCE:{dtd:.3f}" if detected else "NO_DIVERGENCE",
            actions=(ACTION_ENTRY_BLOCK, ACTION_SIZE_REDUCE) if detected else (ACTION_NONE,),
            evidence=evidence,
        )
    # Derive from ob_imbalance vs taker_buy_ratio
    obi = _coerce(ob_imbalance)
    tbr = _coerce(taker_buy_ratio)
    if obi is not None and tbr is not None:
        # ob_imbalance = (bids - asks) / total: positive means bid heavy
        # If bid_heavy but taker_buy < 0.4, divergence detected
        divergence = obi > 0.3 and tbr < 0.4
        divergence_score = abs(obi - (tbr - 0.5)) if divergence else 0.0
        return DetectionResult(
            detector="DEPTH_TAPE_DIVERGENCE",
            detected=divergence,
            confidence=round(min(1.0, divergence_score), 3) if divergence else 0.0,
            reason=f"OB_IMBALANCE_VS_TAPE:obi={obi:.2f},tbr={tbr:.2f}" if divergence else "NO_DIVERGENCE",
            actions=(ACTION_ENTRY_BLOCK, ACTION_SIZE_REDUCE) if divergence else (ACTION_NONE,),
            evidence=evidence,
        )
    return DetectionResult(
        detector="DEPTH_TAPE_DIVERGENCE",
        detected=False,
        confidence=0.0,
        reason="INSUFFICIENT_DATA",
        actions=(ACTION_NONE,),
        evidence=evidence,
    )


# ── Detector 5: Toxic Flow ────────────────────────────────────────────────────

def detect_toxic_flow(
    *,
    toxicity_proxy: float | None = None,
    order_flow_imbalance: float | None = None,
    tape_imbalance: float | None = None,
    toxicity_threshold: float = 0.65,
) -> DetectionResult:
    """Detect toxic/adverse-selection trade flow.

    Uses the existing toxicity_proxy feature (spread + imbalance composite)
    and/or raw order flow imbalance from the tape.
    """
    evidence = {
        "toxicity_proxy": toxicity_proxy,
        "order_flow_imbalance": order_flow_imbalance,
        "tape_imbalance": tape_imbalance,
    }
    tp = _coerce(toxicity_proxy)
    if tp is not None:
        detected = tp >= toxicity_threshold
        return DetectionResult(
            detector="TOXIC_FLOW",
            detected=detected,
            confidence=round(min(1.0, tp), 3) if detected else 0.0,
            reason=f"HIGH_TOXICITY_PROXY:{tp:.3f}" if detected else f"TOXICITY_ACCEPTABLE:{tp:.3f}",
            actions=(ACTION_ENTRY_BLOCK, ACTION_SIZE_REDUCE) if detected else (ACTION_NONE,),
            evidence=evidence,
        )
    # Fall back to raw order flow imbalance
    ofi = _coerce(order_flow_imbalance)
    if ofi is not None:
        detected = abs(ofi) >= toxicity_threshold
        return DetectionResult(
            detector="TOXIC_FLOW",
            detected=detected,
            confidence=round(min(1.0, abs(ofi)), 3) if detected else 0.0,
            reason=f"HIGH_OFI:{ofi:.3f}" if detected else "NO_TOXIC_FLOW",
            actions=(ACTION_ENTRY_BLOCK, ACTION_SIZE_REDUCE) if detected else (ACTION_NONE,),
            evidence=evidence,
        )
    return DetectionResult(
        detector="TOXIC_FLOW",
        detected=False,
        confidence=0.0,
        reason="INSUFFICIENT_DATA",
        actions=(ACTION_NONE,),
        evidence=evidence,
    )


# ── Detector 6: Stop-Run Risk ─────────────────────────────────────────────────

def detect_stop_run_risk(
    *,
    recent_wick_ratio: float | None = None,
    price_touched_round_number: bool | None = None,
    liquidation_count_1m: int | None = None,
    stop_run_risk_score: float | None = None,
    wick_ratio_threshold: float = 0.60,
    liq_count_1m_threshold: int = 3,
    stop_run_score_threshold: float = 0.55,
) -> DetectionResult:
    """Detect stop-run risk — price rapidly reaching stop clusters to fill MM.

    Signals: large wicks, round-number touches, liquidation bursts in 1m.
    """
    evidence = {
        "recent_wick_ratio": recent_wick_ratio,
        "price_touched_round_number": price_touched_round_number,
        "liquidation_count_1m": liquidation_count_1m,
        "stop_run_risk_score": stop_run_risk_score,
    }
    srrs = _coerce(stop_run_risk_score)
    if srrs is not None and srrs >= stop_run_score_threshold:
        return DetectionResult(
            detector="STOP_RUN_RISK",
            detected=True,
            confidence=round(min(1.0, srrs), 3),
            reason=f"HIGH_STOP_RUN_RISK_SCORE:{srrs:.3f}",
            actions=(ACTION_ENTRY_BLOCK, ACTION_EXIT_ACCELERATE),
            evidence=evidence,
        )
    wr = _coerce(recent_wick_ratio)
    lc1m = liquidation_count_1m
    signs = 0
    reasons: list[str] = []
    if wr is not None and wr >= wick_ratio_threshold:
        signs += 1
        reasons.append(f"LARGE_WICK:{wr:.2f}")
    if price_touched_round_number:
        signs += 1
        reasons.append("ROUND_NUMBER_TOUCH")
    if lc1m is not None and lc1m >= liq_count_1m_threshold:
        signs += 1
        reasons.append(f"LIQ_BURST_1M:{lc1m}")
    detected = signs >= 2
    return DetectionResult(
        detector="STOP_RUN_RISK",
        detected=detected,
        confidence=round(signs / 3, 3) if detected else 0.0,
        reason=",".join(reasons) if detected else "NO_STOP_RUN_SIGNS",
        actions=(ACTION_ENTRY_BLOCK, ACTION_EXIT_ACCELERATE) if detected else (ACTION_NONE,),
        evidence=evidence,
    )


# ── Composite evaluation ──────────────────────────────────────────────────────

def evaluate_all_detectors(features: dict) -> dict[str, Any]:
    """Run all 6 detectors against a feature snapshot.

    Returns a composite result with per-detector results and combined action set.
    """
    sweep = detect_sweep(
        price_change_bps=_coerce(features.get("price_change_bps")),
        volume_spike_ratio=_coerce(features.get("volume_spike_ratio")),
        sweep_up_detected=features.get("sweep_up_detected"),
        sweep_down_detected=features.get("sweep_down_detected"),
    )
    spoof = detect_spoof_wall_pull(
        spoof_detected=features.get("spoof_detected"),
        spoof_score=_coerce(features.get("spoof_score")),
        wall_pull_detected=features.get("wall_pull_detected"),
        ob_imbalance=_coerce(features.get("ob_imbalance")),
    )
    liq_hunt = detect_liquidity_hunt(
        liquidity_hunt_detected=features.get("liquidity_hunt_detected"),
        price_touched_stop_zone=features.get("price_touched_stop_zone"),
        liquidation_count_5m=features.get("liquidation_count_5m"),
        nearest_liquidation_level_above=_coerce(features.get("nearest_liquidation_level_above")),
        nearest_liquidation_level_below=_coerce(features.get("nearest_liquidation_level_below")),
        mark_price=_coerce(features.get("mark_price")),
    )
    dtd = detect_depth_tape_divergence(
        depth_vs_tape_divergence=_coerce(features.get("depth_vs_tape_divergence")),
        ob_imbalance=_coerce(features.get("ob_imbalance")),
        taker_buy_ratio=_coerce(features.get("taker_buy_ratio")),
    )
    toxic = detect_toxic_flow(
        toxicity_proxy=_coerce(features.get("toxicity_proxy")),
        order_flow_imbalance=_coerce(features.get("order_flow_imbalance")),
        tape_imbalance=_coerce(features.get("tape_imbalance")),
    )
    stop_run = detect_stop_run_risk(
        recent_wick_ratio=_coerce(features.get("recent_wick_ratio")),
        price_touched_round_number=features.get("price_touched_round_number"),
        liquidation_count_1m=features.get("liquidation_count_1m"),
        stop_run_risk_score=_coerce(features.get("stop_run_risk_score")),
    )

    detectors = [sweep, spoof, liq_hunt, dtd, toxic, stop_run]
    triggered = [d for d in detectors if d.detected]
    all_actions: set[str] = set()
    for d in triggered:
        all_actions.update(d.actions)
    all_actions.discard(ACTION_NONE)

    return {
        "schema_version": SCHEMA_VERSION,
        "any_detected": len(triggered) > 0,
        "triggered_count": len(triggered),
        "combined_actions": sorted(all_actions),
        "entry_blocked": ACTION_ENTRY_BLOCK in all_actions,
        "exit_accelerated": ACTION_EXIT_ACCELERATE in all_actions,
        "size_reduced": ACTION_SIZE_REDUCE in all_actions,
        "detectors": {
            "sweep_up_down": {"detected": sweep.detected, "confidence": sweep.confidence, "reason": sweep.reason},
            "spoof_wall_pull": {"detected": spoof.detected, "confidence": spoof.confidence, "reason": spoof.reason},
            "liquidity_hunt": {"detected": liq_hunt.detected, "confidence": liq_hunt.confidence, "reason": liq_hunt.reason},
            "depth_tape_divergence": {"detected": dtd.detected, "confidence": dtd.confidence, "reason": dtd.reason},
            "toxic_flow": {"detected": toxic.detected, "confidence": toxic.confidence, "reason": toxic.reason},
            "stop_run_risk": {"detected": stop_run.detected, "confidence": stop_run.confidence, "reason": stop_run.reason},
        },
        "live_gate": "blocked_human_only",
        "mutates_exchange": False,
    }
