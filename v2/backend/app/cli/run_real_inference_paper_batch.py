"""Model Track M1 real-inference routeability gate.

Read-only gate for separating proof/default prediction artifacts from real
PPO/MASA inference candidates. It does not enable live trading, does not submit
orders, and does not lower confidence thresholds.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # pragma: no cover - import shape differs between pytest and python -m
    from app.cli.run_paper_shadow_edge_report import (
        confidence_value,
        is_routeability_candidate,
        prediction_confidence_provenance,
    )
except ModuleNotFoundError:  # pragma: no cover
    from v2.backend.app.cli.run_paper_shadow_edge_report import (
        confidence_value,
        is_routeability_candidate,
        prediction_confidence_provenance,
    )

LIQUID_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "LTCUSDT",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_real_inference_paper_batch")
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--symbols", default=",".join(LIQUID_SYMBOLS))
    parser.add_argument("--paper-only", action="store_true")
    parser.add_argument("--no-live", action="store_true")
    parser.add_argument("--max-predictions", type=int, default=50)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    symbols = tuple(symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip())

    if not args.paper_only or not args.no_live:
        report = blocked_report(
            symbols=symbols,
            reason="PAPER_ONLY_AND_NO_LIVE_FLAGS_REQUIRED",
            max_predictions=args.max_predictions,
        )
        write_outputs(output_dir, report)
        print(json.dumps(report["m1_release_gate"], indent=2, sort_keys=True, default=str))
        return 1

    client = redis_client(args.redis_url)
    report = build_m1_report(client=client, symbols=symbols, max_predictions=args.max_predictions)
    write_outputs(output_dir, report)
    print(json.dumps(report["m1_release_gate"], indent=2, sort_keys=True, default=str))
    return 0 if report["m1_release_gate"]["verdict"] == "M1 GO" else 1


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def build_m1_report(*, client: Any, symbols: tuple[str, ...], max_predictions: int) -> dict[str, Any]:
    predictions = scan_json(client, "v2:prediction:*", limit=max_predictions * 10)
    proof_predictions = scan_json(client, "v2:proof:prediction:*", limit=max_predictions * 10)
    sidecar_predictions = scan_json(client, "v2:trainer:rl_core_prediction_sidecar:*", limit=max_predictions * 10)
    live_state = live_control_state(client)
    checkpoint = checkpoint_status(client)
    hybrid_status = read_json_key(client, "v2:trainer:hybrid_cuda:status")
    hybrid_heartbeat = read_json_key(client, "v2:trainer:hybrid_cuda:heartbeat")

    confidence_counts = Counter(prediction_confidence_provenance(row) for row in predictions)
    routeability_candidates = [row for row in predictions if is_routeability_candidate(row)]
    real_values = [confidence_value(row) for row in routeability_candidates]
    real_values = [value for value in real_values if value is not None]
    block_reasons = Counter()
    for row in predictions:
        if is_routeability_candidate(row):
            continue
        provenance = prediction_confidence_provenance(row)
        if provenance in {"PROOF_DEFAULT", "PLACEHOLDER"}:
            block_reasons["PLACEHOLDER_CONFIDENCE_BLOCK"] += 1
        elif provenance == "MISSING":
            block_reasons["MISSING_CONFIDENCE_BLOCK"] += 1
        elif provenance == "INFERRED":
            block_reasons["INFERRED_CONFIDENCE_NOT_ROUTEABLE"] += 1
        else:
            block_reasons["NOT_ROUTEABILITY_CANDIDATE"] += 1

    inventory = real_inference_producer_inventory(
        checkpoint=checkpoint,
        hybrid_status=hybrid_status,
        hybrid_heartbeat=hybrid_heartbeat,
        sidecar_count=len(sidecar_predictions),
        canonical_prediction_count=len(predictions),
    )
    root_cause = classify_root_cause(
        confidence_counts=confidence_counts,
        routeability_candidates=len(routeability_candidates),
        checkpoint=checkpoint,
        hybrid_status=hybrid_status,
        sidecar_count=len(sidecar_predictions),
    )
    gate = classify_m1_gate(
        real_model_count=len(routeability_candidates),
        placeholder_count=sum(confidence_counts.get(name, 0) for name in ("PROOF_DEFAULT", "PLACEHOLDER", "INFERRED")),
        missing_count=confidence_counts.get("MISSING", 0),
        live_state=live_state,
        root_cause=root_cause,
    )
    batch = {
        "generated_at": utc_now(),
        "symbols_requested": list(symbols),
        "max_predictions": max_predictions,
        "predictions_attempted": 0 if gate["verdict"] == "M1 NO-GO" else min(max_predictions, len(symbols)),
        "predictions_emitted": len(routeability_candidates),
        "real_model_confidence_count": len(routeability_candidates),
        "placeholder_or_default_confidence_count": sum(confidence_counts.get(name, 0) for name in ("PROOF_DEFAULT", "PLACEHOLDER", "INFERRED")),
        "missing_confidence_count": confidence_counts.get("MISSING", 0),
        "confidence_distribution": distribution(real_values),
        "confidence_threshold": 0.66,
        "predictions_above_threshold": sum(1 for value in real_values if value >= 0.66),
        "predictions_below_threshold": sum(1 for value in real_values if value < 0.66),
        "routeability_candidates": len(routeability_candidates),
        "accepted_paper_intents": 0,
        "accepted_shadow_intents": 0,
        "fills_created": 0,
        "positions_opened": 0,
        "closed_trades": 0,
        "block_reason_distribution": dict(sorted(block_reasons.items())),
        "proof_prediction_records": len(proof_predictions),
        "sidecar_prediction_records": len(sidecar_predictions),
        "canonical_prediction_records": len(predictions),
        "root_cause": root_cause,
        "live_control_state": live_state,
    }
    return {
        "real_inference_producer_inventory": inventory,
        "real_inference_batch_report": batch,
        "m1_release_gate": gate,
    }


def blocked_report(*, symbols: tuple[str, ...], reason: str, max_predictions: int) -> dict[str, Any]:
    live_state = {
        "live_gate": "unknown",
        "order_transport_submit_enabled": None,
        "live_trading_enabled": None,
        "places_real_order": None,
        "exchange_action_taken": None,
        "any_live_submit_enabled": False,
    }
    gate = {
        "generated_at": utc_now(),
        "verdict": "M1 NO-GO",
        "reason": reason,
        "live_submit_disabled": True,
        "no_live_order_submitted": True,
        "real_model_confidence_count": 0,
        "placeholder_or_default_confidence_count": 0,
        "missing_confidence_count": 0,
        "routeability_candidates": 0,
    }
    return {
        "real_inference_producer_inventory": {"generated_at": utc_now(), "producers": real_inference_producer_rows()},
        "real_inference_batch_report": {
            "generated_at": utc_now(),
            "symbols_requested": list(symbols),
            "max_predictions": max_predictions,
            "predictions_attempted": 0,
            "predictions_emitted": 0,
            "root_cause": reason,
            "live_control_state": live_state,
        },
        "m1_release_gate": gate,
    }


def scan_json(client: Any, pattern: str, *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        iterator = client.scan_iter(match=pattern, count=500)
    except Exception:
        return rows
    for key in iterator:
        payload = read_json_key(client, str(key))
        if payload:
            payload.setdefault("_key", str(key))
            rows.append(payload)
        if len(rows) >= limit:
            break
    return rows


def read_json_key(client: Any, key: str) -> dict[str, Any]:
    try:
        raw = client.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def live_control_state(client: Any) -> dict[str, Any]:
    state = {
        "live_gate": "blocked_human_only",
        "order_transport_submit_enabled": False,
        "live_trading_enabled": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "any_live_submit_enabled": False,
    }
    for key in ("v2:live_gate:state", "v2:trader:execution_state", "v2:live_order_transport:status"):
        payload = read_json_key(client, key)
        for field in ("live_gate", "order_transport_submit_enabled", "live_trading_enabled", "places_real_order", "exchange_action_taken"):
            if field in payload:
                state[field] = payload[field]
        if any(payload.get(field) is True for field in ("order_transport_submit_enabled", "live_trading_enabled", "places_real_order", "exchange_action_taken")):
            state["any_live_submit_enabled"] = True
    return state


def checkpoint_status(client: Any) -> dict[str, Any]:
    evidence = read_json_key(client, "v2:trainer:checkpoint:evidence")
    manifests = sorted(Path(".local_models/v2_native_rl_masa_ppo").glob("*.json"))
    return {
        "redis_checkpoint_evidence_present": bool(evidence),
        "redis_checkpoint_evidence": evidence,
        "local_manifest_count": len(manifests),
        "local_manifest_paths": [str(path) for path in manifests[:10]],
        "checkpoint_available_for_m1": bool(evidence.get("selected_checkpoint_id") or manifests),
        "checkpoint_weight_status": evidence.get("checkpoint_weight_status") or evidence.get("checkpoint_blocker") or "CHECKPOINT_EVIDENCE_MISSING",
    }


def real_inference_producer_inventory(
    *,
    checkpoint: Mapping[str, Any],
    hybrid_status: Mapping[str, Any],
    hybrid_heartbeat: Mapping[str, Any],
    sidecar_count: int,
    canonical_prediction_count: int,
) -> dict[str, Any]:
    rows = real_inference_producer_rows()
    for row in rows:
        if row["file_path"] == "v2/backend/app/cli/v2_rl_core_inference_loop.py":
            row["current_blocker"] = "writes sidecar namespace only; checkpoint status: " + str(checkpoint.get("checkpoint_weight_status"))
            row["current_sidecar_records"] = sidecar_count
        elif row["file_path"] == "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py":
            row["current_blocker"] = "no active REAL_MODEL canonical predictions observed" if canonical_prediction_count else "no canonical predictions observed"
            row["runtime_status_present"] = bool(hybrid_status)
            row["runtime_heartbeat_present"] = bool(hybrid_heartbeat)
    return {
        "generated_at": utc_now(),
        "checkpoint": dict(checkpoint),
        "producers": rows,
    }


def real_inference_producer_rows() -> list[dict[str, Any]]:
    return [
        producer_row(
            "v2/backend/app/cli/v2_rl_core_inference_loop.py",
            "run_once",
            reads_trusted_market_state=True,
            loads_ppo=False,
            loads_masa=False,
            produces_confidence=True,
            confidence_fields=("confidence_raw", "confidence_calibrated", "policy_action_probabilities"),
            confidence_scale="0-1 probability",
            replay=False,
            mtf=False,
            real_source=False,
            proof_confidence=False,
            routeable_namespace=False,
            paper_only=True,
            blocker="sidecar_only_checkpoint_weight_required",
        ),
        producer_row(
            "v2/backend/app/cli/v2_rl_core_worker.py",
            "main",
            reads_trusted_market_state=True,
            loads_ppo=False,
            loads_masa=False,
            produces_confidence=True,
            confidence_fields=("confidence_raw", "confidence_calibrated"),
            confidence_scale="0-1 probability",
            replay=False,
            mtf=False,
            real_source=False,
            proof_confidence=False,
            routeable_namespace=False,
            paper_only=True,
            blocker="status_worker_not_canonical_prediction_writer",
        ),
        producer_row(
            "v2/backend/app/services/rl_core/masa_adapter.py",
            "V2MASAAdapter.get_action_and_value",
            reads_trusted_market_state=True,
            loads_ppo=False,
            loads_masa=False,
            produces_confidence=True,
            confidence_fields=("confidence", "action_probabilities"),
            confidence_scale="0-1 probability",
            replay=True,
            mtf=False,
            real_source=False,
            proof_confidence=False,
            routeable_namespace=False,
            paper_only=True,
            blocker="adapter_output_not_canonical_prediction_writer_and_no_trained_checkpoint",
        ),
        producer_row(
            "v2/backend/app/services/rl_core/trainer_output.py",
            "emit_trainer_output",
            reads_trusted_market_state=True,
            loads_ppo=False,
            loads_masa=False,
            produces_confidence=True,
            confidence_fields=("confidence_raw", "confidence_calibrated"),
            confidence_scale="0-1 probability",
            replay=False,
            mtf=False,
            real_source=False,
            proof_confidence=False,
            routeable_namespace=False,
            paper_only=True,
            blocker="trainer_output_record_not_routeable_prediction",
        ),
        producer_row(
            "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py",
            "run_hybrid_trainer_cycle",
            reads_trusted_market_state=True,
            loads_ppo=True,
            loads_masa=True,
            produces_confidence=True,
            confidence_fields=("confidence_raw", "confidence_calibrated", "confidence_source"),
            confidence_scale="0-1 probability",
            replay=True,
            mtf=True,
            real_source=True,
            proof_confidence=False,
            routeable_namespace=True,
            paper_only=True,
            blocker="not_running_or_no_current_REAL_MODEL_canonical_predictions",
        ),
        producer_row(
            "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py",
            "V2HybridPredictionPublisher.publish_prediction",
            reads_trusted_market_state=False,
            loads_ppo=False,
            loads_masa=False,
            produces_confidence=False,
            confidence_fields=("passes_through_payload",),
            confidence_scale="payload_defined",
            replay=True,
            mtf=True,
            real_source=False,
            proof_confidence=True,
            routeable_namespace=True,
            paper_only=True,
            blocker="publisher_transport_depends_on_upstream_REAL_MODEL_payload",
        ),
    ]


def producer_row(
    file_path: str,
    function: str,
    *,
    reads_trusted_market_state: bool,
    loads_ppo: bool,
    loads_masa: bool,
    produces_confidence: bool,
    confidence_fields: tuple[str, ...],
    confidence_scale: str,
    replay: bool,
    mtf: bool,
    real_source: bool,
    proof_confidence: bool,
    routeable_namespace: bool,
    paper_only: bool,
    blocker: str,
) -> dict[str, Any]:
    return {
        "file_path": file_path,
        "function_or_class": function,
        "reads_trusted_market_state": reads_trusted_market_state,
        "loads_ppo_policy_or_checkpoint": loads_ppo,
        "loads_masa_model_or_checkpoint": loads_masa,
        "produces_real_model_confidence": real_source and produces_confidence,
        "confidence_field_names": list(confidence_fields),
        "confidence_scale": confidence_scale,
        "writes_replay_snapshot_id": replay,
        "writes_mtf_snapshot_id": mtf,
        "writes_confidence_source_REAL_MODEL": real_source,
        "writes_proof_or_default_confidence": proof_confidence,
        "writes_to_routeable_namespace": routeable_namespace,
        "can_run_paper_only_no_live": paper_only,
        "current_blocker": blocker,
    }


def classify_root_cause(
    *,
    confidence_counts: Counter[str],
    routeability_candidates: int,
    checkpoint: Mapping[str, Any],
    hybrid_status: Mapping[str, Any],
    sidecar_count: int,
) -> str:
    if routeability_candidates > 0:
        return "REAL_INFERENCE_ROUTEABILITY_CANDIDATES_PRESENT"
    if confidence_counts.get("PROOF_DEFAULT", 0) or confidence_counts.get("PLACEHOLDER", 0):
        return "PREDICTION_WRITER_ONLY_PROOF_PUBLISHER_FOR_CURRENT_CANONICAL_KEYS"
    if sidecar_count:
        return "REAL_INFERENCE_WRITES_SIDECAR_NAMESPACE_NOT_EXPORTED_AS_ROUTEABLE"
    if not checkpoint.get("checkpoint_available_for_m1"):
        return "MODEL_CHECKPOINT_UNAVAILABLE"
    if not hybrid_status:
        return "REAL_INFERENCE_WORKER_NOT_RUNNING"
    return "REAL_INFERENCE_PATH_UNAVAILABLE"


def classify_m1_gate(
    *,
    real_model_count: int,
    placeholder_count: int,
    missing_count: int,
    live_state: Mapping[str, Any],
    root_cause: str,
) -> dict[str, Any]:
    live_disabled = live_state.get("any_live_submit_enabled") is not True
    no_live_order = live_state.get("places_real_order") is not True and live_state.get("exchange_action_taken") is not True
    if not live_disabled or not no_live_order:
        verdict = "M1 NO-GO"
        reason = "LIVE_SUBMIT_NOT_DISABLED"
    elif real_model_count <= 0:
        verdict = "M1 NO-GO"
        reason = root_cause
    elif placeholder_count > 0:
        verdict = "M1 NO-GO"
        reason = "PLACEHOLDER_DEFAULT_CONFIDENCE_PRESENT_OUTSIDE_ROUTEABILITY"
    else:
        verdict = "M1 GO"
        reason = "REAL_MODEL_ROUTEABILITY_CANDIDATES_PRESENT"
    return {
        "generated_at": utc_now(),
        "verdict": verdict,
        "reason": reason,
        "real_model_confidence_count": real_model_count,
        "placeholder_or_default_confidence_count": placeholder_count,
        "missing_confidence_count": missing_count,
        "routeability_candidates": real_model_count,
        "live_submit_disabled": live_disabled,
        "no_live_order_submitted": no_live_order,
    }


def distribution(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p25": None, "median": None, "p75": None, "max": None}
    values = sorted(values)
    return {
        "min": values[0],
        "p25": percentile(values, 0.25),
        "median": percentile(values, 0.5),
        "p75": percentile(values, 0.75),
        "max": values[-1],
    }


def percentile(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def write_outputs(output_dir: Path, report: Mapping[str, Any]) -> None:
    write_json(output_dir / "real_inference_producer_inventory.json", report["real_inference_producer_inventory"])
    write_json(output_dir / "real_inference_batch_report.json", report["real_inference_batch_report"])
    write_json(output_dir / "m1_release_gate.json", report["m1_release_gate"])
    (output_dir / "real_inference_producer_inventory.md").write_text(
        render_inventory_markdown(report["real_inference_producer_inventory"]),
        encoding="utf-8",
    )
    (output_dir / "real_inference_batch_report.md").write_text(
        render_batch_markdown(report["real_inference_batch_report"], report["m1_release_gate"]),
        encoding="utf-8",
    )


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def render_inventory_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Real Inference Producer Inventory",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        "| File | Function/class | Trusted state | PPO | MASA | Real confidence | Routeable namespace | Current blocker |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("producers", []):
        if not isinstance(row, Mapping):
            continue
        lines.append(
            "| "
            + " | ".join(
                str(row.get(field, ""))
                for field in (
                    "file_path",
                    "function_or_class",
                    "reads_trusted_market_state",
                    "loads_ppo_policy_or_checkpoint",
                    "loads_masa_model_or_checkpoint",
                    "produces_real_model_confidence",
                    "writes_to_routeable_namespace",
                    "current_blocker",
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_batch_markdown(report: Mapping[str, Any], gate: Mapping[str, Any]) -> str:
    fields = (
        "predictions_attempted",
        "predictions_emitted",
        "real_model_confidence_count",
        "placeholder_or_default_confidence_count",
        "missing_confidence_count",
        "routeability_candidates",
        "accepted_paper_intents",
        "accepted_shadow_intents",
        "fills_created",
        "positions_opened",
        "closed_trades",
        "root_cause",
    )
    lines = [
        "# M1 Real Inference Paper Batch Report",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        f"Verdict: `{gate.get('verdict')}`",
        f"Reason: `{gate.get('reason')}`",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for field in fields:
        lines.append(f"| `{field}` | `{report.get(field)}` |")
    return "\n".join(lines) + "\n"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
