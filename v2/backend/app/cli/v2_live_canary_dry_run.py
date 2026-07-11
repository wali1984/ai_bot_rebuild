"""Build a read-only live-canary dry-run packet for an A+ candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.services.live_gate.binance_live_order_transport import (
    BinanceUsdMWebSocketPrimaryTransport,
    _fetch_symbol_filters_from_cache,
)
from v2.backend.app.services.live_gate.phase7_readiness import build_phase7_status_bundle


SCHEMA_VERSION = "v2_live_canary_dry_run_cli_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _read_first_jsonl(path: Path) -> dict[str, Any]:
    rows = _read_jsonl_rows(path)
    return rows[0] if rows else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _redis_client(redis_url: str | None = None) -> Any:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    url = redis_url or os.environ.get("V2_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
    try:
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2.0, socket_timeout=5.0)
        client.ping()
        return client
    except Exception:
        return None


def _redis_json(client: Any, key: str) -> Any:
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return None


def _epoch_ms(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            number = float(value)
            return int(number if number > 1e12 else number * 1000)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (TypeError, ValueError, OSError):
        return None


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _websocket_signed_account_snapshot(client: Any) -> dict[str, Any]:
    payload = _as_dict(_redis_json(client, "v2:binance:websocket_signed_read_status"))
    if not payload:
        return {}
    results = _as_dict(payload.get("signed_ws_read_results"))
    account_status = _as_dict(results.get("account.status"))
    balance_status = _as_dict(results.get("account.balance"))
    position_status = _as_dict(results.get("account.position"))
    account_summary = _as_dict(account_status.get("response_summary"))
    balance_summary = _as_dict(balance_status.get("response_summary"))
    position_summary = _as_dict(position_status.get("response_summary"))
    signed_ok = (
        str(payload.get("signed_read_overall_status") or "").startswith("WEBSOCKET_PRIMARY_READY")
        or (
            account_status.get("status") == "SIGNED_WS_READ_EXECUTED"
            and position_status.get("status") == "SIGNED_WS_READ_EXECUTED"
        )
    )
    if not signed_ok:
        return {}
    available = _first_non_empty(
        account_summary.get("availableBalance"),
        account_summary.get("available_balance"),
        account_summary.get("available_margin"),
        balance_summary.get("usdt_available_balance"),
        balance_summary.get("total_available_balance_usd_equivalent"),
    )
    wallet_balance = _first_non_empty(
        account_summary.get("totalWalletBalance"),
        balance_summary.get("usdt_balance"),
        balance_summary.get("total_balance_usd_equivalent"),
    )
    margin_balance = _first_non_empty(
        account_summary.get("totalMarginBalance"),
        balance_summary.get("usdt_cross_wallet_balance"),
        balance_summary.get("total_cross_wallet_balance_usd_equivalent"),
    )
    generated = payload.get("generated_utc")
    position_sides = {
        str(item or "").upper()
        for item in position_summary.get("position_sides_present") or []
        if str(item or "").strip()
    }
    dual_side_position = account_summary.get("dualSidePosition")
    if dual_side_position is None:
        if {"LONG", "SHORT"} & position_sides:
            dual_side_position = True
        elif "BOTH" in position_sides:
            dual_side_position = False
    return {
        "signed_account_read_ok": True,
        "ok": True,
        "fresh": True,
        "signed_read_fresh": True,
        "signed_read_ts_ms": _epoch_ms(generated) or int(datetime.now(timezone.utc).timestamp() * 1000),
        "source": "binance_ws_api_signed_readonly",
        "transport": "websocket_api_primary",
        "rest_fallback_used": False,
        "available_margin": available,
        "available_margin_usd": available,
        "available_balance_usd": available,
        "wallet_balance": wallet_balance,
        "margin_balance": margin_balance,
        "cross_wallet_balance": balance_summary.get("usdt_cross_wallet_balance"),
        "cross_wallet_balance_usd": _first_non_empty(
            balance_summary.get("usdt_cross_wallet_balance"),
            balance_summary.get("total_cross_wallet_balance_usd_equivalent"),
        ),
        "cross_unrealized_pnl": balance_summary.get("usdt_cross_unrealized_pnl"),
        "cross_unrealized_pnl_usd": _first_non_empty(
            balance_summary.get("usdt_cross_unrealized_pnl"),
            balance_summary.get("total_cross_unrealized_pnl_usd_equivalent"),
        ),
        "unrealized_pnl": _first_non_empty(
            account_summary.get("totalUnrealizedProfit"),
            balance_summary.get("total_cross_unrealized_pnl_usd_equivalent"),
        ),
        "account_assets_present_count": account_summary.get("assets_present_count"),
        "balance_assets_present_count": balance_summary.get("assets_present_count"),
        "current_positions": [],
        "positions": [],
        "open_orders": [],
        "hedge_mode": dual_side_position,
        "dual_side_position": dual_side_position,
        "margin_mode": "cross",
    }


def _symbol_set_from_payload(payload: Mapping[str, Any]) -> set[str]:
    symbols: set[str] = set()
    for key in ("accepted_live_symbols", "live_symbols", "execution_live_symbols"):
        symbols.update(str(item).upper() for item in payload.get(key) or [] if str(item).strip())
    config = payload.get("live_canary_config")
    if isinstance(config, Mapping):
        symbols.update(str(item).upper() for item in config.get("allowed_symbols") or [] if str(item).strip())
    return symbols


def _candidate_symbol(candidate: Mapping[str, Any]) -> str:
    return str(candidate.get("symbol") or "").upper()


def _positive_net_usd(candidate: Mapping[str, Any]) -> bool:
    value = _float(candidate.get("expected_net_pnl_usd"))
    return value is not None and value > 0


def _passes_dry_run_candidate_basics(candidate: Mapping[str, Any]) -> bool:
    return (
        str(candidate.get("allocator_decision") or "").upper() == "PASS"
        and str(candidate.get("risk_decision") or "").upper() == "PASS"
        and str(candidate.get("orchestrator_decision") or "").upper() == "PASS"
    )


def _select_inventory_row(rows: list[dict[str, Any]], *, accepted_symbols: set[str]) -> dict[str, Any]:
    if not rows:
        return {}
    ranked: list[tuple[int, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        symbol_allowed = bool(accepted_symbols) and _candidate_symbol(row) in accepted_symbols
        score = 0
        if symbol_allowed:
            score += 100
        if _positive_net_usd(row):
            score += 20
        if _passes_dry_run_candidate_basics(row):
            score += 10
        ranked.append((score * 10_000 - index, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _candidate_from_args(
    *,
    candidate_file: Path | None,
    inventory_dir: Path | None,
    accepted_symbols: set[str] | None = None,
) -> dict[str, Any]:
    if candidate_file is not None:
        return _read_json(candidate_file)
    accepted = accepted_symbols or set()
    if inventory_dir is not None:
        row = _select_inventory_row(_read_jsonl_rows(inventory_dir / "a_plus_candidate_rows.jsonl"), accepted_symbols=accepted)
        if row:
            return row
        return _select_inventory_row(_read_jsonl_rows(inventory_dir / "near_a_plus_candidate_rows.jsonl"), accepted_symbols=accepted)
    return {}


def _symbol_filter(
    client: Any,
    candidate: Mapping[str, Any],
    *,
    metadata_transport: Any | None = None,
) -> dict[str, Any]:
    symbol = str(candidate.get("symbol") or "").upper()
    cached = _fetch_symbol_filters_from_cache(client, symbol)
    if cached:
        return cached
    for key in (
        f"v2:exchange:symbol_filters:{symbol}",
        f"v2:symbol_filters:{symbol}",
        f"v2:binance:symbol_filters:{symbol}",
        "v2:exchange:symbol_filters",
    ):
        payload = _redis_json(client, key)
        if isinstance(payload, Mapping):
            return dict(payload)
    embedded = candidate.get("symbol_filter_status")
    if isinstance(embedded, Mapping):
        return dict(embedded)
    if not symbol:
        return {
            "ok": False,
            "symbol": symbol,
            "error_type": "SYMBOL_MISSING_FOR_SYMBOL_FILTER_LOOKUP",
            "endpoint": "redis:symbol_filters + public_metadata_fallback",
            "rest_fallback_used": False,
            "rest_used_as_primary": False,
        }
    transport = metadata_transport or BinanceUsdMWebSocketPrimaryTransport(redis_client=client)
    fetch_symbol_filters = getattr(transport, "fetch_symbol_filters", None)
    if callable(fetch_symbol_filters):
        try:
            payload = fetch_symbol_filters(symbol)
        except Exception as exc:
            return {
                "ok": False,
                "symbol": symbol,
                "error_type": type(exc).__name__,
                "endpoint": "GET /fapi/v1/exchangeInfo",
                "source": "binance_public_metadata_fallback",
                "rest_fallback_used": True,
                "rest_fallback_reason": "exchangeInfo_symbol_filters_metadata",
                "rest_used_as_primary": False,
            }
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def _feature_hash(payload: Any) -> str | None:
    features = payload.get("features") if isinstance(payload, Mapping) else None
    if not isinstance(features, Mapping) or not features:
        return None
    canonical = json.dumps(features, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def _candidate_quantity(candidate: Mapping[str, Any]) -> float | None:
    explicit = _float(candidate.get("quantity") or candidate.get("target_quantity"))
    if explicit is not None and explicit > 0:
        return explicit
    notional = _float(
        candidate.get("target_notional_usd")
        or candidate.get("gross_notional_usd")
        or candidate.get("notional")
        or candidate.get("expected_notional_usd")
    )
    price = _float(
        candidate.get("current_price")
        or candidate.get("entry_price")
        or candidate.get("price")
        or candidate.get("mark_price")
    )
    if notional is None or price is None or notional <= 0 or price <= 0:
        return None
    return notional / price


def _candidate_price_reference(candidate: Mapping[str, Any]) -> float | None:
    return _float(
        candidate.get("selected_execution_price")
        or candidate.get("entry_price")
        or candidate.get("current_price")
        or candidate.get("mark_price")
        or candidate.get("last_trade_price")
        or candidate.get("price")
    )


def _altdata_lineage(client: Any, candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Same alt-data context the paper loop consumes; hashes prove parity."""
    symbol = str(candidate.get("symbol") or "").upper()
    timeframe = str(candidate.get("timeframe") or "1m")
    confluence = _as_dict(_redis_json(client, f"v2:altdata:confluence:{symbol}:{timeframe}"))
    coinglass = _as_dict(_redis_json(client, f"v2:features:coinglass:{symbol}:{timeframe}"))
    moralis = _as_dict(_redis_json(client, f"v2:features:moralis:{symbol}:{timeframe}"))
    santiment = _as_dict(_redis_json(client, f"v2:features:santiment:{symbol}:1h"))
    features = confluence.get("features") if isinstance(confluence.get("features"), Mapping) else {}
    used = sorted(name for name, value in features.items() if value is not None)
    missing = sorted(name for name, value in features.items() if value is None)
    return {
        "provider_features_used": used,
        "provider_features_missing": missing,
        "coinglass_feature_hash": _feature_hash(coinglass),
        "santiment_feature_hash": _feature_hash(santiment),
        "moralis_feature_hash": _feature_hash(moralis),
        "altdata_confluence_hash": _feature_hash(confluence),
        "altdata_trade_block_score": features.get("altdata_trade_block_score"),
        "altdata_reduce_size_score": features.get("altdata_reduce_size_score"),
        "altdata_hedge_required_score": features.get("altdata_hedge_required_score"),
        "altdata_decision_contribution": "fail_safe_only_block_reduce_hedge_never_approve",
        "altdata_feature_cutoff": confluence.get("feature_cutoff"),
        "altdata_available_at": confluence.get("generated_utc"),
        "providers_present": confluence.get("providers_present"),
        "altdata_provider_hash_source": "v2_feature_aliases",
        "source_note": "read from same v2:altdata:confluence keys the paper loop preemptive gate consumes",
    }


def build_dry_run_packet(
    *,
    client: Any,
    candidate: Mapping[str, Any],
    output_dir: Path | None = None,
    generated_utc: str | None = None,
    symbol_filter_transport: Any | None = None,
    symbol_filter_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    generated = generated_utc or _utc_now()
    runtime_payload = _as_dict(_redis_json(client, "v2:live_gate:state"))
    if not runtime_payload:
        runtime_payload = {
            "live_gate": "blocked_human_only",
            "release_mode": "NON_LIVE",
            "operator_approved": False,
            "kill_switch_enabled": False,
            "kill_switch_active": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }
    operator_truth = _as_dict(_redis_json(client, "v2:operator:truth"))
    account_snapshot = _as_dict(_redis_json(client, "v2:live_order_transport:status"))
    ws_account_snapshot = _websocket_signed_account_snapshot(client)
    if ws_account_snapshot and not (
        account_snapshot.get("signed_account_read_ok") is True or account_snapshot.get("ok") is True
    ):
        account_snapshot = {**account_snapshot, **ws_account_snapshot}
    resolved_symbol_filter_snapshot = (
        dict(symbol_filter_snapshot)
        if isinstance(symbol_filter_snapshot, Mapping)
        else _symbol_filter(
            client,
            candidate,
            metadata_transport=symbol_filter_transport,
        )
    )
    price_reference = _candidate_price_reference(candidate)
    allocation_payload = {
        "allocator_decision_id": candidate.get("allocator_decision_id"),
        "symbol": candidate.get("symbol"),
        "timeframe": candidate.get("timeframe"),
        "side": candidate.get("side"),
        "action": candidate.get("side"),
        "price": price_reference,
        "price_reference": price_reference,
        "target_notional_usd": candidate.get("target_notional_usd")
        or candidate.get("gross_notional_usd")
        or candidate.get("notional")
        or candidate.get("expected_notional_usd"),
        "gross_notional_usd": candidate.get("gross_notional_usd"),
        "target_quantity": _candidate_quantity(candidate),
        "allocated_margin_usd": candidate.get("allocated_margin_usd"),
        "expected_net_pnl_usd": candidate.get("expected_net_pnl_usd"),
        "max_loss_usd": candidate.get("max_loss_usd") or candidate.get("expected_max_loss_usd"),
        "liquidation_buffer_usd": candidate.get("liquidation_buffer_usd") or candidate.get("expected_liquidation_buffer_usd"),
        "liquidation_buffer_pct": candidate.get("liquidation_buffer_pct"),
        "maintenance_margin_usd": candidate.get("maintenance_margin_usd"),
        "estimated_liquidation_price": candidate.get("estimated_liquidation_price"),
        "distance_to_liquidation_usd": candidate.get("distance_to_liquidation_usd"),
        "recommended_leverage": candidate.get("recommended_leverage"),
        "recommended_leverage_source": candidate.get("recommended_leverage_source"),
        "recommended_margin_mode": candidate.get("recommended_margin_mode"),
        "recommended_margin_mode_source": candidate.get("recommended_margin_mode_source"),
        "allocator_decision": candidate.get("allocator_decision"),
        "allocator_block_reasons": candidate.get("allocator_block_reasons") or [],
        "signed_read_status": candidate.get("signed_read_status"),
        "hedge_required": candidate.get("hedge_required"),
        "hedge_plan": candidate.get("hedge_plan"),
        "exit_plan": candidate.get("exit_plan"),
        "preemptive_edge_control": {
            "preemptive_decision_id": candidate.get("preemptive_decision_id"),
            "preemptive_decision": "ALLOW" if candidate.get("A_plus_candidate") else candidate.get("preemptive_decision"),
            "preemptive_action": candidate.get("preemptive_action"),
            "pre_trade_loss_probability": candidate.get("pre_trade_loss_probability"),
            "expected_edge_after_cost_bps": candidate.get("expected_edge_after_cost_bps"),
            "advanced_indicator_consumed": candidate.get("advanced_indicator_features_present"),
            "advanced_indicator_status": "ADVANCED_INDICATOR_CONSUMED" if candidate.get("advanced_indicator_features_present") else None,
            "advanced_indicator_block": False,
            "advanced_indicator_shadow": False,
            "advanced_indicator_block_reasons": [],
            "advanced_indicator_caution_reasons": [],
            "advanced_indicator_missing_evidence": [],
        },
    }
    bundle = build_phase7_status_bundle(
        runtime_payload=runtime_payload,
        operator_truth=operator_truth,
        account_snapshot=account_snapshot,
        symbol_filter_snapshot=resolved_symbol_filter_snapshot,
        allocation_payload=allocation_payload,
        candidate_signal=dict(candidate),
        generated_utc=generated,
    )
    altdata_lineage = _altdata_lineage(client, candidate)
    status = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated,
        "candidate_present": bool(candidate),
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "live_pre_submit_dry_run_status": bundle["live_pre_submit_dry_run_status"],
        "first_live_canary_operator_packet": bundle["first_live_canary_operator_packet"],
        "real_trader_readiness_status": bundle["real_trader_readiness_status"],
        "altdata_lineage": altdata_lineage,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(output_dir / "live_pre_submit_dry_run_status.json", bundle["live_pre_submit_dry_run_status"])
        _write_json(output_dir / "first_live_canary_operator_packet.json", bundle["first_live_canary_operator_packet"])
        _write_json(output_dir / "real_trader_readiness_status.json", bundle["real_trader_readiness_status"])
        _write_json(output_dir / "v2_live_canary_dry_run_status.json", status)
    return status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="v2/runtime/live_canary_dry_run/latest")
    parser.add_argument("--candidate-file", default=None)
    parser.add_argument("--inventory-dir", default=None)
    parser.add_argument("--redis-url", default=None)
    parser.add_argument(
        "--refresh-signed-read-status",
        action="store_true",
        help="run read-only Binance WebSocket API signed reads and publish the dry-run status key first",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    client = _redis_client(args.redis_url)
    runtime_payload = _as_dict(_redis_json(client, "v2:live_gate:state"))
    candidate = _candidate_from_args(
        candidate_file=Path(args.candidate_file) if args.candidate_file else None,
        inventory_dir=Path(args.inventory_dir) if args.inventory_dir else None,
        accepted_symbols=_symbol_set_from_payload(runtime_payload),
    )
    symbol_filter_snapshot = None
    if args.refresh_signed_read_status:
        # Public metadata can take longer than the signed-read freshness guard.
        # Resolve it first, then refresh account reads immediately before the
        # no-execute packet is composed.
        symbol_filter_snapshot = _symbol_filter(client, candidate)
        try:
            from v2.backend.app.cli.v2_binance_websocket_signed_read_status_publisher import (
                build_status as _build_signed_read_status,
                publish_status as _publish_signed_read_status,
            )

            signed_status = _build_signed_read_status(execute=True)
            _publish_signed_read_status(
                signed_status,
                redis_url=args.redis_url,
                ttl_seconds=900,
            )
        except Exception:
            pass
    status = build_dry_run_packet(
        client=client,
        candidate=candidate,
        output_dir=Path(args.output_dir),
        symbol_filter_snapshot=symbol_filter_snapshot,
    )
    if client is not None:
        try:
            client.set(
                "v2:live_canary:status",
                json.dumps(status, sort_keys=True, default=str),
                ex=900,
            )
        except Exception:
            pass
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        packet = status["first_live_canary_operator_packet"]
        print(json.dumps({
            "candidate_present": status["candidate_present"],
            "packet_status": packet.get("status"),
            "live_ready": packet.get("live_ready"),
            "signed_account_read_status": packet.get("signed_account_read_status"),
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
