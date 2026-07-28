"""V2 native paper portfolio state publisher.

Reads the current V2 paper ledger, recomputes paper equity/PnL from accepted
paper fills plus V2-owned market prices, and writes:

  v2:portfolio:state   (TTL=900s, string/JSON)
  v2/frontend/public/operator_runtime/v2_portfolio_state/latest/
    v2_portfolio_state.json

No live trading, no order placement, no old Redis writes. Held fill-gate rows
are diagnostics only; they are never counted as current open positions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from v2.backend.app.services.paper_accounting.mark_to_market import build_accounting_state
from v2.backend.app.services.paper_trade_management.margin_accounting import (
    build_paper_margin_status,
)

V2_REDIS_PREFIX = "v2:"
PORTFOLIO_RUNTIME_REPO_ROOT_ENV = "V2_PORTFOLIO_RUNTIME_REPO_ROOT"


def _configured_repo_root(
    environ: dict[str, str] | None = None,
    *,
    code_root: Path | None = None,
) -> Path:
    source = os.environ if environ is None else environ
    immutable_code_root = code_root or Path(__file__).resolve().parents[4]
    configured = str(source.get(PORTFOLIO_RUNTIME_REPO_ROOT_ENV) or "").strip()
    return Path(configured).expanduser().resolve() if configured else immutable_code_root


REPO_ROOT = _configured_repo_root()
PORTFOLIO_TTL_S = 900
PAYLOAD_PATH = REPO_ROOT / (
    "v2/frontend/public/operator_runtime/v2_portfolio_state/latest/"
    "v2_portfolio_state.json"
)
PAPER_ACCEPTED_FILLS_STATE_PATH = REPO_ROOT / (
    "v2/frontend/public/operator_runtime/v2_paper_trade_management/latest/"
    "paper_accepted_fills_state.json"
)
INVALID_ADMISSION_REASON = "P0_ENTRY_GATE_BLOCKED_NOT_EXPLORATION_RELAXABLE"

PAPER_INITIAL_CAPITAL = 10_000.0
EST = timezone(timedelta(hours=-4))


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _est_iso() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def _parse_aware_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        r.ping()
        return r
    except Exception:
        return None


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _coerce_float(val: Any) -> float | None:
    if isinstance(val, bool):
        return None
    try:
        if val is None:
            return None
        num = float(val)
    except (TypeError, ValueError):
        return None
    if num != num or num in (float("inf"), float("-inf")):
        return None
    return num


def _session_initial_capital(
    previous_portfolio_state: dict[str, Any],
    ledger: dict[str, Any] | None = None,
    paper_session_state: dict[str, Any] | None = None,
) -> float:
    ledger = ledger or {}
    paper_session_state = paper_session_state or {}
    for candidate in (
        paper_session_state.get("starting_equity_usd"),
        paper_session_state.get("initial_capital"),
        ledger.get("starting_equity_usd"),
        ledger.get("initial_capital"),
        previous_portfolio_state.get("starting_equity_usd"),
        previous_portfolio_state.get("initial_capital"),
    ):
        parsed = _coerce_float(candidate)
        if parsed is not None and parsed > 0:
            return parsed
    return PAPER_INITIAL_CAPITAL


def _redis_json(r, key: str) -> Any | None:
    try:
        raw = r.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _first_number(mapping: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        val = _coerce_float(mapping.get(key))
        if val is not None:
            return val
    return None


def _row_id(row: dict[str, Any]) -> str:
    for key in ("intent_id", "paper_fill_id", "signal_id", "source_prediction_id", "prediction_id"):
        value = row.get(key)
        if value:
            return str(value)
    return json.dumps(row, sort_keys=True, default=str)


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        ident = _row_id(row)
        if ident in seen:
            continue
        seen.add(ident)
        out.append(row)
    return out


def _closed_row_id(row: dict[str, Any]) -> str:
    for key in ("close_id", "outcome_label_id", "trainer_feedback_id", "position_id", "paper_close_id"):
        value = row.get(key)
        if value:
            return str(value)
    return _row_id(row)


def _dedupe_closed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        ident = _closed_row_id(row)
        if ident in seen:
            continue
        seen.add(ident)
        out.append(row)
    return out


def _decode_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _as_dict_rows(payload: Any, *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    payload = _decode_json(payload)
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows: list[dict[str, Any]] = []
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend(dict(row) for row in value if isinstance(row, dict))
        return rows
    return []


def _accepted_fill_state_path(ledger: dict[str, Any]) -> Path | None:
    source = ledger.get("accepted_fill_state_source")
    if not source:
        return None
    path = Path(str(source))
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _read_accepted_fill_state_rows(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    path = _accepted_fill_state_path(ledger)
    if path is None:
        return []
    try:
        payload = path.read_text(encoding="utf-8")
    except Exception:
        return []
    return _as_dict_rows(payload, keys=("accepted_fills", "rows"))


def _row_lineage_ids(row: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for field in (
        "fill_id",
        "ledger_row_id",
        "paper_trade_id",
        "entry_fill_id",
        "source_fill_id",
        "intent_id",
        "source_intent_id",
        "signal_id",
        "entry_signal_id",
        "prediction_id",
        "source_prediction_id",
        "entry_prediction_id",
        "decision_id",
        "entry_decision_id",
        "risk_decision_id",
        "orchestrator_decision_id",
        "allocation_id",
    ):
        value = row.get(field)
        if value not in (None, ""):
            ids.add(str(value))
    for field in (
        "source_fill_ids",
        "source_prediction_ids",
        "entry_fill_ids",
        "lineage_ids",
        "related_fill_ids",
    ):
        values = row.get(field)
        if isinstance(values, list):
            ids.update(str(value) for value in values if value not in (None, ""))
    return ids


def _canonical_sha256(value: Any) -> str | None:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _valid_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


_OPEN_POSITION_PROOF_HASH_FIELDS = (
    "paper_final_admission_receipt_hash",
    "paper_final_admission_bound_material_hash",
    "paper_persisted_ledger_contract_hash",
    "paper_cycle_reservation_commit_receipt_hash",
    "adaptive_policy_action_sha256",
    "adaptive_paper_policy_authorization_sha256",
)


def _proof_backed_open_fill_rows(
    open_positions: list[dict[str, Any]],
    ledger: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Project authoritative open inventory back to accounting fill rows.

    Operational accepted-fill rows are compacted after their entry cycle.  The
    portfolio publisher may therefore reconstruct mark-to-market state from an
    open position only when the paper ledger carries the dedicated immutable
    fill proof and a PASS one-proof-per-position receipt from the same atomic
    transaction.  Position payloads alone never become accounting authority.
    """

    proof_rows = [
        dict(row)
        for row in _as_list(ledger.get("open_position_fill_proofs"))
        if isinstance(row, dict)
    ]
    source_status = ledger.get("paper_open_position_fill_proof_status")
    source_status = dict(source_status) if isinstance(source_status, dict) else {}
    reasons: list[str] = []
    if source_status.get("status") != "PASS":
        reasons.append("OPEN_POSITION_FILL_PROOF_STATUS_NOT_PASS")
    if source_status.get("one_proof_per_open_position") is not True:
        reasons.append("OPEN_POSITION_FILL_PROOF_CARDINALITY_NOT_PROVEN")
    if source_status.get("proof_count") != len(proof_rows):
        reasons.append("OPEN_POSITION_FILL_PROOF_COUNT_MISMATCH")
    if source_status.get("input_open_position_count") != len(open_positions):
        reasons.append("OPEN_POSITION_FILL_PROOF_POSITION_COUNT_MISMATCH")
    if source_status.get("proofs_sha256") != _canonical_sha256(proof_rows):
        reasons.append("OPEN_POSITION_FILL_PROOF_COLLECTION_HASH_MISMATCH")
    if len(proof_rows) != len(open_positions):
        reasons.append("OPEN_POSITION_FILL_PROOF_COLLECTION_CARDINALITY_MISMATCH")

    proof_ids = [str(row.get("proof_id") or "") for row in proof_rows]
    if any(not proof_id for proof_id in proof_ids) or len(proof_ids) != len(set(proof_ids)):
        reasons.append("OPEN_POSITION_FILL_PROOF_IDENTITY_INVALID_OR_DUPLICATE")

    projected: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    for position in open_positions:
        position_id = str(position.get("position_id") or "")
        generation_id = str(position.get("position_generation_id") or "")
        matches = [
            proof
            for proof in proof_rows
            if str(proof.get("position_id") or "") == position_id
            and str(proof.get("position_generation_id") or "") == generation_id
        ]
        if len(matches) != 1:
            reasons.append(
                "OPEN_POSITION_FILL_PROOF_BINDING_COUNT_INVALID:"
                + (position_id or "MISSING_POSITION_ID")
            )
            continue
        proof = matches[0]
        proof_material = dict(proof)
        claimed_proof_id = proof_material.pop("proof_id", None)
        if (
            not _valid_sha256(claimed_proof_id)
            or claimed_proof_id != _canonical_sha256(proof_material)
        ):
            reasons.append("OPEN_POSITION_FILL_PROOF_HASH_INVALID:" + position_id)
        if (
            proof.get("schema_version") != "paper_open_position_fill_proof_v1"
            or proof.get("paper_final_admission_status") != "PASS"
            or proof.get("proof_origin")
            not in {"CURRENT_CYCLE_FINAL_ADMISSION_PASS", "EXISTING_DURABLE_PROOF"}
        ):
            reasons.append("OPEN_POSITION_FILL_PROOF_ADMISSION_CONTRACT_INVALID:" + position_id)
        if (
            proof.get("paper_only") is not True
            or proof.get("routes_to_live") is not False
            or proof.get("places_real_order") is not False
            or proof.get("exchange_action_taken") is not False
        ):
            reasons.append("OPEN_POSITION_FILL_PROOF_SAFETY_FLAGS_INVALID:" + position_id)
        if any(not _valid_sha256(proof.get(field)) for field in _OPEN_POSITION_PROOF_HASH_FIELDS):
            reasons.append("OPEN_POSITION_FILL_PROOF_REQUIRED_HASH_INVALID:" + position_id)

        quantity = _coerce_float(proof.get("quantity"))
        fill_price = _coerce_float(proof.get("fill_price"))
        gross_notional = _coerce_float(proof.get("gross_notional_usd"))
        leverage = _coerce_float(proof.get("effective_leverage"))
        margin = _coerce_float(proof.get("allocated_margin_usd"))
        position_quantity = _coerce_float(position.get("net_quantity"))
        position_price = _coerce_float(
            position.get("avg_entry_price") or position.get("entry_price")
        )
        if (
            quantity is None
            or quantity <= 0.0
            or fill_price is None
            or fill_price <= 0.0
            or gross_notional is None
            or gross_notional <= 0.0
            or leverage is None
            or leverage <= 0.0
            or margin is None
            or margin <= 0.0
            or position_quantity is None
            or not math.isclose(abs(position_quantity), quantity, rel_tol=1e-9, abs_tol=1e-12)
            or position_price is None
            or not math.isclose(position_price, fill_price, rel_tol=1e-9, abs_tol=1e-12)
            or not math.isclose(gross_notional, quantity * fill_price, rel_tol=1e-9, abs_tol=1e-8)
            or not math.isclose(margin, gross_notional / leverage, rel_tol=1e-9, abs_tol=1e-8)
        ):
            reasons.append("OPEN_POSITION_FILL_PROOF_ACCOUNTING_ARITHMETIC_INVALID:" + position_id)
        for field in (
            "fill_id",
            "prediction_id",
            "signal_id",
            "intent_id",
            "orchestrator_decision_id",
            "risk_decision_id",
            "allocation_id",
        ):
            if proof.get(field) in (None, ""):
                reasons.append(
                    f"OPEN_POSITION_FILL_PROOF_LINEAGE_MISSING:{position_id}:{field}"
                )

        projected.append(
            {
                **proof,
                "entry_price": fill_price,
                "notional": gross_notional,
                "source_fill_ids": [proof.get("fill_id")],
                "paper_session_id": position.get("paper_session_id"),
                "session_id": position.get("session_id"),
                "reset_session_id": position.get("reset_session_id"),
                "starting_equity_usd": position.get("starting_equity_usd"),
                "generated_utc": proof.get("proof_created_at"),
                "source": "v2:paper:ledger.open_position_fill_proofs",
            }
        )
        bindings.append(
            {
                "position_id": position_id,
                "position_generation_id": generation_id,
                "proof_id": claimed_proof_id,
                "fill_id": proof.get("fill_id"),
            }
        )

    reasons = sorted(set(reasons))
    status = {
        "schema_version": "portfolio_open_position_fill_proof_accounting_v1",
        "status": "PASS" if not reasons else "BLOCKED",
        "open_position_count": len(open_positions),
        "proof_count": len(proof_rows),
        "projected_fill_count": len(projected) if not reasons else 0,
        "one_proof_per_open_position": bool(
            not reasons and len(projected) == len(open_positions) == len(proof_rows)
        ),
        "bindings": bindings,
        "rejection_reasons": reasons,
        "position_payload_used_as_proof": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    return (projected if not reasons else []), status


def _invalid_admission_source_ids(accepted_rows: list[dict[str, Any]]) -> set[str]:
    invalid_ids: set[str] = set()
    for row in accepted_rows:
        if row.get("entry_gate_block_reasons"):
            invalid_ids.update(_row_lineage_ids(row))
    return invalid_ids


def _split_invalid_admission_rows(
    rows: list[dict[str, Any]],
    invalid_source_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not invalid_source_ids:
        return list(rows), []
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for row in rows:
        if _row_lineage_ids(row) & invalid_source_ids:
            invalid.append(row)
        else:
            valid.append(row)
    return valid, invalid


def _read_v2_market_price(r: Any, symbol: str) -> tuple[float | None, str, str | None]:
    """Read current price from V2-owned public market data only."""
    if r is None or not symbol:
        return None, "MISSING_SYMBOL_OR_REDIS", None
    payload: dict[str, Any] | None = _redis_json(r, f"{V2_REDIS_PREFIX}market:prices:{symbol}")
    if isinstance(payload, dict):
        ticker = payload.get("ticker_24hr") if isinstance(payload.get("ticker_24hr"), dict) else {}
        funding = payload.get("funding") if isinstance(payload.get("funding"), dict) else {}
        for source, container, keys in (
            ("v2:market:prices.ticker_24hr.lastPrice", ticker, ("lastPrice", "weightedAvgPrice")),
            ("v2:market:prices.funding.markPrice", funding, ("markPrice", "indexPrice")),
            ("v2:market:prices", payload, ("price", "last_price", "mark_price", "close")),
        ):
            px = _first_number(container, keys)
            if px is not None and px > 0:
                return px, source, str(payload.get("fetched_utc") or payload.get("generated_utc") or "")
    features = _redis_json(r, f"{V2_REDIS_PREFIX}features:latest:{symbol}:1m")
    if isinstance(features, dict) and features.get("feature_freshness_state") == "CURRENT":
        feats = features.get("features") if isinstance(features.get("features"), dict) else {}
        px = _first_number(feats, ("close_price", "last_price", "mark_price", "lastPrice"))
        if px is not None and px > 0:
            return px, "v2:features:latest:1m", str(features.get("generated_at") or features.get("generated_utc") or "")
    return None, "MISSING_CURRENT_V2_MARKET_PRICE", None


def _paper_side(row: dict[str, Any]) -> str:
    side = str(row.get("side") or row.get("selected_action") or row.get("action") or "").lower()
    if side in {"long", "buy"}:
        return "long"
    if side in {"short", "sell"}:
        return "short"
    return side or "unknown"


def _compute_accepted_position(row: dict[str, Any], r: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    symbol = str(row.get("symbol") or "").upper()
    side = _paper_side(row)
    entry_price = _first_number(row, ("fill_price", "entry_price", "price"))
    row_latest = _first_number(row, ("latest_price", "mark_price", "last_price"))
    market_price, market_source, market_generated = _read_v2_market_price(r, symbol)
    latest_price = market_price if market_price is not None else row_latest
    latest_source = market_source if market_price is not None else str(row.get("latest_price_source") or "ledger_row_latest_price")
    quantity = _first_number(row, ("quantity", "qty", "size"))
    notional = _first_number(row, ("notional", "requested_notional_usdt", "notional_usdt"))
    blockers: list[str] = []
    if not symbol:
        blockers.append("MISSING_SYMBOL")
    if entry_price is None or entry_price <= 0:
        blockers.append("MISSING_ENTRY_OR_FILL_PRICE")
    if latest_price is None or latest_price <= 0:
        blockers.append("MISSING_CURRENT_OR_LEDGER_LATEST_PRICE")
    if quantity is None or quantity == 0:
        if notional is not None and entry_price is not None and entry_price > 0:
            quantity = abs(notional / entry_price)
        else:
            blockers.append("MISSING_QUANTITY_OR_NOTIONAL")
    if notional is None and quantity is not None and entry_price is not None:
        notional = abs(quantity * entry_price)

    unrealized_pnl = None
    unrealized_bps = None
    if not blockers and quantity is not None and entry_price is not None and latest_price is not None:
        signed_qty = abs(quantity)
        if side == "short":
            unrealized_pnl = (entry_price - latest_price) * signed_qty
        else:
            unrealized_pnl = (latest_price - entry_price) * signed_qty
        if notional and notional > 0:
            unrealized_bps = (unrealized_pnl / notional) * 10_000.0

    position = {
        "symbol": symbol,
        "position_state": "accepted_paper_fill_open" if not blockers else "accepted_paper_fill_pnl_blocked",
        "open_position": not blockers,
        "side": side,
        "quantity": quantity,
        "notional": notional,
        "entry_price": entry_price,
        "fill_price": _coerce_float(row.get("fill_price")),
        "latest_price": latest_price,
        "latest_price_source": latest_source,
        "latest_price_source_generated_utc": market_generated,
        "unrealized_pnl_usd": unrealized_pnl,
        "unrealized_bps": unrealized_bps,
        "mfe_bps": _coerce_float(row.get("mfe_bps")),
        "mae_bps": _coerce_float(row.get("mae_bps")),
        "shadow_observation_count": 0,
        "accepted_intent_count": 1,
        "held_intent_count": 0,
        "intent_id": row.get("intent_id"),
        "signal_id": row.get("signal_id"),
        "prediction_id": row.get("source_prediction_id") or row.get("prediction_id"),
        "risk_decision_id": row.get("risk_decision_id"),
        "orchestrator_decision_id": row.get("orchestrator_decision_id"),
        "accepted_at_utc": row.get("accepted_at_utc") or row.get("generated_utc"),
        "source": "v2:paper:ledger.accepted",
        "live_gate": row.get("live_gate"),
        "pnl_blockers": blockers,
    }
    if blockers:
        return position, {"intent_id": row.get("intent_id"), "symbol": symbol, "blockers": blockers}
    return position, None


def _sum_closed_realized(rows: list[dict[str, Any]]) -> float:
    # Authoritative NET realized PnL only.  A legitimate break-even close has
    # realized_net_pnl_usd == 0.0, which is falsy, so a boolean `or` chain would
    # skip it and fall through to a GROSS alias (realized_pnl_usd / realized_pnl
    # / pnl_usd), silently mixing gross into the net sum and corrupting published
    # net economics (G13/G14).  Select the NET keys None-aware so 0.0 is treated
    # as an authoritative value and the gross aliases are never consulted here.
    net_keys = ("realized_net_pnl_usd", "realized_net_pnl", "net_pnl_usd")
    total = 0.0
    for row in rows:
        net_value = None
        for key in net_keys:
            candidate = row.get(key)
            if candidate is not None:
                net_value = candidate
                break
        total += _safe_float(net_value, 0.0)
    return total


def _sum_closed_gross_realized(rows: list[dict[str, Any]]) -> float:
    total = 0.0
    for row in rows:
        total += _safe_float(
            row.get("realized_gross_pnl_usd")
            or row.get("realized_gross_pnl")
            or row.get("gross_pnl_usd")
            or row.get("realized_pnl_usd")
            or row.get("realized_pnl_usdt")
            or row.get("realized_pnl")
            or row.get("pnl_usd"),
            0.0,
        )
    return total


def _mark_price_blockers(positions_by_symbol: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for position in positions_by_symbol:
        if not isinstance(position, dict) or position.get("open_position") is not True:
            continue
        symbol = str(position.get("symbol") or "").upper()
        mark_price = _coerce_float(position.get("last_mark_price"))
        if mark_price is not None and mark_price > 0:
            continue
        blockers.append(
            {
                "symbol": symbol,
                "classification": "MARK_PRICE_MISSING",
                "missing_fields": ["MISSING_CURRENT_MARK_PRICE"],
                "source_fill_ids": list(position.get("source_fill_ids") or []),
                "paper_session_id": position.get("paper_session_id"),
                "reason": "OPEN_PAPER_POSITION_MISSING_CURRENT_V2_MARKET_PRICE",
            }
        )
    return blockers


def _path_label(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def run_once(write_redis: bool = True) -> dict:
    producer_started_at = datetime.now(timezone.utc)
    r = _connect_redis()
    now_utc = _utc_iso()
    now_est = _est_iso()

    positions: list[dict] = []
    total_unrealized_bps = 0.0
    total_mfe_bps = 0.0
    total_mae_bps = 0.0
    unrealized_pnl_usd = 0.0
    open_position_notional = 0.0
    shadow_total = 0
    accepted_total = 0
    accepted_fill_total = 0
    economic_fill_total = 0
    non_economic_fill_total = 0
    blocked_total = 0
    held_total = 0
    symbols_with_positions: list[str] = []
    history_symbols_tracked = 0
    ledger_generated_utc = None
    ledger_count_fields_match_payload = True
    pnl_blockers: list[dict[str, Any]] = []
    mark_price_blockers: list[dict[str, Any]] = []
    portfolio_pnl_blockers: list[dict[str, Any]] = []
    closed_rows: list[dict[str, Any]] = []
    standalone_closed_rows: list[dict[str, Any]] = []
    accounting_inventory: list[dict[str, Any]] = []
    positions_by_symbol: list[dict[str, Any]] = []
    accounting: dict[str, Any] = {}
    active_accepted_fill_total = 0
    accepted_closed_filter_count = 0
    accepted_authoritative_open_suppressed_count = 0
    ledger_authoritative_no_open_positions = False
    accepted_closed_filter_sample: list[dict[str, Any]] = []
    paper_zero_pnl_reason: str | None = None
    last_fill_utc = None
    live_gate_status = "blocked_human_only"
    live_symbols: list[str] = []
    trader_execution_enabled = False
    previous_portfolio_state: dict[str, Any] = {}
    paper_session_state: dict[str, Any] = {}
    current_ledger_payload: dict[str, Any] = {}
    quarantined_invalid_positions: list[dict[str, Any]] = []
    quarantined_invalid_closed_trades: list[dict[str, Any]] = []
    invalid_admission_accepted_rows: list[dict[str, Any]] = []
    invalid_admission_closed_rows: list[dict[str, Any]] = []
    invalid_admission_standalone_closed_rows: list[dict[str, Any]] = []
    accepted_fill_state_rows: list[dict[str, Any]] = []
    accepted_count_rows: list[dict[str, Any]] = []
    raw_accepted_fill_total = 0
    raw_closed_position_count = 0
    invalid_admission_source_id_count = 0
    session_initial_capital = PAPER_INITIAL_CAPITAL
    authoritative_open_positions_for_margin: list[dict[str, Any]] = []
    open_position_fill_proof_accounting_status: dict[str, Any] = {
        "schema_version": "portfolio_open_position_fill_proof_accounting_v1",
        "status": "NOT_EVALUATED_NO_LEDGER",
        "open_position_count": 0,
        "proof_count": 0,
        "projected_fill_count": 0,
        "one_proof_per_open_position": False,
        "bindings": [],
        "rejection_reasons": [],
        "position_payload_used_as_proof": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }

    if r:
        history_symbols_tracked = len(list(r.scan_iter(match="v2:paper:position_history:*", count=500)))
        live_state = _redis_json(r, "v2:live_gate:state")
        trader_state = _redis_json(r, "v2:trader:execution_state")
        if isinstance(live_state, dict):
            live_gate_status = str(live_state.get("live_gate") or live_gate_status)
            live_symbols = [str(s).upper() for s in _as_list(live_state.get("live_symbols") or live_state.get("execution_live_symbols"))]
            trader_execution_enabled = bool(live_state.get("trader_execution_enabled", trader_execution_enabled))
        if isinstance(trader_state, dict):
            trader_execution_enabled = bool(trader_state.get("trader_execution_enabled", trader_execution_enabled))
        session_state = _redis_json(r, "v2:paper:session")
        if isinstance(session_state, dict):
            paper_session_state = session_state
            session_initial_capital = _session_initial_capital(
                previous_portfolio_state,
                paper_session_state=paper_session_state,
            )
        prior_state = _redis_json(r, "v2:portfolio:state")
        if isinstance(prior_state, dict):
            previous_portfolio_state = prior_state
            session_initial_capital = _session_initial_capital(
                previous_portfolio_state,
                paper_session_state=paper_session_state,
            )
        quarantined_invalid_positions = [
            dict(row)
            for row in _as_list(_redis_json(r, "v2:paper:quarantine:invalid_positions"))
            if isinstance(row, dict)
        ]
        quarantined_invalid_closed_trades = [
            dict(row)
            for row in _as_list(_redis_json(r, "v2:paper:quarantine:invalid_closed_trades"))
            if isinstance(row, dict)
        ]
        ledger = _redis_json(r, "v2:paper:ledger")
        standalone_closed = _redis_json(r, "v2:paper:closed_trades")
        standalone_closed_rows = [
            dict(row) for row in _as_list(standalone_closed) if isinstance(row, dict)
        ]
        if isinstance(ledger, dict):
            current_ledger_payload = ledger
            session_initial_capital = _session_initial_capital(
                previous_portfolio_state,
                ledger,
                paper_session_state,
            )
            ledger_generated_utc = ledger.get("generated_utc")
            accepted_rows_raw = _dedupe_rows([dict(row) for row in _as_list(ledger.get("accepted")) if isinstance(row, dict)])
            accepted_fill_state_rows = _dedupe_rows(_read_accepted_fill_state_rows(ledger))
            accepted_count_rows = accepted_fill_state_rows or accepted_rows_raw
            invalid_admission_source_ids = _invalid_admission_source_ids(
                accepted_count_rows + accepted_rows_raw
            )
            invalid_admission_source_id_count = len(invalid_admission_source_ids)
            accepted_rows, invalid_admission_accepted_rows = _split_invalid_admission_rows(
                accepted_count_rows,
                invalid_admission_source_ids,
            )
            shadow_rows = [dict(row) for row in _as_list(ledger.get("shadow_observations")) if isinstance(row, dict)]
            held_rows = [dict(row) for row in _as_list(ledger.get("held_by_paper_fill_gate")) if isinstance(row, dict)]
            ledger_closed_rows = _dedupe_closed_rows([
                dict(row)
                for source in ("closed", "closed_positions", "closed_trades", "closes", "realized", "realized_fills")
                for row in _as_list(ledger.get(source))
                if isinstance(row, dict)
            ])
            closed_rows_raw = (
                _dedupe_closed_rows(standalone_closed_rows)
                if standalone_closed_rows
                else ledger_closed_rows
            )
            closed_rows, invalid_admission_closed_rows = _split_invalid_admission_rows(
                closed_rows_raw,
                invalid_admission_source_ids,
            )
            (
                standalone_closed_rows,
                invalid_admission_standalone_closed_rows,
            ) = _split_invalid_admission_rows(
                standalone_closed_rows,
                invalid_admission_source_ids,
            )
            blocked_total = int(_safe_float(ledger.get("blocked_count"), 0))
            raw_accepted_fill_total = len(accepted_count_rows)
            raw_closed_position_count = len(closed_rows_raw)
            accepted_total = len(accepted_rows)
            accepted_fill_total = len(accepted_rows)
            shadow_total = int(_safe_float(ledger.get("shadow_observation_count"), len(shadow_rows)))
            held_total = int(_safe_float(ledger.get("held_by_paper_fill_gate_count"), len(held_rows)))
            ledger_count_fields_match_payload = (
                int(_safe_float(ledger.get("accepted_count"), len(accepted_count_rows))) == len(accepted_count_rows)
                and int(_safe_float(ledger.get("shadow_observation_count"), len(shadow_rows))) == len(shadow_rows)
                and int(_safe_float(ledger.get("held_by_paper_fill_gate_count"), len(held_rows))) == len(held_rows)
            )
            mark_prices: dict[str, tuple[float | None, str | None, float | None]] = {}
            for row in accepted_rows:
                sym = str(row.get("symbol") or "").upper()
                if not sym:
                    continue
                px, source, _generated = _read_v2_market_price(r, sym)
                mark_prices[sym] = (px, source, None)
            ledger_open_rows = [
                dict(row)
                for row in _as_list(ledger.get("open_positions"))
                if isinstance(row, dict)
            ]
            authoritative_open_positions_for_margin = ledger_open_rows
            accepted_aliases = set().union(
                *(_row_lineage_ids(row) for row in accepted_rows)
            ) if accepted_rows else set()
            proof_required_positions = [
                row
                for row in ledger_open_rows
                if not (_row_lineage_ids(row) & accepted_aliases)
            ]
            if proof_required_positions:
                (
                    proof_backed_fill_rows,
                    open_position_fill_proof_accounting_status,
                ) = _proof_backed_open_fill_rows(ledger_open_rows, ledger)
                if open_position_fill_proof_accounting_status["status"] == "PASS":
                    accepted_rows = _dedupe_rows(
                        [*accepted_rows, *proof_backed_fill_rows]
                    )
                    accepted_total = len(accepted_rows)
                    accepted_fill_total = len(accepted_rows)
                    raw_accepted_fill_total = len(accepted_rows)
                    for row in proof_backed_fill_rows:
                        sym = str(row.get("symbol") or "").upper()
                        if sym and sym not in mark_prices:
                            px, source, _generated = _read_v2_market_price(r, sym)
                            mark_prices[sym] = (px, source, None)
            else:
                source_proofs = _as_list(ledger.get("open_position_fill_proofs"))
                source_proof_status = ledger.get(
                    "paper_open_position_fill_proof_status"
                )
                source_proof_status = (
                    dict(source_proof_status)
                    if isinstance(source_proof_status, dict)
                    else {}
                )
                open_position_fill_proof_accounting_status = {
                    **open_position_fill_proof_accounting_status,
                    "status": "NOT_REQUIRED_CURRENT_OPERATIONAL_ACCEPTED_FILL_BOUND",
                    "open_position_count": len(ledger_open_rows),
                    "proof_count": len(source_proofs),
                    "operational_fill_binding_count": len(ledger_open_rows),
                    "one_proof_per_open_position": bool(
                        source_proof_status.get("status") == "PASS"
                        and source_proof_status.get("one_proof_per_open_position")
                        is True
                        and len(source_proofs) == len(ledger_open_rows)
                    ),
                }
            ledger_positions_by_symbol = ledger.get("positions_by_symbol")
            ledger_open_count = _coerce_float(
                ledger.get("open_position_count")
                if ledger.get("open_position_count") is not None
                else ledger.get("accepted_position_count")
            )
            ledger_authoritative_no_open_positions = (
                ledger_open_count == 0.0
                and ("open_position_count" in ledger or "accepted_position_count" in ledger)
                and not ledger_open_rows
                and not bool(ledger_positions_by_symbol)
            )
            accounting_accepted_rows = [] if ledger_authoritative_no_open_positions else accepted_rows
            accounting = build_accounting_state(
                accounting_accepted_rows,
                closed_rows,
                mark_prices,
                initial_capital=session_initial_capital,
            )
            accounting_inventory = list(accounting.get("inventory") or [])
            positions_by_symbol = list(accounting.get("positions_by_symbol") or [])
            mark_price_blockers = _mark_price_blockers(positions_by_symbol)
            active_accepted_fill_total = int(_safe_float(accounting.get("active_accepted_fill_count"), len(accepted_rows)))
            accepted_closed_filter_count = int(_safe_float(accounting.get("accepted_closed_filter_count"), 0))
            if ledger_authoritative_no_open_positions:
                accepted_authoritative_open_suppressed_count = max(
                    0,
                    len(accepted_rows) - accepted_closed_filter_count,
                )
            accepted_closed_filter_sample = list(accounting.get("accepted_closed_filter_sample") or [])
            economic_fill_total = int(_safe_float(accounting.get("economic_fill_count"), 0))
            non_economic_fill_total = int(_safe_float(accounting.get("non_economic_fill_count"), 0))
            pnl_blockers = list(accounting.get("non_economic_fill_blockers") or [])
            if (
                proof_required_positions
                and open_position_fill_proof_accounting_status.get("status") != "PASS"
            ):
                pnl_blockers.append(
                    {
                        "classification": "OPEN_POSITION_FILL_PROOF_ACCOUNTING_BLOCKED",
                        "missing_fields": list(
                            open_position_fill_proof_accounting_status.get(
                                "rejection_reasons"
                            )
                            or []
                        ),
                        "reason": (
                            "OPEN_POSITION_WITHOUT_OPERATIONAL_ACCEPTED_FILL_REQUIRES_"
                            "VALID_DURABLE_PROOF"
                        ),
                    }
                )
            portfolio_pnl_blockers = [*pnl_blockers, *mark_price_blockers]
            unrealized_pnl_usd = _safe_float(accounting.get("unrealized_pnl"), 0.0)
            total_unrealized_bps = 0.0
            open_position_notional = sum(
                _safe_float(position.get("gross_notional"), 0.0)
                for position in positions_by_symbol
                if position.get("open_position") is True
            )
            paper_zero_pnl_reason = accounting.get("zero_pnl_reason")
            for position in positions_by_symbol:
                sym = str(position.get("symbol") or "").upper()
                if sym:
                    symbols_with_positions.append(sym)
                positions.append({
                    "symbol": sym,
                    "position_state": (
                        "accepted_paper_fill_open"
                        if position.get("open_position") is True
                        else "accepted_paper_fill_closed_or_flat"
                    ),
                    "open_position": bool(position.get("open_position")),
                    "side": position.get("side"),
                    "quantity": position.get("net_quantity"),
                    "notional": position.get("gross_notional"),
                    "entry_price": position.get("avg_entry_price"),
                    "fill_price": position.get("avg_entry_price"),
                    "latest_price": position.get("last_mark_price"),
                    "latest_price_source": position.get("last_mark_price_source"),
                    "paper_session_id": position.get("paper_session_id"),
                    "paper_session_ids": position.get("paper_session_ids"),
                    "session_id": position.get("session_id"),
                    "reset_session_id": position.get("reset_session_id"),
                    "starting_equity_usd": position.get("starting_equity_usd"),
                    "unrealized_pnl_usd": position.get("unrealized_pnl"),
                    "realized_pnl_usd": position.get("realized_pnl"),
                    "unrealized_bps": None,
                    "mfe_bps": None,
                    "mae_bps": None,
                    "shadow_observation_count": 0,
                    "accepted_intent_count": position.get("fill_count"),
                    "held_intent_count": 0,
                    "source": "v2:paper:ledger.accepted.reconstructed",
                    "pnl_blockers": [],
                    "source_fill_ids": position.get("source_fill_ids"),
                })
            for blocker in pnl_blockers:
                sym = str(blocker.get("symbol") or "").upper()
                if sym:
                    symbols_with_positions.append(sym)
            for row in accepted_rows:
                if row.get("accepted_at_utc") or row.get("generated_utc"):
                    last_fill_utc = max(str(last_fill_utc or ""), str(row.get("accepted_at_utc") or row.get("generated_utc")))
            for row in shadow_rows:
                sym = str(row.get("symbol") or "").upper()
                if sym:
                    symbols_with_positions.append(sym)
                positions.append({
                    "symbol": sym,
                    "position_state": "shadow_observation_only",
                    "side": row.get("side", "none"),
                    "unrealized_bps": None,
                    "mfe_bps": None,
                    "mae_bps": None,
                    "shadow_observation_count": 1,
                    "accepted_intent_count": 0,
                    "held_intent_count": 0,
                    "entry_price": row.get("entry_price"),
                    "latest_price": row.get("latest_price"),
                    "intent_id": row.get("intent_id"),
                    "paper_fill_allowed": False,
                    "blocker": "PAPER_FILL_GATE_FALSE_SHADOW_OBSERVATION_ONLY",
                    "source": "v2:paper:ledger.shadow_observations",
                    "live_gate": row.get("live_gate"),
                })
            for row in held_rows[:25]:
                sym = str(row.get("symbol") or "").upper()
                if sym:
                    symbols_with_positions.append(sym)
                positions.append({
                    "symbol": sym,
                    "position_state": "held_by_paper_fill_gate",
                    "open_position": False,
                    "side": row.get("selected_action_upstream", "none"),
                    "unrealized_bps": None,
                    "mfe_bps": None,
                    "mae_bps": None,
                    "shadow_observation_count": 0,
                    "accepted_intent_count": 0,
                    "held_intent_count": 1,
                    "entry_price": None,
                    "latest_price": None,
                    "intent_id": row.get("intent_id"),
                    "paper_fill_gate_status": row.get("paper_fill_gate_status"),
                    "paper_fill_gate_block_reasons": row.get("paper_fill_gate_block_reasons"),
                    "checkpoint_blocker": row.get("checkpoint_blocker"),
                    "source": "v2:paper:ledger.held_by_paper_fill_gate",
                    "live_gate": row.get("live_gate"),
                })
        elif standalone_closed_rows:
            closed_rows = _dedupe_closed_rows(standalone_closed_rows)
            accounting = build_accounting_state(
                [],
                closed_rows,
                {},
                initial_capital=session_initial_capital,
            )
            paper_zero_pnl_reason = accounting.get("zero_pnl_reason")
            portfolio_pnl_blockers = []
            mark_price_blockers = []

    # Sort by unrealized_bps descending
    positions.sort(key=lambda x: _safe_float(x.get("unrealized_bps"), -1_000_000.0), reverse=True)

    open_positions = [p for p in positions if p.get("open_position") is True]
    closed_position_count = len(closed_rows)
    realized_pnl_usd = _safe_float(accounting.get("realized_pnl"), _sum_closed_realized(closed_rows))
    realized_gross_pnl_usd = _sum_closed_gross_realized(
        standalone_closed_rows if standalone_closed_rows else closed_rows
    )
    cash_balance = session_initial_capital + realized_pnl_usd
    equity = cash_balance + unrealized_pnl_usd
    margin_rows = (
        authoritative_open_positions_for_margin
        if authoritative_open_positions_for_margin
        else ([] if ledger_authoritative_no_open_positions else open_positions)
    )
    prior_margin_status = previous_portfolio_state.get("paper_account_margin_status")
    ledger_margin_status = current_ledger_payload.get("paper_account_margin_status")
    margin_buffer_pct = _coerce_float(
        ledger_margin_status.get("min_available_margin_buffer_pct")
        if isinstance(ledger_margin_status, dict)
        else None
    )
    if margin_buffer_pct is None and isinstance(prior_margin_status, dict):
        margin_buffer_pct = _coerce_float(
            prior_margin_status.get("min_available_margin_buffer_pct")
        )
    paper_account_margin_status = build_paper_margin_status(
        equity=equity,
        wallet_balance=cash_balance,
        open_positions=margin_rows,
        min_available_margin_buffer_pct=margin_buffer_pct or 0.0,
        reservations_included_in_open_positions=True,
    )
    paper_account_margin_status["source"] = (
        "V2_PAPER_LEDGER_OPEN_POSITIONS"
        if authoritative_open_positions_for_margin
        else "PORTFOLIO_RECONSTRUCTED_OPEN_POSITIONS"
    )
    paper_account_margin_status["generated_utc"] = now_utc
    total_pnl_usd = realized_pnl_usd + unrealized_pnl_usd
    invalid_admission_realized_pnl_usd = _sum_closed_realized(invalid_admission_closed_rows)
    raw_realized_pnl_including_invalid_admissions = (
        realized_pnl_usd + invalid_admission_realized_pnl_usd
    )
    raw_equity_including_invalid_admissions = (
        session_initial_capital
        + raw_realized_pnl_including_invalid_admissions
        + unrealized_pnl_usd
    )
    previous_high_water = _coerce_float(
        previous_portfolio_state.get("equity_high_water_mark")
        or previous_portfolio_state.get("high_water_mark")
        or previous_portfolio_state.get("equity")
    )
    previous_open_positions = int(_safe_float(previous_portfolio_state.get("open_positions_count"), 0))
    reset_stale_high_water = accepted_closed_filter_count > 0 and previous_open_positions > 0
    carried_high_water = None if reset_stale_high_water else previous_high_water
    equity_high_water_mark = max(session_initial_capital, carried_high_water or session_initial_capital, equity)
    current_drawdown_usd = max(0.0, equity_high_water_mark - equity)
    current_drawdown_bps = (
        current_drawdown_usd / equity_high_water_mark * 10000.0
        if equity_high_water_mark > 0
        else 0.0
    )
    equity_reconciliation_difference = _safe_float(
        accounting.get("equity_reconciliation_difference"),
        equity - (session_initial_capital + realized_pnl_usd + unrealized_pnl_usd),
    )
    # When the standalone v2:paper:closed_trades list is populated, derive
    # closed_ledger_net_pnl from it exclusively — it is the same source the G08
    # guardian verifier reads, so both will always agree regardless of when the
    # portfolio publisher runs relative to the paper loop's write cycle.
    # The ledger dict's "closed_trades" key holds only the last-50 sample, which
    # can cause transient gaps if the portfolio is published between the standalone
    # write and the ledger-dict write.
    # Fall back to the merged/accounting path only when standalone is empty
    # (early startup, test fixtures that don't populate the standalone key).
    closed_ledger_net_pnl = (
        _sum_closed_realized(standalone_closed_rows)
        if standalone_closed_rows
        else _safe_float(accounting.get("closed_ledger_net_pnl"), _sum_closed_realized(closed_rows))
    )
    portfolio_realized_matches_closed_ledger = abs(realized_pnl_usd - closed_ledger_net_pnl) <= 0.01
    if not portfolio_pnl_blockers:
        portfolio_pnl_blockers = list(pnl_blockers)
    if accepted_fill_total == 0 and invalid_admission_accepted_rows:
        classification = "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_INVALID_ADMISSIONS_EXCLUDED"
        paper_equity_reason = "INVALID_ADMISSION_ROWS_EXCLUDED_FROM_CLEAN_SESSION_EQUITY"
    elif accepted_fill_total == 0:
        classification = "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_NO_ACCEPTED_FILLS"
        paper_equity_reason = "NO_ACCEPTED_PAPER_FILL_IN_CURRENT_V2_LEDGER"
    elif active_accepted_fill_total == 0 and closed_rows:
        classification = "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_CLOSED_ONLY"
        paper_equity_reason = "ALL_ACCEPTED_FILLS_ALREADY_REPRESENTED_IN_CLOSED_TRADE_LEDGER"
    elif economic_fill_total == 0:
        classification = "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_NO_ECONOMIC_FILLS"
        paper_equity_reason = paper_zero_pnl_reason or "NO_ECONOMIC_FILLS"
    elif mark_price_blockers:
        classification = "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_MARK_PRICE_MISSING"
        paper_equity_reason = "MARK_PRICE_MISSING"
    elif pnl_blockers:
        classification = "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_PARTIAL_PNL"
        paper_equity_reason = "ACCEPTED_FILL_PNL_BLOCKERS_PRESENT"
    else:
        classification = "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_EQUITY_OK"
        paper_equity_reason = paper_zero_pnl_reason or "EQUITY_RECOMPUTED_FROM_CURRENT_LEDGER_AND_V2_MARKET_PRICES"

    order_counters = {
        "paper_accepted_intent_count": accepted_total,
        "paper_accepted_fill_count": accepted_fill_total,
        "paper_accepted_fill_raw_count": raw_accepted_fill_total,
        "paper_invalid_admission_accepted_count": len(invalid_admission_accepted_rows),
        "paper_economic_fill_count": economic_fill_total,
        "paper_non_economic_fill_count": non_economic_fill_total,
        "paper_held_intent_count": held_total,
        "paper_blocked_intent_count": blocked_total,
        "paper_shadow_observation_count": shadow_total,
        "paper_open_position_count": len(open_positions),
        "paper_closed_position_count": closed_position_count,
        "paper_closed_position_raw_count": raw_closed_position_count,
        "paper_invalid_admission_closed_count": len(invalid_admission_closed_rows),
        "live_order_count": 0,
        "test_order_count": 0,
        "exchange_order_mutation_count": 0,
    }
    quarantined_invalid_row_count = (
        len(quarantined_invalid_positions)
        + len(quarantined_invalid_closed_trades)
        + len(invalid_admission_accepted_rows)
        + len(invalid_admission_closed_rows)
    )
    contains_quarantined_positions = bool(pnl_blockers or quarantined_invalid_row_count)
    producer_generated_time = datetime.now(timezone.utc)
    producer_generated_at = _iso_utc(producer_generated_time)
    ledger_event_time = _parse_aware_utc(ledger_generated_utc)
    source_time_rejection_reasons: list[str] = []
    if current_ledger_payload:
        if ledger_event_time is None:
            source_time_rejection_reasons.append("PAPER_LEDGER_GENERATED_AT_INVALID")
        elif ledger_event_time > producer_generated_time:
            source_time_rejection_reasons.append("PAPER_LEDGER_GENERATED_AFTER_PORTFOLIO_STATE")
        source_event_time = _iso_utc(ledger_event_time) if not source_time_rejection_reasons else None
        source_event_time_source = "v2:paper:ledger.generated_utc"
    else:
        source_event_time = _iso_utc(producer_started_at)
        source_event_time_source = "PORTFOLIO_PUBLISHER_OBSERVATION_NO_LEDGER"
    paper_account_margin_status["generated_utc"] = producer_generated_at
    portfolio_state = {
        "schema_version": "v2_native_portfolio_state_v2",
        "classification": classification,
        "source_event_time": source_event_time,
        "event_time": source_event_time,
        "source_event_time_source": source_event_time_source,
        "source_event_time_raw": ledger_generated_utc,
        "producer_generated_at": producer_generated_at,
        "generated_at": producer_generated_at,
        "generated_utc": producer_generated_at,
        "portfolio_state_time_contract_status": (
            "PASS" if not source_time_rejection_reasons else "BLOCKED"
        ),
        "portfolio_state_time_contract_rejection_reasons": source_time_rejection_reasons,
        "generated_est": now_est,
        "account_mode": "paper_shadow_only",
        "account_scope": "PAPER_SIM_ACCOUNT",
        "source_type": "paper_sim_recomputed_from_v2_ledger",
        "paper_or_live": "paper",
        "contains_simulated_positions": True,
        "contains_live_positions": False,
        "contains_quarantined_positions": contains_quarantined_positions,
        # Canonical PnL source contract (Phase 1 implementation)
        "pnl_source_key": "v2:portfolio:state",
        "pnl_source_route": "/api/v2/portfolio",
        "pnl_source_type": "CANONICAL_CURRENT_SESSION_RUNTIME",
        "freshness_seconds": 0,
        "pnl_conflict_detected": False,
        "pnl_conflict_reason": None,
        "pnl_conflict_sources": [],
        "equity_trusted": not bool(portfolio_pnl_blockers),
        "pnl_trusted": not bool(portfolio_pnl_blockers),
        "reason_if_untrusted": (
            "MARK_PRICE_MISSING_FOR_OPEN_POSITION"
            if mark_price_blockers
            else
            "INVALID_OR_NON_ECONOMIC_PAPER_ROWS_EXCLUDED_FROM_EQUITY"
            if portfolio_pnl_blockers
            else None
        ),
        "quarantined_invalid_position_count": (
            len(pnl_blockers)
            + len(quarantined_invalid_positions)
            + len(invalid_admission_accepted_rows)
        ),
        "quarantined_invalid_closed_trade_count": (
            len(quarantined_invalid_closed_trades)
            + len(invalid_admission_closed_rows)
        ),
        "quarantined_invalid_row_count": quarantined_invalid_row_count,
        "quarantine_keys": {
            "invalid_positions": "v2:paper:quarantine:invalid_positions",
            "invalid_closed_trades": "v2:paper:quarantine:invalid_closed_trades",
        },
        "initial_capital": session_initial_capital,
        "starting_equity_usd": session_initial_capital,
        "reset_session_id": (
            paper_session_state.get("reset_session_id")
            or current_ledger_payload.get("reset_session_id")
            or previous_portfolio_state.get("reset_session_id")
        ),
        "paper_session_id": (
            paper_session_state.get("paper_session_id")
            or current_ledger_payload.get("paper_session_id")
            or previous_portfolio_state.get("paper_session_id")
        ),
        "trader_execution_enabled": trader_execution_enabled,
        "live_gate_status": live_gate_status,
        "live_symbols": live_symbols,
        # Aggregate stats
        "symbols_tracked": len(set(symbols_with_positions)),
        "history_symbols_tracked": history_symbols_tracked,
        "symbols_with_activity": len(set(symbols_with_positions)),
        "total_unrealized_bps": round(total_unrealized_bps, 2),
        "total_mfe_bps": round(total_mfe_bps, 2),
        "total_mae_bps": round(total_mae_bps, 2),
        "shadow_observation_total": shadow_total,
        "accepted_intent_total": accepted_total,
        "accepted_fill_total": accepted_fill_total,
        "accepted_fill_raw_total": raw_accepted_fill_total,
        "accepted_fill_state_row_count": len(accepted_fill_state_rows),
        "accepted_fill_state_source": (
            str(_accepted_fill_state_path(current_ledger_payload).relative_to(REPO_ROOT))
            if _accepted_fill_state_path(current_ledger_payload) is not None
            and _accepted_fill_state_path(current_ledger_payload).is_relative_to(REPO_ROOT)
            else (
                str(_accepted_fill_state_path(current_ledger_payload))
                if _accepted_fill_state_path(current_ledger_payload) is not None
                else None
            )
        ),
        "invalid_admission_source_id_count": invalid_admission_source_id_count,
        "invalid_admission_exclusion_reason": INVALID_ADMISSION_REASON,
        "invalid_admission_accepted_excluded": len(invalid_admission_accepted_rows),
        "invalid_admission_closed_trades_excluded": len(invalid_admission_closed_rows),
        "invalid_admission_standalone_closed_trades_excluded": len(
            invalid_admission_standalone_closed_rows
        ),
        "active_accepted_fill_total": active_accepted_fill_total,
        "accepted_fills_suppressed_by_closed_ledger_count": accepted_closed_filter_count,
        "accepted_fills_suppressed_by_authoritative_open_ledger_count": (
            accepted_authoritative_open_suppressed_count
        ),
        "ledger_authoritative_no_open_positions": ledger_authoritative_no_open_positions,
        "open_position_fill_proof_accounting_status": (
            open_position_fill_proof_accounting_status
        ),
        "economic_fill_total": economic_fill_total,
        "non_economic_fill_total": non_economic_fill_total,
        "held_by_paper_fill_gate_total": held_total,
        "blocked_total": blocked_total,
        "open_positions_count": len(open_positions),
        "closed_positions_count": closed_position_count,
        "closed_positions_raw_count": raw_closed_position_count,
        "order_counters": order_counters,
        "order_counters_source": "v2:paper:ledger + v2:paper:closed_trades",
        # Primary: Net PnL (Phase 1 canonical contract)
        "realized_net_pnl_usd": round(realized_pnl_usd, 8),
        # Diagnostic only: gross legacy/alias PnL before explicit net fields.
        "realized_gross_pnl_usd": round(realized_gross_pnl_usd, 8),
        "unrealized_pnl_usd": round(unrealized_pnl_usd, 8),
        "total_pnl_usd": round(total_pnl_usd, 8),
        # Legacy: Gross PnL alias (for backwards compatibility, not used for equity)
        "realized_pnl_usd": round(realized_pnl_usd, 8),
        "cash_balance": round(cash_balance, 8),
        "wallet_balance": round(cash_balance, 8),
        "open_position_notional": round(open_position_notional, 8),
        "equity": round(equity, 8),
        "used_margin_usd": paper_account_margin_status["used_margin_usd"],
        "available_margin": paper_account_margin_status["free_margin_usd"],
        "free_margin_usd": paper_account_margin_status["free_margin_usd"],
        "free_margin_after_buffer_usd": paper_account_margin_status[
            "free_margin_after_buffer_usd"
        ],
        "paper_account_margin_status": paper_account_margin_status,
        "current_session_equity": round(equity, 8),
        "clean_session_valid_equity_usd": round(equity, 8),
        "clean_session_valid_realized_pnl_usd": round(realized_pnl_usd, 8),
        "clean_session_valid_unrealized_pnl_usd": round(unrealized_pnl_usd, 8),
        "raw_realized_pnl_including_invalid_admissions_usd": round(
            raw_realized_pnl_including_invalid_admissions,
            8,
        ),
        "raw_equity_including_invalid_admissions_usd": round(
            raw_equity_including_invalid_admissions,
            8,
        ),
        "equity_high_water_mark": round(equity_high_water_mark, 8),
        "equity_high_water_mark_reset_reason": (
            "RESET_STALE_HIGH_WATER_AFTER_CLOSED_LEDGER_SUPPRESSED_PHANTOM_OPEN_INVENTORY"
            if reset_stale_high_water
            else None
        ),
        "previous_equity_high_water_mark": round(previous_high_water, 8)
        if previous_high_water is not None
        else None,
        "current_drawdown_usd": round(current_drawdown_usd, 8),
        "current_drawdown_bps": round(current_drawdown_bps, 8),
        "closed_ledger_net_pnl_usd": round(closed_ledger_net_pnl, 8),
        "portfolio_realized_matches_closed_ledger": portfolio_realized_matches_closed_ledger,
        "equity_reconciliation_difference_usd": round(equity_reconciliation_difference, 8),
        "equity_reconciles_within_1_cent": abs(equity_reconciliation_difference) <= 0.01,
        "equity_formula": (
            "initial_capital + cumulative_realized_pnl + unrealized_pnl "
            "- separately_unbooked_costs"
        ),
        "cumulative_realized_pnl": round(realized_pnl_usd, 8),
        "session_realized_pnl": round(_safe_float(accounting.get("session_realized_pnl"), realized_pnl_usd), 8),
        "lifetime_realized_pnl": round(_safe_float(accounting.get("lifetime_realized_pnl"), realized_pnl_usd), 8),
        "equity_change_since_last": round(equity - session_initial_capital, 8),
        "last_fill_utc": last_fill_utc,
        "last_equity_update_utc": now_utc,
        "last_equity_update_est": now_est,
        "paper_equity_reason": paper_equity_reason,
        "paper_equity_source": "v2:paper:ledger + v2:market:prices",
        "paper_zero_pnl_reason": paper_zero_pnl_reason,
        "pnl_blockers": portfolio_pnl_blockers,
        "mark_price_blockers": mark_price_blockers,
        "accepted_closed_filter_sample": accepted_closed_filter_sample[:25],
        "paper_fill_economic_inventory": accounting_inventory[:100],
        "positions_by_symbol": positions_by_symbol[:100],
        "positions": positions[:25],  # top 25
        "open_positions": open_positions[:25],
        "closed_positions": closed_rows[:25],
        "current_paper_ledger_generated_utc": ledger_generated_utc,
        "current_position_source": "v2:paper:ledger",
        "source_matches_redis": True if r else False,
        "ledger_count_fields_match_payload": ledger_count_fields_match_payload,
        "source_payload_ids": {
            "paper_ledger": "v2:paper:ledger",
            "paper_closed_trades": "v2:paper:closed_trades",
            "paper_positions": "v2:paper:positions",
            "market_prices": "v2:market:prices:{symbol}",
            "public_payload": _path_label(PAYLOAD_PATH),
        },
        "ledger_to_portfolio_status": (
            "LEDGER_TO_PORTFOLIO_CLOSED_ONLY" if active_accepted_fill_total == 0 and closed_rows
            else "FILL_TO_POSITION_PIPE_BROKEN" if accepted_fill_total > 0 and economic_fill_total == 0
            else "BROKEN_LEDGER_TO_PORTFOLIO_PIPE" if accepted_fill_total > 0 and len(open_positions) == 0
            else "NO_OPEN_PAPER_POSITION" if accepted_fill_total == 0
            else "LEDGER_TO_PORTFOLIO_PIPE_OK"
        ),
        "live_safety": {
            "live_gate_status": live_gate_status,
            "live_symbols": live_symbols,
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
        },
    }

    record_available_at = _iso_utc(datetime.now(timezone.utc))
    portfolio_state["record_available_at"] = record_available_at
    portfolio_state["available_at"] = record_available_at

    if write_redis and r:
        try:
            r.setex(
                f"{V2_REDIS_PREFIX}portfolio:state",
                PORTFOLIO_TTL_S,
                json.dumps(portfolio_state),
            )
        except Exception as exc:
            portfolio_state["redis_write_error"] = str(exc)

    PAYLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAYLOAD_PATH.write_text(json.dumps(portfolio_state, indent=2))
    return portfolio_state


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 portfolio state publisher")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--loop", action="store_true", help="Run in loop")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--no-redis", action="store_true")
    args = parser.parse_args()

    write_redis = not args.no_redis

    if args.loop:
        while True:
            try:
                result = run_once(write_redis=write_redis)
                print(
                    f"v2_portfolio_state_written classification={result['classification']}"
                    f" symbols_tracked={result['symbols_tracked']}"
                    f" shadow_total={result['shadow_observation_total']}"
                    f" held_total={result['held_by_paper_fill_gate_total']}"
                )
            except Exception as exc:
                print(f"v2_portfolio_state_error: {exc}", file=sys.stderr)
            time.sleep(args.interval_seconds)
    else:
        result = run_once(write_redis=write_redis)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
