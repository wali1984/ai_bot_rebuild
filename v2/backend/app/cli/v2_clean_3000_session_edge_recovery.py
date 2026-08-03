"""Publish clean $3,000 paper-session edge recovery gates.

This is a read-mostly verifier for the post-reset paper session. It scopes
performance, trainer feedback, and A-grade readiness to the active
``paper_session_id`` so pre-reset trades cannot pollute PF, expectancy,
win-rate, bootstrap, or A-grade statistics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GOAL_ID = "V2_3000_CLEAN_SESSION_EDGE_RECOVERY_FROM_ZERO_BASELINE"
REPO_ROOT = Path(__file__).resolve().parents[4]
GOAL_DIR = REPO_ROOT / "goal_state" / GOAL_ID
DEFAULT_SESSION_ID = "paper_3000_final_pre_live_20260705T024432Z"
STARTING_EQUITY_USD = 3_000.0
ENTRY_FREEZE_KEY = "v2:paper:entry_freeze"
FILL_STATE_FILE = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_paper_trade_management/latest"
    / "paper_accepted_fills_state.json"
)
INVALID_ADMISSION_REASON = "P0_ENTRY_GATE_BLOCKED_NOT_EXPLORATION_RELAXABLE"
STALE_PRE_RESET_FREEZE_REASONS = {
    "PORTFOLIO_LEDGER_TRUTH_VALIDATION_AND_QUARANTINE",
    "PAPER_NEW_ENTRIES_HALTED_BY_PORTFOLIO_TRUTH_FREEZE",
    "CLEAN_3000_SESSION_5_TRADE_GATE_FAILED",
    "CLEAN_3000_SESSION_50_TRADE_GATE_IRRECOVERABLE_BLOCKER",
}
# A verified root-cause exit repair (ATR stop floor + MFE breakeven protection,
# see paper_trade_management/exits.py) makes the ATR-stop cluster recoverable:
# losses that closed BEFORE the repair deployment no longer drive the blocking
# cluster flag, while 2+ NEW ATR-stop losses after the repair re-block
# immediately. Authorization requires the current schema-v2 paper-runtime
# evidence, exact run/cycle/process lineage, strict clocks/producer TTL, and
# current source/test/output/command/receipt hashes. A boolean/timestamp-only
# artifact keeps the original fail-closed behaviour. Loser buckets stay
# quarantined independently of this authorization.
ATR_EXIT_REPAIR_DEFAULT_STATUS_PATH = (
    REPO_ROOT
    / "goal_state/V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE"
    / "atr_stop_cluster_repair_status.json"
)
ATR_EXIT_REPAIR_STATUS_PATH = ATR_EXIT_REPAIR_DEFAULT_STATUS_PATH
ATR_EXIT_REPAIR_LEGACY_STATUS_PATH = (
    REPO_ROOT
    / "goal_state/V2_FABLE5_FULL_SYSTEM_A_PLUS_LIVE_READY_1000X_MACHINE_COMPLETION"
    / "atr_stop_cluster_repair_status.json"
)
# Historical path retained only so callers/tests can identify migration-era
# state. It is never an authorization fallback.


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _verified_exit_repair_deployed_utc(
    *,
    observed_utc: str | None = None,
    status_path: Path | None = None,
) -> datetime | None:
    """Authorize only an exact, current Phase 7 runtime-evidence contract.

    The legacy goal artifact is intentionally not consulted.  A local boolean
    such as ``repair_test_passed`` is not authority: current paper runtime
    output, source/test attestations, and the complete receipt are independently
    rehashed before pre-repair losses may be excluded.
    """

    def strict_utc(value: Any) -> datetime | None:
        text = str(value or "")
        if not text or (not text.endswith("Z") and "+" not in text[10:]):
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if (
            parsed.tzinfo is None
            or parsed.utcoffset() is None
            or parsed.utcoffset() != timezone.utc.utcoffset(parsed)
        ):
            return None
        return parsed.astimezone(timezone.utc)

    def canonical_sha256(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    try:
        loaded = json.loads(
            (status_path or ATR_EXIT_REPAIR_STATUS_PATH).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None
    payload = dict(loaded)
    observed_at = strict_utc(
        observed_utc
        or datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    generated_at = strict_utc(payload.get("generated_utc"))
    deployed_at = strict_utc(payload.get("repair_deployed_utc"))
    expires_at = strict_utc(payload.get("expires_at"))
    ttl_seconds = payload.get("ttl_seconds")
    if (
        observed_at is None
        or generated_at is None
        or deployed_at is None
        or expires_at is None
        or isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or ttl_seconds <= 0
        or not (deployed_at <= generated_at <= observed_at <= expires_at)
        or (expires_at - generated_at).total_seconds() != ttl_seconds
        or payload.get("schema_version")
        != "a_plus_phase7_exit_repair_status_v2"
        or payload.get("repair_test_passed") is not True
        or payload.get("paper_entry_freeze_clear_allowed_by_exit_repair")
        is not True
        or payload.get("paper_only") is not True
        or payload.get("routes_to_live") is not False
        or payload.get("places_real_order") is not False
    ):
        return None
    pass_conditions = payload.get("pass_conditions")
    runtime = payload.get("current_paper_exit_runtime_evidence")
    receipt = payload.get("runtime_authorization_receipt")
    if (
        not isinstance(pass_conditions, dict)
        or pass_conditions.get(
            "canonical_current_paper_exit_runtime_evidence_present"
        )
        is not True
        or not isinstance(runtime, dict)
        or not isinstance(receipt, dict)
    ):
        return None
    run_id = str(payload.get("run_id") or "")
    cycle_id = str(payload.get("cycle_id") or "")
    process_instance_id = str(payload.get("process_instance_id") or "")
    runtime_output = runtime.get("runtime_output")
    if (
        not run_id
        or not cycle_id
        or not process_instance_id
        or runtime.get("schema_version")
        != "phase7_current_paper_exit_runtime_evidence_v1"
        or runtime.get("run_id") != run_id
        or runtime.get("cycle_id") != cycle_id
        or runtime.get("process_instance_id") != process_instance_id
        or runtime.get("generated_utc") != payload.get("generated_utc")
        or runtime.get("expires_at") != payload.get("expires_at")
        or runtime.get("ttl_seconds") != ttl_seconds
        or runtime.get("paper_only") is not True
        or runtime.get("routes_to_live") is not False
        or runtime.get("places_real_order") is not False
        or not isinstance(runtime_output, dict)
    ):
        return None
    events = runtime_output.get("exit_events")
    behaviors = runtime_output.get("behavior_observations")
    paper_session_id = str(runtime_output.get("paper_session_id") or "")
    if (
        not paper_session_id
        or not isinstance(events, list)
        or not events
        or not isinstance(behaviors, dict)
    ):
        return None
    required_behaviors = {
        "atr_stop_floor",
        "regime_scaled_atr_stop",
        "missing_atr_floor_fallback",
        "mfe_breakeven_protection",
        "model_reversal_precedence",
        "atr_loser_bucket_quarantine",
    }
    if any(behaviors.get(name) is not True for name in required_behaviors):
        return None
    event_ids: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            return None
        event_time = strict_utc(event.get("event_time"))
        available_at = strict_utc(event.get("available_at"))
        generated_event_at = strict_utc(event.get("generated_at"))
        event_id = str(event.get("exit_event_id") or "")
        if (
            not event_id
            or event_id in event_ids
            or event.get("run_id") != run_id
            or event.get("cycle_id") != cycle_id
            or event.get("process_instance_id") != process_instance_id
            or event.get("paper_session_id") != paper_session_id
            or event.get("paper_only") is not True
            or event.get("routes_to_live") is not False
            or not isinstance(event.get("source_hashes"), dict)
            or not event.get("source_hashes")
            or event_time is None
            or available_at is None
            or generated_event_at is None
            or not (
                event_time
                >= deployed_at
                and event_time
                <= available_at
                <= generated_event_at
                <= generated_at
            )
        ):
            return None
        event_ids.add(event_id)
    if runtime_output.get("observed_exit_count") != len(events):
        return None
    try:
        runtime_output_sha256 = canonical_sha256(runtime_output)
    except (TypeError, ValueError):
        return None
    if runtime.get("runtime_output_sha256") != runtime_output_sha256:
        return None

    expected_source_paths = (
        "v2/backend/app/services/native_trainer/a_plus_phase7_exit_repair.py",
        "v2/backend/app/services/paper_trade_management/exits.py",
        "v2/backend/app/services/paper_trade_management/position_state.py",
        "v2/backend/app/cli/v2_trade_management_paper_loop.py",
        "v2/backend/app/cli/v2_clean_3000_session_edge_recovery.py",
    )
    expected_test_nodes = (
        "v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py::"
        "test_phase7_current_runtime_artifact_contract_authorizes_pre_repair_only",
        "v2/backend/tests/unit/cli/test_v2_clean_3000_session_edge_recovery.py::"
        "test_phase7_current_runtime_artifact_contract_authorizes_pre_repair_only",
    )
    expected_test_paths = tuple(node.split("::", 1)[0] for node in expected_test_nodes)
    try:
        expected_sources = {
            relative: hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
            for relative in expected_source_paths
        }
        expected_tests = {
            relative: hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
            for relative in expected_test_paths
        }
    except OSError:
        return None
    receipt_completed = strict_utc(receipt.get("completed_at"))
    receipt_expires = strict_utc(receipt.get("expires_at"))
    runner_command = str(receipt.get("runner_command") or "")
    authorization_material = {
        "schema_version": payload.get("schema_version"),
        "generated_utc": payload.get("generated_utc"),
        "repair_deployed_utc": payload.get("repair_deployed_utc"),
        "expires_at": payload.get("expires_at"),
        "ttl_seconds": ttl_seconds,
        "run_id": run_id,
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "canonical_current_paper_exit_runtime_evidence_present": True,
        "paper_entry_freeze_clear_allowed_by_exit_repair": True,
        "runtime_output_sha256": runtime_output_sha256,
    }
    unsigned_receipt = dict(receipt)
    claimed_receipt_hash = str(unsigned_receipt.pop("receipt_sha256", ""))
    try:
        receipt_hash_valid = claimed_receipt_hash == canonical_sha256(
            unsigned_receipt
        )
    except (TypeError, ValueError):
        receipt_hash_valid = False
    if (
        receipt.get("schema_version")
        != "v2_a_plus_phase7_runtime_authorization_receipt_v1"
        or receipt.get("run_id") != run_id
        or receipt.get("cycle_id") != cycle_id
        or receipt.get("process_instance_id") != process_instance_id
        or receipt_completed is None
        or receipt_expires is None
        or not (
            deployed_at
            <= receipt_completed
            <= generated_at
            <= observed_at
            <= receipt_expires
        )
        or receipt_expires != expires_at
        or receipt.get("ttl_seconds") != ttl_seconds
        or receipt.get("outcome") != "PASSED"
        or receipt.get("exit_code") != 0
        or receipt.get("paper_only") is not True
        or receipt.get("routes_to_live") is not False
        or receipt.get("places_real_order") is not False
        or not runner_command
        or receipt.get("runner_command_sha256")
        != hashlib.sha256(runner_command.encode("utf-8")).hexdigest()
        or receipt.get("pytest_nodeids") != list(expected_test_nodes)
        or receipt.get("production_source_sha256") != expected_sources
        or receipt.get("test_source_sha256") != expected_tests
        or receipt.get("runtime_output_sha256") != runtime_output_sha256
        or receipt.get("authorization_output_sha256")
        != canonical_sha256(authorization_material)
        or not receipt_hash_valid
    ):
        return None
    return deployed_at


def _row_exit_utc(row: dict[str, Any]) -> datetime | None:
    for field in ("exit_price_utc", "exit_time", "close_time", "closed_at", "generated_utc", "generated_at"):
        parsed = _parse_utc(row.get(field))
        if parsed is not None:
            return parsed
    return None


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")


def _connect_redis() -> Any:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
        client.ping()
        return client
    except Exception:
        return None


def _decode_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _redis_json(client: Any, key: str) -> Any:
    if client is None:
        return None
    try:
        return _decode_json(client.get(key))
    except Exception:
        return None


def _file_json(path: Path) -> Any:
    try:
        return _decode_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _as_rows(payload: Any, *, keys: tuple[str, ...] = ("rows",)) -> list[dict[str, Any]]:
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


def _first_populated_alias_rows(payload: Any, *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        rows = _as_rows(payload, keys=(key,))
        if rows:
            return rows
    return []


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _row_session_id(row: dict[str, Any]) -> str | None:
    value = row.get("paper_session_id") or row.get("session_id") or row.get("reset_session_id")
    return str(value) if value not in (None, "") else None


def _pnl(row: dict[str, Any]) -> float:
    return float(
        _safe_float(
            row.get("realized_pnl_usd")
            or row.get("realized_net_pnl_usd")
            or row.get("pnl_usd")
            or row.get("pnl")
            or 0.0
        )
        or 0.0
    )


def _notional(row: dict[str, Any]) -> float:
    return abs(
        float(
            _safe_float(
                row.get("notional")
                or row.get("notional_usd")
                or row.get("notional_usdt")
                or row.get("gross_notional_usd")
                or row.get("gross_notional")
                or row.get("order_size_usd")
                or row.get("entry_notional_usd")
                or 0.0
            )
            or 0.0
        )
    )


def _side(row: dict[str, Any]) -> str:
    raw = str(row.get("side") or row.get("action") or row.get("selected_action") or "").upper()
    if raw in {"BUY", "LONG"}:
        return "LONG"
    if raw in {"SELL", "SHORT"}:
        return "SHORT"
    return raw or "UNKNOWN"


def _confidence(row: dict[str, Any]) -> float | None:
    return _safe_float(
        row.get("confidence_calibrated")
        or row.get("confidence")
        or row.get("selected_action_probability")
    )


def _current_session_rows(rows: list[dict[str, Any]], session_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    current: list[dict[str, Any]] = []
    old_or_wrong: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for row in rows:
        row_session_id = _row_session_id(row)
        if row_session_id == session_id:
            current.append(row)
        elif row_session_id is None:
            missing.append(row)
        else:
            old_or_wrong.append(row)
    return current, old_or_wrong, missing


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


def _accepted_rows_for_session_counts(
    *,
    ledger_rows: list[dict[str, Any]],
    fill_state_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    if fill_state_rows:
        return fill_state_rows, "paper_accepted_fills_state"
    return ledger_rows, "redis_ledger_sample"


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


def _baseline_metadata_ok(
    *,
    portfolio: dict[str, Any],
    session: dict[str, Any],
    ledger: dict[str, Any],
    session_id: str,
) -> bool:
    portfolio_session_id = str(portfolio.get("paper_session_id") or portfolio.get("reset_session_id") or "")
    ledger_session_id = str(ledger.get("paper_session_id") or ledger.get("reset_session_id") or "")
    session_session_id = str(session.get("paper_session_id") or session.get("reset_session_id") or "")
    portfolio_starting = _safe_float(portfolio.get("starting_equity_usd") or portfolio.get("initial_capital"))
    ledger_starting = _safe_float(ledger.get("starting_equity_usd") or ledger.get("initial_capital"))
    session_starting = _safe_float(session.get("starting_equity_usd") or session.get("initial_capital"))
    return (
        portfolio_session_id == session_id
        and ledger_session_id == session_id
        and session_session_id == session_id
        and portfolio_starting == STARTING_EQUITY_USD
        and ledger_starting == STARTING_EQUITY_USD
        and session_starting == STARTING_EQUITY_USD
        and str(ledger.get("live_gate") or "") == "blocked_human_only"
        and ledger.get("places_real_order") is False
    )


def _profit_factor(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    gross_profit = sum(max(0.0, _pnl(row)) for row in rows)
    gross_loss = abs(sum(min(0.0, _pnl(row)) for row in rows))
    if gross_loss > 0:
        return gross_profit / gross_loss
    if gross_profit > 0:
        return float("inf")
    return 0.0


def _performance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    pnl_values = [_pnl(row) for row in rows]
    wins = sum(1 for value in pnl_values if value > 0)
    losses = sum(1 for value in pnl_values if value < 0)
    gross_profit = sum(value for value in pnl_values if value > 0)
    gross_loss = abs(sum(value for value in pnl_values if value < 0))
    total_notional = sum(_notional(row) for row in rows)
    side_pnl = {"LONG": 0.0, "SHORT": 0.0}
    side_count = {"LONG": 0, "SHORT": 0}
    symbols: set[str] = set()
    for row, pnl in zip(rows, pnl_values):
        side = _side(row)
        if side in side_pnl:
            side_pnl[side] += pnl
            side_count[side] += 1
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            symbols.add(symbol)
    high_confidence_losses = [
        row for row in rows
        if _pnl(row) < 0 and (_confidence(row) or 0.0) >= 0.70
    ]
    atr_stop_losses = [
        row for row in rows
        if _pnl(row) < 0 and "ATR" in str(row.get("close_reason") or row.get("exit_reason") or "").upper()
    ]
    repair_deployed = _verified_exit_repair_deployed_utc()
    if repair_deployed is not None:
        # Rows without a parseable exit timestamp stay post-repair (fail closed).
        atr_stop_losses_post_repair = [
            row for row in atr_stop_losses
            if (_row_exit_utc(row) or datetime.max.replace(tzinfo=timezone.utc)) >= repair_deployed
        ]
    else:
        atr_stop_losses_post_repair = atr_stop_losses
    return {
        "trade_count": count,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / count) if count else None,
        "gross_profit_usd": round(gross_profit, 8),
        "gross_loss_usd": round(gross_loss, 8),
        "net_pnl_usd": round(sum(pnl_values), 8),
        "profit_factor": _profit_factor(rows),
        "expectancy_usd": (sum(pnl_values) / count) if count else None,
        "total_notional_usd": round(total_notional, 8),
        "notional_weighted_expectancy": (sum(pnl_values) / total_notional) if total_notional > 0 else None,
        "long_pnl_usd": round(side_pnl["LONG"], 8),
        "short_pnl_usd": round(side_pnl["SHORT"], 8),
        "long_trade_count": side_count["LONG"],
        "short_trade_count": side_count["SHORT"],
        "symbol_count": len(symbols),
        "symbols": sorted(symbols),
        "high_confidence_loss_count": len(high_confidence_losses),
        "high_confidence_loss_cluster": len(high_confidence_losses) >= 3,
        "atr_stop_loss_count": len(atr_stop_losses),
        "atr_stop_loss_count_post_exit_repair": len(atr_stop_losses_post_repair),
        "atr_stop_cluster": len(atr_stop_losses_post_repair) >= 2,
        "atr_stop_cluster_pre_repair_losses_excluded": (
            repair_deployed is not None and len(atr_stop_losses_post_repair) < len(atr_stop_losses)
        ),
        "atr_exit_repair_deployed_utc": (
            repair_deployed.isoformat(timespec="seconds").replace("+00:00", "Z") if repair_deployed else None
        ),
    }


def _format_float(value: float | None) -> float | str | None:
    if value == float("inf"):
        return "inf"
    return round(value, 8) if isinstance(value, float) else value


def _serialize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: _format_float(value) for key, value in metrics.items()}


def _gate_payload(
    *,
    gate_name: str,
    threshold: int,
    session_id: str,
    metrics: dict[str, Any],
    generated_utc: str,
) -> dict[str, Any]:
    count = int(metrics["trade_count"])
    pf = metrics["profit_factor"]
    expectancy = metrics["expectancy_usd"]
    notional_expectancy = metrics["notional_weighted_expectancy"]
    pending = count < threshold
    pass_conditions: dict[str, bool | None]
    if gate_name == "5_trade":
        pass_conditions = {
            "minimum_trade_count_met": count >= 5,
            "profit_factor_gte_1": None if pending else (pf is not None and pf >= 1.0),
            "expectancy_positive": None if pending else (expectancy is not None and expectancy > 0.0),
        }
    elif gate_name == "50_trade":
        pass_conditions = {
            "minimum_trade_count_met": count >= 50,
            "profit_factor_gte_1": None if pending else (pf is not None and pf >= 1.0),
            "notional_weighted_expectancy_positive": None if pending else (
                notional_expectancy is not None and notional_expectancy > 0.0
            ),
            "no_high_confidence_loss_cluster": None if pending else not bool(metrics["high_confidence_loss_cluster"]),
            "no_atr_stop_cluster": None if pending else not bool(metrics["atr_stop_cluster"]),
        }
    else:
        pass_conditions = {
            "minimum_trade_count_met": count >= 300,
            "profit_factor_gte_1_25": None if pending else (pf is not None and pf >= 1.25),
            "expectancy_positive": None if pending else (expectancy is not None and expectancy > 0.0),
            "long_pnl_positive": None if pending else metrics["long_pnl_usd"] > 0.0,
            "short_pnl_positive": None if pending else metrics["short_pnl_usd"] > 0.0,
            "at_least_20_symbols": None if pending else metrics["symbol_count"] >= 20,
        }
    if pending:
        status = "PENDING"
    elif all(value is True for value in pass_conditions.values()):
        status = "PASS"
    else:
        status = "FAIL_HALT_REQUIRED" if gate_name == "5_trade" else "FAIL"
    return {
        "schema_version": f"clean_3000_session_{gate_name}_gate_v1",
        "generated_utc": generated_utc,
        "paper_session_id": session_id,
        "gate": gate_name,
        "status": status,
        "halt_required": status == "FAIL_HALT_REQUIRED",
        "trade_count": count,
        "required_trade_count": threshold,
        "metrics": _serialize_metrics(metrics),
        "pass_conditions": pass_conditions,
        "pre_reset_trades_excluded": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _future_gate_blockers(metrics: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    trade_count = int(metrics.get("trade_count") or 0)
    if trade_count < 50:
        if metrics.get("high_confidence_loss_cluster") is True:
            blockers.append("HIGH_CONFIDENCE_LOSS_CLUSTER_BEFORE_50_TRADE_GATE")
        if metrics.get("atr_stop_cluster") is True:
            blockers.append("ATR_STOP_CLUSTER_BEFORE_50_TRADE_GATE")
    return blockers


def _atr_stop_diagnostic_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_session_id": _row_session_id(row),
        "symbol": row.get("symbol"),
        "side": _side(row),
        "timeframe": row.get("timeframe") or row.get("selected_timeframe") or row.get("entry_timeframe"),
        "strategy_regime": row.get("strategy_regime") or row.get("regime") or row.get("trend_mode"),
        "close_reason": row.get("close_reason") or row.get("exit_reason"),
        "realized_pnl_usd": _format_float(_pnl(row)),
        "gross_notional_usd": _format_float(_notional(row)),
        "realized_pnl_bps": _format_float(
            _safe_float(row.get("realized_pnl_bps") or row.get("pnl_bps") or row.get("net_pnl_bps"))
        ),
        "mae_bps": _format_float(_safe_float(row.get("mae_bps") or row.get("MAE_bps") or row.get("mae"))),
        "mfe_bps": _format_float(_safe_float(row.get("mfe_bps") or row.get("MFE_bps") or row.get("mfe"))),
        "entry_atr_bps": _format_float(_safe_float(row.get("entry_atr_bps") or row.get("atr_bps"))),
        "atr_stop_bps": _format_float(_safe_float(row.get("atr_stop_bps"))),
        "atr_stop_multiplier_used": _format_float(_safe_float(row.get("atr_stop_multiplier_used"))),
        "entry_time": row.get("entry_time") or row.get("opened_at") or row.get("created_at"),
        "close_time": row.get("close_time") or row.get("closed_at") or row.get("generated_at"),
        "fill_id": row.get("fill_id"),
        "entry_fill_id": row.get("entry_fill_id"),
        "signal_id": row.get("signal_id") or row.get("entry_signal_id"),
        "prediction_id": row.get("prediction_id") or row.get("entry_prediction_id"),
        "decision_id": row.get("decision_id") or row.get("orchestrator_decision_id"),
        "source_fill_ids": row.get("source_fill_ids"),
    }


def _atr_stop_cluster_diagnostic(
    *,
    rows: list[dict[str, Any]],
    metrics: dict[str, Any],
    session_id: str,
    generated_utc: str,
    future_gate_blockers: list[str],
) -> dict[str, Any]:
    atr_stop_loss_rows = [
        _atr_stop_diagnostic_row(row)
        for row in rows
        if _pnl(row) < 0 and "ATR" in str(row.get("close_reason") or row.get("exit_reason") or "").upper()
    ]
    is_blocking = "ATR_STOP_CLUSTER_BEFORE_50_TRADE_GATE" in future_gate_blockers
    return {
        "schema_version": "clean_3000_session_atr_stop_cluster_diagnostic_v1",
        "generated_utc": generated_utc,
        "goal_id": GOAL_ID,
        "paper_session_id": session_id,
        "status": "BLOCKING_50_TRADE_GATE" if is_blocking else "CLEAR",
        "root_cause_classification": "CURRENT_SESSION_ATR_STOP_CLUSTER" if is_blocking else None,
        "future_gate_blockers": future_gate_blockers,
        "trade_count": metrics.get("trade_count"),
        "atr_stop_loss_count": metrics.get("atr_stop_loss_count"),
        "atr_stop_cluster": metrics.get("atr_stop_cluster"),
        "paper_new_entries_halted_required": is_blocking,
        "diagnostic_row_count": len(atr_stop_loss_rows),
        "diagnostic_rows": atr_stop_loss_rows,
        "pre_reset_trades_excluded": True,
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
    }


def _freeze_payload(
    session_id: str,
    gate: dict[str, Any],
    generated_utc: str,
    *,
    reason: str = "CLEAN_3000_SESSION_5_TRADE_GATE_FAILED",
    future_gate_blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "paper_entry_freeze_v1",
        "generated_utc": generated_utc,
        "paper_new_entries_halted": True,
        "new_entries_allowed": False,
        "close_reduce_diagnostics_allowed": True,
        "mark_to_market_allowed": True,
        "reason": reason,
        "future_gate_blockers": future_gate_blockers or [],
        "paper_session_id": session_id,
        "gate": gate,
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
    }


def run(
    *,
    session_id: str | None = None,
    enforce_halt: bool = False,
    clear_stale_freeze: bool = False,
) -> dict[str, Any]:
    generated_utc = _utc_iso()
    client = _connect_redis()
    session = _redis_json(client, "v2:paper:session")
    session = session if isinstance(session, dict) else {}
    portfolio = _redis_json(client, "v2:portfolio:state")
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    ledger = _redis_json(client, "v2:paper:ledger")
    ledger = ledger if isinstance(ledger, dict) else {}
    session_id = session_id or session.get("paper_session_id") or portfolio.get("paper_session_id") or DEFAULT_SESSION_ID

    closed_rows = _as_rows(_redis_json(client, "v2:paper:closed_trades"), keys=("closed_trades", "closes", "rows"))
    if not closed_rows:
        closed_rows = _as_rows(ledger, keys=("closed_trades", "closes"))
    accepted_rows = _first_populated_alias_rows(ledger, keys=("accepted", "accepted_intents"))
    fill_state_rows = _as_rows(_file_json(FILL_STATE_FILE), keys=("accepted_fills", "rows"))
    accepted_count_rows, accepted_count_source = _accepted_rows_for_session_counts(
        ledger_rows=accepted_rows,
        fill_state_rows=fill_state_rows,
    )
    accepted_evidence_rows = accepted_count_rows + accepted_rows
    trainer_rows = _as_rows(_redis_json(client, "v2:trainer:feedback:outcomes"), keys=("trainer_feedback_outcomes", "rows"))
    if not trainer_rows:
        trainer_rows = _as_rows(ledger, keys=("trainer_feedback_outcomes",))
    trainer_quarantine_rows = _as_rows(
        _redis_json(client, "v2:trainer:feedback:outcomes:quarantine"),
        keys=("trainer_feedback_outcomes_quarantine", "rows"),
    )
    if not trainer_quarantine_rows:
        trainer_quarantine_rows = _as_rows(ledger, keys=("trainer_feedback_outcomes_quarantine",))

    session_closed, old_closed, missing_session_closed = _current_session_rows(closed_rows, session_id)
    session_accepted, old_accepted, missing_session_accepted = _current_session_rows(accepted_count_rows, session_id)
    session_trainer, old_trainer, missing_session_trainer = _current_session_rows(trainer_rows, session_id)
    invalid_admission_source_ids = _invalid_admission_source_ids(accepted_evidence_rows)
    valid_session_accepted, invalid_admission_accepted = _split_invalid_admission_rows(
        session_accepted,
        invalid_admission_source_ids,
    )
    valid_session_closed, invalid_admission_closed = _split_invalid_admission_rows(
        session_closed,
        invalid_admission_source_ids,
    )
    valid_session_trainer, invalid_admission_trainer = _split_invalid_admission_rows(
        session_trainer,
        invalid_admission_source_ids,
    )
    metrics = _performance(valid_session_closed)

    five_gate = _gate_payload(
        gate_name="5_trade",
        threshold=5,
        session_id=session_id,
        metrics=metrics,
        generated_utc=generated_utc,
    )
    fifty_gate = _gate_payload(
        gate_name="50_trade",
        threshold=50,
        session_id=session_id,
        metrics=metrics,
        generated_utc=generated_utc,
    )
    three_hundred_gate = _gate_payload(
        gate_name="300_trade",
        threshold=300,
        session_id=session_id,
        metrics=metrics,
        generated_utc=generated_utc,
    )
    future_gate_blockers = _future_gate_blockers(metrics)
    future_gate_halt_required = bool(future_gate_blockers)
    atr_stop_diagnostic = _atr_stop_cluster_diagnostic(
        rows=valid_session_closed,
        metrics=metrics,
        session_id=session_id,
        generated_utc=generated_utc,
        future_gate_blockers=future_gate_blockers,
    )

    freeze_written = False
    stale_entry_freeze_cleared = False
    if enforce_halt and client is not None and (five_gate["halt_required"] or future_gate_halt_required):
        freeze_reason = (
            "CLEAN_3000_SESSION_5_TRADE_GATE_FAILED"
            if five_gate["halt_required"]
            else "CLEAN_3000_SESSION_50_TRADE_GATE_IRRECOVERABLE_BLOCKER"
        )
        freeze_gate = five_gate if five_gate["halt_required"] else fifty_gate
        client.set(
            ENTRY_FREEZE_KEY,
            json.dumps(
                _freeze_payload(
                    session_id,
                    freeze_gate,
                    generated_utc,
                    reason=freeze_reason,
                    future_gate_blockers=future_gate_blockers,
                ),
                sort_keys=True,
            ),
        )
        freeze_written = True

    baseline_ok = _baseline_metadata_ok(
        portfolio=portfolio,
        session=session,
        ledger=ledger,
        session_id=session_id,
    )
    existing_freeze = _redis_json(client, ENTRY_FREEZE_KEY)
    existing_freeze = existing_freeze if isinstance(existing_freeze, dict) else {}
    if (
        clear_stale_freeze
        and client is not None
        and not five_gate["halt_required"]
        and not future_gate_halt_required
        and baseline_ok
        and existing_freeze.get("paper_new_entries_halted") is True
        and str(existing_freeze.get("reason") or "") in STALE_PRE_RESET_FREEZE_REASONS
    ):
        client.delete(ENTRY_FREEZE_KEY)
        stale_entry_freeze_cleared = True
        existing_freeze = {}

    performance_status = {
        "schema_version": "clean_3000_session_performance_status_v1",
        "generated_utc": generated_utc,
        "goal_id": GOAL_ID,
        "paper_session_id": session_id,
        "starting_equity_usd": STARTING_EQUITY_USD,
        "current_equity_usd": portfolio.get("equity"),
        "baseline_ok": baseline_ok,
        "accepted_current_session": len(valid_session_accepted),
        "accepted_current_session_raw": len(session_accepted),
        "invalid_admission_accepted_excluded": len(invalid_admission_accepted),
        "accepted_count_source": accepted_count_source,
        "accepted_all_sessions_seen": len(accepted_count_rows),
        "accepted_fill_state_rows_seen": len(fill_state_rows),
        "accepted_invalid_admission_source_id_count": len(invalid_admission_source_ids),
        "open_positions_current_session": int(ledger.get("open_position_count") or 0),
        "closed_trades_current_session": len(valid_session_closed),
        "closed_trades_current_session_raw": len(session_closed),
        "invalid_admission_closed_trades_excluded": len(invalid_admission_closed),
        "invalid_admission_exclusion_reason": INVALID_ADMISSION_REASON,
        "closed_trades_all_sessions_seen": len(closed_rows),
        "pre_reset_or_wrong_session_closed_trades_excluded": len(old_closed),
        "missing_session_closed_trades_excluded": len(missing_session_closed),
        "pre_reset_or_wrong_session_accepted_excluded": len(old_accepted),
        "accepted_rows_missing_session_id": len(missing_session_accepted),
        "metrics": _serialize_metrics(metrics),
        "five_trade_gate_status": five_gate["status"],
        "fifty_trade_gate_status": fifty_gate["status"],
        "three_hundred_trade_gate_status": three_hundred_gate["status"],
        "future_gate_blockers": future_gate_blockers,
        "future_gate_halt_required": future_gate_halt_required,
        "halt_required": bool(five_gate["halt_required"] or future_gate_halt_required),
        "entry_freeze_written": freeze_written,
        "stale_entry_freeze_cleared": stale_entry_freeze_cleared,
        "entry_freeze_active": bool(existing_freeze.get("paper_new_entries_halted")),
        "entry_freeze_reason": existing_freeze.get("reason"),
        "live_gate": ledger.get("live_gate"),
        "places_real_order": ledger.get("places_real_order"),
        "paper_only": True,
        "routes_to_live": False,
    }
    trainer_status = {
        "schema_version": "clean_3000_session_trainer_feedback_status_v1",
        "generated_utc": generated_utc,
        "paper_session_id": session_id,
        "trainer_feedback_rows_current_session": len(valid_session_trainer),
        "trainer_feedback_rows_current_session_raw": len(session_trainer),
        "trainer_feedback_rows_invalid_admission_excluded": len(invalid_admission_trainer),
        "invalid_admission_exclusion_reason": INVALID_ADMISSION_REASON,
        "trainer_feedback_rows_all_sessions_seen": len(trainer_rows),
        "trainer_feedback_rows_wrong_session_excluded": len(old_trainer),
        "trainer_feedback_rows_missing_session_excluded": len(missing_session_trainer),
        "trainer_quarantine_rows_seen": len(trainer_quarantine_rows),
        "all_current_trainer_rows_session_tagged": len(missing_session_trainer) == 0,
        "pre_reset_feedback_ignored": True,
        "required_fields": [
            "paper_session_id",
            "outcome_label",
            "decision_id",
            "feature_snapshot_id",
            "mtf_snapshot_id",
            "feature_cutoff",
            "available_at",
            "MFE",
            "MAE",
            "fees",
            "slippage",
            "funding",
        ],
        "status": (
            "PENDING_NO_VALID_FEEDBACK_ROWS_INVALID_ADMISSION_EXCLUDED"
            if invalid_admission_trainer and not valid_session_trainer
            else "PENDING_NO_FEEDBACK_ROWS" if not valid_session_trainer else "SESSION_FEEDBACK_ROWS_PRESENT"
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    a_grade_readiness = {
        "schema_version": "clean_3000_session_a_grade_bootstrap_readiness_v1",
        "generated_utc": generated_utc,
        "paper_session_id": session_id,
        "status": "READY" if three_hundred_gate["status"] == "PASS" else "BLOCKED_PENDING_300_TRADE_GATE",
        "do_not_start_a_grade_bootstrap": three_hundred_gate["status"] != "PASS",
        "three_hundred_trade_gate_status": three_hundred_gate["status"],
        "pre_reset_trades_excluded": True,
        "trade_count": metrics["trade_count"],
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }

    GOAL_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(GOAL_DIR / "clean_3000_session_performance_status.json", performance_status)
    _write_json(GOAL_DIR / "clean_3000_session_5_trade_gate.json", five_gate)
    _write_json(GOAL_DIR / "clean_3000_session_50_trade_gate.json", fifty_gate)
    _write_json(GOAL_DIR / "clean_3000_session_300_trade_gate.json", three_hundred_gate)
    _write_json(GOAL_DIR / "clean_3000_session_trainer_feedback_status.json", trainer_status)
    _write_json(GOAL_DIR / "clean_3000_session_a_grade_bootstrap_readiness.json", a_grade_readiness)
    _write_json(GOAL_DIR / "clean_3000_session_atr_stop_cluster_diagnostic.json", atr_stop_diagnostic)
    result = {
        "clean_3000_session_performance_status": performance_status,
        "clean_3000_session_5_trade_gate": five_gate,
        "clean_3000_session_50_trade_gate": fifty_gate,
        "clean_3000_session_300_trade_gate": three_hundred_gate,
        "clean_3000_session_trainer_feedback_status": trainer_status,
        "clean_3000_session_a_grade_bootstrap_readiness": a_grade_readiness,
        "clean_3000_session_atr_stop_cluster_diagnostic": atr_stop_diagnostic,
    }
    _write_json(GOAL_DIR / "clean_3000_session_edge_recovery_run_result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish clean $3,000 session edge recovery gates")
    parser.add_argument("--paper-session-id", default=None)
    parser.add_argument("--enforce-halt", action="store_true", help="Write paper entry freeze if 5-trade gate fails")
    parser.add_argument("--clear-stale-freeze", action="store_true", help="Clear pre-reset quarantine freeze after clean baseline verification")
    parser.add_argument("--loop", action="store_true", help="Continuously publish and enforce gates")
    parser.add_argument("--interval-seconds", type=int, default=30)
    args = parser.parse_args()
    if args.loop:
        while True:
            result = run(
                session_id=args.paper_session_id,
                enforce_halt=args.enforce_halt,
                clear_stale_freeze=args.clear_stale_freeze,
            )
            perf = result["clean_3000_session_performance_status"]
            print(
                "clean_3000_session_edge_recovery "
                f"session={perf['paper_session_id']} "
                f"trades={perf['closed_trades_current_session']} "
                f"g5={perf['five_trade_gate_status']} "
                f"halt_required={perf['halt_required']} "
                f"freeze_written={perf['entry_freeze_written']} "
                f"stale_freeze_cleared={perf['stale_entry_freeze_cleared']}",
                flush=True,
            )
            time.sleep(max(5, int(args.interval_seconds)))
    else:
        print(
            json.dumps(
                run(
                    session_id=args.paper_session_id,
                    enforce_halt=args.enforce_halt,
                    clear_stale_freeze=args.clear_stale_freeze,
                ),
                indent=2,
                sort_keys=True,
                default=_json_default,
            )
        )


if __name__ == "__main__":
    main()
