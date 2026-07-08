"""Pass 3B exact live-path dry run.

Runs the live transport evaluator with a realistic in-memory candidate while a
submit guard makes live submission impossible. No model, signal, paper intent,
training sample, leverage, margin, Redis, or exchange mutation is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.services.live_gate.binance_live_order_transport import (
    BinanceUsdMLiveOrderTransport,
    evaluate_live_order_transport,
)
from app.services.live_gate.live_position_state_machine import (
    LiveCanaryConfig,
    evaluate_live_canary_preflight,
)
from app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION
from app.services.provider_features import build_provider_consumer_context

REQUIRED_DISABLED = {
    "live_gate": "blocked_human_only",
    "order_transport_submit_enabled": False,
    "live_trading_enabled": False,
    "live_blocked": True,
    "operator_approved": False,
    "places_real_order": False,
    "exchange_action_taken": False,
    "release_mode": "NON_LIVE",
}


class ReadOnlyRedisOverlay:
    def __init__(self, client: Any, overlay: Mapping[str, Any] | None = None) -> None:
        self.client = client
        self.overlay = dict(overlay or {})
        self.write_attempts: list[str] = []

    def get(self, key: str) -> Any:
        if key in self.overlay:
            value = self.overlay[key]
            return json.dumps(value, sort_keys=True, default=str)
        return self.client.get(key)

    def scan_iter(self, *args: Any, **kwargs: Any):
        return self.client.scan_iter(*args, **kwargs)

    def set(self, key: str, *_args: Any, **_kwargs: Any) -> bool:
        self.write_attempts.append(str(key))
        raise RuntimeError("PASS3B_READ_ONLY_REDIS_WRITE_BLOCKED")


class SubmitGuardTransport:
    def __init__(self, delegate: BinanceUsdMLiveOrderTransport | None = None, signed_reads: Mapping[str, Any] | None = None) -> None:
        self.delegate = delegate or BinanceUsdMLiveOrderTransport()
        self.signed_reads = dict(signed_reads or {})
        self.submit_function_called = False

    def submit_market_order(self, **_kwargs: Any) -> dict[str, Any]:
        self.submit_function_called = True
        raise AssertionError("PASS3B_SUBMIT_GUARD_CALLED")

    def fetch_position_mode(self, *, api_key: str, api_secret: str) -> dict[str, Any]:
        if "position_mode_status" in self.signed_reads:
            return dict(self.signed_reads["position_mode_status"])
        return self.delegate.fetch_position_mode(api_key=api_key, api_secret=api_secret)

    def fetch_account_margin_status(self, *, api_key: str, api_secret: str) -> dict[str, Any]:
        if "account_margin_status" in self.signed_reads:
            return dict(self.signed_reads["account_margin_status"])
        return self.delegate.fetch_account_margin_status(api_key=api_key, api_secret=api_secret)

    def fetch_symbol_filters(self, symbol: str) -> dict[str, Any]:
        if "symbol_filter_status" in self.signed_reads:
            payload = dict(self.signed_reads["symbol_filter_status"])
            payload.setdefault("symbol", symbol)
            return payload
        fetch = getattr(self.delegate, "fetch_symbol_filters", None)
        if callable(fetch):
            return fetch(symbol)
        return {"ok": False, "error_type": "SYMBOL_FILTER_READER_UNAVAILABLE"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_pass3b_exact_live_path_dry_run")
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    client = redis_client(args.redis_url)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    report = run_exact_live_path_dry_run(client=client, redis_url=args.redis_url, output_dir=out_dir, run_id=run_id)
    (out_dir / "pass3b_exact_live_path_report.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    (out_dir / f"PASS3B_EXACT_LIVE_PATH_DRY_RUN_{run_id}.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 1 if report.get("status") == "PASS3B_FAILED_LIVE_CONTROL_ARMED" else 0


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def run_exact_live_path_dry_run(*, client: Any, redis_url: str, output_dir: Path, run_id: str) -> dict[str, Any]:
    pre_live = read_live_control_state(client)
    pre_check = validate_disabled_live_control(pre_live)
    if not pre_check["ok"]:
        return base_report(run_id, output_dir, redis_url) | {
            "status": "PASS3B_FAILED_LIVE_CONTROL_ARMED",
            "pre_run_live_control": pre_live,
            "pre_run_live_control_check": pre_check,
            "submit_allowed": False,
            "submit_function_called": False,
            "live_order_submitted": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }

    strict = latest_report_summary("pipeline_trust_evidence_pass3b")
    recorded = latest_recorded_summary("recorded_state_verification_pass3b")
    candidate_type, signal = select_candidate(client)
    provider_context = build_provider_consumer_context(
        client,
        role="live_dry_run",
        symbol=str(signal.get("symbol") or "BTCUSDT"),
        timeframe=str(signal.get("timeframe") or "1m"),
        decision_time=signal.get("decision_time") or signal.get("feature_cutoff") or signal.get("available_at"),
    )
    runtime_payload = dry_run_runtime_payload(pre_live["live_gate_state"], str(signal.get("symbol") or "BTCUSDT"))
    signed_reads = build_signed_read_context(signal.get("symbol") or "BTCUSDT")
    signed_read_available = signed_reads.get("available") is True
    if signed_read_available:
        trader_status = {
            "binance_private_readonly": {
                "position_read_status": "HTTP_200",
                "exchange_position": signed_reads["exchange_position"],
                "open_orders": signed_reads["open_orders"],
                "margin_mode": signed_reads["margin_mode"],
                "signed_read_ts_ms": signed_reads["signed_read_ts_ms"],
            }
        }
    else:
        trader_status = {"binance_private_readonly": {"position_read_status": "SIGNED_READ_UNAVAILABLE"}}

    risk_decision_id = signal.get("risk_decision_id") or f"risk_{signal['signal_id']}"
    overlay = {
        "v2:risk:gateway:decisions": [
            {
                "symbol": signal["symbol"],
                "prediction_id": signal.get("prediction_id"),
                "risk_decision_id": risk_decision_id,
                "risk_action": "allow",
                "live_blocked": True,
                "probe_only": candidate_type == "ENGINEERING_CANARY_PROBE",
            }
        ]
    }
    signal["risk_decision_id"] = risk_decision_id
    readonly = ReadOnlyRedisOverlay(client, overlay)
    guard = SubmitGuardTransport(signed_reads=signed_reads)
    submit_exception = None
    try:
        transport_result = evaluate_live_order_transport(
            signal_status={"published_signals": [signal]},
            trader_status=trader_status,
            runtime_read={"source": "pass3b_read_only_overlay", "payload": runtime_payload, "validation": {"valid": True, "blockers": []}},
            redis_client=readonly,
            transport=guard,
            dry_run=False,
        )
    except AssertionError as exc:
        submit_exception = str(exc)
        transport_result = {"status": "PASS3B_SUBMIT_GUARD_FAILED", "blockers": ["SUBMIT_FUNCTION_CALLED"]}

    post_live = read_live_control_state(client)
    post_check = validate_disabled_live_control(post_live)
    blockers = list(transport_result.get("blockers") or [])
    realistic_preflight = evaluate_realistic_candidate_preflight(signal, runtime_payload, signed_reads)
    primary_blockers = primary_blockers_for_report(blockers, realistic_preflight)
    status = classify_status(
        signed_read_available=signed_read_available,
        blockers=blockers,
        realistic_preflight=realistic_preflight,
    )
    return base_report(run_id, output_dir, redis_url) | {
        "status": status,
        "evidence_status": {"strict": strict, "recorded": recorded},
        "strict_verifier_exit": 0 if strict.get("critical_failures") == 0 else 1,
        "recorded_state_verifier_exit": 0 if recorded else None,
        "critical_failures": int(strict.get("critical_failures") or 0),
        "active_stale_count": active_stale_count(strict),
        "candidate_type": candidate_type,
        "candidate": summarize_signal(signal),
        "provider_context": provider_context,
        "optional_provider_failures_core_blocking": False,
        "signed_read_status": signed_reads,
        "signed_read_available": signed_read_available,
        "dry_run_runtime_overlay": summarize_runtime_overlay(runtime_payload),
        "transport_result": transport_result,
        "transport_raw_blockers": blockers,
        "realistic_candidate_preflight": realistic_preflight,
        "primary_blockers": primary_blockers,
        "state_machine_result": (transport_result.get("live_canary_preflight") or {}).get("state_machine"),
        "exchange_local_reconciliation_result": (transport_result.get("live_canary_preflight") or {}).get("exchange_local_reconciliation"),
        "canary_cap_result": (transport_result.get("live_canary_preflight") or {}).get("canary_caps"),
        "lifecycle_safety_result": (transport_result.get("live_canary_preflight") or {}).get("order_lifecycle"),
        "submit_allowed": False,
        "final_submit_allowed_from_transport": bool(transport_result.get("would_submit") or transport_result.get("order_submitted")),
        "final_submit_block_reason": first_final_blocker(primary_blockers),
        "all_blockers": blockers,
        "submit_function_called": guard.submit_function_called,
        "submit_guard_exception": submit_exception,
        "live_order_submitted": bool(transport_result.get("order_submitted")) if not submit_exception else False,
        "places_real_order": bool(transport_result.get("places_real_order")) if not submit_exception else False,
        "exchange_action_taken": bool(transport_result.get("writes_exchange_orders")) if not submit_exception else False,
        "leverage_changed": bool(transport_result.get("leverage_changed")),
        "margin_mode_changed": bool(transport_result.get("margin_mode_changed")),
        "redis_write_attempts_blocked": list(readonly.write_attempts),
        "pre_run_live_control": pre_live,
        "pre_run_live_control_check": pre_check,
        "post_run_live_control": post_live,
        "post_run_live_control_check": post_check,
        "training_sample_created": False,
        "persisted_probe_as_prediction": False,
        "persisted_probe_as_paper_signal": False,
        "persisted_probe_as_paper_intent": False,
        "counted_in_edge_proof": False,
        "pass3c_can_be_considered": status == "PASS3B_EXACT_LIVE_PATH_DRY_RUN_COMPLETE",
    }


def select_candidate(client: Any) -> tuple[str, dict[str, Any]]:
    actionable = []
    try:
        keys = sorted(client.scan_iter(match="v2:prediction:*", count=500))
    except Exception:
        keys = []
    for key in keys:
        payload = read_json_key(client, str(key))
        action = str(payload.get("selected_action") or payload.get("action") or "").lower()
        if payload.get("trust_schema_version") == TRUST_SCHEMA_VERSION and action in {"long", "short", "open_long", "open_short"}:
            actionable.append(payload)
    if actionable:
        selected = actionable[-1]
        signal = engineering_signal_from_prediction(selected)
        return "REAL_TRUSTED_DECISION", signal
    return "ENGINEERING_CANARY_PROBE", engineering_probe_signal()


def engineering_signal_from_prediction(prediction: Mapping[str, Any]) -> dict[str, Any]:
    action = str(prediction.get("selected_action") or prediction.get("action") or "long").lower()
    symbol = str(prediction.get("symbol") or "BTCUSDT").upper()
    side = "long" if action in {"long", "open_long"} else "short"
    signal = engineering_probe_signal(symbol=symbol, action=side)
    for field in ("decision_id", "prediction_id", "mtf_snapshot_id", "replay_snapshot_id", "feature_cutoff", "available_at", "all_tf_candle_timestamps"):
        signal[field] = prediction.get(field)
    signal["candidate_source"] = "REAL_TRUSTED_DECISION"
    return signal


def engineering_probe_signal(symbol: str = "BTCUSDT", action: str = "long") -> dict[str, Any]:
    probe_id = f"probe_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    return {
        "candidate_source": "ENGINEERING_CANARY_PROBE",
        "probe_label": "NON_STRATEGY_TEST",
        "symbol": symbol,
        "timeframe": "1m",
        "action": action,
        "selected_action": action,
        "side": "BUY" if action == "long" else "SELL",
        "order_type": "MARKET",
        "quantity": 0.001,
        "requested_notional_usdt": 5.0,
        "price_target": 50000.0,
        "price_target_after_cost": 50000.0,
        "reduce_only": False,
        "decision_id": probe_id,
        "prediction_id": probe_id,
        "mtf_snapshot_id": "engineering_probe_mtf_not_model_output",
        "replay_snapshot_id": "engineering_probe_replay_not_model_output",
        "feature_cutoff": "engineering_probe_not_model_output",
        "available_at": "engineering_probe_not_model_output",
        "all_tf_candle_timestamps": [1, 2, 3, 4, 5],
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "routes_to_live": False,
        "live_order_allowed": False,
        "expected_move_after_cost_bps": 999.0,
        "confidence": 1.0,
        "market_state_integrity_score": 100.0,
        "paper_state": "ACCEPTED_PAPER_FILL",
        "signal_id": f"sig_{probe_id}",
        "orchestrator_decision_id": f"orch_{probe_id}",
        "live_gate": "blocked_human_only",
        "generated_est": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "live_symbols": [],
    }


def dry_run_runtime_payload(actual: Mapping[str, Any], symbol: str) -> dict[str, Any]:
    symbol_u = str(symbol or "BTCUSDT").upper()
    payload = dict(actual or {})
    payload.update(
        {
            "live_gate": payload.get("live_gate", "blocked_human_only"),
            "order_transport_submit_enabled": False,
            "live_trading_enabled": False,
            "live_blocked": True,
            "operator_approved": False,
            "places_real_order": False,
            "exchange_action_taken": False,
            "release_mode": "NON_LIVE",
            "order_transport_write_guard_enabled": True,
            "accepted_live_symbols": sorted({symbol_u, *[str(item).upper() for item in payload.get("accepted_live_symbols") or []]}),
            "local_position": payload.get("local_position") or {"symbol": symbol_u, "side": "FLAT", "quantity": 0.0},
            "open_positions_count": int(numeric(payload.get("open_positions_count"), 0.0)),
            "daily_order_count": int(numeric(payload.get("daily_order_count"), 0.0)),
            "daily_loss_usd": numeric(payload.get("daily_loss_usd"), 0.0),
            "kill_switch_active": payload.get("kill_switch_active") is True,
            "live_canary_human_armed": False,
        }
    )
    risk_profile = dict(payload.get("risk_profile") or {})
    fields = dict(risk_profile.get("fields") or {})
    fields.setdefault("max_leverage", 1.0)
    fields.setdefault("min_confidence_calibrated", 0.0)
    fields.setdefault("min_expected_move_after_cost_bps", 0.0)
    fields.setdefault("current_drawdown_bps", 0.0)
    fields.setdefault("total_exposure_usdt", 0.0)
    risk_profile["fields"] = fields
    payload["risk_profile"] = risk_profile
    canary = dict(payload.get("live_canary_config") or payload.get("live_canary") or {})
    canary.update(
        {
            "live_canary_enabled": False,
            "allowed_symbols": sorted({symbol_u, *[str(item).upper() for item in canary.get("allowed_symbols") or []]}),
            "max_open_positions": int(canary.get("max_open_positions") or 1),
            "max_notional_usd": numeric(canary.get("max_notional_usd"), 10.0) or 10.0,
            "max_daily_orders": int(canary.get("max_daily_orders") or 3),
            "max_daily_loss_usd": numeric(canary.get("max_daily_loss_usd"), 10.0) or 10.0,
            "allow_hedge_mode": False,
            "allow_averaging_down": False,
            "allow_direct_flip": False,
            "require_reduce_only_for_closes": True,
            "require_kill_switch_clear": True,
            "require_human_operator_arm": True,
            "require_strict_pipeline_trust": True,
            "require_pass2a_trusted_decision": True,
            "require_replay_snapshot": True,
            "require_mtf_snapshot": True,
            "allow_leverage_mutation": False,
            "allow_margin_mode_mutation": False,
            "expected_margin_mode": str(canary.get("expected_margin_mode") or "cross").lower(),
            "expected_hedge_mode": False,
        }
    )
    payload["live_canary_config"] = canary
    return payload


def build_signed_read_context(symbol: str) -> dict[str, Any]:
    env = parse_env(Path("v2/.env.local"))
    api_key = env.get("BINANCE_API_KEY") or env.get("BINANCE_FUT_API_KEY")
    api_secret = env.get("BINANCE_API_SECRET") or env.get("BINANCE_SECRET_KEY") or env.get("BINANCE_FUT_API_SECRET")
    if not api_key or not api_secret:
        return {"available": False, "reason": "BINANCE_CREDENTIALS_MISSING"}
    base = os.environ.get("V2_BINANCE_USDM_BASE_URL", "https://fapi.binance.com").rstrip("/")
    now_ms = int(time.time() * 1000)
    try:
        account = signed_get(base, "/fapi/v3/account", {}, api_key, api_secret)
        open_orders = signed_get(base, "/fapi/v1/openOrders", {"symbol": symbol}, api_key, api_secret)
        position_mode = signed_get(base, "/fapi/v1/positionSide/dual", {}, api_key, api_secret)
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__}
    positions = account.get("positions") if isinstance(account, Mapping) else []
    exchange_position = position_for_symbol(positions if isinstance(positions, list) else [], symbol)
    current_positions = summarize_current_positions(positions if isinstance(positions, list) else [])
    margin_mode = str(exchange_position.get("margin_mode") or "cross").lower()
    symbol_filters = BinanceUsdMLiveOrderTransport(base_url=base).fetch_symbol_filters(symbol)
    dual_side_position = (
        position_mode.get("dualSidePosition") is True
        if isinstance(position_mode, Mapping)
        else None
    )
    return {
        "available": True,
        "signed_read_ts_ms": now_ms,
        "exchange_position": exchange_position,
        "current_positions": current_positions,
        "current_position_count": len(current_positions),
        "open_orders": open_orders if isinstance(open_orders, list) else [],
        "margin_mode": margin_mode,
        "position_mode_status": {
            "ok": isinstance(position_mode, Mapping) and dual_side_position is not None,
            "dual_side_position": dual_side_position,
            "source": "pass3b_signed_read",
            "endpoint": "GET /fapi/v1/positionSide/dual",
        },
        "account_margin_status": {
            "ok": True,
            "can_trade": account.get("canTrade") if isinstance(account, Mapping) else None,
            "available_balance_checked": True,
            "available_balance_redacted": True,
            "_available_balance_usdt": numeric(account.get("availableBalance"), 0.0) if isinstance(account, Mapping) else 0.0,
            "wallet_balance_checked": isinstance(account, Mapping) and account.get("totalWalletBalance") is not None,
            "wallet_balance_redacted": True,
            "_wallet_balance_usdt": numeric(account.get("totalWalletBalance"), 0.0) if isinstance(account, Mapping) else 0.0,
            "margin_mode": margin_mode,
            "signed_read_ts_ms": now_ms,
            "endpoint": "GET /fapi/v3/account",
        },
        "symbol_filter_status": symbol_filters,
    }


def signed_get(base: str, path: str, params: Mapping[str, Any], api_key: str, api_secret: str) -> Any:
    query = dict(params)
    query["timestamp"] = str(int(time.time() * 1000))
    body = urllib.parse.urlencode(query)
    signature = hmac.new(api_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    request = urllib.request.Request(f"{base}{path}?{body}&signature={signature}", headers={"X-MBX-APIKEY": api_key}, method="GET")
    with urllib.request.urlopen(request, timeout=8.0) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def position_for_symbol(positions: list[Any], symbol: str) -> dict[str, Any]:
    for row in positions:
        if not isinstance(row, Mapping) or str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        amount = numeric(row.get("positionAmt"), 0.0)
        side = "LONG" if amount > 0 else "SHORT" if amount < 0 else "FLAT"
        return {"symbol": symbol.upper(), "side": side, "quantity": abs(amount), "margin_mode": row.get("marginType") or "cross"}
    return {"symbol": symbol.upper(), "side": "FLAT", "quantity": 0.0, "margin_mode": "cross"}


def summarize_current_positions(positions: list[Any]) -> list[dict[str, Any]]:
    current: list[dict[str, Any]] = []
    for row in positions:
        if not isinstance(row, Mapping):
            continue
        amount = numeric(row.get("positionAmt"), 0.0)
        if amount == 0:
            continue
        side = "LONG" if amount > 0 else "SHORT"
        current.append(
            {
                "symbol": str(row.get("symbol") or "").upper(),
                "side": side,
                "quantity": abs(amount),
                "margin_mode": str(row.get("marginType") or "cross").lower(),
            }
        )
    return current


def evaluate_realistic_candidate_preflight(signal: Mapping[str, Any], runtime_payload: Mapping[str, Any], signed_reads: Mapping[str, Any]) -> dict[str, Any]:
    if signed_reads.get("available") is not True:
        return {"submit_allowed": False, "reason_code": "SIGNED_READ_UNAVAILABLE", "blockers": ["SIGNED_READ_UNAVAILABLE"]}
    config = LiveCanaryConfig.from_mapping(runtime_payload.get("live_canary_config") or {})
    return evaluate_live_canary_preflight(
        config=config,
        decision=signal,
        replay_snapshot_exists=bool(signal.get("replay_snapshot_id")),
        mtf_snapshot_exists=bool(signal.get("mtf_snapshot_id")),
        strict_pipeline_trust_ok=signal.get("trust_schema_version") == TRUST_SCHEMA_VERSION,
        pass2a_trusted_decision_ok=signal.get("trust_schema_version") == TRUST_SCHEMA_VERSION,
        runtime_payload=runtime_payload,
        local_position=runtime_payload.get("local_position") if isinstance(runtime_payload.get("local_position"), Mapping) else {},
        exchange_position=signed_reads.get("exchange_position") if isinstance(signed_reads.get("exchange_position"), Mapping) else {},
        open_orders=[item for item in signed_reads.get("open_orders", []) if isinstance(item, Mapping)],
        hedge_mode=(signed_reads.get("position_mode_status") or {}).get("dual_side_position")
        if isinstance(signed_reads.get("position_mode_status"), Mapping)
        else None,
        margin_mode=str(signed_reads.get("margin_mode") or ""),
        signed_read_ts_ms=numeric(signed_reads.get("signed_read_ts_ms"), 0.0) or None,
        requested_action=str(signal.get("action") or signal.get("selected_action") or ""),
        symbol=str(signal.get("symbol") or ""),
        quantity=numeric(signal.get("quantity"), 0.0),
        notional_usd=numeric(signal.get("requested_notional_usdt"), 0.0),
        reduce_only=signal.get("reduce_only") is True,
        open_positions_count=int(numeric(runtime_payload.get("open_positions_count"), 0.0)),
        daily_order_count=int(numeric(runtime_payload.get("daily_order_count"), 0.0)),
        daily_loss_usd=numeric(runtime_payload.get("daily_loss_usd"), 0.0),
        kill_switch_active=runtime_payload.get("kill_switch_active") is True,
        human_operator_armed=runtime_payload.get("live_canary_human_armed") is True,
        lifecycle_status={"status": "READY"},
    )


def read_live_control_state(client: Any) -> dict[str, Any]:
    return {
        "live_gate_state": read_json_key(client, "v2:live_gate:state"),
        "trader_execution_state": read_json_key(client, "v2:trader:execution_state"),
        "live_order_transport_status": read_json_key(client, "v2:live_order_transport:status"),
    }


def validate_disabled_live_control(state: Mapping[str, Any]) -> dict[str, Any]:
    live_gate = state.get("live_gate_state") if isinstance(state.get("live_gate_state"), Mapping) else {}
    transport = state.get("live_order_transport_status") if isinstance(state.get("live_order_transport_status"), Mapping) else {}
    mismatches: dict[str, Any] = {}
    warnings: list[str] = []
    for field, expected in REQUIRED_DISABLED.items():
        observed = live_gate.get(field)
        if observed != expected:
            mismatches[field] = {"expected": expected, "observed": observed}
    for field, expected in {"order_submitted": False, "writes_exchange_orders": False}.items():
        if field not in transport:
            warnings.append(f"LIVE_ORDER_TRANSPORT_STATUS_FIELD_MISSING:{field}")
            continue
        observed = transport.get(field)
        if observed is not expected:
            mismatches[field] = {"expected": expected, "observed": observed}
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "warnings": warnings,
        "live_order_transport_status_present": bool(transport),
        "missing_transport_status_fields": [
            field
            for field in ("order_submitted", "writes_exchange_orders")
            if field not in transport
        ],
    }


def classify_status(*, signed_read_available: bool, blockers: list[str], realistic_preflight: Mapping[str, Any]) -> str:
    if not signed_read_available:
        return "PASS3B_BLOCKED_SIGNED_READ_UNAVAILABLE"
    construction_blockers = {
        "LIVE_CANARY:QUANTITY_NOT_POSITIVE",
        "LIVE_CANARY:NOTIONAL_NOT_POSITIVE",
        "LIVE_CANARY:ACTION_NOT_SUPPORTED",
        "LIVE_CANARY:MARGIN_MODE_UNKNOWN",
        "LIVE_CANARY:HEDGE_MODE_MISMATCH",
        "LIVE_CANARY:SIGNED_READ_TIMESTAMP_MISSING",
    }
    realistic_construction = {
        "QUANTITY_NOT_POSITIVE",
        "NOTIONAL_NOT_POSITIVE",
        "ACTION_NOT_SUPPORTED",
        "MARGIN_MODE_UNKNOWN",
        "HEDGE_MODE_MISMATCH",
        "SIGNED_READ_TIMESTAMP_MISSING",
    }.intersection(set(realistic_preflight.get("blockers") or []))
    if construction_blockers.intersection(blockers) and not realistic_construction and (
        "ADAPTIVE_ALLOCATOR_BLOCK_INSUFFICIENT_MARGIN" in blockers
        or "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER" in blockers
    ):
        return "PASS3B_BLOCKED_INSUFFICIENT_AVAILABLE_BALANCE"
    if construction_blockers.intersection(blockers) or realistic_construction:
        return "PASS3B_BLOCKED_BEFORE_REALISTIC_PREFLIGHT"
    return "PASS3B_EXACT_LIVE_PATH_DRY_RUN_COMPLETE"


def primary_blockers_for_report(raw_blockers: list[str], realistic_preflight: Mapping[str, Any]) -> list[str]:
    realistic = [f"REALISTIC_PREFLIGHT:{item}" for item in realistic_preflight.get("blockers", [])]
    if (
        "ADAPTIVE_ALLOCATOR_BLOCK_INSUFFICIENT_MARGIN" in raw_blockers
        or "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER" in raw_blockers
    ):
        merged = [
            "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER",
            *realistic,
        ]
    else:
        merged = [*raw_blockers, *realistic]
    return list(dict.fromkeys(str(item) for item in merged if str(item)))


def first_final_blocker(blockers: list[str]) -> str | None:
    preferred = [
        "LIVE_CANARY:RELEASE_MODE_NON_LIVE",
        "LIVE_CANARY:ORDER_TRANSPORT_SUBMIT_DISABLED",
        "LIVE_CANARY:LIVE_TRADING_DISABLED",
        "LIVE_CANARY:LIVE_CANARY_DISABLED",
        "LIVE_CANARY:HUMAN_OPERATOR_ARM_REQUIRED",
        "LIVE_GATE_RUNTIME_NOT_ENABLED",
        "LIVE_ORDER_TRANSPORT_SUBMIT_NOT_ENABLED",
    ]
    for item in preferred:
        if item in blockers:
            return item
    return blockers[0] if blockers else None


def base_report(run_id: str, output_dir: Path, redis_url: str) -> dict[str, Any]:
    return {"run_id": run_id, "generated_at": utc_now(), "output_dir": str(output_dir), "redis_url": redact(redis_url)}


def read_json_key(client: Any, key: str) -> dict[str, Any]:
    try:
        raw = client.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def latest_report_summary(root: str) -> dict[str, Any]:
    reports = sorted(Path(root).glob("*/report/pipeline_trust_report.json"))
    if not reports:
        return {}
    try:
        summary = dict((json.loads(reports[-1].read_text()).get("summary") or {}))
        summary["_report_path"] = str(reports[-1])
        summary["_evidence_run"] = str(reports[-1].parents[1])
        return summary
    except Exception:
        return {"critical_failures": 1, "status": "parse_failed"}


def latest_recorded_summary(root: str) -> dict[str, Any]:
    reports = sorted(Path(root).glob("*/recorded_state_verification_report.json"))
    if not reports:
        return {}
    try:
        payload = json.loads(reports[-1].read_text())
    except Exception:
        return {"status": "parse_failed"}
    summary = dict(payload.get("metrics") or payload.get("summary") or {})
    summary["_report_path"] = str(reports[-1])
    summary["_recorded_run"] = str(reports[-1].parent)
    return summary


def active_stale_count(summary: Mapping[str, Any]) -> int:
    return int(summary.get("active_stale_count") or 0)


def summarize_signal(signal: Mapping[str, Any]) -> dict[str, Any]:
    return {k: signal.get(k) for k in ("candidate_source", "probe_label", "symbol", "side", "action", "quantity", "requested_notional_usdt", "order_type", "reduce_only", "decision_id", "prediction_id", "replay_snapshot_id", "mtf_snapshot_id", "feature_cutoff", "available_at", "routes_to_live", "live_order_allowed")}


def summarize_runtime_overlay(payload: Mapping[str, Any]) -> dict[str, Any]:
    canary = payload.get("live_canary_config") if isinstance(payload.get("live_canary_config"), Mapping) else {}
    return {
        "release_mode": payload.get("release_mode"),
        "live_gate": payload.get("live_gate"),
        "order_transport_submit_enabled": payload.get("order_transport_submit_enabled"),
        "live_trading_enabled": payload.get("live_trading_enabled"),
        "accepted_live_symbols": payload.get("accepted_live_symbols"),
        "order_transport_write_guard_enabled": payload.get("order_transport_write_guard_enabled"),
        "live_canary_enabled": canary.get("live_canary_enabled"),
        "allowed_symbols": canary.get("allowed_symbols"),
        "max_notional_usd": canary.get("max_notional_usd"),
    }


def numeric(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def redact(value: str) -> str:
    if "@" not in value:
        return value
    scheme, rest = value.split("://", 1)
    return f"{scheme}://***@{rest.split('@', 1)[1]}"


def render_markdown(report: Mapping[str, Any]) -> str:
    candidate = report.get("candidate") or {}
    realistic = report.get("realistic_candidate_preflight") or {}
    realistic_state = realistic.get("state_machine") if isinstance(realistic.get("state_machine"), Mapping) else {}
    realistic_recon = realistic.get("exchange_local_reconciliation") if isinstance(realistic.get("exchange_local_reconciliation"), Mapping) else {}
    realistic_caps = realistic.get("canary_caps") if isinstance(realistic.get("canary_caps"), Mapping) else {}
    realistic_lifecycle = realistic.get("order_lifecycle") if isinstance(realistic.get("order_lifecycle"), Mapping) else {}
    evidence = report.get("evidence_status") if isinstance(report.get("evidence_status"), Mapping) else {}
    strict = evidence.get("strict") if isinstance(evidence.get("strict"), Mapping) else {}
    recorded = evidence.get("recorded") if isinstance(evidence.get("recorded"), Mapping) else {}
    return "\n".join([
        f"# Pass 3B Exact Live-Path Dry Run: {report.get('run_id')}",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        "| Field | Value |",
        "|---|---:|",
        f"| Status | `{report.get('status')}` |",
        f"| Evidence run | `{strict.get('_evidence_run')}` |",
        f"| Recorded-state run | `{recorded.get('_recorded_run')}` |",
        f"| Strict verifier exit | `{report.get('strict_verifier_exit')}` |",
        f"| Recorded-state verifier exit | `{report.get('recorded_state_verifier_exit')}` |",
        f"| Critical failures | `{report.get('critical_failures')}` |",
        f"| Active-stale count | `{report.get('active_stale_count')}` |",
        f"| Candidate type | `{report.get('candidate_type')}` |",
        f"| Candidate symbol | `{candidate.get('symbol')}` |",
        f"| Candidate side | `{candidate.get('side')}` |",
        f"| Candidate quantity | `{candidate.get('quantity')}` |",
        f"| Candidate notional | `{candidate.get('requested_notional_usdt')}` |",
        f"| Signed read available | `{report.get('signed_read_available')}` |",
        f"| State machine allowed | `{realistic_state.get('allowed')}` |",
        f"| State transition | `{realistic_state.get('transition_type')}` |",
        f"| Exchange/local reconciled | `{realistic_recon.get('reconciled')}` |",
        f"| Canary cap allowed | `{realistic_caps.get('allowed')}` |",
        f"| Lifecycle status | `{realistic_lifecycle.get('status')}` |",
        f"| Submit allowed | `{report.get('submit_allowed')}` |",
        f"| Final submit block reason | `{report.get('final_submit_block_reason')}` |",
        f"| Submit function called | `{report.get('submit_function_called')}` |",
        f"| Live order submitted | `{report.get('live_order_submitted')}` |",
        f"| Places real order | `{report.get('places_real_order')}` |",
        f"| Exchange action taken | `{report.get('exchange_action_taken')}` |",
        f"| Leverage changed | `{report.get('leverage_changed')}` |",
        f"| Margin mode changed | `{report.get('margin_mode_changed')}` |",
        f"| Pass 3C can be considered | `{report.get('pass3c_can_be_considered')}` |",
        "",
        "## Primary blockers",
        "",
        "```json",
        json.dumps(report.get("primary_blockers") or [], indent=2),
        "```",
        "",
        "## Realistic candidate preflight blockers",
        "",
        "```json",
        json.dumps(realistic.get("blockers") or [], indent=2),
        "```",
        "",
        "## Raw transport blockers",
        "",
        "```json",
        json.dumps(report.get("all_blockers") or [], indent=2),
        "```",
        "",
        "## No-submit proof",
        "",
        "- `submit_function_called=false` means the guarded submit function was not reached.",
        "- `live_order_submitted=false`, `places_real_order=false`, and `exchange_action_taken=false` confirm no exchange mutation.",
        "- `redis_write_attempts_blocked` records attempted runtime status/audit writes that were blocked by the read-only overlay.",
    ]) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
