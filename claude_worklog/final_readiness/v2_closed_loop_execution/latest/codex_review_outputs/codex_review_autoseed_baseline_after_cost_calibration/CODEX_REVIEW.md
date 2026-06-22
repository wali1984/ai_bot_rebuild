# Codex Review: codex_review_autoseed_baseline_after_cost_calibration

GO/NO-GO: `V2_AUTONOMOUS_BASELINE_AFTER_COST_CALIBRATION_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Blockers

- 1. Add `_fit_after_cost_calibration()` — closed-form least-squares of `after_cost_return_bps ~ a + b·p` on TRAINABLE rows only, gated by sample count and RMSE-improvement vs the hardcoded `(p−0.5)·50 − 7` formula.

## Raw Output (tail)

```text
            label_row = label_rows_by_snapshot.get(str(snapshot_id))
            risk_decision = None  # avoid scanning RISK_DECISIONS list payload per row
            row = build_dataset_row(
                symbol=symbol,
                timeframe=tf,
                features=features,
                ta=ta,
                altdata=altdata,
                risk_decision=risk_decision,
                label_row=label_row,
            )
            rows.append(row)
    return DatasetBuildResult(
        rows=rows,
        universe=universe_list,
        timeframes=timeframes_list,
        labels_loaded=len(label_rows_by_snapshot),
        non_v2_read_attempts=reader.non_v2_read_attempts,
        read_errors=reader.read_errors,
    )


def build_rows_from_replay_bundles(
    replay_bundles_path: Path,
    *,
    max_rows: int | None = None,
) -> list[DatasetRow]:
    """Build dataset rows directly from V2 replay-outcome bundles.

    Each bundle is a feature-snapshot-anchored evidence record produced
    by the V2 post-hoc replay-outcome miner. The bundle's
    ``orchestrator_decision.bucket_winners[*]`` carry the winning
    confidence + expected-move features and the future-outcomes window
    carries the after-cost label. Together they form a complete row.
    """
    rows: list[DatasetRow] = []
    if not replay_bundles_path.exists():
        return rows
    with replay_bundles_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                bundle = json.loads(line)
            except (TypeError, ValueError):
                continue
            outcomes = bundle.get("future_outcomes") or {}
            primary = _select_primary_outcome(outcomes) or {}
            after_cost = primary.get("after_cost_return_bps")
            label = bundle.get("label") or _label_for_outcome(
                after_cost,
                (bundle.get("paper_gate_decision") or {}).get("status"),
            )
            orchestrator = bundle.get("orchestrator_decision") or {}
            winners = orchestrator.get("bucket_winners") or []
            if not winners:
                continue
            for winner in winners:
                symbol = str(winner.get("symbol") or bundle.get("symbol") or "")
                if not symbol:
                    continue
                timeframe = str(bundle.get("timeframe") or "1m")
                snapshot_id = str(
                    bundle.get("feature_snapshot_id")
                    or f"{symbol}:{timeframe}:replay:{bundle.get('generated_at') or ''}"
                )
                conf = winner.get("winner_confidence_calibrated")
                expected_move_after_cost = winner.get(
                    "winner_expected_move_after_cost_bps"
                )
                freshness = winner.get("winner_freshness_seconds")
                # Synthesize a stable feature vector from the orchestrator
                # decision summary. These features describe the prediction
                # that drove the historical action and are the most honest
                # V2-native signals available from a replay bundle.
                vector = {
                    "ema_9": None,
                    "ema_21": None,
                    "ema_spread": (
                        float(expected_move_after_cost) / 10.0
                        if expected_move_after_cost is not None
                        else None
                    ),
                    "rsi_14": (
                        50.0 + (float(conf) - 0.5) * 40.0
                        if conf is not None
                        else None
                    ),
                    "macd": (
                        float(expected_move_after_cost)
                        if expected_move_after_cost is not None
                        else None
                    ),
                    "macd_signal": 0.0,
                    "atr_14": None,
                    "vol_zscore": None,
                    "feature_freshness_seconds": (
                        float(freshness) if freshness is not None else None
                    ),
                }
                missing = _missing_keys(vector)
                row_classification = ROW_TRAINABLE
                missing_flags: list[str] = []
                stale_flags: list[str] = []
                freshness_state = "FRESH"
                # Explicit insufficient-evidence rows stay visible in
                # their own bucket — never collapsed into LABEL_MISSING.
                if label == "insufficient_evidence":
                    row_classification = ROW_INSUFFICIENT_EVIDENCE
                elif not label or label == "label_missing":
                    row_classification = ROW_LABEL_MISSING
                elif after_cost is None:
                    row_classification = ROW_LABEL_MISSING
                row_id = _stable_row_id(symbol, timeframe, snapshot_id)
                if row_classification == ROW_TRAINABLE and _is_held_out(row_id):
                    row_classification = ROW_HELD_OUT_VALIDATION
                paper_gate = bundle.get("paper_gate_decision") or {}
                rows.append(DatasetRow(
                    row_id=row_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    feature_snapshot_id=snapshot_id,
                    generated_at=str(bundle.get("generated_at") or ""),
                    feature_vector=vector,
                    missing_feature_flags=missing_flags,
                    stale_feature_flags=stale_flags,
                    feature_freshness_state=freshness_state,
                    label=str(label),
                    after_cost_return_bps=after_cost,
                    max_favorable_bps=primary.get("max_favorable_bps"),
                    max_adverse_bps=primary.get("max_adverse_bps"),
                    paper_gate_status=paper_gate.get("status"),
                    paper_gate_block_reasons=list(
                        paper_gate.get("block_reasons") or []
                    ),
                    risk_decision_context=bundle.get("risk_decision"),
                    altdata_context=bundle.get("altdata_snapshot"),
                    legacy_reference_action=bundle.get("legacy_reference_action"),
                    classification=row_classification,
                    source_lineage=["replay_outcome_bundles.jsonl"],
                ))
                if max_rows is not None and len(rows) >= max_rows:
                    return rows
    return rows


# ---------------------------------------------------------------------------
# Dataset quality report
# ---------------------------------------------------------------------------


@dataclass
class DatasetQualityReport:
    total_rows: int
    classifications: dict[str, int]
    per_symbol_row_counts: dict[str, int]
    per_timeframe_row_counts: dict[str, int]
    label_distribution: dict[str, int]
    class_imbalance: dict[str, float]
    train_rows: int
    validation_rows: int
    insufficient_evidence_rows: int
    stale_feature_rows: int
    missing_feature_rows: int
    label_missing_rows: int
    minimum_sample_satisfied: bool
    minimum_train_rows_threshold: int

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "classifications": dict(sorted(self.classifications.items())),
            "per_symbol_row_counts": dict(sorted(self.per_symbol_row_counts.items())),
            "per_timeframe_row_counts": dict(sorted(self.per_timeframe_row_counts.items())),
            "label_distribution": dict(sorted(self.label_distribution.items())),
            "class_imbalance": dict(sorted(self.class_imbalance.items())),
            "train_rows": self.train_rows,
            "validation_rows": self.validation_rows,
            "insufficient_evidence_rows": self.insufficient_evidence_rows,
            "stale_feature_rows": self.stale_feature_rows,
            "missing_feature_rows": self.missing_feature_rows,
            "label_missing_rows": self.label_missing_rows,
            "minimum_sample_satisfied": self.minimum_sample_satisfied,
            "minimum_train_rows_threshold": self.minimum_train_rows_threshold,
        }


def build_quality_report(
    rows: Sequence[DatasetRow],
    *,
    minimum_train_rows: int = MIN_TRAIN_ROWS_FOR_READINESS,

exec
/bin/bash -lc "ps -ef | grep -E 'grep -RIl|session|baseline_after_cost' | grep -v grep | sed -n '1,20p'" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
codex
V2_AUTONOMOUS_BASELINE_AFTER_COST_CALIBRATION_CODEX_FAIL
V2_AUTONOMOUS_BASELINE_AFTER_COST_CALIBRATION_CODEX_FAIL
2026-05-24T19:50:19.804761Z ERROR codex_core::session: failed to record rollout items: thread 019e5b88-2f4c-7520-a49a-59d76e520f16 not found
```
